"""三工具结果分流、预算、降级、完整 API 与有限模型视图。"""

import json

import pytest
from fastapi.testclient import TestClient
from gaia_fixtures import SOURCE_ID, execute, source_row, votable
from langchain_core.messages import AIMessage, ToolMessage
from pydantic import ValidationError
from test_chat import ScriptedModel, StubSimbad, query_reply, result
from test_literature_chat import StubAds, ads_call, literature

from astroagent.agent import SYSTEM_PROMPT, AstroAgent
from astroagent.api.chat import get_agent
from astroagent.config import Settings
from astroagent.main import app
from astroagent.schemas import GaiaQuery


class StubGaia:
    def __init__(self, *results):
        self.results = iter(results)
        self.queries = []

    def query(self, arguments):
        self.queries.append(arguments)
        return next(self.results)


def gaia_call(id="gaia-1", **arguments):
    return {
        "name": "query_gaia",
        "id": id,
        "args": {
            "mode": "source_id",
            "source_id": SOURCE_ID,
            **arguments,
        },
    }


def found(status="success"):
    return execute(
        votable([]) if status == "not_found" else b"bad" if status == "error" else votable()
    )[0]


def run(model, simbad=None, ads=None, gaia=None, **settings):
    agent = AstroAgent(
        model,
        simbad or StubSimbad(),
        Settings(_env_file=None, **settings),
        ads or StubAds(),
        gaia or StubGaia(),
    )
    app.dependency_overrides[get_agent] = lambda: agent
    try:
        with TestClient(app) as client:
            return client.post("/api/v1/chat", json={"message": "查询"})
    finally:
        app.dependency_overrides.clear()


def test_full_sample_retained_but_only_first_ten_sent_to_model():
    query = GaiaQuery(
        mode="cone", ra_deg=56.75, dec_deg=24.12, radius_arcmin=5, limit=20, estimate_distance=True
    )
    rows = [
        source_row(source_id=str(int(SOURCE_ID) + i), separation_deg=i * 0.001) for i in range(21)
    ]
    full = execute(votable(rows, cone=True), query=query)[0]
    assert full.status == "success"
    call = {"name": "query_gaia", "id": "g", "args": query.effective_parameters()}
    model = ScriptedModel(AIMessage(content="", tool_calls=[call]), AIMessage(content="位置候选源"))
    gaia = StubGaia(full)
    response = run(model, gaia=gaia)
    body = response.json()
    assert response.status_code == 200 and body["status"] == "success"
    assert body["results"] == body["literature_results"] == []
    api_result = body["gaia_results"][0]
    assert len(api_result["data"]) == len(api_result["analysis"]["distance_estimates"]) == 20
    tool = model.messages[1][-1]
    assert isinstance(tool, ToolMessage) and tool.name == "query_gaia" and tool.tool_call_id == "g"
    view = json.loads(tool.content)
    assert view["rows_shown_to_model"] == view["rows_omitted_from_model"] == 10
    assert len(view["data"]) == len(view["analysis"]["distance_estimates"]) == 10
    assert view["analysis"]["sample_size"] == view["analysis"]["distance_computed_count"] == 20
    assert view["analysis"]["statistics"] == api_result["analysis"]["statistics"]
    assert view["warnings"] == api_result["warnings"] and view["truncated"]
    assert gaia.queries == [query]


@pytest.mark.parametrize(
    "s_status,a_status,g_status,expected",
    [
        ("success", "success", "success", "success"),
        ("error", "success", "success", "partial"),
        ("success", "error", "success", "partial"),
        ("success", "success", "error", "partial"),
        ("not_found", "error", "not_found", "error"),
        ("error", "error", "error", "error"),
    ],
)
def test_three_tool_results_and_sources(s_status, a_status, g_status, expected):
    calls = [gaia_call(), *query_reply("test").tool_calls, ads_call()]
    model = ScriptedModel(AIMessage(content="", tool_calls=calls), AIMessage(content="已查询"))
    body = run(
        model,
        StubSimbad(result(status=s_status)),
        StubAds(literature(a_status)),
        StubGaia(found(g_status)),
    ).json()
    assert body["status"] == expected
    assert len(body["results"]) == len(body["literature_results"]) == len(body["gaia_results"]) == 1
    assert body["results"][0]["status"] == s_status
    assert body["literature_results"][0]["status"] == a_status
    assert body["gaia_results"][0]["status"] == g_status
    assert [s["name"] for s in body["sources"]] == [
        name
        for name, status in [("Gaia", g_status), ("SIMBAD", s_status), ("ADS", a_status)]
        if status == "success"
    ]
    assert [m.tool_call_id for m in model.messages[1][-3:]] == ["gaia-1", "call_0", "ads-1"]


