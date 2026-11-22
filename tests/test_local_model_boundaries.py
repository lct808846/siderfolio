"""Untrusted local output cannot authorize tools, invent facts or escape fixed routing."""

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from pydantic import ValidationError

from astroagent.config import LocalSettings
from astroagent.errors import ServiceError
from astroagent.local_model_client import LocalModelClient, strict_json, validate_title


@pytest.mark.parametrize("raw", ['{"title":"a","title":"b"}', '{"value":NaN}'])
def test_duplicate_or_nonfinite_json_is_rejected(raw):
    with pytest.raises(ValueError):
        strict_json(raw)


def test_numeric_comparison_is_safe_plain_text_but_html_still_rejected():
    assert validate_title("Gaia RUWE<1.4", "Gaia RUWE<1.4") == "Gaia RUWE＜1.4"
    with pytest.raises(ValueError):
        validate_title("<script>test</script>", "<script>test</script>")


def test_long_identifier_cannot_be_truncated_by_title_decoding(monkeypatch):
    client = LocalModelClient(
        LocalSettings(_env_file=None, local_model_name="synthetic", local_model_digest="a" * 64)
    )

    def response(path, payload=None, timeout=None):
        if path == "/api/tags":
            return {"models": [{"name": "synthetic", "digest": "a" * 64}]}
        prompt = json.loads(payload["messages"][1]["content"])
        assert "65225812899613312" not in prompt["source_text"]
        assert "长编号已省略" in prompt["source_text"]
        return {
            "model": "synthetic",
            "message": {"role": "assistant", "content": '{"title":"Gaia源编号查询"}'},
            "done": True,
            "done_reason": "stop",
        }

    monkeypatch.setattr(client, "request", response)
    output, _ = client.generate_title("Query Gaia DR3 source_id 65225812899613312")
    assert output == "Gaia源编号查询"


@pytest.mark.parametrize(
    "url", ["https://example.invalid", "http://evil.invalid", "http://127.0.0.1:11434/path"]
)
def test_arbitrary_native_model_target_is_rejected(url):
    with pytest.raises(ValidationError):
        LocalSettings(_env_file=None, local_model_url=url)


@pytest.mark.parametrize(
    "output,extra",
    [
        ({"title": "M45查询"}, {"tool_calls": [{"function": {"name": "delete_all"}}]}),
        ({"title": "M45查询"}, {"role": "tool"}),
        ({"title": "M45查询"}, {"done_reason": "length"}),
        ({"title": "NGC884查询"}, {}),
        ({"title": "<script>alert(1)</script>"}, {}),
        ({"title": ""}, {}),
        ({"title": "M45" + "查" * 30}, {}),
    ],
)
def test_invalid_titles_and_tool_bearing_responses_are_rejected(monkeypatch, output, extra):
    settings = LocalSettings(
        _env_file=None, local_model_name="synthetic", local_model_digest="a" * 64
    )
    client = LocalModelClient(settings)
    calls = []

    def response(path, payload=None, timeout=None):
        calls.append(path)
        if path == "/api/tags":
            return {"models": [{"name": "synthetic", "digest": "a" * 64}]}
        value = {
            "model": "synthetic",
            "message": {"role": "assistant", "content": json.dumps(output)},
            "done": True,
            "done_reason": "stop",
        }
        value["message"].update({k: v for k, v in extra.items() if k in ("role", "tool_calls")})
        value.update({k: v for k, v in extra.items() if k not in ("role", "tool_calls")})
        assert "tools" not in payload
        return value

    monkeypatch.setattr(client, "request", response)
    with pytest.raises(ServiceError) as caught:
        client.generate_title("查询M45的坐标")
    assert caught.value.error.code == "local_model_invalid_output"
    assert calls == ["/api/tags", "/api/chat"]


@pytest.mark.parametrize("case", ["missing", "wrong_digest", "cloud"])
def test_missing_or_wrong_model_never_starts_generation(monkeypatch, case):
    client = LocalModelClient(
        LocalSettings(_env_file=None, local_model_name="synthetic", local_model_digest="a" * 64)
    )
    calls = []

    def response(path, **kwargs):
        calls.append(path)
        model = {"name": "synthetic", "digest": "b" * 64 if case == "wrong_digest" else "a" * 64}
        if case == "cloud":
            model["remote_host"] = "https://example.invalid"
        return {"models": [] if case == "missing" else [model]}

    monkeypatch.setattr(client, "request", response)
    with pytest.raises(ServiceError):
        client.generate_title("查询M45")
    assert calls == ["/api/tags"]


@pytest.mark.parametrize("response_kind", ["redirect", "encoding", "oversized", "plain"])
def test_local_transport_never_follows_redirects_or_inherits_proxy(monkeypatch, response_kind):
    paths = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            paths.append(self.path)
            self.send_response(302 if response_kind == "redirect" else 200)
            if response_kind == "redirect":
                self.send_header("Location", "https://example.invalid/private")
            if response_kind == "encoding":
                self.send_header("Content-Encoding", "gzip")
            self.end_headers()
            body = b'{"ok":true}' if response_kind != "oversized" else b"x" * (129 * 1024)
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    monkeypatch.setenv("HTTP_PROXY", "http://example.invalid:4321")
    client = LocalModelClient(
        LocalSettings(_env_file=None, local_model_url=f"http://127.0.0.1:{server.server_port}")
    )
    try:
        if response_kind == "plain":
            assert client.request("/synthetic") == {"ok": True}
        else:
            with pytest.raises(ServiceError) as caught:
                client.request("/synthetic")
            assert caught.value.error.code == (
                "local_model_output_limit"
                if response_kind == "oversized"
                else "local_model_unavailable"
            )
        assert paths == ["/synthetic"]
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=2)
