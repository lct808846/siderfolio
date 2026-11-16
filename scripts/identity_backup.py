"""Explicit V1.6 binary pg_dump through Compose; no credential or binary stdout."""

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--docker",
        default=shutil.which("docker") or r"D:\Program Files\Docker\resources\bin\docker.exe",
    )
    parser.add_argument("--confirm-backend-stopped", action="store_true", required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    environment = {}
    for line in args.env_file.read_text(encoding="utf-8-sig").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            name, value = line.split("=", 1)
            environment[name.strip()] = value.strip().strip('"')
    database = environment.get("CONTAINER_DATABASE", "astroagent")
    if not re.fullmatch(r"[a-z][a-z0-9_]{0,62}", database):
        raise ValueError("Invalid database identity")
    command = [args.docker]
    if os.name == "nt":
        command += ["--host", "npipe:////./pipe/docker_engine"]
    command += [
        "compose",
        "--project-directory",
        str(root),
        "--env-file",
        str(args.env_file.resolve()),
        "-f",
        str(root / "compose.yaml"),
        "-f",
        str(root / "compose.plotting.yaml"),
        "-f",
        str(root / "compose.identity.yaml"),
    ]
    running = (
        subprocess.run(
            [*command, "ps", "--status", "running", "--services"],
            capture_output=True,
            check=True,
            timeout=30,
        )
        .stdout.decode()
        .splitlines()
    )
    if "backend" in running:
        raise ValueError("Stop the V1.6 backend before taking a migration backup")
    target = args.output.resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        result = subprocess.run(
            [
                *command,
                "exec",
                "-T",
                "postgres",
                "pg_dump",
                "-U",
                "postgres",
                "-d",
                database,
                "--format=custom",
            ],
            stdout=stream,
            stderr=subprocess.PIPE,
            timeout=600,
        )
    if result.returncode:
        raise ValueError("Backup did not complete; preserve the incomplete file for inspection")
    with target.open("rb") as stream:
        if stream.read(5) != b"PGDMP":
            raise ValueError("Backup is not a PostgreSQL custom archive")
        stream.seek(0)
        sha256 = hashlib.file_digest(stream, "sha256").hexdigest()
    manifest = {
        "format": "pg_dump-custom",
        "database": database,
        "project": "astroagent-v16",
        "created_at": datetime.now(UTC).isoformat(),
        "bytes": target.stat().st_size,
        "sha256": sha256,
        "restore_verified": False,
    }
    metadata = target.with_name(target.name + ".manifest.json")
    descriptor = os.open(metadata, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        json.dump(manifest, stream, ensure_ascii=False, indent=2)
    print(
        json.dumps(
            {
                "backup": str(target),
                "manifest": str(metadata),
                "sha256": sha256,
                "restore_verified": False,
            }
        )
    )


if __name__ == "__main__":
    try:
        main()
    except (Exception, KeyboardInterrupt):
        raise SystemExit(
            "备份未完成；不会覆盖原文件，请检查服务状态及输出位置。部分文件会保留，不能当作有效备份。"
        ) from None
