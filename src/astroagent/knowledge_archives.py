"""格式3知识库归档：原文选择、严格关系检查和原子身份映射。"""

import base64
import hashlib
import json
from copy import deepcopy
from uuid import uuid4

from astroagent.conversations import encode, utc_now
from astroagent.errors import ServiceError
from astroagent.export_schemas import _strict_type
from astroagent.knowledge import FTS_TABLES, indexes_available
from astroagent.knowledge_schemas import (
    DocumentVersion,
    EvidenceRecord,
    KnowledgeDocument,
    KnowledgeOperation,
    TextSource,
    TextUnit,
)
from astroagent.knowledge_service import file_type
from astroagent.knowledge_text import checksum, normalize, segment
from astroagent.project_schemas import Project


def empty_bundle():
    return {
        "mode": "metadata",
        "sources_complete": True,
        "documents": [],
        "versions": [],
        "sources": [],
        "units": [],
        "evidence": [],
        "operations": [],
    }


def read_knowledge(db, project_id, mode, confirmed):
    value = empty_bundle()
    value["mode"] = mode
    value["documents"] = [
        json.loads(r[0])
        for r in db.execute(
            "SELECT record FROM knowledge_documents WHERE project_id=? ORDER BY id", (project_id,)
        )
    ]
    value["evidence"] = [
        json.loads(r[0])
        for r in db.execute(
            "SELECT record FROM knowledge_evidence WHERE project_id=? ORDER BY id", (project_id,)
        )
    ]
    value["operations"] = [
        json.loads(r[0])
        for r in db.execute(
            "SELECT record FROM knowledge_operations WHERE project_id=? ORDER BY id", (project_id,)
        )
    ]
    if mode == "full" and not confirmed:
        raise ServiceError(
            422,
            "knowledge_archive_confirmation_required",
            "完整备份会复制所有文献原文件，请先明确确认。",
        )
    # Reject before building base64 envelopes that cannot fit the fixed 64 MiB member.
    size = db.execute(
        "SELECT coalesce(sum(length(record)+coalesce(length(content),0)*4/3),0) "
        "FROM knowledge_versions WHERE project_id=?",
        (project_id,),
    ).fetchone()[0]
    if mode == "full" and size > 64 * 1024**2:
        raise ServiceError(
            413, "project_archive_too_large", "含原文知识库超过归档单成员上限，未丢弃原文。"
        )
    for row in db.execute(
        "SELECT record,content FROM knowledge_versions WHERE project_id=? ORDER BY id",
        (project_id,),
    ):
        info = json.loads(row[0])
        if mode == "full" and (
            row[1] is None
            or len(row[1]) != info["bytes"]
            or hashlib.sha256(row[1]).hexdigest() != info["sha256"]
        ):
            raise ServiceError(
                409,
                "knowledge_archive_original_missing",
                "存在缺失或损坏原文，不能生成完整备份；可明确选择仅元数据。",
            )
        value["versions"].append(
            {
                "info": info,
                "content_base64": base64.b64encode(row[1]).decode("ascii")
                if mode == "full"
                else None,
            }
        )
    for row in db.execute(
        "SELECT s.record FROM knowledge_sources s JOIN knowledge_versions v "
        "ON v.id=s.version_id WHERE v.project_id=? ORDER BY s.version_id,s.position",
        (project_id,),
    ):
        source = json.loads(row[0])
        if mode != "full":
            source["text"] = None
        value["sources"].append(source)
    for row in db.execute(
        "SELECT record FROM knowledge_units WHERE project_id=? ORDER BY id", (project_id,)
    ):
        unit = json.loads(row[0])
        if mode != "full":
            unit["text"] = None
        value["units"].append(unit)
    value["sources_complete"] = mode == "full" or not value["versions"]
    return value


