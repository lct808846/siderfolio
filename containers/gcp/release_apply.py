"""Apply an attested image release to a pre-provisioned, root-owned GCP Compose project."""

import argparse
import fcntl
import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory

# The installed siblings are root-owned. Ignore the SSH account's working directory.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from release_assets import (  # noqa: E402
    COMMIT,
    DIGEST,
    REPOSITORY,
    capture,
    image_repository,
    validate_manifest,
    validate_version,
    verified_tag,
)

ETC = Path("/etc/astroagent")
STATE = Path("/var/lib/astroagent-release")
CURRENT = STATE / "current.json"
PENDING = STATE / "pending.json"
IMAGES = STATE / "images.json"
DOCKER = ["docker", "--host", "unix:///var/run/docker.sock"]
SENSITIVE = (
    ".github/workflows/release.yml",
    "containers/application/Dockerfile",
    "containers/frontend/Dockerfile",
    "containers/gcp",
    "containers/release/docker-bake.hcl",
    "frontend/server.mjs",
    "scripts/compute_schema.sql",
    "scripts/identity_backup.py",
    "src/astroagent/auth_access.py",
    "src/astroagent/auth_config.py",
    "src/astroagent/auth_mail.py",
    "src/astroagent/auth_security.py",
    "src/astroagent/auth_store.py",
    "src/astroagent/api/admin.py",
    "src/astroagent/api/auth.py",
    "src/astroagent/identity.py",
    "src/astroagent/identity_cli.py",
    "src/astroagent/local_access.py",
    "src/astroagent/postgres.py",
    ":(glob)src/astroagent/**/*_store.py",
)
SCHEMA_STATEMENT = re.compile(
    r"\b(?:ALTER|DROP|TRUNCATE|GRANT|REVOKE|CREATE)\s+"
    r"(?:TABLE|COLUMN|INDEX|EXTENSION|DATABASE|SCHEMA|ROLE|USER|TYPE|TRIGGER|FUNCTION|POLICY)\b",
    re.IGNORECASE,
)
MAX_MANIFEST = 32 * 1024


def now():
    return datetime.now(UTC).isoformat()


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def private_file(path):
    stat = path.stat()
    require(
        path.is_file() and path.resolve() == path and stat.st_uid == 0 and not stat.st_mode & 0o022,
        f"Root-owned regular file required: {path}",
    )
    return path


def root_directory(path):
    for parent in (path, *path.parents):
        require(
            parent.is_dir()
            and parent.resolve() == parent
            and parent.stat().st_uid == 0
            and not parent.stat().st_mode & 0o022,
            f"Root-owned directory required: {parent}",
        )
    return path


