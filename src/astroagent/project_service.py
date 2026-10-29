"""明确选择单工具的直接重跑，以及只读、确定性的快照比较。"""

import threading

from astroagent.ads import AdsService
from astroagent.config import Settings
from astroagent.conversations import utc_now
from astroagent.errors import ServiceError
from astroagent.export_schemas import ExportSnapshot, validate_snapshot
from astroagent.gaia import GaiaService
from astroagent.projects import ProjectRepository
from astroagent.schemas import ChatResponse, GaiaQuery, LiteratureQuery, ObjectQuery
from astroagent.simbad import SimbadService

FAMILIES = {"simbad": "results", "ads": "literature_results", "gaia": "gaia_results"}


def selection(snapshot, family, index):
    try:
        result = snapshot["response"][FAMILIES[family]][index]
        if family == "simbad":
            parameters = ObjectQuery(object_name=result["object_name"]).model_dump()
        elif family == "ads":
            parameters = LiteratureQuery(
                **{k: result[k] for k in LiteratureQuery.model_fields}
            ).model_dump()
        else:
            parameters = GaiaQuery.model_validate(result["query"]).effective_parameters()
        return parameters
    except (IndexError, KeyError, ValueError, TypeError) as exc:
        raise ServiceError(
            422, "rerun_not_supported", "所选结果缺少当前契约支持的完整参数。"
        ) from exc


def get_executor():
    # No language model is constructed or invoked by this path.
    try:
        settings = Settings()
    except ValueError as exc:
        raise ServiceError(503, "invalid_configuration", "服务端工具配置无效。") from exc

    def execute(family, parameters):
        if family == "simbad":
            return SimbadService(settings.simbad_timeout_seconds).query(
                ObjectQuery(**parameters).object_name
            )
        if family == "ads":
            return AdsService(settings.ads_api_token, settings.ads_timeout_seconds).search(
                LiteratureQuery(**parameters)
            )
        return GaiaService(settings.gaia_timeout_seconds).query(GaiaQuery(**parameters))

    return execute


class ProjectService:
    def __init__(self, conversation_service):
        self.conversations = conversation_service
        self.repository = ProjectRepository(conversation_service.repository)
        self.archive_export_slot = threading.Lock()
        self.archive_import_slot = threading.Lock()

    def rerun(self, project_id, snapshot_id, request, executor_factory=get_executor):
        service = self.conversations
        with service.gate:
            existing, digest = self.repository.existing_rerun(project_id, snapshot_id, request)
            if existing:
                return existing, 202 if existing["state"] == "running" else 200
            if not request.confirmed:
                raise ServiceError(
                    422, "rerun_confirmation_required", "请先核对参数并明确确认本次外部查询。"
                )
            snapshot = self.repository.snapshot(project_id, snapshot_id)
            parameters = selection(snapshot, request.family, request.result_index)
            if not service.slots.acquire(blocking=False):
                raise ServiceError(
                    503,
                    "conversation_service_busy",
                    "已有两轮任务正在处理，请稍后重试。",
                    retryable=True,
                )
            try:
                record, turn = self.repository.reserve_rerun(
                    project_id, snapshot_id, request, parameters, digest
                )
            except Exception:
                service.slots.release()
                raise
        try:
            result = executor_factory()(request.family, parameters)
            sources = (
                [p.source for p in result.papers] if request.family == "ads" else [result.source]
            )
            unique = {s.url: s for s in reversed(sources)} if result.status == "success" else {}
            response = ChatResponse(
                status="success" if result.status == "success" else "error",
                answer="程序直接重跑结果（未调用语言模型）。请核查实际参数、状态、来源时间与科学限制。",
                sources=list(reversed(list(unique.values()))),
                **{FAMILIES[request.family]: [result]},
            )
            validate_snapshot(ExportSnapshot.model_validate_json(response.model_dump_json()))
            turn.response = response
            turn.execution_status = "completed"
        except Exception as exc:
            turn.execution_status = "failed"
            turn.error = (
                exc.error
                if isinstance(exc, ServiceError)
                else ServiceError(
                    502, "rerun_failed", "直接重跑未完成，请核对保存状态。", retryable=True
                ).error
            )
        finally:
            turn.completed_at = utc_now()
            try:
                with service.gate:
                    record = self.repository.finish_rerun(record, turn)
            finally:
                service.slots.release()
        return record, 200


