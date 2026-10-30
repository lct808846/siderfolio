"""两个固定模板的同步执行器；只复用现有工具与导出器，不构造模型。"""

import time
from dataclasses import dataclass, field

from astroagent.api.exports import MAX_REQUEST_BYTES, validate_json
from astroagent.conversations import encode
from astroagent.errors import ServiceError
from astroagent.export_schemas import ExportSnapshot, validate_snapshot
from astroagent.exports import CSV_POLICY, build_package, csv_bytes, json_bytes
from astroagent.project_service import get_executor
from astroagent.schemas import ChatResponse, ErrorInfo
from astroagent.workflow_io import package_members
from astroagent.workflow_templates import completed_attempt, digest, response_attempt
from astroagent.workflows import WorkflowRepository


@dataclass
class StepProduct:
    output: dict | None = None
    files: list = field(default_factory=list)
    snapshot_response: ChatResponse | None = None
    query_status: str | None = None
    export_status: str | None = None
    error: ErrorInfo | None = None
    warnings: list[str] = field(default_factory=list)


def response_for(run, family, result):
    results = {"results": [], "gaia_results": [], "literature_results": []}
    if run.template_id == "gaia_field" and run.parameters["input_mode"] == "name":
        from astroagent.schemas import QueryResult

        results["results"] = [
            QueryResult.model_validate(completed_attempt(run, "resolve_name").output["result"])
        ]
    results[{"gaia": "gaia_results", "ads": "literature_results"}[family]] = [result]
    all_results = [r for values in results.values() for r in values]
    successes = [r for r in all_results if r.status == "success"]
    sources = []
    for entry in successes:
        candidates = (
            [p.source for p in entry.papers] if hasattr(entry, "papers") else [entry.source]
        )
        for source in candidates:
            if source.url not in {s.url for s in sources}:
                sources.append(source)
    response = ChatResponse(
        status="success"
        if len(successes) == len(all_results)
        else "partial"
        if successes
        else "error",
        answer=(
            "固定科研流程程序输出，未调用语言模型。请核对条件、时间和来源；"
            + (
                "位置候选源不等于成员，统计与图表只描述交付行，未做自行传播。"
                if family == "gaia"
                else "证据表仅整理实际返回的书目与原摘要，不是全文阅读或系统综述。"
            )
        ),
        sources=sources,
        **results,
    )
    validate_snapshot(ExportSnapshot.model_validate_json(response.model_dump_json()))
    return response


def evidence_rows(response):
    columns = [
        "bibcode",
        "title",
        "authors",
        "year",
        "publication",
        "doi",
        "abstract",
        "abstract_status",
        "source_url",
        "retrieved_at",
        "missing_fields",
        "long_fields",
    ]
    rows, changes, csv_rows = [], [], []
    for paper in response.literature_results[0].papers:
        raw = paper.model_dump(mode="json")
        source = raw.pop("source")
        raw.pop("citation_count", None)
        row = {
            **raw,
            "abstract_status": "missing"
            if paper.abstract is None or paper.abstract == ""
            else "provided",
            "source_url": source["url"],
            "retrieved_at": source["retrieved_at"],
            "missing_fields": [
                key
                for key in ("title", "authors", "year", "publication", "doi", "abstract")
                if raw.get(key) is None or raw.get(key) == "" or raw.get(key) == []
            ],
            "long_fields": [],
        }
        shortened = dict(row)
        for key, value in row.items():
            preview = encode(value) if isinstance(value, (dict, list)) else value
            if isinstance(preview, str) and len(preview) > 32766:
                shortened[key] = preview[:32766]
                row["long_fields"].append(key)
                changes.append(
                    {
                        "file": "ads-evidence.csv",
                        "data_row": len(rows) + 1,
                        "column": key,
                        "reason": "csv_text_preview_32766_characters",
                    }
                )
        rows.append(row)
        csv_rows.append(shortened)
    content = csv_bytes("ads-evidence.csv", columns, csv_rows, changes)
    value = {
        "format_version": "1",
        "columns": columns,
        "rows": rows,
        "query_status": response.literature_results[0].status,
        "source": response.literature_results[0].source.model_dump(mode="json"),
        "csv_policy": {
            **CSV_POLICY,
            "text_preview_limit": 32766,
            "raw_values": "ads-evidence.json",
        },
        "csv_changes": changes,
    }
    return value, content


