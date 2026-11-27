"""Verify release source, publish immutable images and deploy a verified manifest."""

import argparse
import ast
import hashlib
import json
import os
import re
import subprocess
import sys
import tomllib
from pathlib import Path
from tempfile import TemporaryDirectory

VERSION = re.compile(r"v(0|[1-9]\d{0,5})\.(0|[1-9]\d{0,5})\.(0|[1-9]\d{0,5})")
COMMIT = re.compile(r"[a-f0-9]{40}")
DIGEST = re.compile(r"sha256:[a-f0-9]{64}")
REPOSITORY = re.compile(r"[a-z0-9][a-z0-9_.-]*/[a-z0-9][a-z0-9_.-]*")
BOILERPLATE_TAG_TITLE = re.compile(
    r"^(?:Release\s+)?(?:Siderfolio|AstroAgent)\s+v\d+\.\d+\.\d+(?:\s*\([^)]*\))?\.?$",
    re.IGNORECASE,
)
SIGNATURE_BLOCK = re.compile(
    r"-----BEGIN [A-Z0-9 ]+SIGNATURE-----.*?-----END [A-Z0-9 ]+SIGNATURE-----",
    re.DOTALL,
)
GIT_TRAILER = re.compile(
    r"^(?:Signed-off-by|Co-authored-by|Reviewed-by|Acked-by|Tested-by|Change-Id):\s+\S",
    re.IGNORECASE,
)
BAKE = "containers/release/docker-bake.hcl"
APP_INPUTS = (
    ".dockerignore",
    "pyproject.toml",
    "README.md",
    "src",
    "containers/application/Dockerfile",
    "containers/application/requirements-runtime.lock",
)
GCP_DOCKERFILE = "containers/gcp/Dockerfile"
COMPONENTS = {
    "backend": APP_INPUTS,
    "frontend": (".dockerignore", "frontend", "containers/frontend/Dockerfile"),
    "ingress": (".dockerignore", GCP_DOCKERFILE, "containers/gcp/Caddyfile"),
    "postgres": (".dockerignore", GCP_DOCKERFILE, "containers/gcp/10-application.sh"),
    "compute-worker": (*APP_INPUTS, "containers/application/requirements-compute.lock"),
    "plot-executor": APP_INPUTS,
    "plot-python": (
        "containers/plotting/python.Dockerfile",
        "containers/plotting/matplotlibrc",
        "containers/plotting/plot_worker.py",
    ),
    "plot-gnuplot": (
        "containers/plotting/gnuplot.Dockerfile",
        "containers/plotting/plot_worker.py",
    ),
}


def capture(command):
    return subprocess.check_output(command, encoding="utf-8", timeout=120).strip()


def validate_version(version):
    match = VERSION.fullmatch(version)
    if not match:
        raise ValueError("Expected a stable vMAJOR.MINOR.PATCH release tag.")
    return tuple(map(int, match.groups()))


def image_repository(repository, component):
    if not REPOSITORY.fullmatch(repository) or component not in COMPONENTS:
        raise ValueError("Invalid repository or component.")
    return f"ghcr.io/{repository}-{component}"


def _verify_tag_commit_and_versions(tag, git=("git",)):
    validate_version(tag)
    ref = f"refs/tags/{tag}"
    sha = capture([*git, "rev-parse", f"{ref}^{{commit}}"])
    if not COMMIT.fullmatch(sha):
        raise ValueError("The version tag must resolve to a valid commit.")
    subprocess.run(
        [*git, "merge-base", "--is-ancestor", sha, "refs/remotes/origin/main"],
        check=True,
        timeout=30,
    )
    version_file = ast.parse(capture([*git, "show", f"{sha}:src/astroagent/__init__.py"]))
    runtime_versions = [
        ast.literal_eval(node.value)
        for node in version_file.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "__version__" for target in node.targets
        )
    ]
    versions = (
        tomllib.loads(capture([*git, "show", f"{sha}:pyproject.toml"]))["project"]["version"],
        json.loads(capture([*git, "show", f"{sha}:frontend/package.json"]))["version"],
        json.loads(capture([*git, "show", f"{sha}:frontend/package-lock.json"]))["version"],
    )
    if runtime_versions != [tag[1:]] or any(version != tag[1:] for version in versions):
        raise ValueError("The tag must match the committed Python, frontend and lock versions.")
    return sha


