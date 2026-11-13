"""Immutable project plotting lifecycle and byte-identical selected exports."""

import io
import json
import threading
from zipfile import ZIP_DEFLATED, ZipFile

from astroagent import __version__
from astroagent.conversations import encode
from astroagent.errors import ServiceError
from astroagent.plot_data import dataset, digest, from_snapshot, table
from astroagent.plot_executor_client import ExecutorClient
from astroagent.plot_planner import generate, model_context
from astroagent.plot_sandbox import Sandbox, configured
from astroagent.plot_store import PlotStore, ready

RUN_SLOTS = threading.BoundedSemaphore(1)
FILES = {
    "figure.png": "image/png",
    "figure.pdf": "application/pdf",
    "data.csv": "text/csv; charset=utf-8",
    "original.csv": "application/octet-stream",
    "original.tsv": "application/octet-stream",
    "source.json": "application/json",
    "script.py": "text/plain; charset=utf-8",
    "script.plt": "text/plain; charset=utf-8",
    "README.md": "text/plain; charset=utf-8",
    "manifest.json": "application/json",
    "run.log": "text/plain; charset=utf-8",
}


class PlotService:
    def __init__(self, conversations, settings):
        self.conversations = conversations
        self.store = PlotStore(conversations.repository)
        self.settings = settings
        self.sandbox = (
            ExecutorClient(settings)
            if settings.deployment_mode == "container"
            else Sandbox(settings)
        )
        interrupted = self.store.recover()
        self.sandbox.cleanup_interrupted(interrupted)

    def status(self):
        with self.store.repo.connection() as db:
            storage = ready(db)
        enabled = configured(self.settings) and bool(
            self.sandbox.available
            if isinstance(self.sandbox, ExecutorClient)
            else self.sandbox.docker
        )
        if enabled and isinstance(self.sandbox, ExecutorClient):
            try:
                self.sandbox.probe()
            except Exception:
                return {
                    "storage_ready": storage,
                    "execution_configured": False,
                    "message": (
                        "独立绘图执行器未就绪：可查看或生成方案，暂不能执行；不会在宿主机运行。"
                    ),
                }
        return {
            "storage_ready": storage,
            "execution_configured": enabled,
            "message": "执行配置已提供；每次执行前仍将核对Linux容器与资源限制。"
            if enabled
            else "隔离执行未配置：可生成和查看方案，暂不能执行。不会回退到宿主机。",
        }

    def upload(self, project_id, identifier, filename, raw):
        header, rows = table(raw, filename)
        info, data = dataset(identifier, project_id, filename, raw, header, rows)
        return self.store.save_dataset(info, data, raw)

    def snapshot(self, project_id, identifier, request):
        snapshot = self.store.projects.snapshot(project_id, request.snapshot_id)
        info, data, original = from_snapshot(identifier, project_id, snapshot, request.query_index)
        return self.store.save_dataset(info, data, original)

    def preview(self, project_id, identifier):
        with self.store.repo.connection() as db:
            info, data, _ = self.store.dataset(db, project_id, identifier)
        return model_context(info, data)

    def turn(self, project_id, identifier, request):
        # Freeze server-owned complete responses; never trust browser-supplied rows.
        with self.store.repo.connection() as db:
            try:
                existing, _, _ = self.store.dataset(db, project_id, identifier)
            except ServiceError as exc:
                if exc.error.code != "plot_dataset_not_found":
                    raise
            else:
                source = existing["provenance"]
                if all(source.get(key) == value for key, value in request.model_dump().items()):
                    return existing
                raise ServiceError(409, "plot_request_conflict", "此数据集编号已用于其他来源。")
        turn = self.conversations.repository.turn(request.conversation_id, request.turn_id)
        if turn.execution_status != "completed" or turn.response is None:
            raise ServiceError(422, "plot_turn_unavailable", "请等待本轮完整结果返回后再绘图。")
        frozen = self.store.projects.make_snapshot(
            project_id, f"第{turn.revision}轮 Gaia 数据", turn
        )
        frozen["id"] = identifier
        frozen["created_at"] = turn.completed_at or turn.received_at
        with self.store.repo.connection() as db:
            imported = db.execute(
                "SELECT record FROM imported_turn_origins WHERE turn_id=?", (turn.turn_id,)
            ).fetchone()
        if imported:
            frozen["provenance"] = "imported_unverified"
            frozen["origin"] = json.loads(imported[0])
        info, data, original = from_snapshot(identifier, project_id, frozen, request.query_index)
        info["provenance"].update(
            origin_type="conversation_turn",
            conversation_id=request.conversation_id,
            turn_id=request.turn_id,
        )
        return self.store.save_dataset(info, data, original)

    def plan(self, project_id, identifier, request):
        with self.store.repo.connection() as db:
            info, data, _ = self.store.dataset(db, project_id, request.dataset_id)
        value, fresh = self.store.reserve(
            project_id, identifier, "plan", request.model_dump(), request.dataset_id
        )
        if not fresh:
            return value
        try:
            proposal, usage = generate(request, info, data)
            value.update(
                state="completed",
                proposal=proposal,
                script_sha256=digest(proposal["script"].encode()),
                model_usage=usage,
            )
        except ServiceError as exc:
            value.update(state="failed", error=exc.error.message)
        except Exception:
            value.update(state="failed", error="方案生成失败，未执行脚本；不会自动重试。")
        return self.store.finish(value)

    def run(self, project_id, identifier, request):
        payload = request.model_dump()
        # Existing request must remain readable even when the execution environment changes.
        with self.store.repo.connection() as db:
            plan = self.store.operation(db, project_id, request.plan_id)
            existing = db.execute(
                "SELECT record FROM plot_operations WHERE id=?", (identifier,)
            ).fetchone()
            if existing:
                old = json.loads(existing[0])
                if (
                    old["project_id"] != project_id
                    or old["kind"] != "run"
                    or old["request_sha256"] != digest(encode(payload).encode())
                ):
                    raise ServiceError(409, "plot_request_conflict", "请求标识已用于不同操作。")
                return old
            if plan["kind"] != "plan" or plan["state"] != "completed" or plan["proposal"] is None:
                raise ServiceError(409, "plot_plan_unavailable", "请选择已完成的绘图方案。")
            if plan.get("imported"):
                raise ServiceError(
                    409,
                    "plot_imported_plan",
                    "导入脚本只供查看；请基于数据生成并审阅新方案后执行。",
                )
            info, data, original = self.store.dataset(db, project_id, plan["dataset_id"])
        if not RUN_SLOTS.acquire(blocking=False):
            raise ServiceError(409, "plot_executor_busy", "已有绘图运行，请稍后手动提交。")
        try:
            admitted = self.sandbox.admit(plan["proposal"]["engine"])
            value, fresh = self.store.reserve(
                project_id, identifier, "run", payload, plan["dataset_id"]
            )
            if not fresh:
                return value
            value.update(proposal=plan["proposal"], script_sha256=plan["script_sha256"])
            files = {}
            try:
                files, runtime = self.sandbox.run(plan["proposal"], data, identifier, admitted)
                value.update(state="completed", runtime=runtime)
                suffix = "py" if plan["proposal"]["engine"] == "python" else "plt"
                files[f"script.{suffix}"] = plan["proposal"]["script"].encode()
                files["data.csv"] = data
                source_name = (
                    "source.json"
                    if info["source"] == "snapshot"
                    else "original.tsv"
                    if str(info["provenance"].get("filename", "")).lower().endswith(".tsv")
                    else "original.csv"
                )
                files[source_name] = original
                files["README.md"] = (
                    f"# AstroAgent 绘图记录\n\nEngine: {plan['proposal']['engine']}\n\n"
                    + plan["proposal"]["explanation"]
                    + "\n\n"
                    + "\n".join(info["warnings"] + plan["proposal"]["warnings"])
                    + "\n\n在独立等价环境中，将data.csv放在/input/data.csv，脚本写入/output。"
                    + f"实际执行脚本与下载字节一致。\nAstroAgent {__version__}\n"
                ).encode()
                manifest = {
                    "format": "astroagent-plot",
                    "version": 1,
                    "run_id": identifier,
                    "plan_id": plan["id"],
                    "dataset": info,
                    "proposal": plan["proposal"],
                    "script_sha256": value["script_sha256"],
                    "created_at": value["created_at"],
                    "runtime": runtime,
                    "model": plan["request"]["model_id"],
                    "model_usage": plan["model_usage"],
                    "application_version": __version__,
                    "files": {
                        name: {"bytes": len(raw), "sha256": digest(raw)}
                        for name, raw in files.items()
                    },
                }
                files["manifest.json"] = encode(manifest).encode()
            except ServiceError as exc:
                value.update(state="failed", error=exc.error.message)
                value["runtime"] = {
                    "diagnostic": getattr(exc, "plot_diagnostic", ""),
                    "isolation": "linux-docker-v1",
                }
            except Exception:
                value.update(state="failed", error="隔离绘图失败；未交付不完整图形。")
            try:
                return self.store.finish(value, files if value["state"] == "completed" else None)
            except ServiceError:
                value.update(state="failed", error="完整产物未能保存，请检查存储预算；未交付半包。")
                return self.store.finish(value)
        finally:
            RUN_SLOTS.release()

    def output(self, project_id, identifier, name):
        if name not in FILES:
            raise ServiceError(404, "plot_file_not_found", "不支持此文件。")
        with self.store.repo.connection() as db:
            operation = self.store.operation(db, project_id, identifier)
            if name not in operation["files"]:
                raise ServiceError(404, "plot_file_not_found", "此运行没有该文件。")
            row = db.execute(
                "SELECT content FROM plot_outputs WHERE run_id=? AND name=?", (identifier, name)
            ).fetchone()
            if not row:
                raise ServiceError(404, "plot_file_not_found", "绘图文件不存在。")
            return bytes(row[0])

    def bundle(self, project_id, identifier, names):
        if not names or len(names) != len(set(names)) or len(names) > 9:
            raise ServiceError(422, "plot_export_selection", "请选择1至9个不重复文件。")
        stream = io.BytesIO()
        with ZipFile(stream, "w", compression=ZIP_DEFLATED) as archive:
            for name in names:
                archive.writestr(name, self.output(project_id, identifier, name))
        return stream.getvalue()
