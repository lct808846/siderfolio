"""Create a separate private Compose configuration; never copy or migrate application data."""

import argparse
import hashlib
import json
import os
import re
import secrets
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IMAGE_KEYS = {"PYTHON_IMAGE", "NODE_IMAGE", "POSTGRES_IMAGE", "OLLAMA_IMAGE", "DOCKER_CLI_IMAGE"}


def protect_directory(path):
    if os.name == "nt":
        import subprocess

        subprocess.run(
            [
                "icacls",
                str(path),
                "/inheritance:r",
                "/grant:r",
                os.environ["USERDOMAIN"] + "\\" + os.environ["USERNAME"] + ":(OI)(CI)F",
                "*S-1-5-18:(OI)(CI)F",
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    else:
        path.chmod(0o700)


def local_path(path):
    path = path.resolve(strict=True)
    if str(path).startswith("\\\\") or os.name == "nt" and path.drive.lower() != "d:":
        raise ValueError("Choose a local D-drive path on Windows")
    value = path.as_posix()
    if any(c in value for c in '\r\n$"'):
        raise ValueError("Unsupported Compose path")
    return value


def sha256(path):
    result = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024**2):
            result.update(chunk)
    return result.hexdigest()


def prepare_model(source, output):
    pins = json.loads((ROOT / "containers/model-source.json").read_text(encoding="utf-8"))
    for name, expected in pins["files"].items():
        path = source / name
        if path.is_symlink() or sha256(path) != expected:
            raise ValueError("Prepared model metadata or GGUF identity differs")
    template = (source / "template.txt").read_text(encoding="utf-8")
    license_text = (source / "LICENSE.txt").read_text(encoding="utf-8")
    params = json.loads((source / "parameters.json").read_text(encoding="utf-8"))
    if (
        '"""' in template
        or '"""' in license_text
        or set(params) - {"repeat_penalty", "stop", "temperature", "top_k", "top_p"}
    ):
        raise ValueError("Unsupported prepared model definition")
    lines = [
        "FROM /import/model.gguf",
        'TEMPLATE """' + template + '"""',
        'LICENSE """' + license_text + '"""',
        "PARAMETER num_ctx 8192",
    ]
    for key, values in params.items():
        for value in values if isinstance(values, list) else [values]:
            lines.append("PARAMETER " + key + " " + json.dumps(value, ensure_ascii=False))
    (output / "Modelfile").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return local_path(source / pins["gguf"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image-lock", type=Path, required=True)
    parser.add_argument("--embedding-model-dir", type=Path, required=True)
    parser.add_argument("--embedding-sha256", required=True)
    parser.add_argument("--prepared-qwen-dir", type=Path)
    parser.add_argument("--plot-python-image", default="")
    parser.add_argument("--plot-gnuplot-image", default="")
    parser.add_argument("--docker-socket-gid", type=int)
    parser.add_argument("--copy-native-provider-settings", action="store_true")
    parser.add_argument("--confirm-include-credentials", action="store_true")
    args = parser.parse_args()
    output = ROOT / ".astroagent/container"
    try:
        if output.exists():
            raise ValueError("Refuse an existing private configuration directory")
        from lock_container_images import REPOSITORIES, repository

        lock = json.loads(args.image_lock.read_text(encoding="utf-8"))
        images = lock["images"]
        if set(images) != IMAGE_KEYS or not all(
            re.fullmatch(r"[a-zA-Z0-9_./:-]+@sha256:[0-9a-f]{64}", value)
            for value in images.values()
        ):
            raise ValueError("Prepare exact image digests first")
        if lock.get("platform") != "linux/amd64" or any(
            repository(value) != REPOSITORIES[key] for key, value in images.items()
        ):
            raise ValueError("Approved linux/amd64 base repositories required")
        embedding = local_path(args.embedding_model_dir)
        if not args.embedding_model_dir.is_dir() or not re.fullmatch(
            "[0-9a-f]{64}", args.embedding_sha256
        ):
            raise ValueError("Explicit embedding directory and identity required")
        plot_images = (args.plot_python_image, args.plot_gnuplot_image)
        if any(plot_images) or args.docker_socket_gid is not None:
            if not all(re.fullmatch(r"sha256:[0-9a-f]{64}", value) for value in plot_images):
                raise ValueError("Two fixed local plotting image IDs are required")
            if args.docker_socket_gid is None or not 0 <= args.docker_socket_gid <= 2**31 - 1:
                raise ValueError("Explicit Docker socket group ID required")
        settings = json.loads(
            (ROOT / "containers/backend-settings.example.json").read_text(encoding="utf-8")
        )
        if args.copy_native_provider_settings:
            if not args.confirm_include_credentials:
                raise ValueError("Explicit credential-copy confirmation required")
            from dotenv import dotenv_values

            native = dotenv_values(ROOT / ".env")
            for name in (
                "DEEPSEEK_API_KEY",
                "DEEPSEEK_BASE_URL",
                "DEEPSEEK_MODEL",
                "CHAT_MODELS",
                "LLM_THINKING_PARAMETER",
                "LLM_TIMEOUT_SECONDS",
                "ADS_API_TOKEN",
                "SIMBAD_TIMEOUT_SECONDS",
                "ADS_TIMEOUT_SECONDS",
                "GAIA_TIMEOUT_SECONDS",
            ):
                if name in native and native[name] is not None:
                    settings[name] = (
                        json.loads(native[name]) if name == "CHAT_MODELS" else native[name]
                    )
        output.mkdir(parents=True, mode=0o700)
        protect_directory(output)
        private = output / "secrets"
        private.mkdir(mode=0o700)
        for name in (
            "postgres_admin_password",
            "database_password",
            "proxy_token",
            "executor_token",
        ):
            path = private / name
            # Compose mounts these files into Linux containers. Force LF on Windows;
            # shell command substitution otherwise preserves a trailing CR.
            with path.open("xb") as stream:
                stream.write((secrets.token_hex(32) + "\n").encode("ascii"))
            # The host parent is private; mounted files must be readable by non-root service UIDs.
            path.chmod(0o444)
        path = private / "backend-settings.json"
        path.write_text(json.dumps(settings, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        path.chmod(0o444)
        values = {
            **images,
            "EMBEDDING_MODEL_DIR": embedding,
            "EMBEDDING_MODEL_SHA256": args.embedding_sha256,
            "RAG_SEMANTIC_ENABLED": "false",
            "LOCAL_MODEL_ENABLED": "false",
            "LOCAL_MODEL_DIGEST": "",
            "CONTAINER_DATABASE": "astroagent",
        }
        if any(plot_images) or args.docker_socket_gid is not None:
            values.update(
                PLOT_PYTHON_IMAGE=plot_images[0],
                PLOT_GNUPLOT_IMAGE=plot_images[1],
                DOCKER_SOCKET_GID=str(args.docker_socket_gid),
            )
        if args.prepared_qwen_dir:
            values["OLLAMA_IMPORT_GGUF"] = prepare_model(
                args.prepared_qwen_dir.resolve(strict=True), output
            )
        (output / "deployment.env").write_text(
            "\n".join(f'{key}="{value}"' for key, value in values.items()) + "\n", encoding="utf-8"
        )
        shutil.copyfile(args.image_lock, output / "images.lock.json")
        print(
            "Created separate private deployment files. No"
            " images built, containers started, model impo"
            "rted or database changed."
        )
        return 0
    except Exception:
        print(
            "Preparation incomplete; any newly created fil"
            "es are retained for review. Existing configur"
            "ation and data were not overwritten."
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
