"""Explicit, read-only schema5 SQLite backup -> empty PostgreSQL schema6 import.

Never run automatically at startup. Credentials are read only from server environment.
"""

import argparse
import hashlib
import json
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

from astroagent.config import LocalSettings
from astroagent.postgres import COLUMNS, PostgresRepository


def sha256(path):
    sha = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024**2):
            sha.update(chunk)
    return sha.hexdigest()


def row_digest(row):
    values = [
        {"bytes": bytes(value).hex()}
        if isinstance(value, (bytes, bytearray, memoryview))
        else value
        for value in row
    ]
    return hashlib.sha256(
        json.dumps(values, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--expected-sha256", required=True)
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--confirm", action="store_true")
    args = parser.parse_args()
    if not args.confirm:
        parser.error("必须显式--confirm；只接受停服后的一致性SQLite备份，目标必须为空。")
    if args.report.exists():
        parser.error("报告必须是新文件，不覆盖已有证据。")
    repo = None
    report = {
        "kind": "sqlite5_to_postgresql6",
        "started_at": datetime.now(UTC).isoformat(),
        "completed": False,
        "tables": {},
        "retrieval_quality_validated": False,
    }
    try:
        path = args.source.resolve(strict=True)
        source_sha = sha256(path)
        if source_sha != args.expected_sha256.lower():
            raise ValueError("源备份SHA-256不符，未导入。")
        report["source_sha256"] = source_sha
        # immutable avoids creating WAL/SHM. The user must provide a frozen backup, not a live DB.
        with closing(sqlite3.connect(path.as_uri() + "?mode=ro&immutable=1", uri=True)) as source:
            if source.execute("PRAGMA user_version").fetchone()[0] != 5:
                raise ValueError("只支持V0.9 schema5一致性备份。旧库先由对应旧版本在独立副本升级。")
            if (
                source.execute("PRAGMA integrity_check").fetchone()[0] != "ok"
                or source.execute("PRAGMA foreign_key_check").fetchall()
            ):
                raise ValueError("源库完整性或外键校验失败。")
            repo = PostgresRepository(LocalSettings())
            repo.initialize(create=True)
            with repo.connection() as db, repo.transaction(db):
                if any(
                    db.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
                    for table in COLUMNS
                    if table != "knowledge_meta"
                ):
                    raise ValueError("目标含业务数据；拒绝覆盖或混入。")
                if (
                    db.execute("SELECT count(*) FROM rag_answers").fetchone()[0]
                    or db.execute("SELECT count(*) FROM rag_indexes").fetchone()[0]
                ):
                    raise ValueError("目标含RAG数据，拒绝覆盖。")
                for table, fields in COLUMNS.items():
                    if table == "knowledge_meta":
                        continue  # PG indexes are rebuilt from authoritative units.
                    before = []
                    for row in source.execute(f"SELECT {fields} FROM {table} ORDER BY rowid"):
                        # Persist original JSON bytes, timestamps, IDs and file bytes unchanged.
                        before.append(row_digest(row))
                        db.execute(
                            f"INSERT INTO {table} ({fields}) VALUES ("
                            + ",".join("?" for _ in row)
                            + ")",
                            row,
                        )
                    after = [
                        row_digest(tuple(row.values()))
                        for row in db.execute(f"SELECT {fields} FROM {table}")
                    ]
                    expected = hashlib.sha256("".join(sorted(before)).encode()).hexdigest()
                    actual = hashlib.sha256("".join(sorted(after)).encode()).hexdigest()
                    if len(before) != len(after) or expected != actual:
                        raise ValueError("目标记录或文件字节不一致；目标导入事务回滚。")
                    report["tables"][table] = {"rows": len(before), "sha256": actual}
                if repo._used(db) > repo.settings.storage_bytes:
                    raise ValueError("目标业务数据超过256 MiB预算；未提交。")
                if sha256(path) != source_sha:
                    raise ValueError("源备份在导入期间变化；目标事务回滚。")
                report["completed"] = True
        report["next_step"] = (
            "请独立核对旧客户端、原文、检索、归档和故障恢复；向量索引须显式构建。切换后新写入不会回流SQLite。"
        )
    except Exception:
        # Do not print driver connection errors, credentials, source content or private paths.
        report.update(
            completed=False,
            error="migration_failed_target_not_confirmed",
            next_step="核对源哈希、schema5、空目标、数据库权限及预算；失败不删除源或目标，保留排查。",
        )
    finally:
        if repo:
            repo.close()
    report["finished_at"] = datetime.now(UTC).isoformat()
    args.report.parent.mkdir(parents=True, exist_ok=True)
    with args.report.open("x", encoding="utf-8") as output:
        json.dump(report, output, ensure_ascii=False, indent=2)
        output.write("\n")
    print(
        "迁移完成，仍需独立验收。"
        if report["completed"]
        else "迁移未确认完成，详见独立报告；源备份未被本工具改写。"
    )
    return 0 if report["completed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
