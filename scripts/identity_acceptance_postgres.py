"""Run identity/database acceptance in a uniquely owned disposable Docker database."""

import argparse
import json
import os
import secrets
import shutil
import subprocess
import sys
import time
from pathlib import Path
from uuid import uuid4


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--identity-only", action="store_true")
    parser.add_argument("--image-from", default="astroagent-v16-postgres-1")
    parser.add_argument("--tests", nargs="*", default=[])
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    docker = shutil.which("docker") or r"D:\Program Files\Docker\resources\bin\docker.exe"
    command = [docker]
    if os.name == "nt":
        command += ["--host", "npipe:////./pipe/docker_engine"]

    def call(*values):
        return subprocess.check_output([*command, *values], text=True).strip()

    # Reuse the existing pinned PostgreSQL image; never open its database/volume.
    image = call("inspect", "--format", "{{.Image}}", args.image_from)
    name = "astroagent-v16-qa-" + uuid4().hex
    password = secrets.token_hex(24)
    created = False
    try:
        call(
            "run",
            "-d",
            "--name",
            name,
            "--label",
            "astroagent.qa.owner=" + name,
            "-e",
            "POSTGRES_PASSWORD=" + password,
            "-e",
            "POSTGRES_DB=astroagent_test_maintenance",
            "-p",
            "127.0.0.1::5432",
            image,
        )
        created = True
        for _ in range(45):
            ready = subprocess.run(
                [*command, "exec", name, "pg_isready", "-U", "postgres"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            if ready.returncode == 0:
                break
            time.sleep(1)
        else:
            raise RuntimeError("Disposable database did not become ready")
        port = call("port", name, "5432/tcp").rsplit(":", 1)[1]
        env = os.environ.copy()
        env.update(
            ADS_API_TOKEN="",
            DEEPSEEK_API_KEY="",
            ASTROAGENT_AUTH_SECRET="",
            ASTROAGENT_AUTH_SMTP_PASSWORD="",
            ASTROAGENT_RUN_POSTGRES_TESTS="1",
            ASTROAGENT_RUN_LARGE_ACCEPTANCE="1",
            ASTROAGENT_TEST_DATABASE_URL=(
                f"postgresql://postgres:{password}@127.0.0.1:{port}/astroagent_test_maintenance"
            ),
            PYTHONUTF8="1",
        )
        with (args.output / "tests.txt").open("w", encoding="utf8") as log:
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "pytest",
                    "-m",
                    "postgres and identity" if args.identity_only else "postgres",
                    "-q",
                    "--basetemp=.astroagent/acceptance-tmp/" + name,
                    "--junitxml=" + str(args.output / "tests.xml"),
                    *args.tests,
                ],
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
            )
        (args.output / "result.json").write_text(
            json.dumps(
                {
                    "exit_code": result.returncode,
                    "daily_database_used": False,
                    "isolated_container": name,
                },
                indent=2,
            ),
            encoding="utf8",
        )
        print("Disposable PostgreSQL acceptance exit:", result.returncode)
        return result.returncode
    finally:
        if created:
            owner = call(
                "inspect", "--format", '{{index .Config.Labels "astroagent.qa.owner"}}', name
            )
            if owner != name or not name.startswith("astroagent-v16-qa-"):
                raise RuntimeError("Cleanup ownership did not match")
            call("rm", "-f", "-v", name)
            print("Owned disposable database and its temporary volume removed.")


if __name__ == "__main__":
    raise SystemExit(main())
