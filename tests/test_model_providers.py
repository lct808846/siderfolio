"""Offline protocol, credential and destination acceptance with synthetic inputs."""

import json
from types import SimpleNamespace

import httpx
import pytest
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from pydantic import ValidationError

from astroagent.config import Settings
from astroagent.errors import ServiceError
from astroagent.model_client import ProtocolModel, chat_model
from astroagent.model_providers import (
    ProviderInput,
    ProviderRegistry,
    directory_address_allowed,
    provider_url,
)


def draft(**values):
    return ProviderInput(
        **{
            "revision": 0,
            "id": "synthetic",
            "name": "Synthetic provider",
            "base_url": "https://models.example.org/v1",
            "api_key": "synthetic-not-a-credential",
            "models": [{"id": "synthetic-model", "label": "Synthetic"}],
            **values,
        }
    )


def registry():
    return ProviderRegistry(
        SimpleNamespace(settings=SimpleNamespace(local_http=False)),
        Settings(_env_file=None, deepseek_api_key="synthetic-system-key"),
    )


@pytest.mark.parametrize(
    "url",
    [
        "http://api.example.org",
        "https://localhost",
        "https://127.0.0.1",
        "https://10.0.0.1",
        "https://[::1]",
        "https://169.254.169.254",
        "https://host.docker.internal",
        "https://service.internal",
        "https://a.local",
        "https://user:pass@example.org",
        "https://example.org?key=synthetic",
        "https://example.org/#key",
        "https://example.org/white space",
    ],
)
def test_provider_rejects_private_or_credential_urls(url):
    with pytest.raises(ValueError):
        provider_url(url)


@pytest.mark.parametrize(
    "address",
    ["127.0.0.1", "::1", "10.1.2.3", "169.254.169.254", "::ffff:127.0.0.1", "224.0.0.1", "0.0.0.0"],
)
def test_directory_rejects_local_dns_even_in_local_deployment(address):
    assert not directory_address_allowed(address, local_proxy=True)


def test_proxy_dns_exception_is_explicit_and_limited():
    assert directory_address_allowed("8.8.8.8")
    assert not directory_address_allowed("198.18.0.1")
    assert directory_address_allowed("198.18.0.1", local_proxy=True)
    assert not directory_address_allowed("192.168.1.1", local_proxy=True)


def test_provider_secret_retention_requires_same_endpoint_and_protocol():
    service = registry()
    value = {"providers": [service.provider(draft(), {"providers": []})]}
    retained = service.provider(draft(api_key=None, name="Renamed"), value)
    assert retained["api_key"] == "synthetic-not-a-credential"
    for change in [{"base_url": "https://other.example.org/v1"}, {"protocol": "gemini"}]:
        with pytest.raises(ServiceError) as error:
            service.provider(draft(api_key=None, **change), value)
        assert error.value.error.code == "provider_key_required"
    with pytest.raises(ValidationError):
        draft(api_key="synthetic\nkey")
    with pytest.raises(ValidationError):
        draft(models=[{"id": "duplicate", "label": "A"}, {"id": "duplicate", "label": "B"}])


def test_catalog_hides_keys_and_resolves_selected_provider(monkeypatch):
    service = registry()
    value = {
        "revision": 2,
        "default_model": "missing",
        "providers": [service.provider(draft(protocol="gemini"), {"providers": []})],
    }
    public = service.public(value)
    assert "synthetic-not-a-credential" not in json.dumps(public)
    assert "api_key" not in public["providers"][0]
    selection = public["default_model"]
    monkeypatch.setattr(service, "read", lambda: value)
    resolved = service.resolve(selection)
    assert resolved.deepseek_model == "synthetic-model"
    assert resolved.model_protocol == "gemini"
    assert resolved.selected_model_id == selection
    assert resolved.non_thinking_body() == {}
    with pytest.raises(ServiceError):
        service.resolve("not-enabled")
    value["providers"][0]["enabled"] = False
    with pytest.raises(ServiceError) as error:
        service.resolve(None)
    assert error.value.error.code == "model_not_configured"


def install_upstream(monkeypatch, handler):
    original = httpx.Client
    monkeypatch.setattr(
        "astroagent.model_client.httpx.Client",
        lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs),
    )