def save(path, value):
    data = json.dumps(value, sort_keys=True, indent=2) + "\n"
    temporary = path.with_suffix(".tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)
    fd = os.open(path.parent, os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def run(command, *, timeout=600, **kwargs):
    subprocess.run(command, check=True, timeout=timeout, **kwargs)


def get_settings():
    configuration = json.loads(private_file(ETC / "release.json").read_bytes())
    flags = {"enabled", "compute", "rag", "auto_rollback"}
    require(
        set(configuration) == flags | {"project_dir", "repository"}
        and all(type(configuration[key]) is bool for key in flags)
        and REPOSITORY.fullmatch(configuration["repository"]),
        "Invalid installed release configuration.",
    )
    return configuration


class Deployment:
    def __init__(self, settings):
        self.settings = settings
        self.directory = root_directory(Path(settings["project_dir"]))
        env = private_file(self.directory / ".env")
        require(env.stat().st_mode & 0o777 == 0o600, "Production .env must have mode 0600.")
        self.files = [env, private_file(self.directory / "docker-compose.yml")]
        self.compose = [
            *DOCKER,
            "compose",
            "--project-name",
            "astroagent-gcp",
            "--project-directory",
            str(self.directory),
            "--env-file",
            str(env),
            "-f",
            str(self.files[1]),
        ]
        self.verify = ["bash", str(private_file(self.directory / "deploy.sh"))]
        self.files.extend((Path(self.verify[1]), private_file(self.directory / "deploy_env.py")))
        if settings["rag"]:
            overlay = private_file(self.directory / "docker-compose.rag.yml")
            self.files.append(overlay)
            self.compose += ["-f", str(overlay)]
            self.verify.append("--rag")
        self.verify.append("verify")
        self.services = ["backend", "frontend", "ingress"]
        if settings["compute"]:
            self.compose += ["--profile", "compute"]
            self.services.append("compute-worker")

    def contract(self):
        return {
            "compute": self.settings["compute"],
            "rag": self.settings["rag"],
            "files": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in self.files},
        }

    def preflight(self):
        compute = capture(
            [
                *self.compose,
                "exec",
                "-T",
                "backend",
                "printenv",
                "ASTROAGENT_COMPUTE_ENABLED",
            ]
        )
        require(
            compute == str(int(self.settings["compute"])),
            "Running compute profile does not match the installed release configuration.",
        )
        run([*self.compose, "config", "--quiet"])
        run(self.verify, timeout=320)

    def snapshot(self, *, healthy=True):
        observed = {}
        for service in ("postgres", *self.services):
            ids = capture([*self.compose, "ps", "--all", "-q", service]).splitlines()
            if not ids and not healthy:
                observed[service] = {"id": None, "reference": None, "status": "absent"}
                continue
            require(len(ids) == 1, f"Expected one running production {service} container.")
            info = capture(
                [
                    *DOCKER,
                    "inspect",
                    "--format",
                    "{{.Image}}|{{.Config.Image}}|{{.State.Status}}|"
                    "{{if .State.Health}}{{.State.Health.Status}}{{end}}",
                    ids[0],
                ]
            ).split("|")
            require(
                len(info) == 4
                and DIGEST.fullmatch(info[0])
                and (not healthy or info[2:] == ["running", "healthy"]),
                f"Production {service} does not match the expected state.",
            )
            observed[service] = {"id": info[0], "reference": info[1], "status": info[3] or info[2]}
        return observed

    def idle_compute(self):
        if not self.settings["compute"]:
            return
        active = capture(
            [
                *self.compose,
                "exec",
                "-T",
                "postgres",
                "psql",
                "-XAtq",
                "-v",
                "ON_ERROR_STOP=1",
                "-U",
                "postgres",
                "-d",
                "astroagent",
                "-c",
                "SELECT count(*) FROM public.compute_tasks "
                "WHERE state IN ('queued','running','cancelling')",
            ]
        )
        require(active == "0", "Production compute queue is active. Retry the same release later.")

    def use_images(self, selected, pins, ids):
        services = {name: {"image": pins[name]} for name in self.services}
        if self.settings["compute"]:
            services["compute-worker"]["environment"] = {
                "ASTROAGENT_COMPUTE_IMAGE_ID": ids["compute-worker"]
            }
        save(IMAGES, {"services": services})
        if selected:
            run(
                [
                    *self.compose,
                    "-f",
                    str(IMAGES),
                    "up",
                    "-d",
                    "--wait",
                    "--wait-timeout",
                    "180",
                    "--no-deps",
                    "--no-build",
                    "--pull",
                    "never",
                    *selected,
                ]
            )
        run(self.verify, timeout=320)


def fetch_tag(repository, version):
    validate_version(version)
    source = STATE / "source.git"
    git = ["git", "--git-dir", str(source)]
    if not source.is_dir():
        run(["git", "init", "--bare", str(source)])
    tag = f"refs/tags/{version}"
    run(
        [
            *git,
            "fetch",
            "--no-tags",
            f"https://github.com/{repository}.git",
            "+refs/heads/main:refs/remotes/origin/main",
            f"{tag}:{tag}",
        ]
    )
    return git


def require_compatible(git, before, after):
    run([*git, "merge-base", "--is-ancestor", before, after])
    changed = capture([*git, "diff", "--name-only", before, after, "--", *SENSITIVE])
    require(not changed, "Schema, identity, or production configuration requires separate review.")
    sql = capture(
        [*git, "diff", "--unified=0", "--no-ext-diff", before, after, "--", "src", "scripts"]
    )
    require(
        not any(
            line.startswith("+") and SCHEMA_STATEMENT.search(line) for line in sql.splitlines()
        ),
        "New schema statements require separate review.",
    )


def pull_id(reference):
    run([*DOCKER, "pull", "--platform", "linux/amd64", reference])
    inspected = capture(
        [
            *DOCKER,
            "image",
            "inspect",
            "--format",
            "{{.Id}}|{{.Os}}/{{.Architecture}}|{{json .RepoDigests}}",
            reference,
        ]
    ).split("|", 2)
    require(
        len(inspected) == 3
        and DIGEST.fullmatch(inspected[0])
        and inspected[1] == "linux/amd64"
        and reference in json.loads(inspected[2]),
        "Pulled image does not match its pinned digest and architecture.",
    )
    return inspected[0]


def adopt(deployment, version, sha):
    # An operator explicitly records a baseline installed by the manual first-time procedure.
    git = fetch_tag(deployment.settings["repository"], version)
    tagged = capture([*git, "rev-parse", f"refs/tags/{version}^{{commit}}"])
    require(
        COMMIT.fullmatch(sha) and tagged == sha,
        "The recorded baseline must match a release tag in the configured repository.",
    )
    deployment.preflight()
    observed = deployment.snapshot()
    repo = deployment.settings["repository"]
    pins = {
        name: observed[name]["reference"]
        for name in deployment.services
        if re.fullmatch(
            re.escape(image_repository(repo, name)) + r"@sha256:[a-f0-9]{64}",
            observed[name]["reference"],
        )
    }
    save(
        CURRENT,
        {
            "version": version,
            "commit": sha,
            "contract": deployment.contract(),
            "images": observed,
            "pins": pins,
        },
    )
    PENDING.unlink(missing_ok=True)
    print(f"Adopted running baseline {version} ({sha})")


def apply(deployment):
    require(deployment.settings["enabled"], "Automatic production deployment is disabled.")
    require(CURRENT.is_file(), "A verified running baseline must be recorded first.")
    require(not PENDING.exists(), "A previous deployment requires operator reconciliation.")
    current = json.loads(CURRENT.read_bytes())
    require(
        current["contract"] == deployment.contract(), "Installed production files have changed."
    )
    payload = sys.stdin.buffer.read(MAX_MANIFEST + 1)
    require(0 < len(payload) <= MAX_MANIFEST, "Expected one bounded release manifest.")
    manifest = json.loads(payload)
    repository = deployment.settings["repository"]
    validate_manifest(manifest, repository)
    version, sha = manifest["version"], manifest["commit"]
    require(
        validate_version(version) >= validate_version(current["version"]),
        "The release is older than the running version.",
    )
    git = fetch_tag(repository, version)
    signers = private_file(ETC / "release-signers")
    require(verified_tag(version, signers, git) == sha, "Tag mismatch.")
    require_compatible(git, current["commit"], sha)
    before = deployment.snapshot()
    require(before == current["images"], "Running image identity differs from the recorded state.")
    deployment.preflight()

    with TemporaryDirectory(dir=STATE) as directory:
        manifest_file = Path(directory) / "release.json"
        manifest_file.write_bytes(payload)
        run(
            [
                "gh",
                "attestation",
                "verify",
                str(manifest_file),
                "--repo",
                repository,
                "--signer-workflow",
                f"{repository}/.github/workflows/release.yml",
                "--source-ref",
                f"refs/tags/{version}",
                "--source-digest",
                sha,
                "--deny-self-hosted-runners",
            ],
            timeout=120,
        )
        pins = {name: manifest["images"][name] for name in deployment.services}
        if version == current["version"]:
            require(
                sha == current["commit"] and pins == current["pins"],
                "This version is already recorded with a different image set.",
            )
            print(f"{version} ({sha}) is already healthy and recorded.")
            return

        ids = {name: pull_id(reference) for name, reference in pins.items()}
        selected = [name for name in deployment.services if before[name]["id"] != ids[name]]
        if {"backend", "compute-worker"}.intersection(selected):
            deployment.idle_compute()
        report_file = STATE / f"{version}-{datetime.now(UTC):%Y%m%dT%H%M%S%fZ}.json"
        report = {
            "started_at": now(),
            "before_version": current["version"],
            "before_commit": current["commit"],
            "version": version,
            "commit": sha,
            "services_updated": selected,
            "before": before,
            "target_images": pins,
        }
        save(PENDING, report)
        try:
            deployment.use_images(selected, pins, ids)
            after = deployment.snapshot()
            require(
                after["postgres"] == before["postgres"]
                and all(after[name]["id"] == ids[name] for name in deployment.services),
                "Post-deployment running image identity did not match.",
            )
        except (ValueError, OSError, subprocess.SubprocessError) as error:
            report.update(outcome="failed", error=str(error))
            previous_pins = current["pins"]
            can_rollback = deployment.settings["auto_rollback"] and set(previous_pins) == set(pins)
            if selected and can_rollback:
                try:
                    previous_ids = {name: before[name]["id"] for name in deployment.services}
                    deployment.use_images(selected, previous_pins, previous_ids)
                    require(
                        deployment.snapshot() == before, "The previous image set was not restored."
                    )
                    report["outcome"] = "rolled_back"
                    PENDING.unlink()
                except (ValueError, OSError, subprocess.SubprocessError) as rollback_error:
                    report["rollback_error"] = str(rollback_error)
            try:
                report["after"] = deployment.snapshot(healthy=False)
            except (ValueError, OSError, subprocess.SubprocessError):
                pass
            report["finished_at"] = now()
            save(report_file, report)
            print(json.dumps(report, ensure_ascii=False), flush=True)
            raise
        save(
            CURRENT,
            {
                "version": version,
                "commit": sha,
                "contract": deployment.contract(),
                "images": after,
                "pins": pins,
            },
        )
        report.update(outcome="deployed", after=after, finished_at=now())
        save(report_file, report)
        PENDING.unlink()
        print(json.dumps(report, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_subparsers(dest="action", required=True)
    actions.add_parser("apply")
    actions.add_parser("status")
    baseline = actions.add_parser("adopt")
    baseline.add_argument("version")
    baseline.add_argument("commit")
    args = parser.parse_args()
    require(os.geteuid() == 0, "Run the installed production release command as root.")
    os.umask(0o077)
    root_directory(ETC)
    root_directory(STATE)
    home = str(Path.home())
    os.environ.clear()
    os.environ.update(
        PATH="/usr/local/bin:/usr/bin:/bin",
        HOME=home,
        LANG="C.UTF-8",
        DOCKER_CONFIG=str(ETC / "docker"),
        GH_CONFIG_DIR=str(ETC / "gh"),
        GH_PROMPT_DISABLED="1",
        GIT_CONFIG_GLOBAL=str(ETC / "gitconfig"),
        GIT_TERMINAL_PROMPT="0",
    )
    with (STATE / "release.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        deployment = Deployment(get_settings())
        if args.action == "adopt":
            adopt(deployment, args.version, args.commit)
        elif args.action == "status":
            status = {
                "enabled": deployment.settings["enabled"],
                "reconciliation_required": PENDING.exists(),
                "recorded": json.loads(CURRENT.read_bytes()) if CURRENT.exists() else None,
                "running": deployment.snapshot(healthy=False),
            }
            if status["recorded"]:
                status["recorded"].pop("contract")
            print(json.dumps(status, indent=2))
        else:
            apply(deployment)


if __name__ == "__main__":
    try:
        main()
    except (ValueError, KeyError, TypeError, OSError, subprocess.SubprocessError) as failure:
        # Neither the server's .env nor a raw incoming manifest is sent to the runner.
        if isinstance(failure, json.JSONDecodeError):
            failure = ValueError("Malformed release or installed state JSON.")
        raise SystemExit(f"Production release stopped: {failure}") from None
