"""归档schema2的流程与产物关系；所有校验在本地进行，不启动流程。"""

import base64
import copy
import json

from astroagent.conversations import encode, utc_now
from astroagent.errors import ServiceError
from astroagent.export_schemas import (
    ExportManifest,
    ExportSnapshot,
    _strict_type,
    validate_snapshot,
)
from astroagent.project_schemas import Project
from astroagent.schemas import ChatResponse, QueryResult
from astroagent.workflow_io import validate_output
from astroagent.workflow_schemas import WorkflowOperation, WorkflowOutput, WorkflowRun
from astroagent.workflow_templates import (
    DEFINITIONS,
    digest,
    input_digest,
    parameters,
    prepare_input,
)


def read_workflows(db, project_id):
    # Estimate base64 overhead before collecting a potentially large member in memory.
    estimate = db.execute(
        "SELECT coalesce(sum(length(record)),0) FROM workflows WHERE project_id=?", (project_id,)
    ).fetchone()[0]
    estimate += db.execute(
        "SELECT coalesce(sum(length(o.record)+(length(o.content)+2)/3*4),0) "
        "FROM workflow_outputs o JOIN workflows w ON w.id=o.run_id WHERE w.project_id=?",
        (project_id,),
    ).fetchone()[0]
    if estimate > 64 * 1024**2:
        raise ServiceError(413, "project_archive_too_large", "完整流程与产物超过归档单成员上限。")
    run_ids = [
        row[0]
        for row in db.execute(
            "SELECT id FROM workflows WHERE project_id=? ORDER BY id", (project_id,)
        )
    ]
    values = {"runs": [], "operations": [], "outputs": [], "snapshot_refs": []}
    for run_id in run_ids:
        values["runs"].append(
            json.loads(
                db.execute("SELECT record FROM workflows WHERE id=?", (run_id,)).fetchone()[0]
            )
        )
        values["operations"].extend(
            json.loads(row[0])
            for row in db.execute(
                "SELECT record FROM workflow_operations WHERE run_id=? ORDER BY id", (run_id,)
            )
        )
        values["outputs"].extend(
            {"info": json.loads(row[0]), "content_base64": base64.b64encode(row[1]).decode("ascii")}
            for row in db.execute(
                "SELECT record,content FROM workflow_outputs WHERE run_id=? ORDER BY id", (run_id,)
            )
        )
        values["snapshot_refs"].extend(
            {"run_id": run_id, "snapshot_id": row[0]}
            for row in db.execute(
                "SELECT snapshot_id FROM workflow_snapshot_refs "
                "WHERE run_id=? ORDER BY snapshot_id",
                (run_id,),
            )
        )
    return values