def validate_knowledge(value, project_id):
    if not isinstance(value, dict) or set(value) != set(empty_bundle()):
        raise ValueError("Unknown knowledge archive members")
    if value["mode"] not in ("full", "metadata") or type(value["sources_complete"]) is not bool:
        raise ValueError("Invalid original inclusion policy")
    limits = {
        "documents": 100,
        "versions": 200,
        "sources": 100000,
        "units": 250000,
        "evidence": 1000,
        "operations": 500,
    }
    if any(not isinstance(value[k], list) or len(value[k]) > limit for k, limit in limits.items()):
        raise ValueError("Knowledge archive record limit")
    full = value["mode"] == "full"
    if value["sources_complete"] != (full or not value["versions"]):
        raise ValueError("Metadata backup incorrectly claims complete originals")
    documents = [
        _strict_type(KnowledgeDocument).model_validate_json(encode(v)) for v in value["documents"]
    ]
    sources = [_strict_type(TextSource).model_validate_json(encode(v)) for v in value["sources"]]
    units = [_strict_type(TextUnit).model_validate_json(encode(v)) for v in value["units"]]
    evidence = [
        _strict_type(EvidenceRecord).model_validate_json(encode(v)) for v in value["evidence"]
    ]
    operations = [
        _strict_type(KnowledgeOperation).model_validate_json(encode(v)) for v in value["operations"]
    ]
    docs = {v.id: v for v in documents}
    if len(docs) != len(documents) or any(v.project_id != project_id for v in documents):
        raise ValueError("Invalid document identity")
    versions, files = {}, {}
    for item in value["versions"]:
        if not isinstance(item, dict) or set(item) != {"info", "content_base64"}:
            raise ValueError("Invalid file envelope")
        version = _strict_type(DocumentVersion).model_validate_json(encode(item["info"]))
        if (
            version.id in versions
            or version.document_id not in docs
            or version.project_id != project_id
        ):
            raise ValueError("Invalid version identity")
        if full:
            if (
                not isinstance(item["content_base64"], str)
                or len(item["content_base64"]) > ((20 * 1024**2 + 2) // 3) * 4
            ):
                raise ValueError("Invalid original envelope")
            raw = base64.b64decode(item["content_base64"], validate=True)
            if (
                len(raw) != version.bytes
                or hashlib.sha256(raw).hexdigest() != version.sha256
                or file_type(version.filename, raw) != version.media_type
            ):
                raise ValueError("Original digest or type differs")
        else:
            if item["content_base64"] is not None:
                raise ValueError("Metadata backup contains original content")
            raw = None
        if any(c in version.filename for c in "\\/\x00\r\n"):
            raise ValueError("Filename is not a filesystem path")
        Project.utc(version.created_at)
        if version.parsed_at is not None:
            Project.utc(version.parsed_at)
        versions[version.id], files[version.id] = version, raw
    for doc in documents:
        if (
            doc.current_version_id not in versions
            or versions[doc.current_version_id].document_id != doc.id
        ):
            raise ValueError("Missing current version")
        Project.utc(doc.created_at)
        Project.utc(doc.updated_at)
    source_map = {}
    for source in sources:
        version = versions.get(source.version_id)
        key = (source.version_id, source.position)
        if (
            version is None
            or key in source_map
            or source.page != (source.position if version.media_type == "application/pdf" else None)
        ):
            raise ValueError("Invalid source position")
        if (
            source.page is not None
            and version.page_count is not None
            and source.page > version.page_count
        ):
            raise ValueError("Source exceeds the declared physical pages")
        if source.text is not None:
            if not full or checksum(source.text) != source.sha256:
                raise ValueError("Source text digest mismatch")
        elif full and (version.indexed or version.state in ("ready", "partial")):
            raise ValueError("Full backup lost extracted text")
        source_map[key] = source
    unit_map = {}
    for unit in units:
        version, source = (
            versions.get(unit.version_id),
            source_map.get((unit.version_id, unit.source_position)),
        )
        if (
            unit.id in unit_map
            or version is None
            or source is None
            or unit.document_id != version.document_id
            or unit.project_id != project_id
            or not 0 <= unit.char_start < unit.char_end
            or unit.char_end - unit.char_start > 1200
            or unit.char_end > 20 * 1024**2
            or unit.page != source.page
        ):
            raise ValueError("Invalid text unit reference")
        if (
            unit.page is not None and (unit.line_start is not None or unit.line_end is not None)
        ) or (
            unit.page is None
            and (
                unit.line_start is None or unit.line_end is None or unit.line_start > unit.line_end
            )
        ):
            raise ValueError("Invalid physical-page or Markdown-line location")
        if unit.text is not None:
            if (
                not full
                or checksum(unit.text) != unit.sha256
                or source.text is None
                or source.text[unit.char_start : unit.char_end] != unit.text
            ):
                raise ValueError("Unit excerpt does not match its original extraction")
        elif full and source.text is not None:
            raise ValueError("Incomplete full-backup segment")
        unit_map[unit.id] = unit
    for version in versions.values():
        own_sources = sorted(
            [s.model_dump(mode="json") for s in sources if s.version_id == version.id],
            key=lambda s: s["position"],
        )
        own_units = sorted(
            [u.model_dump(mode="json") for u in units if u.version_id == version.id],
            key=lambda u: u["ordinal"],
        )
        if len(own_units) != version.unit_count or [u["ordinal"] for u in own_units] != list(
            range(len(own_units))
        ):
            raise ValueError("Missing unit sequence")
        if version.page_count is not None and len(own_sources) != version.page_count:
            raise ValueError("Physical page count mismatch")
        if version.indexed and not own_units:
            raise ValueError("Empty version incorrectly claims searchable content")
        if own_sources and [s["position"] for s in own_sources] != list(
            range(1, len(own_sources) + 1)
        ):
            raise ValueError("Missing source sequence")
        if version.extraction_sha256 is not None:
            signature = checksum(
                encode(
                    [
                        {key: s[key] for key in ("position", "page", "state", "sha256", "error")}
                        for s in own_sources
                    ]
                )
            )
            if signature != version.extraction_sha256:
                raise ValueError("Extraction summary mismatch")
        if full and own_sources and all(s["text"] is not None for s in own_sources):
            if (
                sum(len(s["text"].encode("utf-8")) for s in own_sources) != version.text_bytes
                or version.text_bytes > 20 * 1024**2
            ):
                raise ValueError("Extraction byte limit")
            expected = segment(own_sources, version.id, project_id, version.document_id)

            # IDs may already have been remapped by an earlier import; positions stay immutable.
            def strip_id(u):
                return {k: v for k, v in u.items() if k != "id"}

            if [strip_id(u) for u in expected] != [strip_id(u) for u in own_units]:
                raise ValueError("Segmentation differs from original text")
            if version.media_type == "text/markdown" and (
                len(own_sources) != 1
                or own_sources[0]["text"] != files[version.id].decode("utf-8-sig")
            ):
                raise ValueError("Markdown extraction differs from original bytes")
    ids, requests = set(), set()
    for op in operations:
        if op.id in ids or op.project_id != project_id or op.client_request_id in requests:
            raise ValueError("Invalid operation identity")
        ids.add(op.id)
        requests.add(op.client_request_id)
        if op.document_id in docs and (
            op.version_id not in versions or versions[op.version_id].document_id != op.document_id
        ):
            raise ValueError("Operation belongs to another document")
        Project.utc(op.created_at)
        if op.completed_at is not None:
            Project.utc(op.completed_at)
    ids = set()
    for record in evidence:
        if record.id in ids or record.project_id != project_id:
            raise ValueError("Invalid evidence identity")
        ids.add(record.id)
        if record.validity != "deleted":
            version, unit = versions.get(record.version_id), unit_map.get(record.unit_id)
            if (
                version is None
                or unit is None
                or version.document_id != record.document_id
                or unit.version_id != version.id
                or record.document_sha256 != version.sha256
                or record.text_sha256 != unit.sha256
                or any(
                    getattr(record, k) != getattr(unit, k)
                    for k in ("page", "line_start", "line_end", "char_start", "char_end")
                )
            ):
                raise ValueError("Evidence does not correspond to its immutable source")
        elif record.document_id in docs:
            raise ValueError("Deleted evidence references an active document")
        Project.utc(record.created_at)
    return {
        "mode": value["mode"],
        "sources_complete": value["sources_complete"],
        "documents": [d.model_dump(mode="json") for d in documents],
        "versions": [
            {"info": v.model_dump(mode="json"), "content": files[v.id]} for v in versions.values()
        ],
        "sources": [s.model_dump(mode="json") for s in sources],
        "units": [u.model_dump(mode="json") for u in units],
        "evidence": [e.model_dump(mode="json") for e in evidence],
        "operations": [o.model_dump(mode="json") for o in operations],
    }


def import_knowledge(db, bundle, project_id, id_map):
    # Include deleted-source identities so tombstones never retain active foreign project IDs.
    doc_ids = (
        {v["id"] for v in bundle["documents"]}
        | {v["document_id"] for v in bundle["evidence"]}
        | {v["document_id"] for v in bundle["operations"]}
    )
    version_ids = (
        {v["info"]["id"] for v in bundle["versions"]}
        | {v["version_id"] for v in bundle["evidence"]}
        | {v["version_id"] for v in bundle["operations"]}
    )
    unit_ids = {v["id"] for v in bundle["units"]} | {v["unit_id"] for v in bundle["evidence"]}
    for kind, keys in (
        ("knowledge_documents", doc_ids),
        ("knowledge_versions", version_ids),
        ("knowledge_units", unit_ids),
        ("knowledge_evidence", {v["id"] for v in bundle["evidence"]}),
        ("knowledge_operations", {v["id"] for v in bundle["operations"]}),
    ):
        id_map[kind] = {key: str(uuid4()) for key in keys}
    full, available = bundle["mode"] == "full", indexes_available(db)
    current_ids = {v["current_version_id"] for v in bundle["documents"]}
    for original in bundle["documents"]:
        item = deepcopy(original)
        item.update(
            id=id_map["knowledge_documents"][original["id"]],
            project_id=project_id,
            current_version_id=id_map["knowledge_versions"][original["current_version_id"]],
            provenance="imported_unverified",
            original_id=original["id"],
        )
        if not full:
            item["state"] = "unavailable"
        elif item["state"] == "parsing":
            item["state"] = "interrupted"
        elif not available and item["state"] == "ready":
            item["state"] = "partial"
        db.execute(
            "INSERT INTO knowledge_documents VALUES (?,?,?)", (item["id"], project_id, encode(item))
        )
    for record in bundle["versions"]:
        original = record["info"]
        item = deepcopy(original)
        item.update(
            id=id_map["knowledge_versions"][original["id"]],
            document_id=id_map["knowledge_documents"][original["document_id"]],
            project_id=project_id,
            original_id=original["id"],
            content_available=full,
            indexed=bool(
                full
                and available
                and original["id"] in current_ids
                and original["state"] in ("ready", "partial")
                and original["unit_count"]
            ),
        )
        if not full:
            item["state"] = "unavailable"
        elif item["state"] == "parsing":
            item["state"] = "interrupted"
        db.execute(
            "INSERT INTO knowledge_versions VALUES (?,?,?,?,?)",
            (item["id"], item["document_id"], project_id, encode(item), record["content"]),
        )
    for original in bundle["sources"]:
        item = {**original, "version_id": id_map["knowledge_versions"][original["version_id"]]}
        db.execute(
            "INSERT INTO knowledge_sources VALUES (?,?,?)",
            (item["version_id"], item["position"], encode(item)),
        )
    version_map = {v["info"]["id"]: v["info"] for v in bundle["versions"]}
    for original in bundle["units"]:
        item = {
            **original,
            "id": id_map["knowledge_units"][original["id"]],
            "project_id": project_id,
            "document_id": id_map["knowledge_documents"][original["document_id"]],
            "version_id": id_map["knowledge_versions"][original["version_id"]],
        }
        text = normalize(item["text"]) if item["text"] is not None else ""
        db.execute(
            "INSERT INTO knowledge_units VALUES (?,?,?,?,?,?)",
            (item["id"], item["version_id"], item["document_id"], project_id, encode(item), text),
        )
        if (
            full
            and available
            and original["version_id"] in current_ids
            and version_map[original["version_id"]]["state"] in ("ready", "partial")
            and item["text"] is not None
        ):
            for table in FTS_TABLES:
                db.execute(
                    f"INSERT INTO {table}(unit_id,project_id,text) VALUES (?,?,?)",
                    (item["id"], project_id, text),
                )
    for original in bundle["evidence"]:
        item = {
            **original,
            "id": id_map["knowledge_evidence"][original["id"]],
            "original_id": original["id"],
            "project_id": project_id,
            "document_id": id_map["knowledge_documents"][original["document_id"]],
            "version_id": id_map["knowledge_versions"][original["version_id"]],
            "unit_id": id_map["knowledge_units"][original["unit_id"]],
        }
        if item["validity"] != "deleted" and not full:
            item["validity"] = "original_unavailable"
        db.execute(
            "INSERT INTO knowledge_evidence VALUES (?,?,?,?)",
            (item["id"], project_id, item["document_id"], encode(item)),
        )
    for original in bundle["operations"]:
        item = {
            **original,
            "id": id_map["knowledge_operations"][original["id"]],
            "project_id": project_id,
            "document_id": id_map["knowledge_documents"][original["document_id"]],
            "version_id": id_map["knowledge_versions"][original["version_id"]],
            "client_request_id": str(uuid4()),
        }
        if item["state"] == "parsing":
            item.update(
                state="interrupted",
                http_status=409,
                completed_at=utc_now(),
                message="导入不会自动解析或执行重建。",
            )
        db.execute(
            "INSERT INTO knowledge_operations VALUES (?,?,?,?,?,?,0)",
            (
                item["id"],
                project_id,
                item["client_request_id"],
                "imported",
                item["state"],
                encode(item),
            ),
        )