@pytest.mark.parametrize("protocol", ["openai_responses", "anthropic", "gemini"])
def test_protocol_text_tool_roundtrip_preserves_opaque_state(monkeypatch, protocol):
    requests = []

    def handler(request):
        body = json.loads(request.content)
        requests.append(body)
        assert "synthetic-key" not in str(request.url)
        if protocol == "anthropic":
            assert request.headers["x-api-key"] == "synthetic-key"
            return httpx.Response(
                200,
                json={
                    "model": "synthetic-model",
                    "stop_reason": "tool_use",
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "call-1",
                            "name": "lookup",
                            "input": {"name": "Vega"},
                        }
                    ],
                },
            )
        if protocol == "gemini":
            assert request.headers["x-goog-api-key"] == "synthetic-key"
            return httpx.Response(
                200,
                json={
                    "candidates": [
                        {
                            "finishReason": "STOP",
                            "content": {
                                "parts": [
                                    {
                                        "thoughtSignature": "synthetic-opaque",
                                        "functionCall": {
                                            "id": "call-1",
                                            "name": "lookup",
                                            "args": {"name": "Vega"},
                                        },
                                    }
                                ]
                            },
                        }
                    ]
                },
            )
        assert request.headers["authorization"] == "Bearer synthetic-key"
        return httpx.Response(
            200,
            json={
                "status": "completed",
                "output": [
                    {"type": "reasoning", "encrypted_content": "synthetic-opaque"},
                    {
                        "type": "function_call",
                        "call_id": "call-1",
                        "name": "lookup",
                        "arguments": '{"name":"Vega"}',
                    },
                ],
            },
        )

    install_upstream(monkeypatch, handler)
    model = ProtocolModel(
        Settings(
            _env_file=None,
            model_protocol=protocol,
            deepseek_api_key="synthetic-key",
            deepseek_model="synthetic-model",
            deepseek_base_url="https://models.example.org/v1",
        ),
        [],
        1500,
        False,
        True,
    )
    messages = [SystemMessage(content="Synthetic instruction"), HumanMessage(content="Vega")]
    answer = model.invoke(messages)
    assert answer.tool_calls[0]["args"] == {"name": "Vega"}
    assert answer.tool_calls[0]["id"] == "call-1"
    followup = getattr(model, protocol + "_request")(
        [
            *messages,
            answer,
            ToolMessage(content='{"found":true}', tool_call_id="call-1", name="lookup"),
        ]
    )[1]
    assert "found" in json.dumps(followup)
    if protocol != "anthropic":
        assert "synthetic-opaque" in json.dumps(followup)
    assert len(requests) == 1


@pytest.mark.parametrize("protocol", ["openai_responses", "anthropic", "gemini"])
@pytest.mark.parametrize(
    "status,code",
    [
        (401, "model_authentication_failed"),
        (404, "model_not_found"),
        (429, "model_rate_limited"),
        (500, "model_unavailable"),
    ],
)
def test_protocol_upstream_errors_are_bounded_and_redacted(monkeypatch, protocol, status, code):
    install_upstream(
        monkeypatch,
        lambda request: httpx.Response(
            status, json={"error": {"message": "synthetic-private-key upstream trace"}}
        ),
    )
    model = chat_model(
        Settings(_env_file=None, model_protocol=protocol, deepseek_api_key="synthetic-key")
    )
    with pytest.raises(ServiceError) as error:
        model.invoke([HumanMessage(content="Synthetic")])
    assert error.value.error.code == code
    assert "synthetic-private-key" not in str(error.value.error)


@pytest.mark.parametrize(
    "protocol,payload",
    [
        ("openai_responses", {"status": "incomplete", "output": []}),
        ("anthropic", {"stop_reason": "max_tokens", "content": []}),
        ("gemini", {"candidates": [{"finishReason": "MAX_TOKENS", "content": {"parts": []}}]}),
    ],
)
def test_incomplete_answers_never_execute_partial_tools(monkeypatch, protocol, payload):
    install_upstream(monkeypatch, lambda request: httpx.Response(200, json=payload))
    model = chat_model(
        Settings(_env_file=None, model_protocol=protocol, deepseek_api_key="synthetic-key")
    )
    with pytest.raises(ServiceError) as error:
        model.invoke([HumanMessage(content="Synthetic")])
    assert error.value.error.code == "model_incomplete_response"


def test_gemini_billing_error_is_specific_without_raw_upstream_text(monkeypatch):
    install_upstream(
        monkeypatch,
        lambda request: httpx.Response(
            402, json={"error": {"message": "Prepayment credits depleted synthetic-private-key"}}
        ),
    )
    with pytest.raises(ServiceError) as error:
        chat_model(
            Settings(_env_file=None, model_protocol="gemini", deepseek_api_key="synthetic-key")
        ).invoke([HumanMessage(content="Synthetic")])
    assert error.value.error.code == "gemini_billing_required"
    assert "预付费余额" in error.value.error.message
    assert "synthetic-private-key" not in error.value.error.message


