"""Format 6 plotting history; import never runs code or calls a model."""

import base64
import json
from copy import deepcopy
from uuid import uuid4

from astroagent.conversations import encode, utc_now
from astroagent.plot_data import canonical, dataset, digest, from_snapshot, table
from astroagent.plot_schemas import PlotDataset, PlotOperation
from astroagent.plot_service import FILES
from astroagent.plot_store import ready, require
from astroagent.project_schemas import Project, Snapshot


def empty():
    return {"datasets": [], "operations": [], "outputs": []}


def read(db, project_id):
    if not ready(db):
        return empty()
    datasets = [
        {
            "info": json.loads(r[0]),
            "data": base64.b64encode(r[1]).decode(),
            "original": base64.b64encode(r[2]).decode(),
        }
        for r in db.execute(
            "SELECT record,data,original FROM plot_datasets WHERE project_id=? ORDER BY id",
            (project_id,),
        )
    ]
    operations = [
        json.loads(r[0])
        for r in db.execute(
            "SELECT record FROM plot_operations WHERE project_id=? ORDER BY id", (project_id,)
        )
    ]
    outputs = [
        {"run_id": r[0], "name": r[1], "content": base64.b64encode(r[2]).decode()}
        for r in db.execute(
            "SELECT o.run_id,o.name,o.content FROM plot_outputs o "
            "JOIN plot_operations p ON p.id=o.run_id "
            "WHERE p.project_id=? ORDER BY o.run_id,o.name",
            (project_id,),
        )
    ]
    return {"datasets": datasets, "operations": operations, "outputs": outputs}


def validate(raw, project_id):
    if (
        not isinstance(raw, dict)
        or set(raw) != {"datasets", "operations", "outputs"}
        or not all(isinstance(v, list) for v in raw.values())
        or len(raw["datasets"]) > 30
        or len(raw["operations"]) > 100
        or len(raw["outputs"]) > 900
    ):
        raise ValueError("Invalid plotting member")
    datasets = {}
    for entry in raw["datasets"]:
        if set(entry) != {"info", "data", "original"}:
            raise ValueError("Invalid dataset member")
        info = PlotDataset.model_validate_json(encode(entry["info"]))
        data, original = (
            base64.b64decode(entry[key], validate=True) for key in ("data", "original")
        )
        if (
            info.id in datasets
            or info.project_id != project_id
            or digest(data) != info.data_sha256
            or digest(original) != info.source_sha256
            or len(original) > 16 * 1024**2
        ):
            raise ValueError("Dataset identity or hash mismatch")
        header, rows = table(data, "data.csv")
        if (
            info.rows != len(rows)
            or header != [c.name for c in info.columns]
            or any(
                c.missing != sum(not row[i].strip() for row in rows)
                for i, c in enumerate(info.columns)
            )
        ):
            raise ValueError("Dataset metadata mismatch")
        Project.utc(info.created_at)
        if info.source == "upload":
            source_header, source_rows = table(original, str(info.provenance.get("filename", "")))
            if canonical(source_header, source_rows) != data:
                raise ValueError("Uploaded source differs from plot data")
            expected, _ = dataset(info.id, info.project_id, info.name, original, header, rows)
        else:
            snapshot = Snapshot.model_validate_json(original).verify_digest()
            expected, expected_data, _ = from_snapshot(
                info.id,
                info.project_id,
                snapshot.model_dump(mode="json"),
                info.provenance.get("query_index", -1),
            )
            if expected_data != data:
                raise ValueError("Snapshot differs from plot data")
        if expected["columns"] != [c.model_dump() for c in info.columns]:
            raise ValueError("Column interpretation differs from source")
        datasets[info.id] = info
    operations = {}
    for value in raw["operations"]:
        op = PlotOperation.model_validate_json(encode(value))
        if (
            op.id in operations
            or op.project_id != project_id
            or op.dataset_id not in datasets
            or op.request_sha256 != digest(encode(op.request).encode())
        ):
            raise ValueError("Plotting operation identity mismatch")
        if op.proposal and (
            op.script_sha256 != digest(op.proposal.script.encode())
            or not set(op.proposal.columns) <= {c.name for c in datasets[op.dataset_id].columns}
        ):
            raise ValueError("Plotting script or columns mismatch")
        if op.state == "completed" and not op.proposal:
            raise ValueError("Completed operation needs a proposal")
        if (
            len(op.files) != len(set(op.files))
            or not set(op.files) <= FILES.keys()
            or (op.files and (op.kind != "run" or op.state != "completed"))
        ):
            raise ValueError("Invalid plotting output references")
        operations[op.id] = op
    for op in operations.values():
        if op.kind == "plan" and op.request.get("dataset_id") != op.dataset_id:
            raise ValueError("Plan data reference mismatch")
        if op.kind == "run":
            plan = operations.get(op.request.get("plan_id"))
            if (
                plan is None
                or plan.kind != "plan"
                or plan.state != "completed"
                or plan.dataset_id != op.dataset_id
            ):
                raise ValueError("Run plan reference mismatch")
            if op.proposal is not None and op.proposal != plan.proposal:
                raise ValueError("Run proposal differs from confirmed plan")
    outputs = {}
    for entry in raw["outputs"]:
        if set(entry) != {"run_id", "name", "content"}:
            raise ValueError("Invalid plotting output")
        key = (entry["run_id"], entry["name"])
        op = operations.get(entry["run_id"])
        content = base64.b64decode(entry["content"], validate=True)
        if (
            key in outputs
            or op is None
            or entry["name"] not in op.files
            or len(content) > 16 * 1024**2
        ):
            raise ValueError("Invalid plotting output identity")
        outputs[key] = content
    if set(outputs) != {(op.id, name) for op in operations.values() for name in op.files}:
        raise ValueError("Missing plotting output")
    for op in operations.values():
        if op.kind == "run" and op.state == "completed":
            names = set(op.files)
            script = "script.py" if op.proposal.engine == "python" else "script.plt"
            if (
                not {"figure.png", "figure.pdf", "data.csv", script, "manifest.json", "README.md"}
                <= names
            ):
                raise ValueError("Incomplete plot delivery")
            if (
                digest(outputs[op.id, script]) != op.script_sha256
                or digest(outputs[op.id, "data.csv"]) != datasets[op.dataset_id].data_sha256
            ):
                raise ValueError("Plot input bytes changed")
            if not outputs[op.id, "figure.png"].startswith(b"\x89PNG\r\n\x1a\n") or not outputs[
                op.id, "figure.pdf"
            ].startswith(b"%PDF-"):
                raise ValueError("Invalid plot media")
            manifest = json.loads(outputs[op.id, "manifest.json"])
            if (
                manifest.get("format") != "astroagent-plot"
                or manifest.get("version") != 1
                or manifest.get("script_sha256") != op.script_sha256
                or manifest.get("proposal") != op.proposal.model_dump()
                or manifest.get("dataset", {}).get("data_sha256")
                != datasets[op.dataset_id].data_sha256
                or manifest.get("dataset", {}).get("source_sha256")
                != datasets[op.dataset_id].source_sha256
            ):
                raise ValueError("Plot manifest differs from saved operation")
            if set(manifest["files"]) != names - {"manifest.json"}:
                raise ValueError("Manifest output mismatch")
            for name, checksum in manifest["files"].items():
                content = outputs[op.id, name]
                if (
                    not isinstance(checksum, dict)
                    or type(checksum.get("bytes")) is not int
                    or checksum != {"bytes": len(content), "sha256": digest(content)}
                ):
                    raise ValueError("Plot output checksum mismatch")
    return raw


