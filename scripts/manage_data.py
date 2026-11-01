"""显式整库一致性备份/独立目录恢复；不启动应用或修改源数据库。"""

import argparse
import hashlib
import json
import re
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

from astroagent import __version__


def checksum(path):
    value = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024**2):
            value.update(chunk)
    return value.hexdigest()


def copy_database(source, destination):
    source = source.resolve(strict=True)
    destination = destination.resolve()
    if not source.is_file() or source == destination:
        raise ValueError("源数据库与新目标必须是不同文件。")
    destination.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation prevents overwriting any existing database, symlink or user file.
    with destination.open("xb"):
        pass
    with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)) as src:
        version = src.execute("PRAGMA user_version").fetchone()[0]
        if version not in (1, 2, 3, 4, 5):
            raise ValueError("源数据库schema不受此版本支持；未执行迁移。")
        with closing(sqlite3.connect(destination)) as dst:
            src.backup(dst)
            if dst.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                raise ValueError("目标数据库一致性检查失败，不能当作完整备份使用。")
            if dst.execute("PRAGMA user_version").fetchone()[0] != version:
                raise ValueError("备份schema不一致。")
    return version


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    backup = sub.add_parser("backup", help="复制SQLite一致性快照，不复制.env或程序环境")
    backup.add_argument("--database", required=True, type=Path)
    backup.add_argument("--output", required=True, type=Path)
    restore = sub.add_parser("restore", help="仅恢复到从未存在的新目录，不覆盖日常库")
    restore.add_argument("--backup", required=True, type=Path)
    restore.add_argument("--new-data-dir", required=True, type=Path)
    restore.add_argument("--expected-sha256", required=True)
    restore.add_argument("--confirm", action="store_true")
    args = parser.parse_args()
    try:
        if args.action == "backup":
            output = args.output.resolve()
            manifest = output.with_name(output.name + ".manifest.json")
            output.parent.mkdir(parents=True, exist_ok=True)
            # Reserve the manifest first, as both outputs must be new.
            with manifest.open("x", encoding="utf-8") as metadata:
                version = copy_database(args.database, output)
                record = {
                    "created_at": datetime.now(UTC).isoformat(),
                    "application_version": __version__,
                    "database_schema": version,
                    "bytes": output.stat().st_size,
                    "sha256": checksum(output),
                    "method": "sqlite3.Connection.backup",
                    "note": "整库字节完整性，不认证来源；不包含.env或运行环境。",
                }
                metadata.write(json.dumps(record, ensure_ascii=False, indent=2) + "\n")
            print(f"备份：{output}\n清单：{manifest}")
        else:
            if not args.confirm or not re.fullmatch(r"[0-9a-fA-F]{64}", args.expected_sha256):
                raise ValueError("恢复必须明确使用--confirm并提供64位期望SHA-256。")
            source = args.backup.resolve(strict=True)
            if checksum(source) != args.expected_sha256.lower():
                raise ValueError("备份哈希与期望值不同，未恢复。")
            root = args.new_data_dir.resolve()
            root.mkdir(parents=True, exist_ok=False)
            destination = root / "astroagent.sqlite3"
            version = copy_database(source, destination)
            if checksum(source) != args.expected_sha256.lower():
                raise ValueError("备份源在恢复期间发生变化，目标未被确认可用。")
            print(f"恢复到独立目录：{destination}\n保留schema{version}，尚未启动服务或升级数据库。")
        return 0
    except (OSError, ValueError, sqlite3.Error) as exc:
        print(
            f"未完成：{exc}\n源数据库未改写。若新目标已产生，它不是已确认的完整备份，请保留排查；不会自动删除数据。"
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
