from astroagent.agent import ADS_TOOL, SIMBAD_TOOL, create_model
from astroagent.config import Settings


def test_dotenv_loads_without_overriding_environment(tmp_path, monkeypatch):
    path = tmp_path / ".env"
    path.write_text("DEEPSEEK_API_KEY=file-key\nDEEPSEEK_MODEL=file-model\n", encoding="utf-8")
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setenv("DEEPSEEK_MODEL", "environment-model")
    settings = Settings(_env_file=path)
    assert settings.deepseek_api_key.get_secret_value() == "file-key"
    assert settings.deepseek_model == "environment-model"
    assert "file-key" not in repr(settings)


def test_model_has_timeout_no_retries_and_registered_tool(monkeypatch):
    captured = {}

    class Model:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        def bind_tools(self, tools):
            captured["tools"] = tools
            return self

    monkeypatch.setattr("astroagent.agent.ChatOpenAI", Model)
    settings = Settings(_env_file=None, deepseek_api_key="test-key", llm_timeout_seconds=9)
    create_model(settings)
    assert captured["api_key"] == "test-key"
    assert captured["base_url"] == str(settings.deepseek_base_url)
    assert captured["timeout"] == 9
    assert captured["max_retries"] == 0
    assert captured["extra_body"] == {"thinking": {"type": "disabled"}}
    assert captured["tools"] == [SIMBAD_TOOL, ADS_TOOL]
