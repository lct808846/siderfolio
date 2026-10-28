"""独立启用的 Gaia/真实模型/名称衔接/三工具验收；显式启用后失败不跳过。"""

import json
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from astroagent.config import Settings
from astroagent.gaia import GAIA_TABLE, GaiaService
from astroagent.main import app
from astroagent.schemas import GaiaQuery

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(os.getenv("ASTROAGENT_RUN_LIVE_GAIA") != "1", reason="Gaia live opt-in"),
]
SOURCE_ID = "5853498713190525696"


def save(name, body):
    directory = os.getenv("ASTROAGENT_RECORD_DIR")
    if directory:
        with (Path(directory) / f"{name}.json").open("x", encoding="utf-8") as stream:
            json.dump(body, stream, ensure_ascii=False, indent=2)
            stream.write("\n")


@pytest.fixture
def service():
    return GaiaService(Settings().gaia_timeout_seconds)


def test_live_gaia_exact_id(service):
    result = service.query(GaiaQuery(mode="source_id", source_id=SOURCE_ID, estimate_distance=True))
    save("exact-id", result.model_dump(mode="json"))
    assert result.status == "success", result.model_dump_json()
    assert result.returned_count == 1 and result.data[0].source_id == SOURCE_ID
    assert result.table == GAIA_TABLE and result.release == "Gaia DR3"
    assert result.data[0].ref_epoch == 2016
    assert result.units["parallax"] == "mas" and result.units["pmra"] == "mas/yr"
    assert result.analysis.sample_size == 1
    assert len(result.analysis.distance_estimates) == 1
    assert result.has_more is False and result.total_found is None


@pytest.mark.parametrize("filtered", [False, True])
def test_live_gaia_cone(service, filtered):
    query = GaiaQuery(
        mode="cone",
        ra_deg=56.75,
        dec_deg=24.12,
        radius_arcmin=5,
        limit=3,
        **({"ruwe_max": 1.4, "parallax_snr_min": 10} if filtered else {}),
    )
    result = service.query(query)
    save(f"cone-{filtered}", result.model_dump(mode="json"))
    assert result.status == "success", result.model_dump_json()
    assert 1 <= result.returned_count <= 3 and result.analysis.sample_size == result.returned_count
    assert all(0 <= r.ra < 360 and -90 <= r.dec <= 90 for r in result.data)
    assert all(0 <= r.separation_arcsec <= 300.000001 for r in result.data)
    assert result.analysis.distance_estimates == []
    assert result.query == query.effective_parameters() and result.maxrec == 4
    assert result.total_found is None and result.analysis.scope == "returned_rows"
    if filtered:
        assert result.analysis.quality_filters == {"ruwe_max": 1.4, "parallax_snr_min": 10}
        assert all(r.ruwe <= 1.4 and r.parallax / r.parallax_error >= 10 for r in result.data)


def test_live_gaia_confirm_empty_condition(service):
    # Confirm rather than assuming that a fixed identifier will always be absent.
    attempts = []
    for identifier in ("1", "2", "3"):
        result = service.query(GaiaQuery(mode="source_id", source_id=identifier))
        attempts.append(result.model_dump(mode="json"))
        if result.status != "success":
            break
    save("confirmed-empty", {"attempts": attempts})
    assert result.status == "not_found", result.model_dump_json()
    assert result.error.code == "gaia_not_found" and result.data == []
    assert result.returned_count == 0 and result.analysis is None and result.has_more is False


@pytest.mark.parametrize("kind", ["source", "name", "three-tools"])
def test_live_gaia_model(kind):
    settings = Settings()
    assert settings.deepseek_api_key.get_secret_value().strip(), "DEEPSEEK_API_KEY is required"
    message = (
        f"查询 Gaia DR3 source_id {SOURCE_ID} 的测量信息并估算距离，"
        "说明单位、历元、距离近似条件与未做的校正，给出来源。"
    )
    if kind == "name":
        message = (
            "先通过 SIMBAD 查 M45 的坐标，再查中心附近 5 角分内最近的 3 个 Gaia DR3 源，"
            "总结视场样本自行。说明位置候选、成员和参考历元的限制，给出来源。"
        )
    if kind == "three-tools":
        assert settings.ads_api_token.get_secret_value().strip(), "ADS_API_TOKEN is required"
        message = (
            f"分别完成三项查询并区分来源：SIMBAD 的 M45 坐标，Gaia DR3 source_id "
            f"{SOURCE_ID} 的测量信息，ADS 的 bibcode:2016A&A...595A...2G 文献。"
            "这三项独立，不假定该 Gaia 源是 M45 成员或该文的研究对象。"
        )
    with TestClient(app) as client:
        response = client.post("/api/v1/chat", json={"message": message})
    body = response.json()
    save(f"model-{kind}", {"message": message, "http_status": response.status_code, "body": body})
    assert response.status_code == 200 and body["status"] == "success", body
    assert body["gaia_results"] and all(r["status"] == "success" for r in body["gaia_results"])
    assert any(s["name"] == "Gaia" for s in body["sources"])
    if kind == "source":
        assert body["gaia_results"][0]["data"][0]["source_id"] == SOURCE_ID
        assert body["gaia_results"][0]["analysis"]["estimate_distance"] is True
        assert "近似" in body["answer"] and "零点" in body["answer"]
    if kind == "name":
        assert body["results"] and body["results"][0]["status"] == "success", body
        coordinates = body["results"][0]["data"]
        used = body["gaia_results"][0]["query"]
        assert used["mode"] == "cone"
        assert used["ra_deg"] == pytest.approx(coordinates["ra_deg"], abs=1e-7)
        assert used["dec_deg"] == pytest.approx(coordinates["dec_deg"], abs=1e-7)
        assert "候选" in body["answer"] and "成员" in body["answer"]
        assert "历元" in body["answer"] or "自行传播" in body["answer"]
    if kind == "three-tools":
        assert body["results"] and body["literature_results"]
        assert {s["name"] for s in body["sources"]} == {"SIMBAD", "ADS", "Gaia"}
        assert all(r["status"] == "success" for r in body["results"] + body["literature_results"])
