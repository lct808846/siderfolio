"""Trusted container entry point. Never invoke on the application host."""

import importlib.metadata
import io
import json
import os
import selectors
import signal
import subprocess
import sys
import tarfile
import time

engine = sys.argv[1]
if engine not in ("python", "gnuplot"):
    sys.exit(2)
os.environ.update(
    HOME="/tmp", MPLCONFIGDIR="/tmp/matplotlib", MPLBACKEND="Agg", MATPLOTLIBRC="/opt/matplotlibrc"
)
command = (
    [sys.executable, "-I", "/input/script.py"]
    if engine == "python"
    else ["/usr/bin/gnuplot", "/input/script.plt"]
)
process = subprocess.Popen(
    command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, start_new_session=True, cwd="/output"
)
selector = selectors.DefaultSelector()
selector.register(process.stdout, selectors.EVENT_READ)
deadline, log = time.monotonic() + 28, bytearray()
try:
    while selector.get_map():
        if time.monotonic() > deadline:
            os.killpg(process.pid, signal.SIGKILL)
            break
        for key, _ in selector.select(timeout=0.1):
            chunk = os.read(key.fileobj.fileno(), 4096)
            if not chunk:
                selector.unregister(key.fileobj)
            else:
                log.extend(chunk[: max(0, 4096 - len(log))])
    remaining = max(0.1, deadline - time.monotonic())
    code = process.wait(timeout=remaining)
except subprocess.TimeoutExpired:
    os.killpg(process.pid, signal.SIGKILL)
    process.wait()
    code = 124
finally:
    selector.close()
with open("/output/run.log", "wb") as stream:
    stream.write(log)
versions = {"engine": engine, "python": sys.version.split()[0]}
if engine == "python":
    versions.update({name: importlib.metadata.version(name) for name in ("numpy", "matplotlib")})
else:
    versions["gnuplot"] = (
        subprocess.check_output(["/usr/bin/gnuplot", "--version"], timeout=2).decode().strip()
    )
with open("/output/runtime.json", "w") as stream:
    json.dump(versions, stream)
# Stream outputs before exit: Docker unmounts the output tmpfs on exit.
status = json.dumps({"exit_code": code}).encode()
with tarfile.open(fileobj=sys.stdout.buffer, mode="w|") as archive:
    entry = tarfile.TarInfo("status.json")
    entry.size = len(status)
    archive.addfile(entry, io.BytesIO(status))
    for name in ("run.log", "runtime.json", "figure.png", "figure.pdf"):
        path = "/output/" + name
        if os.path.lexists(path):
            archive.add(path, arcname=name, recursive=False)
sys.exit(0)