def verified_tag(tag, signers, git=("git",)):
    validate_version(tag)
    ref = f"refs/tags/{tag}"
    sha = capture([*git, "rev-parse", f"{ref}^{{commit}}"])
    document = capture([*git, "cat-file", "tag", ref])
    if (
        not COMMIT.fullmatch(sha)
        or document.splitlines()[:3] != [f"object {sha}", "type commit", f"tag {tag}"]
        or "-----BEGIN SSH SIGNATURE-----" not in document
    ):
        raise ValueError("The version must be an annotated SSH-signed tag pointing at a commit.")
    subprocess.run(
        [
            *git,
            "-c",
            "gpg.format=ssh",
            "-c",
            f"gpg.ssh.allowedSignersFile={signers}",
            "verify-tag",
            ref,
        ],
        check=True,
        timeout=30,
    )
    return _verify_tag_commit_and_versions(tag, git=git)


def verified_unsigned_tag(tag, git=("git",)):
    return _verify_tag_commit_and_versions(tag, git=git)


def registry_digest(reference, *, unpublished=False):
    result = subprocess.run(
        ["docker", "buildx", "imagetools", "inspect", reference],
        capture_output=True,
        text=True,
        timeout=120,
    )
    if result.returncode:
        if unpublished and re.search(
            r"not found|manifest unknown|name unknown|no such manifest",
            result.stderr,
            re.IGNORECASE,
        ):
            return ""
        raise ValueError(f"Cannot inspect registry reference: {reference}")
    digest = re.search(r"^Digest:\s+(sha256:[a-f0-9]{64})\s*$", result.stdout, re.MULTILINE)
    if not digest:
        raise ValueError(f"Cannot identify the registry digest: {reference}")
    return digest[1]


def publish(component, release, sha, repository, output):
    validate_version(release)
    if not COMMIT.fullmatch(sha) or capture(["git", "rev-parse", "HEAD"]) != sha:
        raise ValueError("Publishing requires the exact CI-tested source checkout.")
    repository_name = image_repository(repository, component)
    tree = capture(["git", "ls-tree", "-r", sha, "--", BAKE, *COMPONENTS[component]])
    inputs = hashlib.sha256(tree.encode()).hexdigest()
    reusable = f"{repository_name}:inputs-{inputs}"
    digest = registry_digest(reusable, unpublished=True)
    if not digest:
        subprocess.run(
            [
                "docker",
                "buildx",
                "bake",
                "-f",
                BAKE,
                "--push",
                "--set",
                f"{component}.tags={reusable}",
                "--set",
                # Do not automatically inherit write access from a linked GitHub repository.
                f"{component}.labels.io.astroagent.source=https://github.com/{repository}",
                "--set",
                f"{component}.labels.org.opencontainers.image.revision={sha}",
                "--set",
                f"{component}.labels.io.astroagent.inputs={inputs}",
                "--set",
                f"{component}.cache-from=type=registry,ref={repository_name}:build-cache",
                "--set",
                f"{component}.cache-to=type=registry,ref={repository_name}:build-cache,mode=max",
                component,
            ],
            check=True,
            timeout=3600,
        )
        digest = registry_digest(reusable)
    pinned = f"{repository_name}@{digest}"
    for alias in (release, f"sha-{sha}"):
        tag = f"{repository_name}:{alias}"
        existing = registry_digest(tag, unpublished=True)
        if not existing:
            subprocess.run(
                [
                    "docker",
                    "buildx",
                    "imagetools",
                    "create",
                    "--prefer-index=false",
                    "--tag",
                    tag,
                    pinned,
                ],
                check=True,
                timeout=120,
            )
            existing = registry_digest(tag)
        if existing != digest:
            raise ValueError(f"Release alias already identifies another digest: {tag}")
    output.write_text(json.dumps({"component": component, "image": pinned}) + "\n", "utf-8")


def validate_manifest(manifest, repository):
    if set(manifest) != {"format", "version", "commit", "repository", "images"}:
        raise ValueError("Unexpected release manifest fields.")
    if manifest["format"] != 1 or manifest["repository"] != repository:
        raise ValueError("Incorrect release manifest version or repository.")
    validate_version(manifest["version"])
    if not COMMIT.fullmatch(manifest["commit"]):
        raise ValueError("Invalid release commit SHA.")
    if set(manifest["images"]) != set(COMPONENTS):
        raise ValueError("Release requires every expected image.")
    for component, reference in manifest["images"].items():
        name, _, digest = reference.partition("@")
        if name != image_repository(repository, component) or not DIGEST.fullmatch(digest):
            raise ValueError(f"Invalid image digest for {component}.")


