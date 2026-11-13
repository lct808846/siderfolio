"""Trusted Docker Desktop broker using isolated, temporary input volumes."""

import io
import json
import os
import subprocess
import tarfile
import time
from contextlib import contextmanager

from astroagent.plot_sandbox import Sandbox, unavailable


class DockerDesktopSandbox(Sandbox):
    """Trusted, internal broker over the local Desktop socket; never expose it to jobs."""

    def __init__(self, settings, owner):
        Sandbox.__init__(self, settings)
        self.owner = owner
        self.settings.plot_executor_owner = owner
        self.deadline = None

    def call(self, *args, timeout=10, input=None):
        if not self.docker:
            raise unavailable()
        cleanup = args[0] == "rm" or args[:2] == ("volume", "rm")
        if self.deadline is not None and not cleanup:
            timeout = min(timeout, self.deadline - time.monotonic())
            if timeout <= 0:
                raise subprocess.TimeoutExpired("isolated-executor", 60)
        env = {key: os.environ[key] for key in ("PATH", "LANG") if key in os.environ}
        env["DOCKER_CONFIG"] = "/tmp/empty-docker-config"
        result = subprocess.run(
            [self.docker, "--host", "unix:///var/run/docker.sock", *args],
            input=input,
            capture_output=True,
            timeout=min(timeout, 3) if cleanup else timeout,
            env=env,
        )
        if result.returncode or len(result.stdout) > 20 * 1024**2:
            raise unavailable()
        return result.stdout

    def admit(self, engine):
        info = json.loads(self.call("info", "--format", "{{json .}}"))
        if "docker desktop" not in str(info.get("OperatingSystem", "")).lower():
            raise unavailable()
        return Sandbox.admit(self, engine)

    def volume_name(self, run_id):
        return "astroagent-input-" + self.owner + "-" + run_id

    @contextmanager
    def inputs(self, proposal, data, run_id, image):
        volume = self.volume_name(run_id)
        seed = "astroagent-seed-" + run_id
        created = seeded = False
        try:
            # Refuse existing names; never adopt an unrelated volume or container.
            existing = self.call(
                "volume", "ls", "--filter", "name=^" + volume + "$", "--format", "{{.Name}}"
            )
            if existing.strip():
                raise unavailable()
            self.call(
                "volume", "create", "--label", "org.astroagent.executor-owner=" + self.owner, volume
            )
            created = True
            self.call(
                "create",
                "--name",
                seed,
                "--label",
                "org.astroagent.executor-owner=" + self.owner,
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
                "--mount",
                "type=volume,src=" + volume + ",dst=/input,volume-nocopy",
                "--entrypoint",
                "/usr/local/bin/python3",
                image,
                "-V",
            )
            seeded = True
            stream = io.BytesIO()
            with tarfile.open(fileobj=stream, mode="w") as archive:
                suffix = "py" if proposal["engine"] == "python" else "plt"
                for name, raw in (
                    ("data.csv", data),
                    ("script." + suffix, proposal["script"].encode()),
                ):
                    member = tarfile.TarInfo(name)
                    member.size, member.mode, member.uid, member.gid = len(raw), 0o444, 65532, 65532
                    archive.addfile(member, io.BytesIO(raw))
            self.call("cp", "-a", "-", seed + ":/input", input=stream.getvalue())
            self.call("rm", "--force", seed)
            seeded = False
            yield "type=volume,src=" + volume + ",dst=/input,readonly,volume-nocopy"
        finally:
            try:
                if seeded:
                    self.call("rm", "--force", seed)
            finally:
                if created:
                    self.call("volume", "rm", volume)

    def valid_input_mount(self, mount, run_id):
        return mount.get("Type") == "volume" and mount.get("Name") == self.volume_name(run_id)

    def cleanup_owned(self, run_id):
        try:
            label = "label=org.astroagent.executor-owner=" + self.owner
            names = (
                self.call("ps", "-a", "--filter", label, "--format", "{{.Names}}")
                .decode()
                .splitlines()
            )
            for name in ("astroagent-plot-" + run_id, "astroagent-seed-" + run_id):
                if name in names:
                    self.call("rm", "--force", name)
            volumes = (
                self.call("volume", "ls", "--filter", label, "--format", "{{.Name}}")
                .decode()
                .splitlines()
            )
            if self.volume_name(run_id) in volumes:
                self.call("volume", "rm", self.volume_name(run_id))
            return True
        except Exception:
            return False
