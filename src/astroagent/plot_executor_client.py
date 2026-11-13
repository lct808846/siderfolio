"""Restricted authenticated transport; a web process never receives Docker access."""

import base64
import hashlib
import http.client
import json
import time
from uuid import UUID

from astroagent.errors import ServiceError
from astroagent.local_model_client import strict_json
from astroagent.plot_sandbox import IMAGE, MAX_OUTPUT, configured, unavailable

MAX_REQUEST = 8 * 1024**2
MAX_RESPONSE = 24 * 1024**2


def encoded(value):
    return base64.b64encode(value).decode("ascii")


def decoded(value, maximum):
    if not isinstance(value, str) or len(value) > (maximum + 2) // 3 * 4:
        raise ValueError("Payload size")
    raw = base64.b64decode(value, validate=True)
    if len(raw) > maximum:
        raise ValueError("Payload size")
    return raw


class ExecutorClient:
    def __init__(self, settings):
        self.settings = settings
        self.available = bool(
            configured(settings) and len(settings.plot_executor_token.get_secret_value()) == 64
        )

    def request(self, path, body=None, method=None, timeout=None):
        if not self.available or self.settings.plot_executor_url != "http://plot-executor:8090":
            raise unavailable()
        connection = http.client.HTTPConnection("plot-executor", 8090, timeout=2)
        deadline = time.monotonic() + (timeout or self.settings.plot_timeout_seconds + 35)
        try:
            raw = None if body is None else json.dumps(body, ensure_ascii=False).encode()
            if raw is not None and len(raw) > MAX_REQUEST:
                raise ValueError("Request limit")
            connection.connect()
            sock = connection.sock
            sock.settimeout(max(0.01, deadline - time.monotonic()))
            connection.request(
                method or ("GET" if raw is None else "POST"),
                path,
                body=raw,
                headers={
                    "Host": "plot-executor:8090",
                    "Authorization": "Bearer "
                    + self.settings.plot_executor_token.get_secret_value(),
                    "Content-Type": "application/json",
                    "Accept-Encoding": "identity",
                },
            )
            sock.settimeout(max(0.01, deadline - time.monotonic()))
            response = connection.getresponse()
            if response.getheader("Content-Encoding", "identity") != "identity":
                raise ValueError("Compressed output")
            content = bytearray()
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError()
                sock.settimeout(remaining)
                chunk = response.read1(min(65536, MAX_RESPONSE + 1 - len(content)))
                if not chunk:
                    break
                content.extend(chunk)
                if len(content) > MAX_RESPONSE:
                    raise ValueError("Response limit")
            value = strict_json(content.decode())
            if response.status != 200:
                error = value.get("error", {})
                allowed = {
                    "plot_script_failed": 422,
                    "plot_execution_timeout": 504,
                    "plot_output_invalid": 422,
                    "plot_executor_busy": 409,
                    "plot_executor_duplicate": 409,
                }
                code = error.get("code")
                if code in allowed:
                    raise ServiceError(
                        allowed[code], code, "独立绘图任务未完成，请核对原运行记录；不会自动重试。"
                    )
                raise unavailable()
            if value.get("protocol") != 1:
                raise ValueError("Protocol mismatch")
            return value
        except ServiceError:
            raise
        except Exception as exc:
            raise unavailable() from exc
        finally:
            connection.close()

    def admit(self, engine):
        images = self.probe()
        return getattr(self.settings, f"plot_{engine}_image"), images[engine]["id"]

    def probe(self):
        value = self.request("/v1/status", timeout=5)
        images = value.get("images", {})
        for engine in ("python", "gnuplot"):
            image = images.get(engine, {})
            if (
                value.get("ready") is not True
                or image.get("reference") != getattr(self.settings, f"plot_{engine}_image")
                or not IMAGE.fullmatch(image.get("id", ""))
            ):
                raise unavailable()
        return images

    def run(self, proposal, data, run_id, admitted):
        identifier = str(UUID(run_id))
        script = proposal["script"]
        body = {
            "engine": proposal["engine"],
            "script": script,
            "data_base64": encoded(data),
            "script_sha256": hashlib.sha256(script.encode()).hexdigest(),
            "data_sha256": hashlib.sha256(data).hexdigest(),
        }
        value = self.request("/v1/runs/" + identifier, body)
        files = value.get("files", {})
        if set(files) != {"figure.png", "figure.pdf"} or value.get("run_id") != identifier:
            raise unavailable()
        output = {}
        for name, item in files.items():
            raw = decoded(item["base64"], MAX_OUTPUT)
            if hashlib.sha256(raw).hexdigest() != item["sha256"]:
                raise unavailable()
            output[name] = raw
        runtime = value.get("runtime", {})
        if (
            runtime.get("image_id") != admitted[1]
            or runtime.get("network") != "none"
            or runtime.get("isolation") != "docker-desktop-wsl2-v1"
        ):
            raise unavailable()
        return output, runtime

    def cleanup_interrupted(self, ids):
        # Executor owns its durable ledger and cleanup. A web restart must neither wait
        # for an unavailable executor nor cancel/replay a live independent job.
        return None