class WorkflowService:
    def __init__(self, conversation_service):
        self.conversations = conversation_service
        self.repository = WorkflowRepository(conversation_service.repository)

    def execute(self, project_id, run_id, request, executor_factory=get_executor):
        service = self.conversations
        with service.gate:
            existing, request_hash = self.repository.existing(project_id, run_id, request)
            if existing is not None:
                return {
                    "operation": existing,
                    "run": self.repository.detail(project_id, run_id),
                }, 202 if existing.state == "running" else 200
            if not request.confirmed:
                raise ServiceError(
                    422,
                    "workflow_confirmation_required",
                    "请核对步骤、参数和数据源后明确启动或继续。",
                )
            run = self.repository.read(project_id, run_id)
            if run.state == "running":
                raise ServiceError(409, "workflow_busy", "该流程正在运行，请读取状态。")
            if run.state == "succeeded":
                raise ServiceError(
                    409, "workflow_already_completed", "流程已完成；需要新查询时请新建运行。"
                )
            self.repository.validate_reuse(run)
            if not service.slots.acquire(blocking=False):
                raise ServiceError(
                    503,
                    "conversation_service_busy",
                    "已有两项执行任务，请稍后重试。",
                    retryable=True,
                )
            try:
                operation = self.repository.reserve_operation(
                    project_id, run_id, request, request_hash
                )
            except Exception:
                service.slots.release()
                raise
        failure = None
        try:
            for step in run.steps:
                if step.state in ("succeeded", "skipped"):
                    continue
                with service.gate:
                    current, attempt = self.repository.begin_step(
                        project_id, run_id, operation, step.id
                    )
                started = time.perf_counter()
                try:
                    product = self.perform(current, step.id, attempt.input, executor_factory)
                except ServiceError as exc:
                    product = StepProduct(error=exc.error)
                except Exception:
                    product = StepProduct(
                        error=ErrorInfo(
                            code="workflow_step_failed",
                            message="本步骤未能完成，请核查已保存记录。",
                            retryable=True,
                        )
                    )
                with service.gate:
                    current = self.repository.finish_step(
                        project_id, run_id, attempt.id, product, time.perf_counter() - started
                    )
                if current.state == "failed":
                    break
        except ServiceError as exc:
            failure = exc.error
        except Exception:
            failure = ErrorInfo(
                code="workflow_execution_failed",
                message="执行状态未完整确认，请读取流程记录。",
                retryable=True,
            )
        finally:
            try:
                with service.gate:
                    operation = self.repository.finish_operation(
                        project_id, run_id, operation.id, failure
                    )
            finally:
                service.slots.release()
        return {"operation": operation, "run": self.repository.detail(project_id, run_id)}, 200

    def perform(self, run, step_id, actual, executor_factory):
        if step_id == "resolve_name":
            result = executor_factory()("simbad", actual["parameters"])
            output = {"result": result.model_dump(mode="json")}
            if (
                result.status != "success"
                or result.data is None
                or result.data.ra_deg is None
                or result.data.dec_deg is None
            ):
                return StepProduct(
                    output=output,
                    query_status=result.status,
                    error=result.error
                    or ErrorInfo(
                        code="workflow_missing_coordinates",
                        message="SIMBAD没有可用ICRS坐标，未执行依赖查询。",
                    ),
                )
            output["coordinates"] = {"ra_deg": result.data.ra_deg, "dec_deg": result.data.dec_deg}
            return StepProduct(
                output=output,
                query_status=result.status,
                warnings=["后续查询沿用本次SIMBAD坐标，未做自行传播。"],
            )
        if step_id in ("query_gaia", "query_ads"):
            family = actual["family"]
            result = executor_factory()(family, actual["parameters"])
            response = response_for(run, family, result)
            return StepProduct(
                output={"response": response.model_dump(mode="json")},
                query_status=result.status,
                error=result.error if result.status == "error" else None,
                warnings=(
                    ["没有匹配结果，后续仅保存空结果及状态。"]
                    if result.status == "not_found"
                    else []
                ),
            )
        response = ChatResponse.model_validate(response_attempt(run).output["response"])
        if step_id == "evidence_table":
            value, content = evidence_rows(response)
            return StepProduct(
                output=value,
                files=[
                    ("ads-evidence.csv", "text/csv", content),
                    ("ads-evidence.json", "application/json", json_bytes(value)),
                ],
                query_status=response.literature_results[0].status,
                warnings=["CSV中的长文本是明确标记的预览，原文与原始值在JSON中保留。"]
                if value["csv_changes"]
                else [],
            )
        if step_id == "save_snapshot":
            return StepProduct(
                output={
                    "response_sha256": digest(response.model_dump(mode="json")),
                    "status": response.status,
                },
                snapshot_response=response,
            )
        source = completed_attempt(run, "save_snapshot")
        snapshot = self.repository.projects.snapshot(run.project_id, source.snapshot_id)
        raw = encode(
            {"schema_version": "1", "snapshot": snapshot["response"], "plots": actual["plots"]}
        ).encode()
        if len(raw) > MAX_REQUEST_BYTES:
            raise ServiceError(
                413,
                "workflow_export_too_large",
                "完整导出请求超过2 MiB；查询快照保留，未裁剪数据。",
            )
        package = build_package(validate_json(raw))
        members, manifest = package_members(package)
        files = [("workflow-results.zip", "application/zip", package)]
        files.append(("export-manifest.json", "application/json", members["manifest.json"]))
        for path, content in members.items():
            if path.endswith(".png"):
                files.append((path.rsplit("/", 1)[-1], "image/png", content))
        warnings = [
            f"图表 {p.get('kind')} 未生成：{p.get('reason')}"
            for p in manifest["plots"]
            if p["status"] != "success"
        ]
        return StepProduct(
            output={"manifest": manifest, "answer_origin": "program_fixed_workflow"},
            files=files,
            export_status=manifest["export_status"],
            warnings=warnings,
        )
