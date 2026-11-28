"""租户隔离（aa_<32-hex>）的 V2.3 项目数据表与确定性分析运行持久化存储。"""

from __future__ import annotations

from astroagent.conversations import encode, utc_now
from astroagent.errors import ServiceError
from astroagent.projects import ProjectRepository
from astroagent.table_io import ParsedTable, decode_canonical_ecsv_gz, encode_canonical_ecsv_gz
from astroagent.table_schemas import (
    MAX_PROJECT_RUNS,
    MAX_PROJECT_TABLES,
    TABLE_SCHEMA_VERSION,
    AnalysisDataset,
    AnalysisRunRecord,
)
from astroagent.usage import require_storage

DDL = (
    "CREATE TABLE IF NOT EXISTS table_meta (version INTEGER PRIMARY KEY CHECK (version = 1))",
    (
        "CREATE TABLE IF NOT EXISTS analysis_datasets ("
        "id TEXT PRIMARY KEY, "
        "project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE, "
        "name TEXT NOT NULL, "
        "source TEXT NOT NULL, "
        "source_sha256 TEXT NOT NULL, "
        "data_sha256 TEXT NOT NULL, "
        "row_count INTEGER NOT NULL, "
        "column_count INTEGER NOT NULL, "
        "record TEXT NOT NULL, "
        "data_gz BYTEA NOT NULL, "
        "created_at TEXT NOT NULL, "
        "updated_at TEXT NOT NULL)"
    ),
    (
        "CREATE INDEX IF NOT EXISTS idx_analysis_datasets_proj "
        "ON analysis_datasets (project_id, created_at DESC)"
    ),
    (
        "CREATE TABLE IF NOT EXISTS analysis_runs ("
        "id TEXT PRIMARY KEY, "
        "project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE, "
        "operator TEXT NOT NULL, "
        "state TEXT NOT NULL, "
        "request_sha256 TEXT NOT NULL, "
        "output_dataset_id TEXT REFERENCES analysis_datasets(id) ON DELETE SET NULL, "
        "record TEXT NOT NULL, "
        "created_at TEXT NOT NULL)"
    ),
    (
        "CREATE INDEX IF NOT EXISTS idx_analysis_runs_proj "
        "ON analysis_runs (project_id, created_at DESC)"
    ),
    f"INSERT INTO table_meta(version) VALUES({TABLE_SCHEMA_VERSION}) "
    "ON CONFLICT (version) DO NOTHING",
)


def ready(db) -> bool:
    if getattr(db, "dialect", None) != "postgresql":
        return False
    if not db.execute("SELECT to_regclass('table_meta')").fetchone()[0]:
        return False
    row = db.execute("SELECT version FROM table_meta").fetchone()
    return bool(row and row[0] == TABLE_SCHEMA_VERSION)


def used(db) -> int:
    if not ready(db):
        return 0
    ds_bytes = int(
        db.execute(
            "SELECT COALESCE(SUM(octet_length(record) + octet_length(data_gz)), 0) "
            "FROM analysis_datasets"
        ).fetchone()[0]
    )
    run_bytes = int(
        db.execute("SELECT COALESCE(SUM(octet_length(record)), 0) FROM analysis_runs").fetchone()[0]
    )
    return ds_bytes + run_bytes


