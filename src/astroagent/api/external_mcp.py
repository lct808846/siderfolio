"""V2.1 管理员 MFA 后台：受控外部 MCP 服务状态、工具发现与按项审批接口。"""

from __future__ import annotations

from fastapi import APIRouter, Request

from astroagent.api.admin import admin, writable
from astroagent.api.auth import runtime, source
from astroagent.external_mcp_schemas import (
    AdminMcpServersResponse,
    ExternalMcpServerStatus,
    ServerToggleRequest,
    ToolApproveRequest,
)
from astroagent.schemas import ErrorResponse

router = APIRouter(
    prefix="/api/v1/admin/mcp",
    tags=["administration"],
    responses={code: {"model": ErrorResponse} for code in (401, 403, 404, 409, 422, 502, 503, 504)},
)


@router.get("/servers", response_model=AdminMcpServersResponse)
def list_external_mcp_servers(request: Request):
    service, _ = runtime(request), admin(request)
    return service.external_mcp.list_servers(auto_sync_stale=True)


@router.post("/servers/{server_id}/toggle", response_model=ExternalMcpServerStatus)
def toggle_external_mcp_server(server_id: str, body: ServerToggleRequest, request: Request):
    service, user = runtime(request), admin(request)
    service.store.rate("admin_change", source(request), user["id"], limit=30)
    with service.store.connect() as db:
        writable(db, user)
        status = service.external_mcp.toggle_server(
            db, server_id, enabled=body.enabled, actor_id=user["id"]
        )
    if body.enabled:
        return service.external_mcp.sync_server(server_id, actor_id=user["id"], record_audit=True)
    return status


@router.post("/servers/{server_id}/discover", response_model=ExternalMcpServerStatus)
def discover_external_mcp_server(server_id: str, request: Request):
    service, user = runtime(request), admin(request)
    service.store.rate("admin_change", source(request), user["id"], limit=30)
    with service.store.connect() as db:
        writable(db, user)
    return service.external_mcp.sync_server(server_id, actor_id=user["id"], record_audit=True)


@router.post(
    "/servers/{server_id}/tools/{remote_name}/approve",
    response_model=ExternalMcpServerStatus,
)
def approve_external_mcp_tool(
    server_id: str,
    remote_name: str,
    body: ToolApproveRequest,
    request: Request,
):
    service, user = runtime(request), admin(request)
    service.store.rate("admin_change", source(request), user["id"], limit=30)
    with service.store.connect() as db:
        writable(db, user)
        return service.external_mcp.approve_tool(
            db,
            server_id,
            remote_name,
            expected_definition_sha256=body.expected_definition_sha256,
            actor_id=user["id"],
        )


@router.post(
    "/servers/{server_id}/tools/{remote_name}/revoke",
    response_model=ExternalMcpServerStatus,
)
def revoke_external_mcp_tool(server_id: str, remote_name: str, request: Request):
    service, user = runtime(request), admin(request)
    service.store.rate("admin_change", source(request), user["id"], limit=30)
    with service.store.connect() as db:
        writable(db, user)
        return service.external_mcp.revoke_tool(db, server_id, remote_name, actor_id=user["id"])
