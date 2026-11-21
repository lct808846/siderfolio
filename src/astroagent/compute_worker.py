"""Offline worker supervising fixed executables, per-execution fencing and deadlines."""

import fcntl
import os
import signal
import subprocess
import sys
import time
from contextlib import suppress
from pathlib import Path
from tempfile import TemporaryDirectory

from astroagent.compute_io import attempts, spool, write
from astroagent.compute_petar import PETAR_EXECUTABLE
from astroagent.compute_schemas import WALL_SECONDS


def heartbeat(root: Path, petar: bool) -> None:
    (root / "heartbeat").touch()
    if petar:
        (root / "petar-heartbeat").touch()


def execute(root: Path, directory: Path, petar: bool) -> None:
    if (directory / "cancel").exists():
        write(directory / "done", "cancelled")
        return
    if (directory / "started").exists():
        # A previous container stopped. Its children were removed with the container.
        write(directory / "done", "interrupted")
        return
    write(directory / "started", True)
    (directory / "heartbeat").touch()
    deadline = time.monotonic() + WALL_SECONDS
    stop_state = None
    with (
        TemporaryDirectory(prefix="astroagent-compute-") as workspace,
        subprocess.Popen(
            [sys.executable, "-m", "astroagent.compute_runner", str(directory)],
            cwd=workspace,
            env={
                "PATH": "/usr/local/bin:/usr/bin:/bin",
                "PYTHONDONTWRITEBYTECODE": "1",
                "ASTROAGENT_COMPUTE_IMAGE_ID": os.getenv("ASTROAGENT_COMPUTE_IMAGE_ID", ""),
            },
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            start_new_session=True,
        ) as process,
    ):
        try:
            while process.poll() is None:
                heartbeat(root, petar)
                (directory / "heartbeat").touch()
                if (directory / "cancel").exists():
                    stop_state = "cancelled"
                    break
                if time.monotonic() >= deadline:
                    stop_state = "failed"
                    break
                time.sleep(0.25)
        finally:
            # PeTar is a child of the runner. Stop the entire group before discarding scratch data.
            with suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGKILL)
            process.wait()

    if stop_state == "failed":
        write(directory / "failure", "模拟已达到 120 秒运行上限，请缩短时长或减少粒子数。")
    state = stop_state or (
        "succeeded" if process.returncode == 0 and (directory / "result").is_file() else "failed"
    )
    write(directory / "done", state)


def main() -> None:
    root = spool()
    petar = os.access(PETAR_EXECUTABLE, os.X_OK)
    with (root / "worker.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        while True:
            heartbeat(root, petar)
            for directory in attempts(root):
                if (directory / "input").is_file() and not (directory / "done").exists():
                    execute(root, directory, petar)
            time.sleep(0.5)


if __name__ == "__main__":
    main()