def assemble(version, sha, repository, inputs, output):
    images = {}
    for part in sorted(inputs.glob("image-*.json")):
        record = json.loads(part.read_text("utf-8"))
        name = record["component"]
        if name in images:
            raise ValueError(f"Duplicate image component: {name}")
        images[name] = record["image"]
    manifest = {
        "format": 1,
        "version": version,
        "commit": sha,
        "repository": repository,
        "images": images,
    }
    validate_manifest(manifest, repository)
    output.write_text(json.dumps(manifest, sort_keys=True, indent=2) + "\n", "utf-8")


def preserve_local_titles(compose, override):
    backend = capture([*compose, "ps", "--all", "-q", "backend"])
    if not backend:
        return
    info = json.loads(capture(["docker", "inspect", backend]))[0]
    environment = dict(entry.split("=", 1) for entry in info["Config"]["Env"])
    enabled = environment.get("ASTROAGENT_LOCAL_MODEL_ENABLED", "").lower()
    if enabled not in {"true", "1", "on", "yes", "t", "y"}:
        return

    network_name = "astroagent-gcp_models"
    network = json.loads(capture(["docker", "network", "inspect", network_name]))[0]
    ollama = "astroagent-gcp-ollama-1"
    members = network.get("Containers") or {}
    health = capture(["docker", "inspect", "--format", "{{.State.Health.Status}}", ollama])
    if (
        not network["Internal"]
        or (network.get("Labels") or {}).get("com.docker.compose.project") != "astroagent-gcp"
        or network_name not in info["NetworkSettings"]["Networks"]
        or not any(peer["Name"] == ollama for peer in members.values())
        or environment.get("ASTROAGENT_LOCAL_MODEL_URL") != "http://ollama:11434"
        or health != "healthy"
    ):
        raise ValueError("The local title model must remain on its healthy internal network.")

    model_settings = {
        key: environment[key]
        for key in (
            "ASTROAGENT_LOCAL_MODEL_ENABLED",
            "ASTROAGENT_LOCAL_MODEL_NAME",
            "ASTROAGENT_LOCAL_MODEL_DIGEST",
            "ASTROAGENT_LOCAL_MODEL_THREADS",
            "ASTROAGENT_LOCAL_MODEL_QUEUE_SIZE",
            "ASTROAGENT_LOCAL_MODEL_TIMEOUT_SECONDS",
        )
        if key in environment
    }
    override["services"]["backend"].update(environment=model_settings, networks=["models"])
    override["networks"] = {"models": {"external": True, "name": network_name}}


