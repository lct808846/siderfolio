"""离线测试禁止真实 HTTP 请求；live 测试需要单独显式启用。"""

import httpx
import pytest
import requests


@pytest.fixture(autouse=True)
def block_external_http(request, monkeypatch):
    if request.node.get_closest_marker("live"):
        return

    def blocked(*args, **kwargs):
        raise AssertionError("Offline tests must not access external HTTP services")

    monkeypatch.setattr(requests.Session, "request", blocked)
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", blocked)
