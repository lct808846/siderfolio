"""固定四至七成员项目 ZIP（schema1/2/3/4）；完整校验后单事务恢复，不解压到文件系统。"""

import hashlib
import json
import math
import stat
import zlib
from copy import deepcopy
from io import BytesIO
from uuid import uuid4
from zipfile import ZIP_DEFLATED, ZIP_STORED, BadZipFile, ZipFile

from astroagent import __version__
from astroagent.conversation_schemas import Conversation, Turn
from astroagent.conversations import encode, utc_now
from astroagent.errors import ServiceError
from astroagent.export_schemas import ExportSnapshot, _strict_type, validate_snapshot
from astroagent.project_schemas import ArchiveManifest, Project, Rerun, Snapshot

MAX_COMPRESSED = 32 * 1024**2
MAX_TOTAL = 128 * 1024**2
MAX_MEMBER = 64 * 1024**2
MEMBERS = {"manifest.json", "project.json", "conversations.json", "snapshots.json"}


def invalid(text="项目包校验失败，未导入任何数据。"):
    return ServiceError(422, "invalid_project_archive", text)


def strict_json(raw):
    def pairs(items):
        value = {}
        for key, item in items:
            if key in value:
                raise ValueError("Duplicate JSON key")
            value[key] = item
        return value

    def constant(value):
        raise ValueError("Non-finite JSON")

    def walk(value, depth=0):
        if depth > 32 or isinstance(value, float) and not math.isfinite(value):
            raise ValueError("Unsupported JSON")
        if isinstance(value, dict):
            for item in value.values():
                walk(item, depth + 1)
        elif isinstance(value, list):
            for item in value:
                walk(item, depth + 1)

    value = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs, parse_constant=constant)
    walk(value)
    return value


