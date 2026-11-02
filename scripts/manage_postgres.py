"""Explicit pg_dump backup / pg_restore into a newly created database; no overwrite."""

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import unquote, urlsplit

from astroagent.config import LocalSettings


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024**2):
            digest.update(chunk)
    return digest.hexdigest()


def environment(url, database=None):
    parsed = urlsplit(url)
    result = {
        key: os.environ[key]
        for key in ("PATH", "SystemRoot", "WINDIR", "TEMP", "TMP", "LANG", "LC_ALL")
        if key in os.environ
    }
    result.update(
        PGHOST=parsed.hostname,
        PGPORT=str(parsed.port or 5432),
        PGDATABASE=database or unquote(parsed.path.lstrip("/")),
        PGUSER=unquote(parsed.username or ""),
        PGPASSWORD=unquote(parsed.password or ""),
        PGCONNECT_TIMEOUT="5",
    )
    return result


def run(program, arguments, env):
    executable = shutil.which(program)
    if not executable:
        raise ValueError("PostgreSQL客户端工具不在PATH中。")
    result = subprocess.run(
        [executable, *arguments],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        env=env,
        timeout=300,
        check=False,
    )
    if result.returncode:
        raise ValueError(
            "数据库维护工具未成功退出，未确认目标可用；未输出可能含敏感信息的驱动错误。"
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    backup = commands.add_parser("backup")
    backup.add_argument("--output", required=True, type=Path)
    backup.add_argument("--confirm-include-originals", action="store_true")
    restore = commands.add_parser("restore")
    restore.add_argument("--backup", required=True, type=Path)
    restore.add_argument("--expected-sha256", required=True)
    restore.add_argument("--new-database", required=True)
    restore.add_argument("--confirm-trusted-backup", action="store_true")
    args = parser.parse_args()
    try:
        import psycopg
        from psycopg import sql

        url = LocalSettings().database_url.get_secret_value()
        if not url:
            raise ValueError("先在服务端环境配置本机ASTROAGENT_DATABASE_URL。")
        if args.action == "backup":
            if not args.confirm_include_originals:
                raise ValueError("整库备份包含个人原文与问答，须明确--confirm-include-originals。")
            target = args.output.resolve()
            manifest = target.with_name(target.name + ".manifest.json")
            target.parent.mkdir(parents=True, exist_ok=True)
            with manifest.open("x", encoding="utf-8") as record:
                with target.open("xb") as output:
                    executable = shutil.which("pg_dump")
                    if not executable:
                        raise ValueError("pg_dump不在PATH中。")
                    result = subprocess.run(
                        [executable, "--format=custom", "--no-owner", "--no-acl"],
                        stdin=subprocess.DEVNULL,
                        stdout=output,
                        stderr=subprocess.PIPE,
                        env=environment(url),
                        timeout=300,
                        check=False,
                    )
                    if result.returncode:
                        raise ValueError("备份工具未成功退出，不将新目标当作完整备份。")
                record.write(
                    json.dumps(
                        {
                            "created_at": datetime.now(UTC).isoformat(),
                            "method": "pg_dump_custom",
                            "sha256": sha256(target),
                            "bytes": target.stat().st_size,
                            "includes_originals": True,
                            "includes_vectors": True,
                            "includes_server_configuration_files": False,
                            "includes_model_files": False,
                            "restore_verified": False,
                        },
                        ensure_ascii=False,
                        indent=2,
                    )
                    + "\n"
                )
            print("一致性备份及清单已生成；尚未验证独立恢复。")
        else:
            if not args.confirm_trusted_backup or not re.fullmatch(
                r"[a-z][a-z0-9_]{0,62}", args.new_database
            ):
                raise ValueError(
                    "仅恢复可信自建备份，须明确确认且新数据库名只能是小写字母、数字、下划线。"
                )
            source = args.backup.resolve(strict=True)
            if sha256(source) != args.expected_sha256.lower():
                raise ValueError("备份SHA-256不符，未创建目标。")
            with psycopg.connect(url, autocommit=True, connect_timeout=5) as connection:
                if connection.execute(
                    "SELECT 1 FROM pg_database WHERE datname=%s", (args.new_database,)
                ).fetchone():
                    raise ValueError("目标数据库已存在，拒绝覆盖。")
                connection.execute(
                    sql.SQL("CREATE DATABASE {} TEMPLATE template0").format(
                        sql.Identifier(args.new_database)
                    )
                )
            run(
                "pg_restore",
                [
                    "--dbname",
                    args.new_database,
                    "--single-transaction",
                    "--exit-on-error",
                    "--no-owner",
                    "--no-acl",
                    str(source),
                ],
                environment(url, args.new_database),
            )
            if sha256(source) != args.expected_sha256.lower():
                raise ValueError("恢复期间备份源改变，目标未确认。")
            print(
                "已恢复到新数据库；尚未启动应用或核对计数、原文、向量及模型。模型缺失不会自动下载。"
            )
        return 0
    except Exception:
        print(
            "维护未确认完成。核对环境、权限、新目标与源哈希；未覆盖已有数据库。新目标若已产生将保留排查，不自动删除。"
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
