"""Explicit Compose-only pg_dump / restore-to-new-database. No host database connection."""

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]


def sha256(path):
    result = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024**2):
            result.update(chunk)
    return result.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--env-file", type=Path, default=ROOT / ".astroagent/container/deployment.env"
    )
    parser.add_argument("--project", default="astroagent-v15")
    parser.add_argument(
        "--rootless", action="store_true", help="Use the current Linux user's local rootless socket"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    backup = commands.add_parser("backup")
    backup.add_argument("--output", type=Path, required=True)
    backup.add_argument("--confirm-include-originals", action="store_true")
    restore = commands.add_parser("restore")
    restore.add_argument("--backup", type=Path, required=True)
    restore.add_argument("--expected-sha256", required=True)
    restore.add_argument("--new-database", required=True)
    restore.add_argument("--confirm-trusted-backup", action="store_true")
    args = parser.parse_args()
    try:
        if not re.fullmatch("[a-z][a-z0-9_-]{0,62}", args.project):
            raise ValueError("Project name")
        public = {}
        for line in args.env_file.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.startswith("#"):
                key, value = line.split("=", 1)
                public[key] = value.strip().strip('"')
        database = public.get("CONTAINER_DATABASE", "astroagent")
        if not re.fullmatch("[a-z][a-z0-9_]{0,62}", database):
            raise ValueError("Database name")
        executable = shutil.which("docker") or (
            "D:/Program Files/Docker/resources/bin/docker.exe" if os.name == "nt" else None
        )
        if not executable:
            raise ValueError("Local Docker CLI is unavailable")
        prefix = [
            executable,
            "--host",
            "npipe:////./pipe/docker_engine"
            if os.name == "nt"
            else f"unix:///run/user/{os.getuid()}/docker.sock"
            if args.rootless
            else "unix:///var/run/docker.sock",
            "compose",
            "--project-name",
            args.project,
            "--env-file",
            str(args.env_file.resolve()),
            "-f",
            str(ROOT / "compose.yaml"),
            "exec",
            "-T",
            "--user",
            "postgres",
            "postgres",
        ]

        def run(command, *, input=None, stdin=None, stdout=subprocess.PIPE):
            process = subprocess.run(
                [*prefix, *command],
                input=input,
                stdin=stdin,
                stdout=stdout,
                stderr=subprocess.PIPE,
                timeout=600,
            )
            if process.returncode:
                raise ValueError("Database tool did not complete")
            return process.stdout

        credential = 'export PGPASSWORD="$(cat /run/secrets/postgres_admin_password)"; '
        if args.command == "backup":
            if not args.confirm_include_originals:
                raise ValueError("Explicit originals confirmation required")
            target = args.output.resolve()
            if target.exists() or target.with_name(target.name + ".manifest.json").exists():
                raise ValueError("Refuse an existing backup target")
            target.parent.mkdir(parents=True, exist_ok=True)
            partial = target.with_name(target.name + ".partial")
            with partial.open("xb") as output:
                run(
                    [
                        "sh",
                        "-ec",
                        credential
                        + (
                            "exec pg_dump -U postgres --format=custom --no"
                            '-owner --no-acl --dbname "$1"'
                        ),
                        "astroagent-backup",
                        database,
                    ],
                    stdout=output,
                )
            partial.replace(target)
            record = {
                "created_at": datetime.now(UTC).isoformat(),
                "sha256": sha256(target),
                "bytes": target.stat().st_size,
                "method": "pg_dump_custom",
                "database": database,
                "project": args.project,
                "includes_originals": True,
                "includes_vectors": True,
                "includes_saved_plot_bytes": True,
                "includes_model_files": False,
                "includes_credentials": False,
                "restore_verified": False,
                "public_configuration": {
                    key: value
                    for key, value in public.items()
                    if key.endswith("_IMAGE")
                    or key in ("EMBEDDING_MODEL_SHA256", "LOCAL_MODEL_DIGEST")
                },
            }
            with target.with_name(target.name + ".manifest.json").open(
                "x", encoding="utf-8"
            ) as stream:
                json.dump(record, stream, ensure_ascii=False, indent=2)
                stream.write("\n")
            print(
                "Created a consistent database backup and mani"
                "fest; independent restore remains unverified."
            )
        else:
            name = args.new_database
            source = args.backup.resolve(strict=True)
            if (
                not args.confirm_trusted_backup
                or not re.fullmatch("[a-z][a-z0-9_]{0,62}", name)
                or name in (database, "postgres", "template0", "template1")
                or not re.fullmatch("[0-9a-f]{64}", args.expected_sha256)
                or sha256(source) != args.expected_sha256
            ):
                raise ValueError(
                    "Trusted backup, expected identity and distinct new database required"
                )
            # Read TOC without restoring; installed extensions remain administrator-owned.
            with source.open("rb") as stream:
                listing = run(["pg_restore", "--list"], stdin=stream).decode("utf-8")
            kept = []
            for line in listing.splitlines():
                if ";" in line and not line.startswith(";"):
                    items = line.split(";", 1)[1].split()
                    extension = items[2] == "EXTENSION" if len(items) > 4 else False
                    comment = items[2:5] == ["COMMENT", "-", "EXTENSION"]
                    if extension or comment:
                        extension_name = items[4] if extension else items[5]
                        if extension_name not in ("vector", "pg_trgm"):
                            raise ValueError("Unexpected extension")
                        continue
                kept.append(line)
            # CREATE DATABASE atomically refuses any existing target; never drop/clean a database.
            sql = f'CREATE DATABASE "{name}" OWNER astroagent TEMPLATE template0;\n'
            run(
                [
                    "sh",
                    "-ec",
                    credential + "exec psql -U postgres -d postgres --set ON_ERROR_STOP=1",
                ],
                input=sql.encode(),
            )
            run(
                [
                    "sh",
                    "-ec",
                    credential + 'exec psql -U postgres -d "$1" --set ON_ERROR_STOP=1',
                    "astroagent-extensions",
                    name,
                ],
                input=b"CREATE EXTENSION vector; CREATE EXTENSION pg_trgm;\n",
            )
            temporary = "/tmp/astroagent-restore-" + str(uuid4()) + ".list"
            try:
                run(
                    ["sh", "-ec", 'umask 077; cat > "$1"', "astroagent-toc", temporary],
                    input=("\n".join(kept) + "\n").encode(),
                )
                with source.open("rb") as stream:
                    run(
                        [
                            "sh",
                            "-ec",
                            credential
                            + (
                                "exec pg_restore -U postgres --role=astroagent"
                                ' --dbname "$1" --use-list "$2" --single-trans'
                                "action --exit-on-error --no-owner --no-acl"
                            ),
                            "astroagent-restore",
                            name,
                            temporary,
                        ],
                        stdin=stream,
                    )
            finally:
                run(["rm", "-f", "--", temporary])
            if sha256(source) != args.expected_sha256:
                raise ValueError("Backup changed during restore")
            print(
                "Restored into a new database only. Counts, ap"
                "plication behavior and scientific results rem"
                "ain unverified; no application switch was mad"
                "e."
            )
        return 0
    except Exception:
        print(
            "Maintenance incomplete. Existing databases we"
            "re not overwritten; any new database or parti"
            "al backup is retained for review. No credenti"
            "als are printed."
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
