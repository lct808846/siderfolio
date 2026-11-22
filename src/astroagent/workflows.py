"""流程短事务、检查点与持久输出；外部调用由服务层在事务外执行。"""

import hashlib
import json
from datetime import datetime
from uuid import uuid4

from astroagent.conversation_schemas import Turn
from astroagent.conversations import utc_now
from astroagent.errors import ServiceError
from astroagent.project_schemas import Snapshot
from astroagent.projects import ProjectRepository
from astroagent.schemas import ErrorInfo
from astroagent.workflow_schemas import (
    StepAttempt,
    WorkflowOperation,
    WorkflowOutput,
    WorkflowRun,
    WorkflowStep,
)
from astroagent.workflow_templates import (
    DEFINITIONS,
    TEMPLATE_VERSION,
    digest,
    environment,
    input_digest,
    parameters,
    prepare_input,
    step_software,
)

MAX_OUTPUT_BYTES = 16 * 1024**2
OPERATION_RESERVE = 64 * 1024


class WorkflowRepository:
    def __init__(self, repository):
        self.repo = repository
        self.projects = ProjectRepository(repository)

    def _run(self, db, project_id, identifier, revision=None):
        self.projects._project(db, project_id)
        row = db.execute(
            "SELECT record FROM workflows WHERE id=? AND project_id=?", (identifier, project_id)
        ).fetchone()
        if row is None:
            raise ServiceError(404, "workflow_not_found", "该项目中没有此流程。")
        run = WorkflowRun.model_validate_json(row[0])
        if revision is not None and run.revision != revision:
            raise ServiceError(409, "workflow_revision_conflict", "流程已更新，请刷新状态。")
        return run

    def _save(self, db, run):
        run.updated_at = utc_now()
        run.revision += 1
        record = run.model_dump_json()
        if len(record.encode()) > self.repo.settings.turn_bytes:
            raise ServiceError(
                413, "workflow_record_too_large", "流程完整记录超过单项上限，未裁剪保存。"
            )
        db.execute("UPDATE workflows SET record=?,state=? WHERE id=?", (record, run.state, run.id))
        self.projects._touch(db, run.project_id)

    def create(self, project_id, request):
        with self.repo.connection() as db, self.repo.transaction(db):
            self.projects._project(db, project_id, request.expected_revision)
            self.projects._idle(db, project_id)
            if (
                db.execute(
                    "SELECT count(*) FROM workflows WHERE project_id=?", (project_id,)
                ).fetchone()[0]
                >= 50
            ):
                raise ServiceError(409, "workflow_limit", "每项目最多保存50次流程运行。")
            run = WorkflowRun(
                id=str(uuid4()),
                project_id=project_id,
                name=request.name,
                template_id=request.template_id,
                template_version=TEMPLATE_VERSION,
                parameters=request.parameters.model_dump(mode="json"),
                requested_parameters=request.parameters.model_dump(mode="json", exclude_unset=True),
                revision=0,
                created_at=utc_now(),
                updated_at=utc_now(),
                software=environment(),
                steps=[
                    WorkflowStep(id=sid, title=title)
                    for sid, title in DEFINITIONS[request.template_id]
                ],
            )
            if run.template_id == "gaia_field" and run.parameters["input_mode"] == "coordinates":
                run.steps[0].state = "skipped"
                run.steps[0].skip_reason = "用户直接指定ICRS坐标，未执行SIMBAD解析。"
            db.execute(
                "INSERT INTO workflows VALUES (?,?,?,?,0)",
                (run.id, project_id, run.state, run.model_dump_json()),
            )
            self.projects._touch(db, project_id)
            self.projects._budget(db)
            return run

    def list(self, project_id):
        with self.repo.connection() as db:
            self.projects._project(db, project_id)
            return [
                {
                    key: value[key]
                    for key in (
                        "id",
                        "project_id",
                        "name",
                        "template_id",
                        "template_version",
                        "state",
                        "revision",
                        "updated_at",
                        "provenance",
                    )
                }
                for row in db.execute(
                    "SELECT record FROM workflows WHERE project_id=? ORDER BY rowid DESC",
                    (project_id,),
                )
                for value in [json.loads(row[0])]
            ]

    def detail(self, project_id, identifier):
        with self.repo.connection() as db:
            db.execute("BEGIN")
            value = self._run(db, project_id, identifier).model_dump(mode="json")
            value["outputs"] = [
                json.loads(row[0])
                for row in db.execute(
                    "SELECT record FROM workflow_outputs WHERE run_id=? ORDER BY rowid",
                    (identifier,),
                )
            ]
            value["operations"] = [
                json.loads(row[0])
                for row in db.execute(
                    "SELECT record FROM workflow_operations WHERE run_id=? ORDER BY rowid",
                    (identifier,),
                )
            ]
            return value

    def read(self, project_id, identifier):
        with self.repo.connection() as db:
            return self._run(db, project_id, identifier)

    def output(self, project_id, run_id, output_id):
        with self.repo.connection() as db:
            self._run(db, project_id, run_id)
            row = db.execute(
                "SELECT record,content FROM workflow_outputs WHERE id=? AND run_id=?",
                (output_id, run_id),
            ).fetchone()
            if row is None:
                raise ServiceError(404, "workflow_output_not_found", "该流程没有此输出。")
            info = WorkflowOutput.model_validate_json(row[0])
            if len(row[1]) != info.bytes or hashlib.sha256(row[1]).hexdigest() != info.sha256:
                raise ServiceError(422, "workflow_output_corrupt", "输出完整性不符，未交付文件。")
            return info, row[1]

    def existing(self, project_id, run_id, request):
        request_hash = digest({"run_id": run_id, **request.model_dump()})
        with self.repo.connection() as db:
            self._run(db, project_id, run_id)
            row = db.execute(
                "SELECT request_hash,record FROM workflow_operations "
                "WHERE run_id=? AND request_id=?",
                (run_id, request.client_request_id),
            ).fetchone()
            if row and row[0] != request_hash:
                raise ServiceError(409, "request_id_conflict", "此请求编号已用于另一项执行条件。")
            return (WorkflowOperation.model_validate_json(row[1]) if row else None), request_hash

    def validate_reuse(self, run):
        if run.provenance != "local":
            raise ServiceError(
                409, "workflow_imported_read_only", "导入流程仅可核查，请确认参数后新建本地运行。"
            )
        if (
            run.template_version != TEMPLATE_VERSION
            or [s.id for s in run.steps] != [s[0] for s in DEFINITIONS[run.template_id]]
            or any(s.version != "1" for s in run.steps)
        ):
            raise ServiceError(
                422, "workflow_template_changed", "旧模板不支持继续，请保留历史并新建运行。"
            )
        try:
            normalized = parameters(run.template_id, run.parameters)
        except ValueError as exc:
            raise ServiceError(
                422, "workflow_parameters_changed", "参数不符合原规范，请新建运行。"
            ) from exc
        if normalized != run.parameters:
            raise ServiceError(422, "workflow_parameters_changed", "参数不符合原规范，请新建运行。")
        with self.repo.connection() as db:
            try:
                db.execute("BEGIN")
                for step in run.steps:
                    if step.state == "skipped":
                        if (
                            step.id != "resolve_name"
                            or run.parameters.get("input_mode") != "coordinates"
                        ):
                            raise ValueError("无效跳过步骤")
                        continue
                    if step.state != "succeeded":
                        continue
                    attempt = step.attempts[-1]
                    value, dependencies = prepare_input(run, step.id)
                    software = step_software(step.id)
                    if (
                        attempt.software != software
                        or attempt.input != value
                        or [d.model_dump() for d in attempt.dependencies]
                        != [d.model_dump() for d in dependencies]
                        or attempt.input_sha256
                        != input_digest(run, step, value, dependencies, software)
                    ):
                        raise ValueError("输入、上游摘要或软件版本已变化")
                    if attempt.output is None or attempt.output_sha256 != digest(attempt.output):
                        raise ValueError("成功输出缺失或摘要不符")
                    if attempt.snapshot_id:
                        snapshot = Snapshot.model_validate(
                            self.projects._get(db, "snapshots", attempt.snapshot_id, run.project_id)
                        ).verify_digest()
                        if (
                            snapshot.sha256 != attempt.output["response_sha256"]
                            or not db.execute(
                                "SELECT 1 FROM workflow_snapshot_refs "
                                "WHERE run_id=? AND snapshot_id=?",
                                (run.id, snapshot.id),
                            ).fetchone()
                        ):
                            raise ValueError("快照引用或内容已失效")
                    for identifier in attempt.output_ids:
                        row = db.execute(
                            "SELECT record,content FROM workflow_outputs WHERE id=? AND run_id=?",
                            (identifier, run.id),
                        ).fetchone()
                        if row is None:
                            raise ValueError("成功步骤的文件缺失")
                        info = WorkflowOutput.model_validate_json(row[0])
                        if (
                            info.attempt_id != attempt.id
                            or len(row[1]) != info.bytes
                            or hashlib.sha256(row[1]).hexdigest() != info.sha256
                        ):
                            raise ValueError("成功步骤文件哈希不符")
            except (ValueError, KeyError, IndexError, TypeError) as exc:
                raise ServiceError(
                    422,
                    "workflow_checkpoint_invalid",
                    "保存的检查点或依赖已失效，请核查后新建运行。",
                ) from exc
            except ServiceError as exc:
                if exc.status_code != 404:
                    raise
                raise ServiceError(
                    422, "workflow_checkpoint_invalid", "检查点引用缺失，请保留历史并新建运行。"
                ) from exc

    def reserve_operation(self, project_id, run_id, request, request_hash):
        with self.repo.connection() as db, self.repo.transaction(db):
            run = self._run(db, project_id, run_id, request.expected_revision)
            if run.state == "running":
                raise ServiceError(409, "workflow_busy", "该流程仍在执行，请读取状态。")
            if (
                db.execute(
                    "SELECT count(*) FROM workflow_operations WHERE run_id=?", (run_id,)
                ).fetchone()[0]
                >= 20
            ):
                raise ServiceError(
                    409, "workflow_operation_limit", "流程执行请求记录已满，请保留历史并新建运行。"
                )
            operation = WorkflowOperation(
                id=str(uuid4()),
                run_id=run_id,
                client_request_id=request.client_request_id,
                state="running",
                created_at=utc_now(),
            )
            db.execute(
                "INSERT INTO workflow_operations VALUES (?,?,?,?,?,?,?)",
                (
                    operation.id,
                    run_id,
                    request.client_request_id,
                    request_hash,
                    "running",
                    operation.model_dump_json(),
                    OPERATION_RESERVE,
                ),
            )
            run.state = "running"
            run.error = None
            self._save(db, run)
            self.projects._budget(db)
            return operation

    def begin_step(self, project_id, run_id, operation, step_id):
        with self.repo.connection() as db, self.repo.transaction(db):
            run = self._run(db, project_id, run_id)
            step = next(s for s in run.steps if s.id == step_id)
            if len(step.attempts) >= 5:
                raise ServiceError(
                    409, "workflow_attempt_limit", "该步骤已达到5次尝试，请新建运行。"
                )
            value, dependencies = prepare_input(run, step.id)
            software = step_software(step.id)
            attempt = StepAttempt(
                id=str(uuid4()),
                operation_id=operation.id,
                client_request_id=operation.client_request_id,
                sequence=len(step.attempts) + 1,
                state="running",
                input=value,
                input_sha256=input_digest(run, step, value, dependencies, software),
                dependencies=dependencies,
                software=software,
                started_at=utc_now(),
            )
            step.attempts.append(attempt)
            step.state = "running"
            step.error = None
            run.current_step_id = step_id
            reserve = self.repo.settings.turn_bytes * (
                2 if step_id in ("save_snapshot", "evidence_table", "export_results") else 1
            )
            db.execute(
                "UPDATE workflows SET reserved_bytes=? WHERE id=?",
                (reserve + OPERATION_RESERVE, run.id),
            )
            self._save(db, run)
            self.projects._budget(db)
            return run, attempt

    def _snapshot(self, db, run, response):
        now, cid, tid = utc_now(), str(uuid4()), str(uuid4())
        turn = Turn(
            conversation_id=cid,
            turn_id=tid,
            revision=1,
            client_request_id=str(uuid4()),
            message="固定流程输出（无模型调用）：" + run.name,
            execution_status="completed",
            received_at=now,
            completed_at=now,
            response=response,
        )
        raw = turn.model_dump_json()
        if len(raw.encode()) > self.repo.settings.turn_bytes:
            raise ServiceError(413, "workflow_result_too_large", "完整流程输出超过单条记录上限。")
        db.execute(
            "INSERT INTO conversations VALUES (?,?,?,?,?,?)",
            (cid, "流程 · " + run.name[:70], now, now, 1, 0),
        )
        db.execute("INSERT INTO project_conversations VALUES (?,?)", (cid, run.project_id))
        db.execute(
            "INSERT INTO turns VALUES (?,?,?,?,?,?,?,?,0)",
            (
                tid,
                cid,
                1,
                turn.client_request_id,
                digest({"workflow": run.id}),
                "completed",
                raw,
                len(raw.encode()),
            ),
        )
        value = self.projects.make_snapshot(run.project_id, run.name, turn)
        self.projects._insert_snapshot(db, value)
        db.execute("INSERT INTO workflow_snapshot_refs VALUES (?,?)", (run.id, value["id"]))
        return value["id"]

    def finish_step(self, project_id, run_id, attempt_id, product, elapsed):
        with self.repo.connection() as db, self.repo.transaction(db):
            run = self._run(db, project_id, run_id)
            step = next(s for s in run.steps if s.attempts and s.attempts[-1].id == attempt_id)
            attempt = step.attempts[-1]
            attempt.state = "failed" if product.error else "succeeded"
            attempt.completed_at = utc_now()
            attempt.elapsed_seconds = max(0, elapsed)
            attempt.output = product.output
            attempt.output_sha256 = digest(product.output) if product.output is not None else None
            attempt.error = product.error
            attempt.query_status = product.query_status
            attempt.export_status = product.export_status
            attempt.warnings = product.warnings
            if not product.error:
                if product.snapshot_response is not None:
                    attempt.snapshot_id = self._snapshot(db, run, product.snapshot_response)
                for filename, media, data in product.files:
                    if len(data) > MAX_OUTPUT_BYTES:
                        raise ServiceError(
                            413, "workflow_output_too_large", "完整文件超过16 MiB，未截断保存。"
                        )
                    info = WorkflowOutput(
                        id=str(uuid4()),
                        run_id=run.id,
                        project_id=project_id,
                        attempt_id=attempt.id,
                        filename=filename,
                        media_type=media,
                        bytes=len(data),
                        sha256=hashlib.sha256(data).hexdigest(),
                        created_at=utc_now(),
                    )
                    db.execute(
                        "INSERT INTO workflow_outputs VALUES (?,?,?,?)",
                        (info.id, run.id, info.model_dump_json(), data),
                    )
                    attempt.output_ids.append(info.id)
            step.state = attempt.state
            step.error = product.error
            if product.error:
                run.state = "failed"
                run.error = product.error
            db.execute("UPDATE workflows SET reserved_bytes=0 WHERE id=?", (run.id,))
            self._save(db, run)
            self.projects._budget(db)
            return run

    def finish_operation(self, project_id, run_id, operation_id, error=None):
        with self.repo.connection() as db, self.repo.transaction(db):
            run = self._run(db, project_id, run_id)
            row = db.execute(
                "SELECT record FROM workflow_operations WHERE id=? AND run_id=?",
                (operation_id, run_id),
            ).fetchone()
            operation = WorkflowOperation.model_validate_json(row[0])
            if error:
                run.error = error
                run.state = "failed"
                for step in run.steps:
                    if step.state == "running":
                        step.state = "interrupted"
                        attempt = step.attempts[-1]
                        attempt.state = "interrupted"
                        attempt.completed_at = utc_now()
                        attempt.error = ErrorInfo(
                            code="workflow_commit_unknown",
                            message="远端可能已执行但输出未确认保存；需要显式创建新尝试。",
                            retryable=True,
                        )
                        step.error = attempt.error
                        run.state = "interrupted"
            elif all(s.state in ("succeeded", "skipped") for s in run.steps):
                run.state = "succeeded"
                run.current_step_id = None
            operation.state = run.state
            operation.error = run.error
            operation.completed_at = utc_now()
            db.execute(
                "UPDATE workflow_operations SET state=?,record=?,reserved_bytes=0 WHERE id=?",
                (operation.state, operation.model_dump_json(), operation.id),
            )
            db.execute("UPDATE workflows SET reserved_bytes=0 WHERE id=?", (run.id,))
            self._save(db, run)
            self.projects._budget(db)
            return operation

    def delete(self, project_id, run_id, request):
        with self.repo.connection() as db, self.repo.transaction(db):
            run = self._run(db, project_id, run_id, request.expected_revision)
            if not request.confirmed:
                raise ServiceError(
                    422, "workflow_confirmation_required", "请确认只删除流程及其专属输出。"
                )
            if run.state == "running":
                raise ServiceError(409, "workflow_busy", "运行中的流程不能删除。")
            from astroagent.project_links import invalidate

            invalidate(
                db,
                project_id,
                target_type="workflow_run",
                target_ids=[run_id],
                reason="workflow_deleted",
            )
            db.execute("DELETE FROM workflows WHERE id=?", (run_id,))
            self.projects._touch(db, project_id)

    @staticmethod
    def recover(db):
        now = utc_now()
        for row in db.execute("SELECT record FROM workflows WHERE state='running'").fetchall():
            run = WorkflowRun.model_validate_json(row[0])
            error = ErrorInfo(
                code="workflow_interrupted",
                message="服务重启中断流程；远端调用可能已执行，未自动重放。",
                retryable=True,
            )
            run.state, run.error, run.updated_at = "interrupted", error, now
            run.revision += 1
            for step in run.steps:
                if step.state == "running":
                    step.state, step.error = "interrupted", error
                    attempt = step.attempts[-1]
                    attempt.state, attempt.error, attempt.completed_at = "interrupted", error, now
                    attempt.elapsed_seconds = max(
                        0,
                        (
                            datetime.fromisoformat(now) - datetime.fromisoformat(attempt.started_at)
                        ).total_seconds(),
                    )
            db.execute(
                "UPDATE workflows SET state='interrupted',record=?,reserved_bytes=0 WHERE id=?",
                (run.model_dump_json(), run.id),
            )
            project = ProjectRepository._get(db, "projects", run.project_id)
            project["revision"] += 1
            project["updated_at"] = now
            ProjectRepository._put(db, "projects", project)
        for row in db.execute(
            "SELECT record FROM workflow_operations WHERE state='running'"
        ).fetchall():
            operation = WorkflowOperation.model_validate_json(row[0])
            operation.state, operation.completed_at = "interrupted", now
            operation.error = ErrorInfo(
                code="workflow_interrupted",
                message="操作中断，不会自动再次访问数据源。",
                retryable=True,
            )
            db.execute(
                "UPDATE workflow_operations SET state='interrupted',record=?,reserved_bytes=0 "
                "WHERE id=?",
                (operation.model_dump_json(), operation.id),
            )