def deploy_ssh(version, sha, repository, registry_user):
    token = sys.stdin.readline(4096).rstrip("\r\n")
    manifest = json.load(sys.stdin)
    validate_manifest(manifest, repository)
    if (manifest["version"], manifest["commit"]) != (version, sha) or not token:
        raise ValueError("The deployment requires the matching manifest and registry access.")

    directory = Path("containers/gcp").resolve()
    env_file = directory / ".env"
    if env_file.is_symlink() or not env_file.is_file() or env_file.stat().st_mode & 0o777 != 0o600:
        raise ValueError("Prepare the server's containers/gcp/.env with mode 600 before release.")
    compose = [
        "docker",
        "compose",
        "--project-name",
        "astroagent-gcp",
        "--project-directory",
        str(directory),
        "--env-file",
        str(env_file),
        "-f",
        str(directory / "docker-compose.yml"),
    ]

    def compose_config(*options):
        result = subprocess.run(
            [*compose, "config", *options], encoding="utf-8", capture_output=True, timeout=30
        )
        if result.returncode:
            raise ValueError("The server's Compose configuration could not be resolved.")
        return result.stdout

    settings = dict(
        line.split("=", 1) for line in compose_config("--environment").splitlines() if "=" in line
    )
    rag = bool(settings.get("EMBEDDING_MODEL_DIR") and settings.get("EMBEDDING_MODEL_SHA256"))
    if rag:
        compose.extend(("-f", str(directory / "docker-compose.rag.yml")))
    plotting = settings.get("PLOT_ENABLED", "0") == "1"
    if plotting:
        compose.extend(("-f", str(directory / "docker-compose.plot.yml")))
    site = subprocess.run(
        [sys.executable, str(directory / "deploy_env.py"), "verify"],
        input=compose_config("--format", "json"),
        encoding="utf-8",
        capture_output=True,
        check=False,
        timeout=30,
    )
    if site.returncode:
        raise ValueError("Server configuration did not pass deploy_env.py verification.")
    _, compute = site.stdout.split()
    services = ["backend", "frontend", "ingress"]
    if compute == "1":
        compose.extend(("--profile", "compute"))
        services.append("compute-worker")

    sql = [
        *compose,
        "exec",
        "-T",
        "postgres",
        "psql",
        "-U",
        "postgres",
        "-d",
        "astroagent",
        "-Atq",
        "-v",
        "ON_ERROR_STOP=1",
        "-c",
    ]
    if (
        not capture([*compose, "ps", "--status", "running", "-q", "postgres"])
        or capture([*sql, "SELECT to_regclass('public.auth_meta') IS NOT NULL"]) != "t"
    ):
        raise ValueError("The server's existing PostgreSQL identity database must be initialized.")

    images = manifest["images"]
    service_override = {"services": {name: {"image": images[name]} for name in services}}
    preserve_local_titles(compose, service_override)

    with TemporaryDirectory(prefix="siderfolio-release-") as temporary:
        private = Path(temporary)
        config = os.environ | {"DOCKER_CONFIG": str(private / "docker")}
        login = subprocess.run(
            ["docker", "login", "ghcr.io", "-u", registry_user, "--password-stdin"],
            input=token + "\n",
            text=True,
            capture_output=True,
            check=False,
            timeout=30,
            env=config,
        )
        del token
        if login.returncode:
            raise ValueError("GHCR login failed. Check this repository's package read access.")
        override = private / "images.json"
        override.write_text(json.dumps(service_override), "utf-8")
        pull = [*compose, "-f", str(override)]
        subprocess.run([*pull, "pull", *services], check=True, timeout=900, env=config)
        has_compute = capture([*sql, "SELECT to_regclass('public.compute_tasks') IS NOT NULL"])
        if compute == "1" and has_compute != "t":
            raise ValueError("Initialize the optional compute schema on the server first.")
        if (
            has_compute == "t"
            and capture(
                [
                    *sql,
                    "SELECT count(*) FROM public.compute_tasks "
                    "WHERE state IN ('running','cancelling')",
                ]
            )
            != "0"
        ):
            raise ValueError("Wait for active compute tasks before replacing the backend.")
        runtime = os.environ | {"COMPOSE_REMOVE_ORPHANS": "false"}
        if compute == "1":
            runtime["COMPUTE_IMAGE_ID"] = capture(
                [
                    "docker",
                    "image",
                    "inspect",
                    "--format",
                    "{{.Id}}",
                    images["compute-worker"],
                ]
            )
        subprocess.run(
            [
                *pull,
                "up",
                "-d",
                "--no-deps",
                "--no-build",
                "--pull",
                "never",
                "--wait",
                "--wait-timeout",
                "240",
                *services,
            ],
            check=True,
            timeout=300,
            env=runtime,
        )
        verify = ["bash", str(directory / "deploy.sh")]
        if rag:
            verify.append("--rag")
        subprocess.run([*verify, "verify"], check=True, timeout=240, env=runtime)
        if plotting:
            subprocess.run(
                [
                    *pull,
                    "exec",
                    "-T",
                    "backend",
                    "python",
                    "-c",
                    "from astroagent.config import LocalSettings; "
                    "from astroagent.plot_executor_client import ExecutorClient; "
                    "ExecutorClient(LocalSettings()).probe()",
                ],
                check=True,
                timeout=30,
            )


def _strip_signature_blocks(text):
    return SIGNATURE_BLOCK.sub("", text).replace("\r\n", "\n").strip()


