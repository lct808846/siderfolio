"""健康检查及 API 文档的基本验收。"""

from fastapi.testclient import TestClient

from astroagent.main import app


def test_health_without_deepseek_key(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)

    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    assert response.json() == {"status": "ok"}


def test_swagger_ui_is_disabled_in_v16():
    with TestClient(app) as client:
        response = client.get("/docs")

    assert response.status_code == 404
    assert "application/json" in response.headers["content-type"]


def test_health_is_documented_in_openapi():
    schema = app.openapi()
    assert schema["info"]["title"] == "AstroAgent"
    assert "200" in schema["paths"]["/health"]["get"]["responses"]