def validate_workflows(value, project_id, snapshots):
    if not isinstance(value, dict) or set(value) != {
        "runs",
        "operations",
        "outputs",
        "snapshot_refs",
    }:
        raise ValueError("Invalid workflow member")
    if (
        any(not isinstance(v, list) for v in value.values())
        or len(value["runs"]) > 50
        or len(value["operations"]) > 1000
        or len(value["outputs"]) > 8000
        or len(value["snapshot_refs"]) > 250
    ):
        raise ValueError("Workflow archive quota exceeded")
    runs = [_strict_type(WorkflowRun).model_validate_json(encode(r)) for r in value["runs"]]
    operations = [
        _strict_type(WorkflowOperation).model_validate_json(encode(o)) for o in value["operations"]
    ]
    if len({r.id for r in runs}) != len(runs) or len({o.id for o in operations}) != len(operations):
        raise ValueError("Duplicate workflow identities")
    run_map, op_map = {r.id: r for r in runs}, {o.id: o for o in operations}
    snapshot_map = {s["id"]: s for s in snapshots}
    attempt_map, actual_refs, request_keys = {}, set(), set()
    for operation in operations:
        if (
            operation.run_id not in run_map
            or (operation.run_id, operation.client_request_id) in request_keys
            or operation.state not in ("running", "succeeded", "failed", "interrupted")
        ):
            raise ValueError("Invalid workflow operation reference")
        request_keys.add((operation.run_id, operation.client_request_id))
        Project.utc(operation.created_at)
        if operation.completed_at is not None:
            Project.utc(operation.completed_at)
    for run in runs:
        if (
            run.project_id != project_id
            or not run.name.strip()
            or parameters(run.template_id, run.parameters) != run.parameters
        ):
            raise ValueError("Invalid workflow owner or parameters")
        if [s.id for s in run.steps] != [s[0] for s in DEFINITIONS[run.template_id]]:
            raise ValueError("Unsupported workflow step definition")
        if run.current_step_id is not None and run.current_step_id not in {s.id for s in run.steps}:
            raise ValueError("Invalid current step")
        if sum(o.run_id == run.id for o in operations) > 20:
            raise ValueError("Too many operations")
        Project.utc(run.created_at)
        Project.utc(run.updated_at)
        for step in run.steps:
            if step.state == "skipped":
                if (
                    step.id != "resolve_name"
                    or run.parameters.get("input_mode") != "coordinates"
                    or step.attempts
                    or not step.skip_reason
                ):
                    raise ValueError("Unsupported skipped step")
                continue
            if not step.attempts and step.state != "pending":
                raise ValueError("Step state lacks attempt")
            if step.attempts and step.state != step.attempts[-1].state:
                raise ValueError("Step state differs from latest attempt")
            for number, attempt in enumerate(step.attempts, 1):
                if (
                    attempt.id in attempt_map
                    or attempt.sequence != number
                    or attempt.operation_id not in op_map
                    or attempt.state not in ("running", "succeeded", "failed", "interrupted")
                ):
                    raise ValueError("Invalid attempt identity")
                operation = op_map[attempt.operation_id]
                if (
                    operation.run_id != run.id
                    or operation.client_request_id != attempt.client_request_id
                ):
                    raise ValueError("Attempt belongs to another operation")
                if attempt.state == "succeeded" and (
                    number != len(step.attempts)
                    or attempt.output is None
                    or attempt.error is not None
                ):
                    raise ValueError("Invalid successful attempt")
                if attempt.output_sha256 != (
                    digest(attempt.output) if attempt.output is not None else None
                ):
                    raise ValueError("Workflow output digest differs")
                if attempt.input_sha256 != input_digest(
                    run, step, attempt.input, attempt.dependencies, attempt.software
                ):
                    raise ValueError("Workflow input digest differs")
                Project.utc(attempt.started_at)
                if attempt.completed_at is not None:
                    Project.utc(attempt.completed_at)
                attempt_map[attempt.id] = (run, step, attempt)
                if attempt.snapshot_id:
                    if (
                        step.id != "save_snapshot"
                        or attempt.state != "succeeded"
                        or attempt.snapshot_id not in snapshot_map
                    ):
                        raise ValueError("Invalid workflow snapshot reference")
                    snapshot = snapshot_map[attempt.snapshot_id]
                    if snapshot["project_id"] != project_id or snapshot[
                        "sha256"
                    ] != attempt.output.get("response_sha256"):
                        raise ValueError("Workflow snapshot differs")
                    actual_refs.add((run.id, attempt.snapshot_id))
                if attempt.output is not None:
                    validate_step_output(step.id, attempt.output)
            if (
                step.state == "succeeded"
                and step.id == "save_snapshot"
                and step.attempts[-1].snapshot_id is None
            ):
                raise ValueError("Missing successful snapshot")
        if run.state == "succeeded" and any(
            s.state not in ("succeeded", "skipped") for s in run.steps
        ):
            raise ValueError("Run masks incomplete steps")
    for run, step, attempt in attempt_map.values():
        for dependency in attempt.dependencies:
            target = attempt_map.get(dependency.attempt_id)
            if (
                target is None
                or target[0].id != run.id
                or target[1].id != dependency.step_id
                or target[2].state != "succeeded"
                or target[2].output_sha256 != dependency.sha256
                or run.steps.index(target[1]) >= run.steps.index(step)
            ):
                raise ValueError("Invalid upstream dependency")
        expected, dependencies = prepare_input(run, step.id)
        if expected != attempt.input or [d.model_dump() for d in dependencies] != [
            d.model_dump() for d in attempt.dependencies
        ]:
            raise ValueError("Actual workflow input does not match its declared dependency")
        if attempt.output is not None and step.id == "resolve_name":
            result = attempt.output["result"]
            if (
                result["object_name"] != attempt.input["parameters"]["object_name"]
                or attempt.query_status != result["status"]
            ):
                raise ValueError("Resolution query differs from actual input")
            if attempt.state == "succeeded" and "coordinates" not in attempt.output:
                raise ValueError("Successful resolution lacks coordinates")
        if attempt.output is not None and step.id in ("query_gaia", "query_ads"):
            response = attempt.output["response"]
            field = "gaia_results" if step.id == "query_gaia" else "literature_results"
            if len(response[field]) != 1:
                raise ValueError("Query step must preserve exactly one new tool result")
            result = response[field][0]
            actual_parameters = (
                result["query"]
                if step.id == "query_gaia"
                else {key: result[key] for key in ("query", "rows", "start", "sort")}
            )
            if (
                actual_parameters != attempt.input["parameters"]
                or attempt.query_status != result["status"]
                or attempt.state == "succeeded"
                and result["status"] == "error"
            ):
                raise ValueError("Result does not correspond to the actual query")
            if step.id == "query_ads" and (response["results"] or response["gaia_results"]):
                raise ValueError("ADS workflow contains unrelated tool results")
            if step.id == "query_gaia":
                expected_resolutions = (
                    [run.steps[0].attempts[-1].output["result"]]
                    if run.parameters["input_mode"] == "name"
                    else []
                )
                if response["results"] != expected_resolutions or response["literature_results"]:
                    raise ValueError("Gaia workflow resolution differs from upstream")
        if (
            attempt.state == "succeeded"
            and step.id == "save_snapshot"
            and attempt.output["response_sha256"] != attempt.input["response_sha256"]
        ):
            raise ValueError("Saved snapshot differs from dependency")
    listed_refs = set()
    for reference in value["snapshot_refs"]:
        if not isinstance(reference, dict) or set(reference) != {"run_id", "snapshot_id"}:
            raise ValueError("Invalid workflow snapshot reference fields")
        pair = (reference["run_id"], reference["snapshot_id"])
        if pair in listed_refs:
            raise ValueError("Duplicate snapshot reference")
        listed_refs.add(pair)
    if actual_refs != listed_refs:
        raise ValueError("Incomplete workflow snapshot references")
    outputs, output_map, output_contents = [], {}, {}
    for record in value["outputs"]:
        if (
            not isinstance(record, dict)
            or set(record) != {"info", "content_base64"}
            or not isinstance(record["content_base64"], str)
            or len(record["content_base64"]) > ((16 * 1024**2 + 2) // 3) * 4
        ):
            raise ValueError("Invalid workflow output envelope")
        info = _strict_type(WorkflowOutput).model_validate_json(encode(record["info"]))
        target = attempt_map.get(info.attempt_id)
        if (
            info.id in output_map
            or target is None
            or info.run_id != target[0].id
            or info.project_id != project_id
            or target[2].state != "succeeded"
            or info.id not in target[2].output_ids
        ):
            raise ValueError("Invalid workflow file owner")
        content = base64.b64decode(record["content_base64"], validate=True)
        validate_output(info, content)
        Project.utc(info.created_at)
        outputs.append({"info": info.model_dump(), "content": content})
        output_map[info.id] = info
        output_contents[info.id] = content
    for run, step, attempt in attempt_map.values():
        if len(set(attempt.output_ids)) != len(attempt.output_ids) or any(
            i not in output_map or output_map[i].attempt_id != attempt.id
            for i in attempt.output_ids
        ):
            raise ValueError("Missing or duplicate workflow files")
        if attempt.state != "succeeded" and attempt.output_ids:
            raise ValueError("Uncommitted step exposes files")
        files = [output_map[i] for i in attempt.output_ids]
        if len({f.filename for f in files}) != len(files):
            raise ValueError("Duplicate workflow output names")
        if step.id not in ("evidence_table", "export_results") and files:
            raise ValueError("Unexpected file-producing step")
        if attempt.state == "succeeded" and step.id == "evidence_table":
            if {(f.filename, f.media_type) for f in files} != {
                ("ads-evidence.csv", "text/csv"),
                ("ads-evidence.json", "application/json"),
            }:
                raise ValueError("Incomplete evidence files")
            from astroagent.workflow_service import evidence_rows
            from astroagent.workflow_templates import response_attempt

            expected_value, expected_csv = evidence_rows(
                ChatResponse.model_validate(response_attempt(run).output["response"])
            )
            if attempt.output != expected_value:
                raise ValueError("Evidence table differs from returned abstracts")
            for info in files:
                content = output_contents[info.id]
                if (
                    info.media_type == "text/csv"
                    and content != expected_csv
                    or info.media_type == "application/json"
                    and json.loads(content) != expected_value
                ):
                    raise ValueError("Evidence download differs from preserved raw values")
        if attempt.state == "succeeded" and step.id == "export_results":
            names = {f.filename for f in files}
            expected = {"workflow-results.zip", "export-manifest.json"} | {
                p["output_path"].rsplit("/", 1)[-1]
                for p in attempt.output["manifest"]["plots"]
                if p["status"] == "success"
            }
            if names != expected:
                raise ValueError("Incomplete export files")
            from astroagent.workflow_io import package_members

            content = next(
                output_contents[f.id] for f in files if f.filename == "workflow-results.zip"
            )
            members, manifest = package_members(content)
            saved_step = next(s for s in run.steps if s.id == "save_snapshot")
            snapshot = snapshot_map[saved_step.attempts[-1].snapshot_id]
            if (
                json.loads(members["snapshot.json"]) != snapshot["response"]
                or manifest != attempt.output["manifest"]
            ):
                raise ValueError("Workflow ZIP differs from its named snapshot")
            for info in files:
                if (
                    info.media_type == "application/json"
                    and json.loads(output_contents[info.id]) != manifest
                ):
                    raise ValueError("Workflow manifest download differs")
                if info.media_type == "image/png":
                    original = next(
                        members[path]
                        for path in members
                        if path.rsplit("/", 1)[-1] == info.filename
                    )
                    if output_contents[info.id] != original:
                        raise ValueError("PNG preview differs from its ZIP")
    return {
        "runs": [r.model_dump(mode="json") for r in runs],
        "operations": [o.model_dump(mode="json") for o in operations],
        "outputs": outputs,
        "snapshot_refs": value["snapshot_refs"],
    }


def validate_step_output(step_id, output):
    if not isinstance(output, dict):
        raise ValueError("Invalid step output")
    if step_id == "resolve_name":
        if set(output) not in ({"result"}, {"result", "coordinates"}):
            raise ValueError("Unknown name-resolution output")
        result = _strict_type(QueryResult).model_validate_json(encode(output["result"]))
        if result.source.name != "SIMBAD":
            raise ValueError("Invalid name-resolution source")
        if "coordinates" in output and (
            result.status != "success"
            or result.data is None
            or output["coordinates"]
            != {"ra_deg": result.data.ra_deg, "dec_deg": result.data.dec_deg}
        ):
            raise ValueError("Coordinates differ from returned measurement")
    elif step_id in ("query_gaia", "query_ads"):
        if set(output) != {"response"}:
            raise ValueError("Unknown query output")
        validate_snapshot(ExportSnapshot.model_validate_json(encode(output["response"])))
    elif step_id == "save_snapshot":
        if set(output) != {"response_sha256", "status"}:
            raise ValueError("Unknown snapshot output")
    elif step_id == "export_results":
        if (
            set(output) != {"manifest", "answer_origin"}
            or output["answer_origin"] != "program_fixed_workflow"
        ):
            raise ValueError("Unknown export output")
        _strict_type(ExportManifest).model_validate_json(encode(output["manifest"]))
    elif (
        set(output)
        != {
            "format_version",
            "columns",
            "rows",
            "query_status",
            "source",
            "csv_policy",
            "csv_changes",
        }
        or output["format_version"] != "1"
        or not isinstance(output["rows"], list)
        or len(output["rows"]) > 10
    ):
        raise ValueError("Unknown evidence output")


def import_workflows(db, bundle, project_id, id_map, archive_sha256):
    from uuid import uuid4

    for kind, values in (
        ("workflows", bundle["runs"]),
        ("workflow_operations", bundle["operations"]),
    ):
        id_map[kind] = {v["id"]: str(uuid4()) for v in values}
    id_map["workflow_attempts"] = {
        a["id"]: str(uuid4()) for r in bundle["runs"] for s in r["steps"] for a in s["attempts"]
    }
    id_map["workflow_outputs"] = {v["info"]["id"]: str(uuid4()) for v in bundle["outputs"]}
    key_map = {o["id"]: str(uuid4()) for o in bundle["operations"]}
    now = utc_now()
    interrupted = {
        "code": "imported_workflow_interrupted",
        "message": "导入的运行记录已中断；未执行或自动恢复外部查询。",
        "retryable": False,
    }
    id_map["workflow_request_keys"] = dict(key_map)
    for old in bundle["runs"]:
        run = copy.deepcopy(old)
        run.update(
            id=id_map["workflows"][old["id"]],
            project_id=project_id,
            provenance="imported_unverified",
            original_id=old["id"],
            archive_sha256=archive_sha256,
        )
        if run["state"] == "running":
            run.update(
                state="interrupted", updated_at=now, revision=run["revision"] + 1, error=interrupted
            )
        for step in run["steps"]:
            if step["state"] == "running":
                step.update(state="interrupted", error=interrupted)
            for attempt in step["attempts"]:
                old_op = attempt["operation_id"]
                attempt.update(
                    id=id_map["workflow_attempts"][attempt["id"]],
                    operation_id=id_map["workflow_operations"][old_op],
                    client_request_id=key_map[old_op],
                )
                for dependency in attempt["dependencies"]:
                    dependency["attempt_id"] = id_map["workflow_attempts"][dependency["attempt_id"]]
                if attempt["snapshot_id"]:
                    attempt["snapshot_id"] = id_map["snapshots"][attempt["snapshot_id"]]
                attempt["output_ids"] = [
                    id_map["workflow_outputs"][i] for i in attempt["output_ids"]
                ]
                if attempt["state"] == "running":
                    attempt.update(state="interrupted", completed_at=now, error=interrupted)
        if len(encode(run).encode("utf-8")) > 16 * 1024**2:
            raise ServiceError(
                413, "workflow_record_too_large", "归档流程记录超过16 MiB，未写入数据。"
            )
        db.execute(
            "INSERT INTO workflows VALUES (?,?,?,?,0)",
            (run["id"], project_id, run["state"], encode(run)),
        )
    for old in bundle["operations"]:
        value = copy.deepcopy(old)
        value.update(
            id=id_map["workflow_operations"][old["id"]],
            run_id=id_map["workflows"][old["run_id"]],
            client_request_id=key_map[old["id"]],
        )
        if value["state"] == "running":
            value.update(state="interrupted", completed_at=now, error=interrupted)
        db.execute(
            "INSERT INTO workflow_operations VALUES (?,?,?,?,?,?,0)",
            (
                value["id"],
                value["run_id"],
                value["client_request_id"],
                "imported:" + archive_sha256,
                value["state"],
                encode(value),
            ),
        )
    for record in bundle["outputs"]:
        old = record["info"]
        info = {
            **old,
            "id": id_map["workflow_outputs"][old["id"]],
            "run_id": id_map["workflows"][old["run_id"]],
            "project_id": project_id,
            "attempt_id": id_map["workflow_attempts"][old["attempt_id"]],
            "provenance": "imported_unverified",
            "original_id": old["id"],
        }
        db.execute(
            "INSERT INTO workflow_outputs VALUES (?,?,?,?)",
            (info["id"], info["run_id"], encode(info), record["content"]),
        )
    for reference in bundle["snapshot_refs"]:
        db.execute(
            "INSERT INTO workflow_snapshot_refs VALUES (?,?)",
            (
                id_map["workflows"][reference["run_id"]],
                id_map["snapshots"][reference["snapshot_id"]],
            ),
        )
