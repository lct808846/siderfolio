"""Optional PostgreSQL extension; initialized only by an explicit setup request."""

import json

from astroagent.conversations import encode, utc_now
from astroagent.errors import ServiceError
from astroagent.plot_data import digest
from astroagent.plot_schemas import PlotOperation
from astroagent.projects import ProjectRepository

DDL = (
    "CREATE TABLE plot_meta (version INTEGER PRIMARY KEY CHECK (version=1))",
    "CREATE TABLE plot_datasets (id TEXT PRIMARY KEY, "
    "project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE, "
    "record TEXT NOT NULL, data BYTEA NOT NULL, original BYTEA NOT NULL)",
    "CREATE TABLE plot_operations (id TEXT PRIMARY KEY, "
    "project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE, "
    "kind TEXT NOT NULL, state TEXT NOT NULL, record TEXT NOT NULL)",
    "CREATE TABLE plot_outputs (run_id TEXT NOT NULL "
    "REFERENCES plot_operations(id) ON DELETE CASCADE, "
    "name TEXT NOT NULL, content BYTEA NOT NULL, PRIMARY KEY(run_id,name))",
    "INSERT INTO plot_meta(version) VALUES(1)",
)


def ready(db):
    if getattr(db, "dialect", None) != "postgresql":
        return False
    if not db.execute("SELECT to_regclass('plot_meta')").fetchone()[0]:
        return False
    return db.execute("SELECT version FROM plot_meta").fetchone()[0] == 1


def require(db):
    if not ready(db):
        raise ServiceError(
            409, "plot_storage_not_initialized", "请先在绘图工作区确认创建绘图扩展表。"
        )


def used(db):
    if not ready(db):
        return 0
    return db.execute(
        "SELECT COALESCE((SELECT SUM(octet_length(record)+octet_length(data)+"
        "octet_length(original)) FROM plot_datasets),0)+"
        "COALESCE((SELECT SUM(octet_length(record)+CASE WHEN state='running' "
        "THEN 20000000 ELSE 0 END) FROM plot_operations),0)+"
        "COALESCE((SELECT SUM(octet_length(content)) FROM plot_outputs),0)"
    ).fetchone()[0]


def assert_idle(db, project_id):
    if (
        ready(db)
        and db.execute(
            "SELECT 1 FROM plot_operations WHERE project_id=? AND state='running'", (project_id,)
        ).fetchone()
    ):
        raise ServiceError(
            409, "plot_project_busy", "项目正在生成绘图方案或执行绘图，请先核对运行状态。"
        )