def _extract_release_notes_file(version, sha, git=("git",)):
    result = subprocess.run(
        [*git, "show", f"{sha}:docs/releases/{version}.md"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        timeout=30,
    )
    if result.returncode != 0:
        return ""
    return result.stdout.lstrip("\ufeff").replace("\r\n", "\n").strip()


def _extract_tag_notes(version, git=("git",)):
    ref = f"refs/tags/{version}"
    obj_type = subprocess.run(
        [*git, "cat-file", "-t", ref],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        timeout=30,
    )
    if obj_type.returncode != 0 or obj_type.stdout.strip() != "tag":
        return ""
    raw = capture([*git, "cat-file", "tag", ref])
    _, sep, message = raw.replace("\r\n", "\n").partition("\n\n")
    if not sep:
        return ""
    cleaned = _strip_signature_blocks(message)
    if not cleaned:
        return ""
    lines = cleaned.splitlines()
    if BOILERPLATE_TAG_TITLE.fullmatch(lines[0].strip()):
        lines = lines[1:]
        while lines and not lines[0].strip():
            lines = lines[1:]
    return "\n".join(lines).strip()


def _previous_stable_tag(version, sha, git=("git",)):
    target_tuple = validate_version(version)
    output = capture([*git, "tag", "--merged", sha])
    candidates = []
    for raw_tag in output.splitlines():
        tag = raw_tag.strip()
        if not tag or tag == version or not VERSION.fullmatch(tag):
            continue
        parsed = validate_version(tag)
        if parsed < target_tuple:
            candidates.append((parsed, tag))
    if not candidates:
        return ""
    candidates.sort()
    return candidates[-1][1]


def _format_commit_notes(prev_tag, sha, git=("git",)):
    rev_spec = f"{prev_tag}..{sha}" if prev_tag else sha
    command = [*git, "log"]
    if not prev_tag:
        command.extend(["-n", "1"])
    command.extend(["--no-merges", "--format=%H%x1f%s%x1f%b%x1e", rev_spec])
    raw = subprocess.check_output(command, encoding="utf-8", timeout=120)
    if not raw.strip() and prev_tag:
        raw = subprocess.check_output(
            [*git, "log", "-n", "1", "--format=%H%x1f%s%x1f%b%x1e", sha],
            encoding="utf-8",
            timeout=120,
        )
    entries = []
    for record in raw.split("\x1e"):
        record = record.strip("\n\r")
        if not record:
            continue
        parts = record.split("\x1f")
        if len(parts) < 2:
            continue
        commit_sha = parts[0].strip()[:7]
        subject = parts[1].strip()
        body = parts[2] if len(parts) > 2 else ""
        if not subject:
            continue
        item_lines = [f"- {subject} (`{commit_sha}`)"]
        for line in body.replace("\r\n", "\n").splitlines():
            stripped = line.strip()
            if not stripped or GIT_TRAILER.match(stripped):
                continue
            item_lines.append(f"  {stripped}")
        entries.append("\n".join(item_lines))
    if not entries:
        return f"## 更新内容\n\n- 发布提交 `{sha[:7]}`"
    return "## 更新内容\n\n" + "\n".join(entries)


def build_release_notes(version, sha, repository, git=("git",)):
    validate_version(version)
    if not COMMIT.fullmatch(sha) or not REPOSITORY.fullmatch(repository):
        raise ValueError("Invalid release commit SHA or repository.")
    prev_tag = _previous_stable_tag(version, sha, git=git)
    body = _extract_release_notes_file(version, sha, git=git)
    if not body:
        body = _extract_tag_notes(version, git=git)
    if not body:
        body = _format_commit_notes(prev_tag, sha, git=git)
    compare_prefix = f"https://github.com/{repository}/compare/"
    if prev_tag and compare_prefix.lower() not in body.lower():
        body = f"{body}\n\n**Full Changelog**: {compare_prefix}{prev_tag}...{version}"
    return body.rstrip() + "\n"


def write_release_notes(version, sha, repository, output, git=("git",)):
    notes = build_release_notes(version, sha, repository, git=git)
    output.write_text(notes, "utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_subparsers(dest="action", required=True)
    auth = actions.add_parser("authorize")
    auth.add_argument("version")
    auth.add_argument("signers", type=Path)
    auth_unsigned = actions.add_parser("authorize-unsigned")
    auth_unsigned.add_argument("version")
    deploy = actions.add_parser("deploy-ssh")
    for name in ("version", "sha", "repository", "registry_user"):
        deploy.add_argument(name)
    notes = actions.add_parser("notes")
    for name in ("version", "sha", "repository"):
        notes.add_argument(name)
    notes.add_argument("output", type=Path)
    image = actions.add_parser("publish")
    image.add_argument("component", choices=COMPONENTS)
    for action in (image, actions.add_parser("assemble")):
        action.add_argument("version")
        action.add_argument("sha")
        action.add_argument("repository")
        if action is not image:
            action.add_argument("inputs", type=Path)
        action.add_argument("output", type=Path)
    args = parser.parse_args()
    if args.action in ("authorize", "authorize-unsigned"):
        sha = (
            verified_tag(args.version, args.signers)
            if args.action == "authorize"
            else verified_unsigned_tag(args.version)
        )
        if capture(["git", "rev-parse", "HEAD"]) != sha:
            raise ValueError("The release tag and checked-out commit disagree.")
        with Path(os.environ["GITHUB_OUTPUT"]).open("a", encoding="utf-8") as result:
            result.write(f"version={args.version}\nsha={sha}\n")
    elif args.action == "publish":
        publish(args.component, args.version, args.sha, args.repository, args.output)
    elif args.action == "deploy-ssh":
        deploy_ssh(args.version, args.sha, args.repository, args.registry_user)
    elif args.action == "notes":
        write_release_notes(args.version, args.sha, args.repository, args.output)
    else:
        assemble(args.version, args.sha, args.repository, args.inputs, args.output)


if __name__ == "__main__":
    main()
