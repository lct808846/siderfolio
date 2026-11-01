"""项目格式4的links.json；严格本地验证及逐层软引用重映射。"""

import json
from copy import deepcopy
from uuid import uuid4

from astroagent.conversation_schemas import Turn
from astroagent.conversations import encode
from astroagent.export_schemas import _strict_type
from astroagent.link_schemas import LinkRequestRecord, ProjectLink
from astroagent.project_links import ProjectLinks, turn_fingerprint
from astroagent.project_schemas import Project
from astroagent.workflow_templates import digest


def empty_links():
    return {"links": [], "requests": []}


def read_links(db, project_id, mode, repository):
    # This adapter reuses the evidence verifier, not the search engine or parser.
    from types import SimpleNamespace

    from astroagent.knowledge_service import KnowledgeService

    adapter = SimpleNamespace(repository=repository)
    adapter.knowledge = KnowledgeService(adapter)
    resolver = ProjectLinks(adapter)
    values, cache = empty_links(), {}
    for row in db.execute(
        "SELECT record FROM project_links WHERE project_id=? ORDER BY id", (project_id,)
    ):
        link = ProjectLink.model_validate_json(row[0])
        resolved = resolver.resolve(db, link, cache, include_evidence=False)
        link = resolved["link"]
        if (
            not link.target_invalidated
            and not resolved["target"].available
            and resolved["target"].provenance == "unknown"
        ):
            link = link.model_copy(
                update={
                    "state": "target_unavailable",
                    "target_invalidated": True,
                    "invalidation_reason": "target_missing_or_changed_at_export",
                }
            )
        evidence = db.execute(
            "SELECT record FROM knowledge_evidence WHERE project_id=? AND id=?",
            (project_id, link.evidence_id),
        ).fetchone()
        if not link.evidence_invalidated and (
            evidence is None or json.loads(evidence[0])["validity"] == "deleted"
        ):
            link = link.model_copy(
                update={
                    "evidence_invalidated": True,
                    "state": "target_unavailable"
                    if link.target_invalidated
                    else "evidence_unavailable",
                    "invalidation_reason": "evidence_deleted_or_missing",
                }
            )
        elif mode == "metadata" and not link.target_invalidated:
            link = link.model_copy(
                update={
                    "state": "target_unavailable"
                    if not resolved["target"].available
                    else "evidence_unavailable"
                }
            )
        values["links"].append(link.model_dump(mode="json"))
    values["requests"] = [
        json.loads(row[0])
        for row in db.execute(
            "SELECT record FROM project_link_requests WHERE project_id=? ORDER BY id", (project_id,)
        )
    ]
    return values