class PlotStore:
    def __init__(self, repo):
        self.repo = repo
        self.projects = ProjectRepository(repo)

    def initialize(self):
        with self.repo.connection() as db, self.repo.transaction(db):
            if not ready(db):
                for statement in DDL:
                    db.execute(statement)

    def recover(self):
        interrupted = []
        with self.repo.connection() as db, self.repo.transaction(db):
            if ready(db):
                for row in db.execute("SELECT record FROM plot_operations WHERE state='running'"):
                    value = json.loads(row[0])
                    if value["kind"] == "run":
                        interrupted.append(value["id"])
                    value.update(
                        state="interrupted",
                        completed_at=utc_now(),
                        error="服务重启中断了操作；不会自动重放模型调用或脚本。",
                    )
                    self.put_operation(db, value)
        return interrupted

    def dataset(self, db, project_id, identifier):
        require(db)
        row = db.execute(
            "SELECT record,data,original FROM plot_datasets WHERE id=? AND project_id=?",
            (identifier, project_id),
        ).fetchone()
        if row is None:
            raise ServiceError(404, "plot_dataset_not_found", "该项目中不存在此数据集。")
        return json.loads(row[0]), bytes(row[1]), bytes(row[2])

    def save_dataset(self, info, data, original):
        with self.repo.connection() as db, self.repo.transaction(db):
            require(db)
            self.projects._project(db, info["project_id"])
            row = db.execute(
                "SELECT record FROM plot_datasets WHERE id=?", (info["id"],)
            ).fetchone()
            if row:
                old = json.loads(row[0])
                if (
                    old["project_id"] != info["project_id"]
                    or old["source_sha256"] != info["source_sha256"]
                    or old["data_sha256"] != info["data_sha256"]
                    or old["name"] != info["name"]
                    or old["source"] != info["source"]
                    or old["provenance"] != info["provenance"]
                ):
                    raise ServiceError(
                        409, "plot_request_conflict", "同一数据集标识不能用于不同输入。"
                    )
                return old
            if (
                db.execute(
                    "SELECT count(*) FROM plot_datasets WHERE project_id=?", (info["project_id"],)
                ).fetchone()[0]
                >= 30
            ):
                raise ServiceError(409, "plot_dataset_limit", "每个项目最多30份绘图数据集。")
            db.execute(
                "INSERT INTO plot_datasets(id,project_id,record,data,original) VALUES(?,?,?,?,?)",
                (info["id"], info["project_id"], encode(info), data, original),
            )
            self.projects._touch(db, info["project_id"])
            self.projects._budget(db)
            return info

    def list(self, project_id):
        with self.repo.connection() as db:
            require(db)
            self.projects._project(db, project_id)
            return {
                "datasets": [
                    json.loads(r[0])
                    for r in db.execute(
                        "SELECT record FROM plot_datasets WHERE project_id=? ORDER BY id",
                        (project_id,),
                    )
                ],
                "operations": [
                    json.loads(r[0])
                    for r in db.execute(
                        "SELECT record FROM plot_operations WHERE project_id=? "
                        "ORDER BY record::jsonb->>'created_at' DESC",
                        (project_id,),
                    )
                ],
            }

    def operation(self, db, project_id, identifier):
        require(db)
        row = db.execute(
            "SELECT record FROM plot_operations WHERE id=? AND project_id=?",
            (identifier, project_id),
        ).fetchone()
        if not row:
            raise ServiceError(404, "plot_operation_not_found", "该项目中不存在此绘图记录。")
        return json.loads(row[0])

    @staticmethod
    def put_operation(db, value):
        db.execute(
            "UPDATE plot_operations SET state=?,record=? WHERE id=?",
            (value["state"], encode(value), value["id"]),
        )

    def reserve(self, project_id, identifier, kind, request, dataset_id):
        request_hash = digest(encode(request).encode())
        with self.repo.connection() as db, self.repo.transaction(db):
            require(db)
            self.projects._project(db, project_id)
            row = db.execute(
                "SELECT record FROM plot_operations WHERE id=?", (identifier,)
            ).fetchone()
            if row:
                old = json.loads(row[0])
                if (
                    old["project_id"] != project_id
                    or old["kind"] != kind
                    or old["request_sha256"] != request_hash
                ):
                    raise ServiceError(409, "plot_request_conflict", "请求标识已用于不同绘图操作。")
                return old, False
            assert_idle(db, project_id)
            if (
                db.execute(
                    "SELECT count(*) FROM plot_operations WHERE project_id=?", (project_id,)
                ).fetchone()[0]
                >= 100
            ):
                raise ServiceError(409, "plot_operation_limit", "每个项目最多100条方案及运行记录。")
            value = PlotOperation(
                id=identifier,
                project_id=project_id,
                dataset_id=dataset_id,
                kind=kind,
                state="running",
                created_at=utc_now(),
                request_sha256=request_hash,
                request=request,
            ).model_dump()
            db.execute(
                "INSERT INTO plot_operations(id,project_id,kind,state,record) VALUES(?,?,?,?,?)",
                (identifier, project_id, kind, "running", encode(value)),
            )
            self.projects._touch(db, project_id)
            self.projects._budget(db)
            return value, True

    def finish(self, value, files=None):
        with self.repo.connection() as db, self.repo.transaction(db):
            old = self.operation(db, value["project_id"], value["id"])
            if old["state"] != "running":
                return old
            value["completed_at"] = utc_now()
            value["files"] = sorted(files or {})
            self.put_operation(db, value)
            for name, raw in (files or {}).items():
                db.execute(
                    "INSERT INTO plot_outputs(run_id,name,content) VALUES(?,?,?)",
                    (value["id"], name, raw),
                )
            self.projects._touch(db, value["project_id"])
            self.projects._budget(db)
            return value
