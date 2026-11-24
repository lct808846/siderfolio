"""Explicit local administration. No automatic legacy ownership or default admin."""

import argparse
import hashlib
import json
from pathlib import Path
from uuid import uuid4

from psycopg import sql

from astroagent.auth_config import AuthSettings
from astroagent.auth_security import email_address
from astroagent.auth_store import AUTH_LOCK, AuthStore
from astroagent.config import LocalSettings
from astroagent.errors import ServiceError
from astroagent.feedback import install_feedback_schema
from astroagent.postgres import COLUMNS, LOCK_ID

BUSINESS_TABLES = set(COLUMNS) | {
    "astroagent_meta",
    "conversation_archives",
    "rag_indexes",
    "rag_active",
    "rag_vectors",
    "rag_previews",
    "rag_answers",
    "rag_answer_requests",
    "plot_meta",
    "plot_datasets",
    "plot_operations",
    "plot_outputs",
    "local_assistant_meta",
    "local_assistant_tasks",
}
METADATA = {"astroagent_meta", "knowledge_meta", "local_assistant_meta", "plot_meta"}


def inventory(db, namespace):
    tables = {
        row["tablename"]
        for row in db.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname=%s", (namespace,)
        ).fetchall()
    }
    if namespace == "public":
        tables = {name for name in tables if not name.startswith("auth_")}
    if tables - BUSINESS_TABLES:
        raise ServiceError(
            409, "migration_unknown_tables", "发现不属于迁移清单的表，请停止并人工核对。"
        )
    counts = {}
    for table in sorted(tables):
        counts[table] = db.execute(
            sql.SQL("SELECT count(*) AS n FROM {}.{}").format(
                sql.Identifier(namespace), sql.Identifier(table)
            )
        ).fetchone()["n"]
    return counts


