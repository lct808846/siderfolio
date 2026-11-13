"""Explicit preparation only: turn approved image repositories into immutable local pins."""

import argparse
import json
import os
import re
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path

REPOSITORIES = {
    "PYTHON_IMAGE": "python",
    "NODE_IMAGE": "node",
    "POSTGRES_IMAGE": "pgvector/pgvector",
    "OLLAMA_IMAGE": "ollama/ollama",
    "DOCKER_CLI_IMAGE": "docker",
}


def repository(reference):
    return (
        reference.split("@", 1)[0]
        .rsplit(":", 1)[0]
        .removeprefix("docker.io/")
        .removeprefix("library/")
        if ":" in reference.split("@", 1)[0]
        else reference.split("@", 1)[0].removeprefix("docker.io/").removeprefix("library/")
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path("containers/images.example.json"))
    parser.add_argument(
        "--output", type=Path, default=Path(".astroagent/container-images.lock.json")
    )
    parser.add_argument(
        "--confirm-download-images",
        action="store_true",
        help="Allow explicit pulls if preparing images; never starts containers",
    )
    parser.add_argument(
        "--rootless", action="store_true", help="Use the current Linux user's local rootless socket"
    )
    args = parser.parse_args()
    try:
        host = (
            "npipe:////./pipe/docker_engine"
            if os.name == "nt"
            else f"unix:///run/user/{os.getuid()}/docker.sock"
            if args.rootless
            else "unix:///var/run/docker.sock"
        )
        executable = shutil.which("docker") or (
            "D:/Program Files/Docker/resources/bin/docker.exe" if os.name == "nt" else None
        )
        if not executable:
            raise ValueError("Local Docker CLI is unavailable")
        docker = [executable, "--host", host]
        selected = json.loads(args.source.read_text(encoding="utf-8"))
        if set(selected) != set(REPOSITORIES):
            raise ValueError("Expected the five approved base repositories")
        result = {
            "created_at": datetime.now(UTC).isoformat(),
            "platform": "linux/amd64",
            "images": {},
            "snapshots": {},
            "build_verified": False,
        }
        for key, reference in selected.items():
            if (
                not isinstance(reference, str)
                or not re.fullmatch(r"[a-zA-Z0-9_./:@-]+", reference)
                or repository(reference) != REPOSITORIES[key]
            ):
                raise ValueError("Unapproved image repository")
            if args.confirm_download_images:
                subprocess.run(
                    [*docker, "pull", "--platform", "linux/amd64", reference],
                    check=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=1800,
                )
            process = subprocess.run(
                [*docker, "image", "inspect", reference],
                check=True,
                capture_output=True,
                timeout=15,
            )
            detail = json.loads(process.stdout)[0]
            if detail["Os"] != "linux" or detail["Architecture"] != "amd64":
                raise ValueError("linux/amd64 image required")
            pins = [
                pin
                for pin in detail.get("RepoDigests", [])
                if repository(pin) == REPOSITORIES[key]
                and re.fullmatch(r"[a-zA-Z0-9_./:-]+@sha256:[0-9a-f]{64}", pin)
            ]
            if not pins:
                raise ValueError("No immutable repository digest available")
            result["images"][key] = sorted(pins)[0]
            result["snapshots"][key] = {"selected": reference, "image_id": detail["Id"]}
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8") as stream:
            json.dump(result, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        print(
            "Recorded image identities only; no build, con"
            "tainer startup or acceptance was performed."
        )
        return 0
    except Exception:
        print(
            "Image preparation incomplete. Check approved "
            "tags, local cache and output path; no existin"
            "g lock file was overwritten."
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
