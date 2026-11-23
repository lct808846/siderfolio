"""Check signed source and produce an immutable image manifest for a formal release."""

import argparse
import ast
import hashlib
import json
import os
import re
import subprocess
import tomllib
from pathlib import Path

VERSION = re.compile(r"v(0|[1-9]\d{0,5})\.(0|[1-9]\d{0,5})\.(0|[1-9]\d{0,5})")
COMMIT = re.compile(r"[a-f0-9]{40}")
DIGEST = re.compile(r"sha256:[a-f0-9]{64}")
REPOSITORY = re.compile(r"[a-z0-9][a-z0-9_.-]*/[a-z0-9][a-z0-9_.-]*")
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
    return subprocess.check_output(command, text=True, timeout=120).strip()


def validate_version(version):
    match = VERSION.fullmatch(version)
    if not match:
        raise ValueError("Expected a stable vMAJOR.MINOR.PATCH release tag.")
    return tuple(map(int, match.groups()))


def image_repository(repository, component):
    if not REPOSITORY.fullmatch(repository) or component not in COMPONENTS:
        raise ValueError("Invalid repository or component.")
    return f"ghcr.io/{repository}-{component}"


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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_subparsers(dest="action", required=True)
    auth = actions.add_parser("authorize")
    auth.add_argument("version")
    auth.add_argument("signers", type=Path)
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
    if args.action == "authorize":
        sha = verified_tag(args.version, args.signers)
        if capture(["git", "rev-parse", "HEAD"]) != sha:
            raise ValueError("The signed version and checked-out commit disagree.")
        with Path(os.environ["GITHUB_OUTPUT"]).open("a", encoding="utf-8") as result:
            result.write(f"version={args.version}\nsha={sha}\n")
    elif args.action == "publish":
        publish(args.component, args.version, args.sha, args.repository, args.output)
    else:
        assemble(args.version, args.sha, args.repository, args.inputs, args.output)


if __name__ == "__main__":
    main()
