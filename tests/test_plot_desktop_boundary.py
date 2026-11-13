"""Security checks for the Docker Desktop plotting broker."""

import http.client
import json
import subprocess
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from astroagent.errors import ServiceError
from astroagent.plot_executor_client import ExecutorClient
from astroagent.plot_executor_daemon import DockerDesktopSandbox
from astroagent.plot_executor_server import Executor, Handler


def test_socket_only_mounted_in_unpublished_internal_broker():
    root = Path(__file__).resolve().parents[1]
    base = yaml.safe_load((root / "compose.yaml").read_text(encoding="utf-8"))
    overlay = yaml.safe_load((root / "compose.plotting.yaml").read_text(encoding="utf-8"))
    broker = overlay["services"]["plot-executor"]
    assert "ports" not in broker and broker["networks"] == ["execution"]
    assert overlay["networks"]["execution"]["internal"] is True
    ingress = base["services"]["ingress"]
    assert ingress["ports"] == ["127.0.0.1:5173:5173"]
    assert "secrets" not in ingress and "docker.sock" not in str(ingress)
    assert "web" not in ingress["networks"] and "edge" in ingress["networks"]
    assert base["networks"]["edge"]["internal"] is True
    assert "ports" not in base["services"]["frontend"]
    mounts = broker["volumes"]
    socket = [
        m for m in mounts if isinstance(m, dict) and m.get("target") == "/var/run/docker.sock"
    ]
    assert len(socket) == 1 and socket[0]["source"] == "/var/run/docker.sock"
    assert all(
        "docker.sock" not in str(base["services"][name].get("volumes", []))
        for name in ("backend", "frontend")
    )
    assert all(
        "docker.sock" not in str(v) for v in overlay["services"]["backend"].get("volumes", [])
    )


def test_untrusted_request_cannot_supply_docker_parameters():
    executor = object.__new__(Executor)
    executor.slot = threading.BoundedSemaphore(1)
    executor.sandbox = SimpleNamespace()
    with pytest.raises(ValueError, match="Unexpected fields"):
        executor.run(
            "00000000-0000-4000-8000-000000000001",
            {
                "engine": "python",
                "script": "pass",
                "data_base64": "",
                "script_sha256": "",
                "data_sha256": "",
                "mount": "/:/host",
            },
        )


def test_broker_cli_does_not_inherit_model_or_database_secrets(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "synthetic-secret")
    monkeypatch.setenv("ASTROAGENT_DATABASE_URL", "synthetic-database")
    monkeypatch.setattr("astroagent.plot_sandbox.shutil.which", lambda _: "/usr/bin/docker")
    calls = []

    def run(args, **kwargs):
        calls.append((args, kwargs))
        return SimpleNamespace(
            returncode=0, stdout=json.dumps({"OperatingSystem": "Docker Desktop"}).encode()
        )

    monkeypatch.setattr(subprocess, "run", run)
    broker = DockerDesktopSandbox(SimpleNamespace(), "owner")
    broker.call("info", "--format", "{{json .}}")
    args, kwargs = calls[0]
    assert args[:3] == ["/usr/bin/docker", "--host", "unix:///var/run/docker.sock"]
    assert "DEEPSEEK_API_KEY" not in kwargs["env"]
    assert "ASTROAGENT_DATABASE_URL" not in kwargs["env"]


def test_non_desktop_daemon_is_rejected(monkeypatch):
    broker = DockerDesktopSandbox(SimpleNamespace(), "owner")
    monkeypatch.setattr(broker, "call", lambda *args, **kwargs: b'{"OperatingSystem":"Ubuntu"}')
    with pytest.raises(ServiceError) as exc:
        broker.admit("python")
    assert exc.value.error.code == "plot_sandbox_unavailable"


def test_client_reads_authenticated_status_from_internal_server(monkeypatch):
    token = "a" * 64
    python_id, gnuplot_id = "sha256:" + "b" * 64, "sha256:" + "c" * 64
    images = {
        "python": {"reference": python_id, "id": python_id},
        "gnuplot": {"reference": gnuplot_id, "id": gnuplot_id},
    }
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.executor = SimpleNamespace(token=token, status=lambda: {"ready": True, "images": images})
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    connection = http.client.HTTPConnection
    monkeypatch.setattr(
        "astroagent.plot_executor_client.http.client.HTTPConnection",
        lambda _host, _port, **kwargs: connection("127.0.0.1", server.server_port, **kwargs),
    )
    settings = SimpleNamespace(
        plot_execution_enabled=True,
        plot_python_image=python_id,
        plot_gnuplot_image=gnuplot_id,
        plot_executor_token=SimpleNamespace(get_secret_value=lambda: token),
        plot_executor_url="http://plot-executor:8090",
        plot_timeout_seconds=30,
    )
    try:
        assert ExecutorClient(settings).probe() == images
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