def export_archive(
    repository,
    identifier,
    revision,
    format_version=4,
    knowledge_mode="metadata",
    confirmed_include_originals=False,
):
    with repository.repo.connection() as db:
        db.execute("BEGIN")
        project = repository._project(db, identifier, revision)
        ids = [
            r[0]
            for r in db.execute(
                "SELECT conversation_id FROM project_conversations "
                "WHERE project_id=? ORDER BY conversation_id",
                (identifier,),
            )
        ]
        conversations = []
        turn_ids = set()
        for cid in ids:
            turns = [
                json.loads(r[0])
                for r in db.execute(
                    "SELECT record FROM turns WHERE conversation_id=? ORDER BY ordinal", (cid,)
                )
            ]
            turn_ids.update(t["turn_id"] for t in turns)
            conversations.append(
                {"conversation": repository.repo._conversation(db, cid), "turns": turns}
            )
        snapshots = [
            json.loads(r[0])
            for r in db.execute(
                "SELECT record FROM snapshots WHERE project_id=? ORDER BY id", (identifier,)
            )
        ]
        reruns = [
            json.loads(r[0])
            for r in db.execute(
                "SELECT record FROM reruns WHERE project_id=? ORDER BY id", (identifier,)
            )
        ]
        from astroagent.workflow_archives import read_workflows

        workflows = read_workflows(db, identifier)
        from astroagent.knowledge_archives import read_knowledge

        knowledge = read_knowledge(
            db,
            identifier,
            knowledge_mode if format_version >= 3 else "metadata",
            confirmed_include_originals,
        )
        from astroagent.link_archives import read_links

        links = read_links(db, identifier, knowledge["mode"], repository.repo)
        if format_version < 4 and (links["links"] or links["requests"]):
            raise ServiceError(
                409,
                "project_links_archive_requires_v4",
                "项目含关联或其操作历史，不能丢弃后导出旧格式。",
            )
        if format_version < 3 and any(
            knowledge[key] for key in ("documents", "versions", "evidence", "operations")
        ):
            raise ServiceError(
                409,
                "knowledge_archive_requires_v3",
                "项目含知识库或历史引用，不能丢弃后导出旧格式。",
            )
        if format_version == 1 and workflows["runs"]:
            raise ServiceError(
                409, "workflow_archive_requires_v2", "项目含科研流程，不能丢弃流程后导出旧格式。"
            )
    # Origin IDs are immutable provenance. Active references outside this bundle are detached.
    for value in [*snapshots, *reruns]:
        if value["conversation_id"] not in ids or value["turn_id"] not in turn_ids:
            value["conversation_id"] = value["turn_id"] = None
    payloads = {
        "project.json": encode({"project": project, "reruns": reruns}).encode(),
        "conversations.json": encode(conversations).encode(),
        "snapshots.json": encode(snapshots).encode(),
    }
    if format_version >= 2:
        payloads["workflows.json"] = encode(workflows).encode()
    if format_version >= 3:
        payloads["knowledge.json"] = encode(knowledge).encode()
    if format_version == 4:
        payloads["links.json"] = encode(links).encode()
    manifest = ArchiveManifest(
        format="astroagent-project",
        version=format_version,
        exported_at=utc_now(),
        application_version=__version__,
        knowledge_mode=knowledge["mode"] if format_version >= 3 else None,
        sources_complete=knowledge["sources_complete"] if format_version >= 3 else None,
        files={
            name: {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
            for name, raw in payloads.items()
        },
    )
    payloads["manifest.json"] = encode(manifest.model_dump(exclude_none=True)).encode()
    if sum(map(len, payloads.values())) > MAX_TOTAL or any(
        len(b) > MAX_MEMBER for b in payloads.values()
    ):
        raise ServiceError(413, "project_archive_too_large", "完整归档超出限制，未截断或交付半包。")
    stream = BytesIO()
    with ZipFile(stream, "w", compression=ZIP_DEFLATED) as archive:
        for name in sorted(payloads):
            archive.writestr(name, payloads[name])
    result = stream.getvalue()
    if len(result) > MAX_COMPRESSED:
        raise ServiceError(413, "project_archive_too_large", "压缩归档超过32 MiB，未交付半包。")
    return result


def decode_archive(raw):
    if len(raw) > MAX_COMPRESSED:
        raise ServiceError(413, "project_archive_too_large", "项目包超过32 MiB。")
    try:
        data, total = {}, 0
        with ZipFile(BytesIO(raw)) as archive:
            infos = archive.infolist()
            member_names = {i.filename for i in infos}
            if len(infos) != len(member_names) or member_names not in (
                MEMBERS,
                MEMBERS | {"workflows.json"},
                MEMBERS | {"workflows.json", "knowledge.json"},
                MEMBERS | {"workflows.json", "knowledge.json", "links.json"},
            ):
                raise ValueError("Fixed unique members required")
            for info in infos:
                mode = stat.S_IFMT(info.external_attr >> 16)
                if info.file_size > MAX_MEMBER:
                    raise ServiceError(413, "project_archive_too_large", "项目包单成员超过64 MiB。")
                if (
                    info.flag_bits & 1
                    or mode not in (0, stat.S_IFREG)
                    or info.compress_type not in (ZIP_DEFLATED, ZIP_STORED)
                ):
                    raise ValueError("Unsupported member")
                content = bytearray()
                with archive.open(info) as member:
                    while chunk := member.read(65536):
                        content.extend(chunk)
                        total += len(chunk)
                        if len(content) > MAX_MEMBER or total > MAX_TOTAL:
                            raise ServiceError(
                                413, "project_archive_too_large", "项目包实际解压大小超限。"
                            )
                data[info.filename] = bytes(content)
        manifest_raw = strict_json(data["manifest.json"])
        if not isinstance(manifest_raw, dict) or type(manifest_raw.get("version")) is not int:
            raise ValueError("Integer archive version required")
        manifest = ArchiveManifest.model_validate(manifest_raw)
        expected_members = MEMBERS if manifest.version == 1 else MEMBERS | {"workflows.json"}
        if manifest.version >= 3:
            expected_members |= {"knowledge.json"}
            if manifest.version == 4:
                expected_members |= {"links.json"}
        elif manifest.knowledge_mode is not None or manifest.sources_complete is not None:
            raise ValueError("Knowledge metadata requires archive format3")
        if set(data) != expected_members:
            raise ValueError("Archive members differ from format version")
        Project.utc(manifest.exported_at)
        if set(manifest.files) != expected_members - {"manifest.json"}:
            raise ValueError("Incomplete manifest")
        for name, entry in manifest.files.items():
            if (
                set(entry) != {"bytes", "sha256"}
                or type(entry["bytes"]) is not int
                or entry["bytes"] != len(data[name])
                or entry["sha256"] != hashlib.sha256(data[name]).hexdigest()
            ):
                raise ValueError("Digest or size differs")
        project_file = strict_json(data["project.json"])
        if not isinstance(project_file, dict) or set(project_file) != {"project", "reruns"}:
            raise ValueError("Invalid project object")
        project = Project.model_validate(project_file["project"])
        snapshots_raw, conversations_raw = (
            strict_json(data["snapshots.json"]),
            strict_json(data["conversations.json"]),
        )
        if (
            not isinstance(snapshots_raw, list)
            or not isinstance(conversations_raw, list)
            or not isinstance(project_file["reruns"], list)
        ):
            raise ValueError("Invalid collections")
        if (
            len(snapshots_raw) > 100
            or len(conversations_raw) > 20
            or len(project_file["reruns"]) > 100
        ):
            raise ValueError("Too many records")
        snapshots = [
            Snapshot.model_validate(s).verify_digest().model_dump(mode="json")
            for s in snapshots_raw
        ]
        reruns = [Rerun.model_validate(r).model_dump() for r in project_file["reruns"]]
        conversations, conv_ids, turn_ids = [], set(), set()
        for value in conversations_raw:
            if (
                not isinstance(value, dict)
                or set(value) != {"conversation", "turns"}
                or not isinstance(value["turns"], list)
            ):
                raise ValueError("Invalid conversation")
            conv = (
                _strict_type(Conversation)
                .model_validate_json(encode(value["conversation"]))
                .model_dump()
            )
            if (
                not 0 <= conv["revision"] <= 40
                or len(value["turns"]) != conv["revision"]
                or conv["id"] in conv_ids
            ):
                raise ValueError("Invalid conversation revision")
            from uuid import UUID

            UUID(conv["id"])
            if (
                not conv["title"].strip()
                or len(conv["title"]) > 80
                or conv["metadata_revision"] < 0
            ):
                raise ValueError("Invalid conversation metadata")
            Project.utc(conv["created_at"])
            Project.utc(conv["updated_at"])
            conv_ids.add(conv["id"])
            turns, keys = [], set()
            for index, item in enumerate(value["turns"]):
                turn = _strict_type(Turn).model_validate_json(encode(item)).model_dump(mode="json")
                for key in ("turn_id", "conversation_id", "client_request_id"):
                    UUID(turn[key])
                if (
                    turn["turn_id"] in turn_ids
                    or turn["conversation_id"] != conv["id"]
                    or turn["revision"] != index + 1
                    or turn["client_request_id"] in keys
                    or len(turn["message"]) > 4000
                ):
                    raise ValueError("Broken turn reference")
                turn_ids.add(turn["turn_id"])
                keys.add(turn["client_request_id"])
                Project.utc(turn["received_at"])
                if turn["completed_at"] is not None:
                    Project.utc(turn["completed_at"])
                if turn["response"] is not None:
                    validate_snapshot(ExportSnapshot.model_validate_json(encode(turn["response"])))
                turns.append(turn)
            conversations.append({"conversation": conv, "turns": turns})
        snapshot_ids = {s["id"] for s in snapshots}
        rerun_ids = {r["id"] for r in reruns}
        if (
            len(snapshot_ids) != len(snapshots)
            or len(rerun_ids) != len(reruns)
            or len({r["client_request_id"] for r in reruns}) != len(reruns)
        ):
            raise ValueError("Duplicate records")
        turn_map = {t["turn_id"]: t for c in conversations for t in c["turns"]}
        snapshot_map = {s["id"]: s for s in snapshots}
        for turn in turn_map.values():
            context = turn["context"]
            if context["strategy_version"] != "1":
                raise ValueError("Unsupported context strategy")
            ids = [
                *context["included_turn_ids"],
                *context["omitted_turn_ids"],
                *(r["turn_id"] for r in context["referenced_results"]),
                *(r["turn_id"] for r in context["omissions"] if "turn_id" in r),
            ]
            for old_id in ids:
                previous = turn_map.get(old_id)
                if (
                    previous is None
                    or previous["conversation_id"] != turn["conversation_id"]
                    or previous["revision"] >= turn["revision"]
                ):
                    raise ValueError("Broken history reference")
            for reference in context["referenced_results"]:
                previous = turn_map[reference["turn_id"]]["response"]
                family = {"simbad": "results", "ads": "literature_results", "gaia": "gaia_results"}[
                    reference["family"]
                ]
                if previous is None or not 0 <= reference["result_index"] < len(previous[family]):
                    raise ValueError("Invalid historical result index")
        for value in [*snapshots, *reruns]:
            if value["project_id"] != project.id or (value["conversation_id"] is None) != (
                value["turn_id"] is None
            ):
                raise ValueError("Broken project reference")
            if value["conversation_id"] is not None and (
                value["conversation_id"] not in conv_ids
                or value["turn_id"] not in turn_ids
                or turn_map[value["turn_id"]]["conversation_id"] != value["conversation_id"]
            ):
                raise ValueError("Broken conversation reference")
        for value in snapshots:
            if value["rerun_of"] is not None and value["rerun_of"] not in snapshot_ids:
                raise ValueError("Broken snapshot rerun relation")
            if (
                value["turn_id"] is not None
                and turn_map[value["turn_id"]]["response"] != value["response"]
            ):
                raise ValueError("Snapshot differs from origin turn")
        for value in reruns:
            if (
                value["source_snapshot_id"] is not None
                and value["source_snapshot_id"] not in snapshot_ids
                or value["snapshot_id"] is not None
                and value["snapshot_id"] not in snapshot_ids
            ):
                raise ValueError("Broken rerun reference")
            if (
                value["snapshot_id"] is not None
                and snapshot_map[value["snapshot_id"]]["turn_id"] != value["turn_id"]
            ):
                raise ValueError("Rerun target differs")
            Project.utc(value["created_at"])
            if value["completed_at"]:
                Project.utc(value["completed_at"])
        from astroagent.workflow_archives import validate_workflows

        workflows = (
            validate_workflows(strict_json(data["workflows.json"]), project.id, snapshots)
            if manifest.version >= 2
            else {"runs": [], "operations": [], "outputs": [], "snapshot_refs": []}
        )
        from astroagent.knowledge_archives import empty_bundle, validate_knowledge

        knowledge = (
            validate_knowledge(strict_json(data["knowledge.json"]), project.id)
            if manifest.version >= 3
            else empty_bundle()
        )
        if manifest.version >= 3 and (
            manifest.knowledge_mode != knowledge["mode"]
            or manifest.sources_complete != knowledge["sources_complete"]
        ):
            raise ValueError("Original inclusion policy differs from manifest")
        from astroagent.link_archives import empty_links, validate_links

        links = (
            validate_links(
                strict_json(data["links.json"]),
                project.id,
                conversations,
                snapshots,
                workflows,
                knowledge,
            )
            if manifest.version == 4
            else empty_links()
        )
        return {
            "links": links,
            "knowledge": knowledge,
            "project": project.model_dump(),
            "conversations": conversations,
            "snapshots": snapshots,
            "reruns": reruns,
            "workflows": workflows,
        }
    except ServiceError:
        raise
    except (
        ValueError,
        TypeError,
        KeyError,
        BadZipFile,
        OSError,
        RuntimeError,
        RecursionError,
        OverflowError,
        EOFError,
        zlib.error,
    ) as exc:
        raise invalid() from exc


def import_archive(repository, raw):
    bundle = decode_archive(raw)
    digest = hashlib.sha256(raw).hexdigest()
    old = bundle["project"]["id"]
    id_map = {
        "projects": {old: str(uuid4())},
        "conversations": {},
        "turns": {},
        "snapshots": {},
        "reruns": {},
    }
    for c in bundle["conversations"]:
        id_map["conversations"][c["conversation"]["id"]] = str(uuid4())
        id_map["turns"].update({t["turn_id"]: str(uuid4()) for t in c["turns"]})
    for kind in ("snapshots", "reruns"):
        id_map[kind].update({v["id"]: str(uuid4()) for v in bundle[kind]})
    project = deepcopy(bundle["project"])
    project.update(
        id=id_map["projects"][old],
        revision=0,
        updated_at=utc_now(),
        provenance="imported_unverified",
        original_id=old,
        import_map=id_map,
        archive_sha256=digest,
    )
    project_id = project["id"]
    incoming = len(encode(project).encode())
    incoming += sum(
        len(encode(c["conversation"]).encode()) + sum(len(encode(t).encode()) for t in c["turns"])
        for c in bundle["conversations"]
    )
    incoming += sum(len(encode(run).encode()) for run in bundle["workflows"]["runs"])
    incoming += sum(
        len(encode(operation).encode()) for operation in bundle["workflows"]["operations"]
    )
    incoming += sum(
        len(record["content"]) + len(encode(record["info"]).encode())
        for record in bundle["workflows"]["outputs"]
    )
    incoming += sum(
        len(encode(value).encode()) for kind in ("snapshots", "reruns") for value in bundle[kind]
    )
    incoming += sum(
        len(encode(v).encode())
        for key in ("documents", "sources", "units", "evidence", "operations")
        for v in bundle["knowledge"][key]
    )
    incoming += sum(
        len(encode(v["info"]).encode()) + len(v["content"] or b"")
        for v in bundle["knowledge"]["versions"]
    )
    incoming += sum(
        len(encode(value).encode())
        for kind in ("links", "requests")
        for value in bundle["links"][kind]
    )
    # Preflight before any write; exact normalized bytes are checked in-transaction.
    with repository.repo.connection() as db:
        if repository.repo._used(db) + incoming > repository.settings.storage_bytes:
            raise ServiceError(409, "project_import_limit", "完整导入内容超过剩余存储预算。")
    with repository.repo.connection() as db, repository.repo.transaction(db):
        if (
            db.execute("SELECT count(*) FROM projects").fetchone()[0] >= 20
            or db.execute("SELECT count(*) FROM conversations").fetchone()[0]
            + len(bundle["conversations"])
            > repository.settings.max_conversations
        ):
            raise ServiceError(
                409, "project_import_limit", "导入将超过项目或会话配额，未写入数据。"
            )
        db.execute("INSERT INTO projects VALUES (?,?)", (project_id, encode(project)))
        for entry in bundle["conversations"]:
            c = deepcopy(entry["conversation"])
            c["id"] = id_map["conversations"][c["id"]]
            db.execute(
                "INSERT INTO conversations VALUES "
                "(:id,:title,:created_at,:updated_at,:revision,:metadata_revision)",
                c,
            )
            db.execute("INSERT INTO project_conversations VALUES (?,?)", (c["id"], project_id))
            for source_turn in entry["turns"]:
                if len(entry["turns"]) > repository.settings.max_turns:
                    raise ServiceError(409, "project_import_limit", "归档轮次超过当前会话配额。")
                t = deepcopy(source_turn)
                t.update(turn_id=id_map["turns"][t["turn_id"]], conversation_id=c["id"])
                context = t["context"]
                for key in ("included_turn_ids", "omitted_turn_ids"):
                    context[key] = [id_map["turns"].get(x, x) for x in context[key]]
                for value in context["referenced_results"]:
                    value["turn_id"] = id_map["turns"].get(value["turn_id"], value["turn_id"])
                for omission in context["omissions"]:
                    if omission.get("turn_id") in id_map["turns"]:
                        omission["turn_id"] = id_map["turns"][omission["turn_id"]]
                if t["execution_status"] == "running":
                    t.update(
                        execution_status="interrupted",
                        completed_at=utc_now(),
                        error={
                            "code": "imported_interrupted",
                            "message": "导入的运行记录已中断，未执行查询。",
                            "retryable": False,
                        },
                    )
                text = encode(t)
                if len(text.encode()) > repository.settings.turn_bytes:
                    raise ServiceError(
                        413, "project_import_limit", "归档单轮内容超出当前存储上限。"
                    )
                request_hash = hashlib.sha256(
                    encode(
                        {
                            "message": t["message"],
                            "client_request_id": t["client_request_id"],
                            "expected_revision": t["revision"] - 1,
                        }
                    ).encode()
                ).hexdigest()
                db.execute(
                    "INSERT INTO turns VALUES (?,?,?,?,?,?,?,?,?)",
                    (
                        t["turn_id"],
                        c["id"],
                        t["revision"],
                        t["client_request_id"],
                        request_hash,
                        t["execution_status"],
                        text,
                        len(text.encode()),
                        0,
                    ),
                )
                db.execute(
                    "INSERT INTO imported_turn_origins VALUES (?,?)",
                    (
                        t["turn_id"],
                        encode(
                            {
                                "conversation_id": source_turn["conversation_id"],
                                "turn_id": source_turn["turn_id"],
                                "snapshot_id": None,
                                "archive_sha256": digest,
                            }
                        ),
                    ),
                )
        for original in bundle["snapshots"]:
            value = deepcopy(original)
            value.update(
                id=id_map["snapshots"][original["id"]],
                project_id=project_id,
                provenance="imported_unverified",
            )
            value["origin"].update(snapshot_id=original["id"], archive_sha256=digest)
            value["conversation_id"] = id_map["conversations"].get(value["conversation_id"])
            value["turn_id"] = id_map["turns"].get(value["turn_id"])
            value["rerun_of"] = id_map["snapshots"].get(value["rerun_of"])
            repository._insert_snapshot(db, value)
        for original in bundle["reruns"]:
            value = deepcopy(original)
            value.update(
                id=id_map["reruns"][value["id"]],
                project_id=project_id,
                client_request_id=str(uuid4()),
            )
            for key, kind in (
                ("conversation_id", "conversations"),
                ("turn_id", "turns"),
                ("source_snapshot_id", "snapshots"),
                ("snapshot_id", "snapshots"),
            ):
                value[key] = id_map[kind].get(value[key])
            if value["state"] == "running":
                value.update(
                    state="interrupted",
                    completed_at=utc_now(),
                    error={"code": "imported_interrupted", "message": "导入记录不自动重放。"},
                )
            db.execute(
                "INSERT INTO reruns VALUES (?,?,?,?,?,?,0)",
                (
                    value["id"],
                    project_id,
                    value["client_request_id"],
                    "imported:" + digest,
                    value["state"],
                    encode(value),
                ),
            )
        from astroagent.workflow_archives import import_workflows

        import_workflows(db, bundle["workflows"], project_id, id_map, digest)
        from astroagent.knowledge_archives import import_knowledge

        import_knowledge(db, bundle["knowledge"], project_id, id_map)
        from astroagent.link_archives import import_links

        import_links(db, bundle["links"], project_id, id_map, digest, bundle["knowledge"]["mode"])
        project["import_map"] = id_map
        repository._put(db, "projects", project)
        repository._budget(db)
    return {"project": project, "id_map": id_map, "archive_sha256": digest}
