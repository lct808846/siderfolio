"""Format5 RAG history. No previews, credentials, model files or vectors in a project ZIP."""

import json
import re
from copy import deepcopy
from uuid import uuid4

from astroagent.conversations import encode
from astroagent.export_schemas import _strict_type
from astroagent.rag_schemas import RagAnswer, RagRequestRecord
from astroagent.workflow_templates import digest


def empty_rag():
    return {"answers": [], "requests": []}


def read_rag(db, project_id):
    if getattr(db, "dialect", None) != "postgresql":
        return empty_rag()
    return {
        key: [
            json.loads(row[0])
            for row in db.execute(
                f"SELECT record FROM {table} WHERE project_id=? ORDER BY id", (project_id,)
            )
        ]
        for key, table in (("answers", "rag_answers"), ("requests", "rag_answer_requests"))
    }


def validate_rag(raw, project_id, knowledge):
    if (
        not isinstance(raw, dict)
        or set(raw) != {"answers", "requests"}
        or not all(isinstance(v, list) for v in raw.values())
        or len(raw["answers"]) > 100
        or len(raw["requests"]) > 1000
    ):
        raise ValueError("Invalid RAG member")
    answers = [
        _strict_type(RagAnswer).model_validate_json(encode(value)) for value in raw["answers"]
    ]
    requests = [
        _strict_type(RagRequestRecord).model_validate_json(encode(value))
        for value in raw["requests"]
    ]
    for values in (answers, requests):
        if len({v.id for v in values}) != len(values) or len(
            {v.client_request_id for v in values}
        ) != len(values):
            raise ValueError("Duplicate RAG identity")
    evidence = {value["id"]: value for value in knowledge["evidence"]}
    request_map = {v.answer_id: v for v in requests}
    if len(request_map) != len(requests):
        raise ValueError("Multiple RAG creation requests claim the same answer")
    from astroagent.project_schemas import Project

    for record in answers:
        Project.utc(record.created_at)
        if record.completed_at:
            Project.utc(record.completed_at)
        if (
            record.project_id != project_id
            or not 1 <= len(record.evidence) <= 8
            or len(record.history_ids) > 3
        ):
            raise ValueError("Invalid RAG project or scope")
        operation = request_map.get(record.id)
        if operation is None or operation.client_request_id != record.client_request_id:
            raise ValueError("RAG answer has no matching operation")
        labels = {item.label for item in record.evidence}
        if (
            labels != {f"E{i + 1}" for i in range(len(record.evidence))}
            or not set(record.citation_labels) <= labels
        ):
            raise ValueError("Invalid RAG citation labels")
        if any(identifier not in request_map for identifier in record.history_ids):
            raise ValueError("Missing RAG history identity without creation tombstone")
        if record.state == "completed":
            inline = set(re.findall(r"\[(E[0-9]+)\]", record.answer))
            if (
                not inline
                or inline != set(record.citation_labels)
                or not inline <= labels
                or len(record.answer) > 4000
            ):
                raise ValueError("Completed RAG answer has invalid citations")
        for item in record.evidence:
            old = item.view.evidence
            if item.view.text is not None or old.project_id != project_id:
                raise ValueError("RAG records must not duplicate raw excerpts")
            current = evidence.get(old.id)
            if current is None:
                raise ValueError("Missing frozen RAG evidence")
            if current and any(
                current[field] != getattr(old, field)
                for field in (
                    "document_id",
                    "version_id",
                    "unit_id",
                    "document_sha256",
                    "text_sha256",
                    "char_start",
                    "char_end",
                    "page",
                    "line_start",
                    "line_end",
                )
            ):
                raise ValueError("RAG changed fixed evidence identity")
    for request in requests:
        if request.project_id != project_id:
            raise ValueError("RAG request outside project")
        Project.utc(request.created_at)
    return {
        "answers": [v.model_dump(mode="json") for v in answers],
        "requests": [v.model_dump(mode="json") for v in requests],
    }


def import_rag(db, bundle, project_id, id_map, archive_sha):
    if not bundle["answers"] and not bundle["requests"]:
        return
    if getattr(db, "dialect", None) != "postgresql":
        raise ValueError("RAG history requires PostgreSQL runtime")
    answer_ids = {v["id"] for v in bundle["answers"]} | {v["answer_id"] for v in bundle["requests"]}
    id_map["rag_answers"] = {old: str(uuid4()) for old in answer_ids}
    id_map["rag_requests"] = {v["id"]: str(uuid4()) for v in bundle["requests"]}
    soft = id_map.setdefault("rag_soft_references", {})

    def ref(group, old):
        if old is None:
            return None
        return id_map.get(group, {}).get(old) or soft.setdefault(group + ":" + old, str(uuid4()))

    operations = {}
    for old in bundle["requests"]:
        value = deepcopy(old)
        value.update(
            id=id_map["rag_requests"][old["id"]],
            project_id=project_id,
            client_request_id=str(uuid4()),
            answer_id=ref("rag_answers", old["answer_id"]),
            original_id=old["id"],
        )
        value["request_sha256"] = digest(
            {"imported": archive_sha, "request": value["client_request_id"]}
        )
        operations[old["answer_id"]] = value
        db.execute(
            "INSERT INTO rag_answer_requests VALUES (?,?,?,?,?,?)",
            (
                value["id"],
                project_id,
                value["client_request_id"],
                value["request_sha256"],
                value["answer_id"],
                encode(value),
            ),
        )
    for old in bundle["answers"]:
        value = deepcopy(old)
        operation = operations[old["id"]]
        value.update(
            id=ref("rag_answers", old["id"]),
            project_id=project_id,
            client_request_id=operation["client_request_id"],
            preview_id=ref("rag_previews", old["preview_id"]),
            history_ids=[ref("rag_answers", identifier) for identifier in old["history_ids"]],
            document_ids=[
                ref("knowledge_documents", identifier) for identifier in old["document_ids"]
            ],
            version_ids=[
                ref("knowledge_versions", identifier) for identifier in old["version_ids"]
            ],
            index_id=ref("rag_indexes", old["index_id"]),
            provenance="imported_unverified",
            original_id=old["id"],
            archive_sha256=archive_sha,
        )
        if value["state"] == "running":
            value.update(state="interrupted", error="导入的运行记录不自动重试。")
        for item in value["evidence"]:
            view, evidence = item["view"], item["view"]["evidence"]
            for key, group in (
                ("id", "knowledge_evidence"),
                ("document_id", "knowledge_documents"),
                ("version_id", "knowledge_versions"),
                ("unit_id", "knowledge_units"),
            ):
                evidence[key] = ref(group, evidence[key])
            evidence.update(project_id=project_id, validity="original_unavailable")
            view.update(
                text=None, content_url=None, warning="导入的固定引用须重新核对原文，来源未经认证。"
            )
        db.execute(
            "INSERT INTO rag_answers VALUES (?,?,?,?,?,?,0)",
            (
                value["id"],
                project_id,
                value["client_request_id"],
                operation["request_sha256"],
                value["state"],
                encode(value),
            ),
        )
