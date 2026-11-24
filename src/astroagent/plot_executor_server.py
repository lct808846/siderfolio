"""Standalone executor. Fixed operations only; never run this HTTP server in the web process."""

import hashlib
import os
import re
import secrets
import signal
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

from astroagent.conversations import encode, utc_now
from astroagent.errors import ServiceError
from astroagent.local_model_client import strict_json
from astroagent.plot_data import table
from astroagent.plot_executor_client import MAX_REQUEST, decoded, encoded
from astroagent.plot_executor_daemon import DockerDesktopSandbox, RootlessDockerSandbox
from astroagent.plot_sandbox import DESKTOP_BOUNDARY, IMAGE, ROOTLESS_BOUNDARY, unavailable

SANDBOXES = {DESKTOP_BOUNDARY: DockerDesktopSandbox, ROOTLESS_BOUNDARY: RootlessDockerSandbox}


class Executor:
    def __init__(self):
        self.boundary = os.getenv("ASTROAGENT_EXECUTOR_DAEMON_BOUNDARY")
        if self.boundary not in SANDBOXES:
            raise ValueError("A supported executor boundary is required")
        self.token = Path("/run/secrets/executor_token").read_text().strip()
        if not re.fullmatch("[0-9a-f]{64}", self.token):
            raise ValueError("Executor credential")
        self.root = Path("/var/lib/astroagent-executor")
        self.root.mkdir(parents=True, exist_ok=True)
        import fcntl

        self.lock_file = (self.root / "service.lock").open("a+")
        fcntl.flock(self.lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        owner_path = self.root / "owner"
        if not owner_path.exists():
            with owner_path.open("x") as stream:
                stream.write(str(uuid4()))
                stream.flush()
                os.fsync(stream.fileno())
        owner = str(UUID(owner_path.read_text().strip()))
        python_image, gnuplot_image = (
            os.environ["ASTROAGENT_PLOT_" + engine.upper() + "_IMAGE"]
            for engine in ("python", "gnuplot")
        )
        if not all(IMAGE.fullmatch(image) for image in (python_image, gnuplot_image)):
            raise ValueError("Pinned protocol 2 images are required")
        settings = SimpleNamespace(
            data_dir=self.root,
            plot_execution_enabled=True,
            plot_python_image=python_image,
            plot_gnuplot_image=gnuplot_image,
            plot_timeout_seconds=30,
            plot_docker_host="unix:///var/run/docker.sock",
        )
        self.sandbox = SANDBOXES[self.boundary](settings, owner)
        self.slot = threading.BoundedSemaphore(1)
        self.records = {}
        paths = list(self.root.glob("*.json"))
        if len(paths) > 1000:
            raise ValueError("Ledger limit")
        for path in paths:
            if path.is_symlink() or path.stat().st_size > 4096:
                raise ValueError("Invalid ledger")
            identifier = str(UUID(path.stem))
            record = strict_json(path.read_text())
            if record["id"] != identifier:
                raise ValueError("Invalid ledger identity")
            self.records[identifier] = record
            if record["state"] == "running" or record.get("cleanup_pending"):
                clean = self.sandbox.cleanup_owned(identifier)
                self.save(
                    identifier, record["request_sha256"], "interrupted", cleanup_pending=not clean
                )

    def save(self, identifier, request_sha256, state, cleanup_pending=False):
        record = {
            "id": identifier,
            "request_sha256": request_sha256,
            "state": state,
            "updated_at": utc_now(),
            "cleanup_pending": cleanup_pending,
        }
        target = self.root / (identifier + ".json")
        temporary = self.root / (identifier + ".tmp")
        with temporary.open("w", encoding="utf-8") as stream:
            stream.write(encode(record))
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(target)
        directory = os.open(self.root, os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
        self.records[identifier] = record

    def retry_cleanup(self):
        for identifier, record in list(self.records.items()):
            if record.get("cleanup_pending"):
                if not self.sandbox.cleanup_owned(identifier):
                    raise unavailable()
                self.save(identifier, record["request_sha256"], "interrupted")

    def status(self):
        if not self.slot.acquire(blocking=False):
            raise ServiceError(409, "plot_executor_busy", "绘图执行器正在处理任务。")
        try:
            self.retry_cleanup()
            images = {}
            for engine in ("python", "gnuplot"):
                reference, identifier = self.sandbox.admit(engine)
                images[engine] = {"reference": reference, "id": identifier}
            return {"ready": True, "images": images, "isolation": self.boundary}
        finally:
            self.slot.release()

    def run(self, identifier, payload):
        if set(payload) != {"engine", "script", "data_base64", "script_sha256", "data_sha256"}:
            raise ValueError("Unexpected fields")
        engine, script = payload["engine"], payload["script"]
        if (
            engine not in ("python", "gnuplot")
            or not isinstance(script, str)
            or not 1 <= len(script) <= 24000
            or "\x00" in script
        ):
            raise ValueError("Invalid script")
        data = decoded(payload["data_base64"], 5 * 1024**2)
        if (
            payload["script_sha256"] != hashlib.sha256(script.encode()).hexdigest()
            or payload["data_sha256"] != hashlib.sha256(data).hexdigest()
        ):
            raise ValueError("Input digest")
        table(data, "data.csv")
        if not self.slot.acquire(blocking=False):
            raise ServiceError(409, "plot_executor_busy", "已有绘图任务，请稍后手动提交。")
        recorded = False
        request_hash = hashlib.sha256(encode(payload).encode()).hexdigest()
        try:
            self.retry_cleanup()
            if identifier in self.records:
                raise ServiceError(409, "plot_executor_duplicate", "该编号已记录，不会重复执行。")
            if len(self.records) >= 1000:
                raise unavailable()
            self.save(identifier, request_hash, "running", cleanup_pending=True)
            recorded = True
            self.sandbox.deadline = time.monotonic() + 60
            admitted = self.sandbox.admit(engine)
            files, runtime = self.sandbox.run(
                {"engine": engine, "script": script}, data, identifier, admitted
            )
            runtime["isolation"] = self.boundary
            if not self.sandbox.cleanup_owned(identifier):
                raise unavailable()
            self.save(identifier, request_hash, "completed")
            return {
                "run_id": identifier,
                "runtime": runtime,
                "files": {
                    name: {"base64": encoded(raw), "sha256": hashlib.sha256(raw).hexdigest()}
                    for name, raw in files.items()
                },
            }
        except BaseException:
            if recorded:
                clean = self.sandbox.cleanup_owned(identifier)
                self.save(identifier, request_hash, "failed", cleanup_pending=not clean)
            raise
        finally:
            self.sandbox.deadline = None
            self.slot.release()

    def cleanup(self, identifier):
        if not self.slot.acquire(blocking=False):
            raise ServiceError(409, "plot_executor_busy", "任务正在运行，不会在运行中清理。")
        try:
            if identifier in self.records:
                record = self.records[identifier]
                clean = self.sandbox.cleanup_owned(identifier)
                self.save(
                    identifier,
                    record["request_sha256"],
                    "interrupted" if record["state"] == "running" else record["state"],
                    cleanup_pending=not clean,
                )
                if not clean:
                    raise unavailable()
            return {"run_id": identifier}
        finally:
            self.slot.release()


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass  # No request bodies, Authorization values or generated scripts in access logs.

    def reply(self, status, value):
        raw = encode({"protocol": 1, **value}).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(raw)

    def handle_operation(self):
        try:
            self.connection.settimeout(5)
            if (
                self.path == "/health"
                and self.command == "GET"
                and self.client_address[0] in ("127.0.0.1", "::1")
            ):
                return self.reply(200, {"alive": True})
            if (
                self.headers.get("Host") != "plot-executor:8090"
                or len(self.headers.get_all("Authorization", [])) != 1
                or not secrets.compare_digest(
                    self.headers.get("Authorization", ""), "Bearer " + self.server.executor.token
                )
            ):
                return self.reply(403, {"error": {"code": "executor_forbidden"}})
            if self.path == "/v1/status" and self.command == "GET":
                return self.reply(200, self.server.executor.status())
            match = re.fullmatch(r"/v1/runs/([0-9a-f-]{36})", self.path)
            if not match or self.command not in ("POST", "DELETE"):
                return self.reply(404, {"error": {"code": "executor_not_found"}})
            identifier = str(UUID(match[1]))
            if (
                self.headers.get("Transfer-Encoding")
                or self.headers.get("Content-Encoding", "identity") != "identity"
                or self.headers.get("Content-Type") != "application/json"
                or len(self.headers.get_all("Content-Length", [])) != 1
            ):
                raise ValueError("Invalid content transport")
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= MAX_REQUEST:
                return self.reply(413, {"error": {"code": "executor_input_limit"}})
            content, deadline = bytearray(), time.monotonic() + 15
            while len(content) < length:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError()
                self.connection.settimeout(min(remaining, 5))
                chunk = self.rfile.read1(min(65536, length - len(content)))
                if not chunk:
                    raise ValueError("Incomplete request")
                content.extend(chunk)
            payload = strict_json(content.decode())
            if not isinstance(payload, dict):
                raise ValueError("Object required")
            if self.command == "DELETE":
                if payload:
                    raise ValueError("No cleanup parameters")
                value = self.server.executor.cleanup(identifier)
            else:
                value = self.server.executor.run(identifier, payload)
            self.reply(200, value)
        except ServiceError as exc:
            self.reply(exc.status_code, {"error": {"code": exc.error.code}})
        except (ValueError, TypeError, KeyError, RecursionError, UnicodeError):
            self.reply(422, {"error": {"code": "executor_input_invalid"}})
        except Exception:
            self.reply(503, {"error": {"code": "plot_sandbox_unavailable"}})

    do_GET = do_POST = do_DELETE = handle_operation


class Server(ThreadingHTTPServer):
    # On shutdown, wait for bounded active jobs to finish or reach their deadline.
    daemon_threads = False
    request_queue_size = 8

    def handle_error(self, request, client_address):
        # A disconnected client must not cause a traceback or request content in logs.
        pass

    def __init__(self, executor):
        self.executor = executor
        self.connections = threading.BoundedSemaphore(8)
        super().__init__(("0.0.0.0", 8090), Handler)

    def get_request(self):
        connection, address = super().get_request()
        connection.settimeout(5)
        return connection, address

    def process_request(self, request, client_address):
        if not self.connections.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self.connections.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.connections.release()


def main():
    try:
        import argparse

        parser = argparse.ArgumentParser()
        parser.add_argument("--clear-terminal-ledger", action="store_true")
        parser.add_argument("--confirm-clear-request-identifiers", action="store_true")
        args = parser.parse_args()
        executor = Executor()
        if args.clear_terminal_ledger:
            if not args.confirm_clear_request_identifiers:
                raise ValueError("Explicit confirmation is required")
            executor.retry_cleanup()
            for identifier, record in executor.records.items():
                if record["state"] != "running" and not record.get("cleanup_pending"):
                    (executor.root / (identifier + ".json")).unlink()
            print(
                "Cleared terminal executor identifiers; applic"
                "ation history and model/data files were retai"
                "ned."
            )
            return
        with Server(executor) as server:
            previous = signal.signal(
                signal.SIGTERM,
                lambda *_: threading.Thread(target=server.shutdown, daemon=True).start(),
            )
            try:
                server.serve_forever(poll_interval=0.25)
            finally:
                signal.signal(signal.SIGTERM, previous)
    except Exception:
        raise SystemExit(
            "Executor configuration is unavailable; no host execution fallback."
        ) from None


if __name__ == "__main__":
    main()