@pytest.mark.parametrize(
    "protocol,payload",
    [
        (
            "openai_responses",
            {
                "status": "completed",
                "output": [
                    {
                        "type": "message",
                        "content": [{"type": "output_text", "text": "Synthetic answer"}],
                    }
                ],
            },
        ),
        (
            "anthropic",
            {"stop_reason": "end_turn", "content": [{"type": "text", "text": "Synthetic answer"}]},
        ),
        (
            "gemini",
            {
                "candidates": [
                    {
                        "finishReason": "STOP",
                        "content": {
                            "parts": [
                                {"thought": True, "text": "Private reasoning"},
                                {"text": "Synthetic answer"},
                            ]
                        },
                    }
                ]
            },
        ),
    ],
)
def test_complete_text_answers_and_invalid_payloads(monkeypatch, protocol, payload):
    response = {"value": payload}
    install_upstream(monkeypatch, lambda request: httpx.Response(200, json=response["value"]))
    model = chat_model(
        Settings(_env_file=None, model_protocol=protocol, deepseek_api_key="synthetic-key")
    )
    answer = model.invoke([HumanMessage(content="Synthetic")])
    assert answer.content == "Synthetic answer"
    assert answer.response_metadata["finish_reason"] == "stop"
    response["value"] = {"unexpected": True}
    with pytest.raises(ServiceError) as error:
        model.invoke([HumanMessage(content="Synthetic")])
    assert error.value.error.code == "model_invalid_response"


@pytest.mark.parametrize("protocol", ["openai_responses", "anthropic", "gemini"])
def test_timeout_is_explicit_and_retries_are_not_implicit(monkeypatch, protocol):
    calls = []

    def handler(request):
        calls.append(request)
        raise httpx.ReadTimeout("synthetic-private-error")

    install_upstream(monkeypatch, handler)
    model = chat_model(
        Settings(_env_file=None, model_protocol=protocol, deepseek_api_key="synthetic-key")
    )
    with pytest.raises(ServiceError) as error:
        model.invoke([HumanMessage(content="Synthetic")])
    assert error.value.error.code == "model_timeout"
    assert len(calls) == 1
    assert "synthetic-private-error" not in error.value.error.message


def test_openai_chat_uses_actual_adapter_without_network(monkeypatch):
    from astroagent import model_client

    requests = []

    def handle(request):
        requests.append(json.loads(request.content))
        return httpx.Response(
            200,
            request=request,
            json={
                "id": "synthetic",
                "model": "synthetic-model",
                "object": "chat.completion",
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": "Synthetic answer"},
                    }
                ],
            },
        )

    original = model_client.ChatOpenAI
    monkeypatch.setattr(
        model_client,
        "ChatOpenAI",
        lambda **kwargs: original(
            **kwargs,
            http_client=httpx.Client(transport=httpx.MockTransport(handle), trust_env=False),
            http_async_client=httpx.AsyncClient(
                transport=httpx.MockTransport(handle), trust_env=False
            ),
        ),
    )
    model = chat_model(
        Settings(_env_file=None, deepseek_api_key="synthetic-key", deepseek_model="synthetic-model")
    )
    assert model.invoke([HumanMessage(content="Synthetic")]).content == "Synthetic answer"
    assert requests[0]["model"] == "synthetic-model"
    assert requests[0]["thinking"] == {"type": "disabled"}


def test_offline_guard_includes_proxy_transport():
    with httpx.Client(proxy="http://127.0.0.1:9", trust_env=False) as client:
        with pytest.raises(AssertionError, match="Offline tests"):
            client.get("https://models.example.invalid/synthetic")


@pytest.mark.parametrize("protocol", ["openai_chat", "openai_responses", "anthropic", "gemini"])
def test_model_directory_filters_invalid_entries_and_authentication(monkeypatch, protocol):
    import socket

    service = registry()
    monkeypatch.setattr(service, "read", lambda: {"providers": []})
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443))],
    )
    seen = []
    status = {"code": 200}

    def handler(request):
        seen.append(request)
        assert request.method == "GET"
        if protocol == "gemini":
            data = {
                "models": [
                    {
                        "name": "models/synthetic-model",
                        "displayName": "Synthetic",
                        "supportedGenerationMethods": ["generateContent"],
                    },
                    {"name": "models/embedding", "supportedGenerationMethods": ["embedContent"]},
                ],
                "nextPageToken": "synthetic-next-page",
            }
        else:
            data = {
                "data": [
                    {"id": "synthetic-model"},
                    {"id": "invalid model"},
                    {"id": "synthetic-model"},
                    None,
                ],
                "has_more": True,
            }
        return httpx.Response(status["code"], json=data)

    install_upstream(monkeypatch, handler)
    found = service.discover(draft(protocol=protocol))
    assert [m["id"] for m in found["models"]] == ["synthetic-model"]
    assert found["truncated"]
    assert "synthetic-not-a-credential" not in json.dumps(found)
    status["code"] = 401
    with pytest.raises(ServiceError) as error:
        service.discover(draft(protocol=protocol))
    assert error.value.error.code == "provider_auth_failed"
    assert len(seen) == 2
