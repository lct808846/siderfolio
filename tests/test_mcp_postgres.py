"""MCP transport switching through the authenticated API and a disposable database."""

import pytest
from test_identity_postgres import identity_client as identity_client
from test_identity_postgres import post, synthetic_admin

from astroagent.config import LocalSettings, Settings
from astroagent.execution import MODEL_TASK_SLOTS
from astroagent.mcp_client import (
    close_mcp_runtime,
    get_mcp_runtime_status,
    initialize_mcp_runtime,
    load_persisted_astronomy_transport,
    read_persisted_astronomy_transport,
)
from astroagent.mcp_contract import MCP_TARGET_PROTOCOL_VERSION, MCP_TOOL_NAMES

pytestmark = [pytest.mark.identity, pytest.mark.postgres]


def test_mcp_transport_switch_with_admin_and_persistence(identity_client):
    client = identity_client
    path = "setup/astronomy-transport"
    body = {"transport": "mcp"}
    assert client.put(f"/api/v1/{path}", json=body).status_code == 401
    synthetic_admin(client)
    assert client.get("/api/v1/setup/status").json()["astronomy_tool_transport"] == "direct"
    assert MODEL_TASK_SLOTS.acquire(blocking=False)
    try:
        busy = post(client, path, body, "PUT")
        assert busy.status_code == 409, busy.text
        assert busy.json()["error"]["code"] == "transport_switch_busy"
        assert read_persisted_astronomy_transport(client.store) is None
    finally:
        MODEL_TASK_SLOTS.release()

    switched = post(client, path, body, "PUT")
    assert switched.status_code == 200, switched.text
    status = switched.json()
    assert status["astronomy_tool_transport"] == "mcp"
    assert status["mcp_status"] == "ready"
    assert status["mcp_protocol_version"] == MCP_TARGET_PROTOCOL_VERSION
    assert status["mcp_tools"] == list(MCP_TOOL_NAMES)

    close_mcp_runtime()
    assert load_persisted_astronomy_transport(client.store) == "mcp"
    local = LocalSettings()
    initialize_mcp_runtime(local, Settings())
    assert get_mcp_runtime_status(local)["mcp_status"] == "ready"

    reverted = post(client, path, {"transport": "direct"}, "PUT")
    assert reverted.status_code == 200, reverted.text
    assert reverted.json()["mcp_status"] == "disabled"
    assert read_persisted_astronomy_transport(client.store) == "direct"
