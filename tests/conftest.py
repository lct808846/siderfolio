"""离线测试禁止真实 HTTP 请求；live 测试需要单独显式启用。"""

import httpx
import pytest
import requests


@pytest.fixture(autouse=True)
def isolate_local_storage(tmp_path, monkeypatch):
    monkeypatch.setenv("ASTROAGENT_DATA_DIR", str(tmp_path / "local-data"))
    monkeypatch.setenv("ASTROAGENT_ALLOWED_HOSTS", '["testserver","127.0.0.1","localhost","[::1]"]')


@pytest.fixture(autouse=True)
def block_external_http(request, monkeypatch):
    if request.node.get_closest_marker("live"):
        return

    def blocked(*args, **kwargs):
        raise AssertionError("Offline tests must not access external HTTP services")

    monkeypatch.setattr(requests.Session, "request", blocked)
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", blocked)
