"""Isolated acceptance for attachment boundaries and per-turn model selection."""

from io import BytesIO
from uuid import uuid4
from zipfile import ZipFile

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from astroagent.api import conversations as routes
from astroagent.config import Settings
from astroagent.errors import ServiceError
from astroagent.main import app
from astroagent.schemas import ChatResponse
from scripts.export_samples import synthetic_request


@pytest.fixture
def client(monkeypatch):
    calls = []

    class Agent:
        def __init__(self, model):
            self.model = model

        def converse(self, message, context):
            calls.append((self.model, message, context))
            return ChatResponse.model_validate(synthetic_request()["snapshot"])

    monkeypatch.setattr(routes, "get_agent_for_model", lambda model: Agent(model))
    with TestClient(app) as value:
        value.calls = calls
        yield value


@pytest.mark.parametrize(
    "name,body",
    [
        ("sample.txt", "中文\n第二行"),
        ("sample.md", "# 中文"),
        ("sample.csv", "name,value\nM45,3"),
        ("sample.json", '{"sample": 3}'),
    ],
)
def test_local_text_upload_preserves_content(client, name, body):
    response = client.post(
        "/api/v1/chat/attachments",
        files={"file": (name, body.encode(), "application/octet-stream")},
    )
    assert response.status_code == 200, response.text
    assert response.json()["text"] == body
    assert response.json()["truncated"] is False
    assert not client.calls


def test_docx_text_and_attachment_limits(client):
    buffer = BytesIO()
    with ZipFile(buffer, "w") as doc:
        doc.writestr(
            "word/document.xml",
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>合成文献</w:t></w:r></w:p></w:body></w:document>',
        )
    result = client.post(
        "/api/v1/chat/attachments", files={"file": ("sample.docx", buffer.getvalue())}
    )
    assert result.status_code == 200, result.text
    assert "合成文献" in result.json()["text"]
    result = client.post(
        "/api/v1/chat/attachments", files={"file": ("large.txt", ("字" * 7000).encode())}
    )
    assert result.status_code == 200 and result.json()["truncated"] is True
    assert len(result.json()["text"].encode()) <= 16384
    assert (
        client.post("/api/v1/chat/attachments", files={"file": ("bad.exe", b"abc")}).status_code
        == 415
    )
    assert (
        client.post("/api/v1/chat/attachments", files={"file": ("bad.pdf", b"not pdf")}).status_code
        == 422
    )
    assert not client.calls


def test_pdf_attachment_extracts_text_with_page_marker(client):
    writer = PdfWriter()
    page = writer.add_blank_page(width=612, height=792)
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    page[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})}
    )
    stream = DecodedStreamObject()
    stream.set_data(b"BT /F1 12 Tf 80 700 Td (Synthetic PDF ORBIT-7429) Tj ET")
    page[NameObject("/Contents")] = writer._add_object(stream)
    output = BytesIO()
    writer.write(output)
    response = client.post(
        "/api/v1/chat/attachments", files={"file": ("synthetic.pdf", output.getvalue())}
    )
    assert response.status_code == 200, response.text
    assert "[物理页 1]" in response.json()["text"]
    assert "ORBIT-7429" in response.json()["text"]
    assert not client.calls


def test_model_switch_attachment_persistence_and_idempotency(client):
    item = client.post(
        "/api/v1/chat/attachments", files={"file": ("sample.txt", b"fixture evidence")}
    ).json()
    conversation = client.post("/api/v1/conversations", json={"title": "acceptance"}).json()
    url = f"/api/v1/conversations/{conversation['id']}/turns"
    request = {
        "message": "first",
        "client_request_id": str(uuid4()),
        "expected_revision": 0,
        "model": "model-one",
        "attachments": [item],
    }
    first = client.post(url, json=request)
    assert first.status_code == 200, first.text
    assert first.json()["model"] == "model-one"
    assert first.json()["attachments"][0]["text"] == "fixture evidence"
    replay = client.post(url, json=request)
    assert replay.status_code == 200 and len(client.calls) == 1
    changed = dict(request, model="model-two")
    assert client.post(url, json=changed).status_code == 409
    second = client.post(
        url,
        json={
            "message": "follow up",
            "client_request_id": str(uuid4()),
            "expected_revision": 1,
            "model": "model-two",
        },
    )
    assert second.status_code == 200, second.text
    assert [call[0] for call in client.calls] == ["model-one", "model-two"]
    assert first.json()["turn_id"] in client.calls[-1][2].record.included_turn_ids


def test_model_allowlist_rejects_unknown():
    settings = Settings(
        _env_file=None,
        deepseek_model="alpha",
        chat_models=[{"id": "alpha", "label": "A"}, {"id": "beta", "label": "B"}],
    )
    assert settings.for_model("beta").deepseek_model == "beta"
    with pytest.raises(ServiceError):
        settings.for_model("not-allowed")