def restore(db, bundle, project_id, id_map):
    if not any(bundle.values()):
        return
    require(db)
    id_map["plot_datasets"] = {v["info"]["id"]: str(uuid4()) for v in bundle["datasets"]}
    id_map["plot_operations"] = {v["id"]: str(uuid4()) for v in bundle["operations"]}
    for entry in bundle["datasets"]:
        info = deepcopy(entry["info"])
        info.update(id=id_map["plot_datasets"][info["id"]], project_id=project_id)
        info["provenance"] = {
            **info["provenance"],
            "imported_unverified": True,
            "original_dataset_id": entry["info"]["id"],
        }
        db.execute(
            "INSERT INTO plot_datasets(id,project_id,record,data,original) VALUES(?,?,?,?,?)",
            (
                info["id"],
                project_id,
                encode(info),
                base64.b64decode(entry["data"]),
                base64.b64decode(entry["original"]),
            ),
        )
    for source in bundle["operations"]:
        op = deepcopy(source)
        op.update(
            id=id_map["plot_operations"][op["id"]],
            project_id=project_id,
            dataset_id=id_map["plot_datasets"][op["dataset_id"]],
            imported=True,
        )
        for key, mapping in (("dataset_id", "plot_datasets"), ("plan_id", "plot_operations")):
            if key in op["request"]:
                if op["request"][key] not in id_map[mapping]:
                    raise ValueError("Missing plotting request reference")
                op["request"][key] = id_map[mapping][op["request"][key]]
        op["runtime"] = {
            **op["runtime"],
            "original_operation_id": source["id"],
            "original_request_sha256": source["request_sha256"],
            "imported_unverified": True,
        }
        op["request_sha256"] = digest(encode(op["request"]).encode())
        if op["state"] == "running":
            op.update(state="interrupted", completed_at=utc_now(), error="导入操作不自动重放。")
        db.execute(
            "INSERT INTO plot_operations(id,project_id,kind,state,record) VALUES(?,?,?,?,?)",
            (op["id"], project_id, op["kind"], op["state"], encode(op)),
        )
    for entry in bundle["outputs"]:
        db.execute(
            "INSERT INTO plot_outputs(run_id,name,content) VALUES(?,?,?)",
            (
                id_map["plot_operations"][entry["run_id"]],
                entry["name"],
                base64.b64decode(entry["content"]),
            ),
        )