class TableStore:
    def __init__(self, repo):
        self.repo = repo
        self.projects = ProjectRepository(repo)

    def _ensure_ready(self, db) -> None:
        if getattr(db, "dialect", None) != "postgresql":
            raise ServiceError(
                503,
                "table_storage_unavailable",
                "天文数据表存储仅支持已就绪的 PostgreSQL 数据库。",
            )
        if not ready(db):
            for statement in DDL:
                db.execute(statement)

    def list_datasets(self, project_id: str) -> list[AnalysisDataset]:
        with self.repo.connection() as db:
            self.projects._project(db, project_id)
            if not ready(db):
                return []
            rows = db.execute(
                "SELECT record FROM analysis_datasets WHERE project_id=? "
                "ORDER BY created_at DESC, id DESC",
                (project_id,),
            ).fetchall()
            return [AnalysisDataset.model_validate_json(row[0]) for row in rows]

    def list_runs(self, project_id: str) -> list[AnalysisRunRecord]:
        with self.repo.connection() as db:
            self.projects._project(db, project_id)
            if not ready(db):
                return []
            rows = db.execute(
                "SELECT record FROM analysis_runs WHERE project_id=? "
                "ORDER BY created_at DESC, id DESC",
                (project_id,),
            ).fetchall()
            return [AnalysisRunRecord.model_validate_json(row[0]) for row in rows]

    def get_dataset(self, project_id: str, dataset_id: str) -> AnalysisDataset:
        with self.repo.connection() as db:
            self.projects._project(db, project_id)
            if not ready(db):
                raise ServiceError(404, "table_dataset_not_found", "该项目中不存在此数据表。")
            row = db.execute(
                "SELECT record FROM analysis_datasets WHERE id=? AND project_id=?",
                (dataset_id, project_id),
            ).fetchone()
            if row is None:
                raise ServiceError(404, "table_dataset_not_found", "该项目中不存在此数据表。")
            return AnalysisDataset.model_validate_json(row[0])

    def get_dataset_with_data(
        self, project_id: str, dataset_id: str
    ) -> tuple[AnalysisDataset, ParsedTable, bytes]:
        with self.repo.connection() as db:
            self.projects._project(db, project_id)
            if not ready(db):
                raise ServiceError(404, "table_dataset_not_found", "该项目中不存在此数据表。")
            row = db.execute(
                "SELECT record, data_gz FROM analysis_datasets WHERE id=? AND project_id=?",
                (dataset_id, project_id),
            ).fetchone()
            if row is None:
                raise ServiceError(404, "table_dataset_not_found", "该项目中不存在此数据表。")
            dataset = AnalysisDataset.model_validate_json(row[0])
            gz_bytes = bytes(row[1])
        parsed = decode_canonical_ecsv_gz(gz_bytes)
        return dataset, parsed, gz_bytes

    def save_dataset(
        self,
        *,
        dataset_id: str,
        project_id: str,
        name: str,
        source: str,
        source_sha256: str,
        parsed: ParsedTable,
        lineage,
        warnings: list[str] | None = None,
    ) -> AnalysisDataset:
        _, gz_bytes, data_sha256 = encode_canonical_ecsv_gz(parsed)
        now = utc_now()
        dataset = AnalysisDataset(
            id=dataset_id,
            project_id=project_id,
            name=name.strip()[:128] or "未命名数据表",
            source=source,
            format=parsed.format,
            source_sha256=source_sha256,
            data_sha256=data_sha256,
            row_count=len(parsed.rows),
            column_count=len(parsed.columns),
            columns=parsed.columns,
            coordinate_frame=parsed.coordinate_frame,
            ref_epoch=parsed.ref_epoch,
            header_meta=parsed.header_meta or {},
            lineage=lineage,
            warnings=list(dict.fromkeys([*(parsed.warnings or []), *(warnings or [])])),
            created_at=now,
            updated_at=now,
        )
        record_json = encode(dataset.model_dump(mode="json"))
        require_storage(len(gz_bytes) + len(record_json.encode("utf-8")))
        with self.repo.connection() as db, self.repo.transaction(db):
            self._ensure_ready(db)
            self.projects._project(db, project_id)
            existing = db.execute(
                "SELECT record FROM analysis_datasets WHERE id=?",
                (dataset_id,),
            ).fetchone()
            if existing is not None:
                old = AnalysisDataset.model_validate_json(existing[0])
                if (
                    old.project_id != project_id
                    or old.source_sha256 != source_sha256
                    or old.data_sha256 != data_sha256
                ):
                    raise ServiceError(
                        409, "table_dataset_conflict", "同一数据表标识不能用于不同内容。"
                    )
                return old
            count = db.execute(
                "SELECT count(*) FROM analysis_datasets WHERE project_id=?",
                (project_id,),
            ).fetchone()[0]
            if count >= MAX_PROJECT_TABLES:
                raise ServiceError(
                    409,
                    "table_dataset_limit",
                    f"单个项目最多保存 {MAX_PROJECT_TABLES} 张数据表，请先清理无用表格。",
                )
            db.execute(
                "INSERT INTO analysis_datasets("
                "id, project_id, name, source, source_sha256, data_sha256, "
                "row_count, column_count, record, data_gz, created_at, updated_at"
                ") VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    dataset.id,
                    dataset.project_id,
                    dataset.name,
                    dataset.source,
                    dataset.source_sha256,
                    dataset.data_sha256,
                    dataset.row_count,
                    dataset.column_count,
                    record_json,
                    gz_bytes,
                    dataset.created_at,
                    dataset.updated_at,
                ),
            )
            self.projects._touch(db, project_id)
            self.projects._budget(db)
            return dataset

    def delete_dataset(self, project_id: str, dataset_id: str) -> None:
        with self.repo.connection() as db, self.repo.transaction(db):
            self.projects._project(db, project_id)
            if not ready(db):
                raise ServiceError(404, "table_dataset_not_found", "该项目中不存在此数据表。")
            row = db.execute(
                "SELECT id FROM analysis_datasets WHERE id=? AND project_id=?",
                (dataset_id, project_id),
            ).fetchone()
            if row is None:
                raise ServiceError(404, "table_dataset_not_found", "该项目中不存在此数据表。")
            db.execute(
                "DELETE FROM analysis_datasets WHERE id=? AND project_id=?",
                (dataset_id, project_id),
            )
            self.projects._touch(db, project_id)

    def get_run(self, project_id: str, run_id: str) -> AnalysisRunRecord:
        with self.repo.connection() as db:
            self.projects._project(db, project_id)
            if not ready(db):
                raise ServiceError(404, "table_run_not_found", "该项目中不存在此分析记录。")
            row = db.execute(
                "SELECT record FROM analysis_runs WHERE id=? AND project_id=?",
                (run_id, project_id),
            ).fetchone()
            if row is None:
                raise ServiceError(404, "table_run_not_found", "该项目中不存在此分析记录。")
            return AnalysisRunRecord.model_validate_json(row[0])

    def save_run(self, run: AnalysisRunRecord) -> AnalysisRunRecord:
        record_json = encode(run.model_dump(mode="json"))
        require_storage(len(record_json.encode("utf-8")))
        with self.repo.connection() as db, self.repo.transaction(db):
            self._ensure_ready(db)
            self.projects._project(db, run.project_id)
            count = db.execute(
                "SELECT count(*) FROM analysis_runs WHERE project_id=?",
                (run.project_id,),
            ).fetchone()[0]
            if count >= MAX_PROJECT_RUNS:
                # 保留最近 MAX_PROJECT_RUNS 条，超出则淘汰最老记录避免阻塞科研分析
                oldest = db.execute(
                    "SELECT id FROM analysis_runs WHERE project_id=? "
                    "ORDER BY created_at ASC LIMIT ?",
                    (run.project_id, count - MAX_PROJECT_RUNS + 1),
                ).fetchall()
                for row in oldest:
                    db.execute("DELETE FROM analysis_runs WHERE id=?", (row[0],))
            db.execute(
                "INSERT INTO analysis_runs("
                "id, project_id, operator, state, request_sha256, "
                "output_dataset_id, record, created_at"
                ") VALUES(?,?,?,?,?,?,?,?)",
                (
                    run.id,
                    run.project_id,
                    run.operator,
                    run.state,
                    run.request_sha256,
                    run.output_dataset_id,
                    record_json,
                    run.created_at,
                ),
            )
            self.projects._touch(db, run.project_id)
            self.projects._budget(db)
            return run
