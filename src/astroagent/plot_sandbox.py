"""Linux Docker execution only. No subprocess fallback for generated scripts."""

import io
import json
import os
import re
import shutil
import struct
import subprocess
import tarfile
import tempfile
from pathlib import Path

from astroagent.errors import ServiceError

IMAGE = re.compile(r"(?:sha256:|[a-zA-Z0-9./_:-]+@sha256:)[0-9a-f]{64}$")
MAX_OUTPUT = 8 * 1024**2


def configured(settings):
    return bool(
        settings.plot_execution_enabled
        and all(
            IMAGE.fullmatch(v) for v in (settings.plot_python_image, settings.plot_gnuplot_image)
        )
    )


def unavailable():
    return ServiceError(
        503,
        "plot_sandbox_unavailable",
        "隔离绘图环境未就绪；没有在宿主机执行脚本。请核对本机Linux Docker和固定镜像配置。",
    )


class Sandbox:
    def __init__(self, settings):
        self.settings = settings
        self.docker = shutil.which("docker")

    def call(self, *args, timeout=10):
        env = {
            key: os.environ[key]
            for key in ("PATH", "SystemRoot", "WINDIR", "TEMP", "TMP")
            if key in os.environ
        }
        result = subprocess.run(
            [self.docker, "--host", self.settings.plot_docker_host, *args],
            capture_output=True,
            timeout=timeout,
            env=env,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if result.returncode or len(result.stdout) > 20 * 1024**2:
            raise unavailable()
        return result.stdout

    def admit(self, engine):
        if not self.docker or not configured(self.settings):
            raise unavailable()
        try:
            info = json.loads(self.call("info", "--format", "{{json .}}"))
            if info.get("OSType") != "linux" or not any(
                "seccomp" in s for s in info.get("SecurityOptions", [])
            ):
                raise unavailable()
            if any("unconfined" in s for s in info.get("SecurityOptions", [])):
                raise unavailable()
            if any(info.get(key) for key in ("Warnings",)) or not all(
                info.get(key) for key in ("MemoryLimit", "PidsLimit", "CpuCfsQuota", "SwapLimit")
            ):
                raise unavailable()
            image = getattr(self.settings, f"plot_{engine}_image")
            detail = json.loads(self.call("image", "inspect", image))[0]
            config = detail.get("Config", {})
            if (
                detail.get("Os") != "linux"
                or config.get("Volumes")
                or config.get("Labels", {}).get("org.astroagent.plot-protocol") != "2"
            ):
                raise unavailable()
            return image, detail["Id"]
        except ServiceError:
            raise
        except Exception as exc:
            raise unavailable() from exc

    def artifact(self, name, container):
        raw = self.call("cp", f"{container}:/output/{name}", "-")
        with tarfile.open(fileobj=io.BytesIO(raw)) as archive:
            members = archive.getmembers()
            if (
                len(members) != 1
                or members[0].name != name
                or not members[0].isfile()
                or not 0 < members[0].size <= MAX_OUTPUT
            ):
                raise ServiceError(422, "plot_output_invalid", "绘图输出格式或大小无效。")
            return archive.extractfile(members[0]).read(MAX_OUTPUT + 1)

    def run(self, proposal, data, run_id, admitted):
        image, image_id = admitted
        container = "astroagent-plot-" + run_id
        suffix = "py" if proposal["engine"] == "python" else "plt"
        root = Path(self.settings.data_dir).resolve() / "plot-jobs"
        root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="job-", dir=root) as directory:
            path = Path(directory).resolve()
            if "," in str(path):
                raise unavailable()
            (path / "data.csv").write_bytes(data)
            (path / f"script.{suffix}").write_text(
                proposal["script"], encoding="utf-8", newline="\n"
            )
            path.chmod(0o755)
            for member in path.iterdir():
                member.chmod(0o644)
            created = False
            try:
                self.call(
                    "create",
                    "--name",
                    container,
                    "--label",
                    "org.astroagent.plot-job=1",
                    "--pull",
                    "never",
                    "--network",
                    "none",
                    "--read-only",
                    "--user",
                    "65532:65532",
                    "--cap-drop",
                    "ALL",
                    "--security-opt",
                    "no-new-privileges=true",
                    "--memory",
                    "256m",
                    "--memory-swap",
                    "256m",
                    "--cpus",
                    "1",
                    "--pids-limit",
                    "32",
                    "--ulimit",
                    "nofile=64:64",
                    "--ulimit",
                    "fsize=8388608:8388608",
                    "--log-driver",
                    "none",
                    "--no-healthcheck",
                    "--mount",
                    f"type=bind,src={path},dst=/input,readonly",
                    "--tmpfs",
                    "/output:rw,noexec,nosuid,nodev,size=20m,mode=1777",
                    "--tmpfs",
                    "/tmp:rw,noexec,nosuid,nodev,size=8m,mode=1777",
                    "--workdir",
                    "/output",
                    "--entrypoint",
                    "/usr/local/bin/python3",
                    image,
                    "-I",
                    "/opt/plot_worker.py",
                    proposal["engine"],
                )
                created = True
                details = json.loads(self.call("inspect", container))[0]
                host = details["HostConfig"]
                mounts = [m for m in details["Mounts"] if m.get("Type") != "tmpfs"]
                if (
                    details["Image"] != image_id
                    or host["NetworkMode"] != "none"
                    or host.get("Privileged")
                    or details["Config"].get("User") != "65532:65532"
                    or "ALL" not in host.get("CapDrop", [])
                    or not any(
                        "no-new-privileges" in value for value in host.get("SecurityOpt", [])
                    )
                    or not host["ReadonlyRootfs"]
                    or host["Memory"] != 256 * 1024**2
                    or host["MemorySwap"] != 256 * 1024**2
                    or host["PidsLimit"] != 32
                    or host["NanoCpus"] != 1000000000
                    or len(mounts) != 1
                    or mounts[0].get("RW")
                    or mounts[0].get("Destination") != "/input"
                ):
                    raise unavailable()
                raw = self.call(
                    "start", "--attach", container, timeout=self.settings.plot_timeout_seconds
                )
                with tarfile.open(fileobj=io.BytesIO(raw)) as archive:
                    members = archive.getmembers()
                    allowed = {"status.json", "run.log", "runtime.json", "figure.png", "figure.pdf"}
                    if (
                        len(members) > len(allowed)
                        or len({member.name for member in members}) != len(members)
                        or any(
                            member.name not in allowed
                            or not member.isfile()
                            or member.size > MAX_OUTPUT
                            for member in members
                        )
                    ):
                        raise ServiceError(422, "plot_output_invalid", "绘图输出格式或大小无效。")
                    output = {
                        member.name: archive.extractfile(member).read(MAX_OUTPUT + 1)
                        for member in members
                    }
                status = json.loads(output["status.json"])
                if status.get("exit_code") != 0:
                    exc = ServiceError(
                        422,
                        "plot_script_failed",
                        "脚本执行失败或超出资源限制；未交付不完整图形。请调整方案后创建新运行。",
                    )
                    exc.plot_diagnostic = (
                        output.get("run.log", b"").decode("utf-8", errors="replace")[:4096]
                        or "运行日志不可用。"
                    )
                    raise exc
                png = output.get("figure.png", b"")
                pdf = output.get("figure.pdf", b"")
                versions = json.loads(output["runtime.json"])
                if (
                    len(png) < 24
                    or png[:8] != b"\x89PNG\r\n\x1a\n"
                    or not all(0 < n <= 2400 for n in struct.unpack(">II", png[16:24]))
                    or not pdf.startswith(b"%PDF-")
                ):
                    raise ServiceError(
                        422, "plot_output_invalid", "脚本未生成有效的PNG/PDF，或图像超过2400像素。"
                    )
                # Image-supplied versions are evidence, not a proof of script correctness.
                if not isinstance(versions, dict) or len(json.dumps(versions)) > 4096:
                    raise unavailable()
                return {"figure.png": png, "figure.pdf": pdf}, {
                    "image_id": image_id,
                    "engine_versions": versions,
                    "isolation": "linux-docker-v1",
                    "network": "none",
                    "memory_mib": 256,
                    "cpu": 1,
                    "timeout_seconds": self.settings.plot_timeout_seconds,
                }
            except subprocess.TimeoutExpired as exc:
                raise ServiceError(
                    504,
                    "plot_execution_timeout",
                    "绘图执行超时，容器已请求强制清理；不会自动重试。",
                ) from exc
            finally:
                if created:
                    self.call("rm", "--force", container)

    def cleanup_interrupted(self, ids):
        # Target only exact persisted running UUIDs, never enumerate/delete user containers.
        if not self.docker:
            return
        for identifier in ids:
            try:
                self.call("rm", "--force", "astroagent-plot-" + identifier)
            except Exception:
                pass