def snapshot_summary(snapshot):
    response = snapshot["response"]
    tools = []
    for family, field in FAMILIES.items():
        for index, result in enumerate(response[field]):
            tools.append(
                {
                    "family": family,
                    "result_index": index,
                    "parameters": selection(snapshot, family, index),
                    **{
                        k: result.get(k)
                        for k in (
                            "status",
                            "returned_count",
                            "total_found",
                            "has_more",
                            "truncated",
                            "archive_overflow",
                            "source",
                            "error",
                            "release",
                            "table",
                            "data",
                        )
                        if k != "data" or family == "simbad"
                    },
                }
            )
    return {
        "name": snapshot["name"],
        "created_at": snapshot["created_at"],
        "status": response["status"],
        "software": snapshot["software"],
        "provenance": snapshot["provenance"],
        "sha256": snapshot["sha256"],
        "tools": tools,
    }


def compare_snapshots(left, right, match_identifiers=False):
    a, b = snapshot_summary(left), snapshot_summary(right)
    differences = []

    def walk(x, y, path):
        if isinstance(x, dict) and isinstance(y, dict):
            for key in sorted(x.keys() | y.keys()):
                child = path + "/" + key.replace("~", "~0").replace("/", "~1")
                if key not in x or key not in y:
                    differences.append(
                        {
                            "path": child,
                            "kind": "added" if key in y else "removed",
                            "left": {"present": key in x, "value": x.get(key)},
                            "right": {"present": key in y, "value": y.get(key)},
                        }
                    )
                else:
                    walk(x[key], y[key], child)
        elif isinstance(x, list) and isinstance(y, list):
            for index in range(max(len(x), len(y))):
                if index >= len(x) or index >= len(y):
                    differences.append(
                        {
                            "path": path + "/" + str(index),
                            "kind": "added" if index >= len(x) else "removed",
                            "left": {
                                "present": index < len(x),
                                "value": x[index] if index < len(x) else None,
                            },
                            "right": {
                                "present": index < len(y),
                                "value": y[index] if index < len(y) else None,
                            },
                        }
                    )
                else:
                    walk(x[index], y[index], path + "/" + str(index))
        elif type(x) is not type(y) or x != y:
            differences.append(
                {
                    "path": path,
                    "kind": "changed",
                    "left": {"present": True, "value": x},
                    "right": {"present": True, "value": y},
                }
            )

    walk(a, b, "")
    matches = []
    if match_identifiers:
        for family, field in (("gaia", "gaia_results"), ("ads", "literature_results")):
            for i, x in enumerate(left["response"][field]):
                for j, y in enumerate(right["response"][field]):
                    allowed = (
                        family == "ads"
                        or all(x.get(k) == y.get(k) for k in ("endpoint", "release", "table"))
                        and x["query"].get("mode") == y["query"].get("mode")
                    )
                    if not allowed:
                        continue
                    rows, key = ("data", "source_id") if family == "gaia" else ("papers", "bibcode")
                    xs, ys = (
                        {r[key] for r in x[rows] if r.get(key)},
                        {r[key] for r in y[rows] if r.get(key)},
                    )
                    matches.append(
                        {
                            "family": family,
                            "left_index": i,
                            "right_index": j,
                            "intersection": sorted(xs & ys),
                            "left_only": sorted(xs - ys),
                            "right_only": sorted(ys - xs),
                        }
                    )
    return {
        "left_id": left["id"],
        "right_id": right["id"],
        "left": a,
        "right": b,
        "differences": differences,
        "identifiers": matches,
        "warnings": [
            "仅比较交付样本与查询元数据；不表示总体增减、显著性或成员变化。",
            "Gaia只在同源、同发布版和同查询模式时按精确字符串编号比较；未推断空间匹配或科学等价。",
        ],
    }