def confirm(user, action):
    print(
        json.dumps(
            {"action": action, "target_id": user["id"], "target_email": user["email_display"]},
            ensure_ascii=False,
        )
    )
    if input("请输入完整目标账号ID确认：").strip() != user["id"]:
        raise ValueError("Confirmation did not match")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("generate-key")
    sub.add_parser("initialize")
    sub.add_parser("install-feedback")
    for name in ("bootstrap-admin", "recover-admin-totp", "claim-legacy"):
        entry = sub.add_parser(name)
        entry.add_argument("--email", required=True)
        entry.add_argument("--apply", action="store_true")
        if name == "recover-admin-totp":
            entry.add_argument(
                "--reason", choices=["lost_authenticator", "administrator_recovery"], required=True
            )
        if name == "claim-legacy":
            entry.add_argument("--backup-file", type=Path)
            entry.add_argument("--backup-sha256")
    args = parser.parse_args()
    if args.action == "generate-key":
        from cryptography.fernet import Fernet

        print(Fernet.generate_key().decode())
        return
    store = AuthStore(LocalSettings(), AuthSettings())
    if args.action == "install-feedback":
        with store.connect() as db:
            db.execute("SELECT pg_advisory_xact_lock(%s)", (AUTH_LOCK,))
            installed = install_feedback_schema(db)
        print("已安装反馈表。" if installed else "反馈表已存在。")
        return
    with store.connect() as db:
        # Both old and new services must be stopped. These are session locks.
        for lock in (LOCK_ID, AUTH_LOCK + 1):
            if not db.execute("SELECT pg_try_advisory_lock(%s) AS ok", (lock,)).fetchone()["ok"]:
                raise ValueError("Stop all V1.5/V1.6 backends before local maintenance")
        if args.action == "initialize":
            # The outer connection retains the offline locks throughout installation.
            store.install()
            print("身份表已初始化；旧业务表仍隔离，未自动认领。")
            return
        store.check()
        db.execute("SELECT pg_advisory_xact_lock(%s)", (AUTH_LOCK,))
        key, _ = email_address(args.email)
        user = db.execute(
            "SELECT * FROM public.auth_users WHERE email_key=%s FOR UPDATE", (key,)
        ).fetchone()
        if not user or not user["active"] or user["disabled"]:
            raise ValueError("An existing activated, enabled account is required")
        if args.action == "bootstrap-admin":
            if db.execute("SELECT 1 FROM public.auth_users WHERE admin LIMIT 1").fetchone():
                raise ValueError(
                    "Administrator already exists; use the authenticated administration flow"
                )
            if not args.apply:
                print(
                    json.dumps(
                        {
                            "target_id": user["id"],
                            "email": user["email_display"],
                            "status": "preview_only",
                        },
                        ensure_ascii=False,
                    )
                )
                return
            confirm(user, args.action)
            db.execute(
                "UPDATE public.auth_users SET admin=true,generation=generation+1 WHERE id=%s",
                (user["id"],),
            )
            store.revoke(db, user["id"])
            store.audit(
                db,
                None,
                "admin_bootstrapped_offline",
                "ok",
                user["id"],
                reason="local_operator_confirmation",
            )
        elif args.action == "recover-admin-totp":
            if not user["admin"]:
                raise ValueError("Only an existing administrator can be recovered")
            if not args.apply:
                print(json.dumps({"target_id": user["id"], "status": "preview_only"}))
                return
            confirm(user, args.action)
            db.execute(
                (
                    "UPDATE public.auth_users SET totp_secret=NULL,totp_pending=NULL,totp_pending"
                    "_until=NULL,totp_step=-1,generation=generation+1 WHERE id=%s"
                ),
                (user["id"],),
            )
            db.execute("DELETE FROM public.auth_recovery WHERE user_id=%s", (user["id"],))
            store.revoke(db, user["id"])
            store.audit(
                db, None, "admin_totp_recovered_offline", "ok", user["id"], reason=args.reason
            )
        else:
            counts = inventory(db, "public")
            target_counts = inventory(db, user["namespace"])
            print(
                json.dumps(
                    {
                        "database": db.execute("SELECT current_database() AS name").fetchone()[
                            "name"
                        ],
                        "target_id": user["id"],
                        "email": user["email_display"],
                        "legacy_counts": counts,
                        "target_counts": target_counts,
                    },
                    ensure_ascii=False,
                )
            )
            if not counts:
                raise ValueError("No unclaimed legacy data was found")
            if any(n for table, n in target_counts.items() if table not in METADATA):
                raise ValueError(
                    "Target already has business data; no merge or overwrite is supported"
                )
            if not args.apply:
                return
            backup = args.backup_file
            if not backup or not backup.is_file() or not args.backup_sha256:
                raise ValueError("A verified pg_dump custom-format backup and SHA-256 are required")
            with backup.open("rb") as stream:
                if stream.read(5) != b"PGDMP":
                    raise ValueError("A pg_dump custom-format backup is required")
                stream.seek(0)
                checksum = hashlib.file_digest(stream, "sha256").hexdigest()
            if checksum != args.backup_sha256.lower():
                raise ValueError("Backup hash does not match")
            confirm(user, args.action)
            namespace = "aa_" + uuid4().hex
            db.execute(
                sql.SQL("CREATE SCHEMA {} AUTHORIZATION CURRENT_USER").format(
                    sql.Identifier(namespace)
                )
            )
            db.execute(
                sql.SQL("REVOKE ALL ON SCHEMA {} FROM PUBLIC").format(sql.Identifier(namespace))
            )
            for table in counts:
                db.execute(
                    sql.SQL("ALTER TABLE public.{} SET SCHEMA {}").format(
                        sql.Identifier(table), sql.Identifier(namespace)
                    )
                )
            if inventory(db, namespace) != counts:
                raise ValueError("Transferred row counts do not match; transaction will roll back")
            db.execute(
                "UPDATE public.auth_users SET namespace=%s,generation=generation+1 WHERE id=%s",
                (namespace, user["id"]),
            )
            db.execute(
                "INSERT INTO public.auth_meta(key,value) VALUES ('legacy_claim',%s)",
                (
                    json.dumps(
                        {
                            "owner": user["id"],
                            "namespace": namespace,
                            "counts": counts,
                            "backup_sha256": checksum,
                        }
                    ),
                ),
            )
            store.revoke(db, user["id"])
            store.audit(
                db,
                None,
                "legacy_claimed_offline",
                "ok",
                user["id"],
                reason="verified_backup_and_explicit_confirmation",
            )
        print("操作完成。保留原备份；请重启V1.6并安排隔离环境验收。")


if __name__ == "__main__":
    try:
        main()
    except (Exception, KeyboardInterrupt):
        # Never echo parser input, credentials, database URLs or SQL parameters.
        raise SystemExit(
            "本机管理操作未完成；未提交的变更已回滚。请检查配置、服务停机状态与确认参数。"
        ) from None