def validate_links(raw, project_id, conversations, snapshots, workflows, knowledge):
    if (
        not isinstance(raw, dict)
        or set(raw) != {"links", "requests"}
        or not isinstance(raw["links"], list)
        or not isinstance(raw["requests"], list)
        or len(raw["links"]) > 1000
        or len(raw["requests"]) > 3000
    ):
        raise ValueError("Invalid links member")
    links = [_strict_type(ProjectLink).model_validate_json(encode(value)) for value in raw["links"]]
    requests = [
        _strict_type(LinkRequestRecord).model_validate_json(encode(value))
        for value in raw["requests"]
    ]
    if (
        len({v.id for v in links}) != len(links)
        or len({v.id for v in requests}) != len(requests)
        or len({v.client_request_id for v in requests}) != len(requests)
    ):
        raise ValueError("Duplicate link or request identity")
    targets = {("snapshot", s["id"]): (s["sha256"], None, True) for s in snapshots}
    for conversation in conversations:
        for turn in conversation["turns"]:
            targets[("conversation_turn", turn["turn_id"])] = (
                turn_fingerprint(Turn.model_validate(turn)),
                turn["conversation_id"],
                turn["response"] is not None and turn["execution_status"] != "running",
            )
    targets.update(
        {
            ("workflow_run", run["id"]): (
                None,
                None,
                run["state"] in ("succeeded", "failed", "interrupted"),
            )
            for run in workflows["runs"]
        }
    )
    evidence = {record["id"]: record for record in knowledge["evidence"]}
    units = {unit["id"]: unit for unit in knowledge["units"]}
    originals = {v["info"]["id"] for v in knowledge["versions"] if v["content"] is not None}
    mapping, pairs = {link.id: link for link in links}, set()

    def validate_reference(link, historical=False):
        if link.project_id != project_id:
            raise ValueError("Link belongs to another project")
        Project.utc(link.created_at)
        Project.utc(link.updated_at)
        target = targets.get((link.target_type, link.target_id))
        if not historical:
            if link.target_invalidated and link.state != "target_unavailable":
                raise ValueError("Invalid target tombstone")
            if not link.target_invalidated and target is None:
                raise ValueError("Missing target must be a tombstone")
            if (
                link.evidence_invalidated
                and not link.target_invalidated
                and link.state not in ("evidence_unavailable", "target_unavailable")
            ):
                raise ValueError("Invalid evidence tombstone")
        if target and not link.target_invalidated:
            if link.target_type != "workflow_run" and link.target_fingerprint != target[0]:
                raise ValueError("Link changed immutable result")
            if link.target_type == "conversation_turn" and link.target_conversation_id != target[1]:
                raise ValueError("Wrong conversation owner")
        record = evidence.get(link.evidence_id)
        if record:
            if (
                record["version_id"] != link.evidence_version_id
                or record["text_sha256"] != link.evidence_text_sha256
                or record["document_sha256"] != link.evidence_document_sha256
            ):
                raise ValueError("Link changed its frozen evidence")
            if not historical and record["validity"] == "deleted" and not link.evidence_invalidated:
                raise ValueError("Deleted evidence is not marked unavailable")
        elif not historical and not link.evidence_invalidated:
            raise ValueError("Missing evidence is not a tombstone")
        if (
            not historical
            and link.state == "active"
            and (
                target is None
                or not target[2]
                or record is None
                or link.target_invalidated
                or link.evidence_invalidated
                or knowledge["mode"] == "metadata"
                or record["validity"] == "deleted"
                or record["version_id"] not in originals
                or units.get(record["unit_id"], {}).get("text") is None
            )
        ):
            raise ValueError("Unavailable original falsely exposed as active link")

    for link in links:
        validate_reference(link)
        if not link.target_invalidated and not link.evidence_invalidated:
            pair = (link.target_type, link.target_id, link.evidence_id)
            if pair in pairs:
                raise ValueError("Duplicate eligible association")
            pairs.add(pair)
    for request in requests:
        if request.project_id != project_id or request.link_id != request.response.id:
            raise ValueError("Invalid link operation reference")
        Project.utc(request.created_at)
        validate_reference(request.response, historical=True)
        active = mapping.get(request.link_id)
        if active and any(
            getattr(active, key) != getattr(request.response, key)
            for key in (
                "target_type",
                "target_id",
                "evidence_id",
                "evidence_version_id",
                "evidence_text_sha256",
                "evidence_document_sha256",
                "target_fingerprint",
            )
        ):
            raise ValueError("Historical request rewrites link endpoints")
    return {
        "links": [link.model_dump(mode="json") for link in links],
        "requests": [request.model_dump(mode="json") for request in requests],
    }


def import_links(db, bundle, project_id, id_map, archive_sha256, mode):
    link_ids = {v["id"] for v in bundle["links"]} | {v["link_id"] for v in bundle["requests"]}
    id_map["project_links"] = {old: str(uuid4()) for old in link_ids}
    id_map["project_link_requests"] = {v["id"]: str(uuid4()) for v in bundle["requests"]}
    id_map["link_soft_references"] = {}

    def map_ref(group, old):
        if old is None:
            return None
        value = id_map.get(group, {}).get(old)
        if value:
            return value
        key = f"{group}:{old}"
        return id_map["link_soft_references"].setdefault(key, str(uuid4()))

    def remap(original, historical=False):
        link = deepcopy(original)
        group = {
            "conversation_turn": "turns",
            "snapshot": "snapshots",
            "workflow_run": "workflows",
        }[link["target_type"]]
        link.update(
            id=id_map["project_links"][original["id"]],
            project_id=project_id,
            target_id=map_ref(group, original["target_id"]),
            target_conversation_id=map_ref("conversations", original["target_conversation_id"]),
            evidence_id=map_ref("knowledge_evidence", original["evidence_id"]),
            evidence_version_id=map_ref("knowledge_versions", original["evidence_version_id"]),
            provenance="imported_unverified",
            original_id=original["id"],
            original_target_id=original["target_id"],
            original_evidence_id=original["evidence_id"],
            archive_sha256=archive_sha256,
        )
        if not historical and mode == "metadata" and link["state"] != "target_unavailable":
            link["state"] = "evidence_unavailable"
        return link

    for old in bundle["links"]:
        link = remap(old)
        db.execute(
            "INSERT INTO project_links VALUES (?,?,?,?,?,?)",
            (
                link["id"],
                project_id,
                link["target_type"],
                link["target_id"],
                link["evidence_id"],
                encode(link),
            ),
        )
    for old in bundle["requests"]:
        request = deepcopy(old)
        request.update(
            id=id_map["project_link_requests"][old["id"]],
            project_id=project_id,
            client_request_id=str(uuid4()),
            link_id=id_map["project_links"][old["link_id"]],
            response=remap(old["response"], historical=True),
            original_id=old["id"],
        )
        request["request_sha256"] = digest(
            {"imported_archive": archive_sha256, "request_id": request["client_request_id"]}
        )
        db.execute(
            "INSERT INTO project_link_requests VALUES (?,?,?,?,?)",
            (
                request["id"],
                project_id,
                request["client_request_id"],
                request["request_sha256"],
                encode(request),
            ),
        )
