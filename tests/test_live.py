"""显式启用后访问真实服务；不把模拟数据作为联网验收。"""

import os
from urllib.parse import urlparse

import pytest
from fastapi.testclient import TestClient

from astroagent.main import app
from astroagent.simbad import SIMBAD_SERVERS, SimbadService

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(os.getenv("ASTROAGENT_RUN_LIVE") != "1", reason="live tests are opt-in"),
]


def test_live_simbad_betelgeuse():
    result = SimbadService().query("Betelgeuse")
    assert result.status == "success", result.model_dump_json()
    assert result.data is not None
    assert result.data.main_id
    assert 88 < result.data.ra_deg < 90
    assert 7 < result.data.dec_deg < 8


def test_live_chat_betelgeuse():
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/chat", json={"message": "请查询 Betelgeuse 的坐标和天体类型，并给出数据来源。"}
        )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "success", body
    assert body["results"] and body["sources"]
    assert any(
        result["status"] == "success" and result["data"]["ra_deg"] is not None
        for result in body["results"]
    )
    source = urlparse(body["sources"][0]["url"])
    assert source.hostname in SIMBAD_SERVERS and source.path == "/simbad/sim-id"