@pytest.mark.parametrize(
    "final",
    [
        TimeoutError(),
        AIMessage(content=" "),
        AIMessage(content="", tool_calls=[gaia_call("g2")]),
        AIMessage(content="", tool_calls=[{"name": "shell", "id": "bad", "args": {}}]),
    ],
)
def test_model_failure_or_limit_retains_all_three_results(final):
    calls = [*query_reply("test").tool_calls, ads_call(), gaia_call()]
    model = ScriptedModel(AIMessage(content="", tool_calls=calls), final)
    body = run(
        model,
        StubSimbad(result()),
        StubAds(literature()),
        StubGaia(found()),
        agent_max_tool_calls=3,
    ).json()
    assert body["status"] == "partial" and body["warnings"]
    assert len(body["results"]) == len(body["literature_results"]) == len(body["gaia_results"]) == 1
    assert "gaia_results" in body["answer"]


def test_gaia_sources_deduplicate_keep_first_success():
    failed, first, second = found("error"), found(), found()
    model = ScriptedModel(
        AIMessage(content="", tool_calls=[gaia_call("g1"), gaia_call("g2"), gaia_call("g3")]),
        AIMessage(content="完成"),
    )
    body = run(model, gaia=StubGaia(failed, first, second)).json()
    assert body["status"] == "partial" and len(body["gaia_results"]) == 3
    assert body["sources"] == [first.source.model_dump(mode="json")]


@pytest.mark.parametrize(
    "bad",
    [
        gaia_call(limit=20),
        gaia_call(source_id=1),
        gaia_call(id="ads-1"),
        gaia_call(adql="DROP TABLE"),
    ],
)
def test_mixed_batch_invalid_gaia_cannot_execute_other_tools(bad):
    simbad, ads, gaia = StubSimbad(), StubAds(), StubGaia()
    model = ScriptedModel(AIMessage(content="", tool_calls=[ads_call(), bad]))
    response = run(model, simbad, ads, gaia)
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "model_invalid_tool_call"
    assert not simbad.names and not ads.queries and not gaia.queries


def test_three_tools_share_budget_before_execution():
    simbad, ads, gaia = StubSimbad(), StubAds(), StubGaia()
    model = ScriptedModel(
        AIMessage(content="", tool_calls=[*query_reply("test").tool_calls, ads_call(), gaia_call()])
    )
    response = run(model, simbad, ads, gaia, agent_max_tool_calls=2)
    assert response.json()["error"]["code"] == "agent_limit_reached"
    assert not simbad.names and not ads.queries and not gaia.queries


def test_name_chain_uses_separate_simbad_result_and_two_calls():
    simbad_result = result("M45")
    arguments = {
        "mode": "cone",
        "ra_deg": simbad_result.data.ra_deg,
        "dec_deg": simbad_result.data.dec_deg,
        "radius_arcmin": 5,
    }
    call = {"name": "query_gaia", "id": "g", "args": arguments}
    model = ScriptedModel(
        query_reply("M45"),
        AIMessage(content="", tool_calls=[call]),
        AIMessage(content="位置候选源，未进行自行传播"),
    )
    gaia = StubGaia(found())
    body = run(model, StubSimbad(simbad_result), gaia=gaia).json()
    assert body["status"] == "success" and len(model.messages) == 3
    assert gaia.queries[0].ra_deg == simbad_result.data.ra_deg
    assert gaia.queries[0].dec_deg == simbad_result.data.dec_deg
    assert "SIMBAD 失败或缺少坐标则停止" in SYSTEM_PROMPT
    assert "最近或唯一行" in SYSTEM_PROMPT and "未校正视差零点" in SYSTEM_PROMPT


def test_missing_ads_token_does_not_break_gaia():
    model = ScriptedModel(
        AIMessage(content="", tool_calls=[gaia_call()]), AIMessage(content="完成")
    )
    body = run(model, gaia=StubGaia(found()), ads_api_token="").json()
    assert body["status"] == "success" and not body["literature_results"]


def test_initialization_and_openapi_do_not_access_databases(monkeypatch):
    # block_external_http also rejects any implicit constructor or metadata request.
    monkeypatch.setenv("GAIA_TIMEOUT_SECONDS", "8")
    agent = get_agent()
    assert agent.gaia.timeout == 8
    with TestClient(app) as client:
        assert client.get("/health").json() == {"status": "ok"}
        schema = client.get("/openapi.json").json()
        assert schema["info"]["version"] == "0.3.0"
        assert "gaia_results" in schema["components"]["schemas"]["ChatResponse"]["properties"]
        monkeypatch.setenv("GAIA_TIMEOUT_SECONDS", "private-invalid")
        response = client.post("/api/v1/chat", json={"message": "Gaia"})
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "invalid_configuration"
        assert "private-invalid" not in response.text
        assert client.get("/health").status_code == 200


@pytest.mark.parametrize("value", [0, -1, 121, "bad", "nan", "inf"])
def test_invalid_gaia_timeout(value):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, gaia_timeout_seconds=value)
