"""V2.1 外部 MCP 服务端管理持久化、审批生命周期与活动工具目录投影。"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

from astroagent.errors import ServiceError
from astroagent.external_mcp_client import ExternalMcpHttpClient
from astroagent.external_mcp_schemas import (
    AdminMcpServersResponse,
    DiscoveredExternalTool,
    ExternalMcpServerConfig,
    ExternalMcpServerStatus,
)
from astroagent.skill_schemas import ExternalToolPreview
from astroagent.tool_catalog import ToolCatalogEntry

V21_MCP_DDL = (
    """
    CREATE TABLE IF NOT EXISTS public.mcp_external_servers (
        server_id text PRIMARY KEY,
        enabled boolean NOT NULL DEFAULT false,
        protocol_version text NOT NULL DEFAULT '',
        server_name text NOT NULL DEFAULT '',
        server_version text NOT NULL DEFAULT '',
        last_discovered_at timestamptz,
        last_sync_status text NOT NULL DEFAULT 'never'
            CHECK (last_sync_status IN ('never','ok','error','incompatible')),
        last_error_code text NOT NULL DEFAULT '',
        last_error_message text NOT NULL DEFAULT '',
        discovered_tools_json text NOT NULL DEFAULT '[]',
        updated_at timestamptz NOT NULL DEFAULT now(),
        updated_by text REFERENCES public.auth_users(id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS public.mcp_external_tool_approvals (
        server_id text NOT NULL REFERENCES public.mcp_external_servers(server_id) ON DELETE CASCADE,
        remote_name text NOT NULL,
        tool_id text NOT NULL UNIQUE,
        approved boolean NOT NULL DEFAULT false,
        approved_definition_sha256 text NOT NULL DEFAULT '',
        approved_schema_json text NOT NULL DEFAULT '{}',
        approved_description text NOT NULL DEFAULT '',
        approved_title text NOT NULL DEFAULT '',
        approved_at timestamptz,
        approved_by text REFERENCES public.auth_users(id),
        revoked_at timestamptz,
        revoked_by text REFERENCES public.auth_users(id),
        PRIMARY KEY (server_id, remote_name)
    )
    """,
)


def install_v21_mcp_schema(db) -> bool:
    for statement in V21_MCP_DDL:
        db.execute(statement)
    exists = db.execute(
        "SELECT 1 FROM public.auth_meta WHERE key='v21_mcp_schema' AND value='1'"
    ).fetchone()
    if exists:
        return False
    db.execute(
        "INSERT INTO public.auth_meta(key,value) VALUES ('v21_mcp_schema','1') "
        "ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value"
    )
    return True


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat()
    return str(value)


def _is_stale(last_discovered_at: Any, ttl_seconds: int) -> bool:
    if last_discovered_at is None:
        return True
    if isinstance(last_discovered_at, str):
        try:
            dt = datetime.fromisoformat(last_discovered_at)
        except ValueError:
            return True
    elif isinstance(last_discovered_at, datetime):
        dt = last_discovered_at
    else:
        return True
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return datetime.now(UTC) - dt > timedelta(seconds=ttl_seconds)


class ExternalMcpRegistryService:
    """管理员受控外部 MCP 服务发现、工具审批与活动目录查询。"""

    def __init__(
        self,
        store,
        local_settings,
        *,
        client: ExternalMcpHttpClient | None = None,
    ):
        self.store = store
        self.local_settings = local_settings
        self.client = client or ExternalMcpHttpClient()

    @property
    def feature_enabled(self) -> bool:
        return bool(getattr(self.local_settings, "external_mcp_enabled", False))

    def configured_servers(self) -> dict[str, ExternalMcpServerConfig]:
        if not self.feature_enabled:
            return {}
        servers = getattr(self.local_settings, "external_mcp_servers", ()) or ()
        return {server.id: server for server in servers}

    def _require_configured(self, server_id: str) -> ExternalMcpServerConfig:
        if not self.feature_enabled:
            raise ServiceError(
                409,
                "external_mcp_disabled",
                "服务端未开启外部 MCP 接入开关（ASTROAGENT_EXTERNAL_MCP_ENABLED）。",
            )
        config = self.configured_servers().get(server_id)
        if config is None:
            raise ServiceError(404, "mcp_server_not_found", "未找到该预配外部 MCP 服务。")
        return config

    def _ensure_server_row(self, db, server_id: str) -> dict[str, Any]:
        install_v21_mcp_schema(db)
        db.execute(
            "INSERT INTO public.mcp_external_servers(server_id, enabled) VALUES (%s, false) "
            "ON CONFLICT(server_id) DO NOTHING",
            (server_id,),
        )
        row = db.execute(
            "SELECT * FROM public.mcp_external_servers WHERE server_id=%s",
            (server_id,),
        ).fetchone()
        assert row is not None
        return dict(row)

    def _build_server_status(
        self,
        db,
        config: ExternalMcpServerConfig,
        row: dict[str, Any],
    ) -> ExternalMcpServerStatus:
        try:
            raw_tools = json.loads(row.get("discovered_tools_json") or "[]")
            if not isinstance(raw_tools, list):
                raw_tools = []
        except ValueError:
            raw_tools = []
        approvals_rows = db.execute(
            "SELECT * FROM public.mcp_external_tool_approvals WHERE server_id=%s",
            (config.id,),
        ).fetchall()
        approvals = {r["remote_name"]: dict(r) for r in approvals_rows}

        tools: list[DiscoveredExternalTool] = []
        for item in raw_tools:
            if not isinstance(item, dict):
                continue
            remote_name = str(item.get("remote_name") or "")
            if not remote_name:
                continue
            approval = approvals.get(remote_name)
            approved = bool(approval and approval.get("approved"))
            approved_sha = str(approval.get("approved_definition_sha256") or "") if approval else ""
            current_sha = str(item.get("definition_sha256") or "")
            definition_changed = bool(approved and approved_sha and approved_sha != current_sha)
            tools.append(
                DiscoveredExternalTool(
                    remote_name=remote_name,
                    tool_id=str(item.get("tool_id") or ""),
                    title=str(item.get("title") or remote_name),
                    description=str(item.get("description") or ""),
                    input_schema=item.get("input_schema")
                    if isinstance(item.get("input_schema"), dict)
                    else {},
                    output_schema=item.get("output_schema")
                    if isinstance(item.get("output_schema"), dict)
                    else None,
                    read_only_hint=item.get("read_only_hint"),
                    destructive_hint=item.get("destructive_hint"),
                    eligible_readonly=bool(item.get("eligible_readonly")),
                    definition_sha256=current_sha,
                    approved=approved and not definition_changed,
                    definition_changed=definition_changed,
                    approved_definition_sha256=approved_sha,
                    approved_at=_iso(approval.get("approved_at")) if approval else None,
                    revoked_at=_iso(approval.get("revoked_at")) if approval else None,
                    parameter_names=list(item.get("parameter_names") or []),
                )
            )
        return ExternalMcpServerStatus(
            server_id=config.id,
            title=config.title,
            description=config.description,
            endpoint_display=config.endpoint_display,
            protocol_version=config.protocol_version,
            negotiated_protocol_version=str(row.get("protocol_version") or ""),
            server_name=str(row.get("server_name") or ""),
            server_version=str(row.get("server_version") or ""),
            enabled=bool(row.get("enabled")),
            auth_env_ref=config.auth_env_var,
            auth_configured=config.auth_configured,
            last_discovered_at=_iso(row.get("last_discovered_at")),
            last_sync_status=row.get("last_sync_status") or "never",
            last_error_code=str(row.get("last_error_code") or ""),
            last_error_message=str(row.get("last_error_message") or ""),
            cache_stale=_is_stale(row.get("last_discovered_at"), config.cache_ttl_seconds),
            tools=tools,
        )

    def sync_server(
        self,
        server_id: str,
        *,
        actor_id: str | None = None,
        record_audit: bool = False,
    ) -> ExternalMcpServerStatus:
        config = self._require_configured(server_id)
        try:
            outcome = self.client.discover(config)
            sync_status = "ok"
            err_code = ""
            err_msg = ""
        except ServiceError as exc:
            outcome = None
            sync_status = (
                "incompatible" if exc.error.code == "mcp_incompatible_protocol" else "error"
            )
            err_code = exc.error.code
            err_msg = exc.error.message

        with self.store.connect() as db:
            self._ensure_server_row(db, server_id)
            if outcome is not None:
                db.execute(
                    "UPDATE public.mcp_external_servers SET "
                    "protocol_version=%s, server_name=%s, server_version=%s, "
                    "last_discovered_at=now(), last_sync_status='ok', "
                    "last_error_code='', last_error_message='', "
                    "discovered_tools_json=%s, updated_at=now(), updated_by=%s "
                    "WHERE server_id=%s",
                    (
                        outcome.protocol_version,
                        outcome.server_name,
                        outcome.server_version,
                        json.dumps(outcome.tools, ensure_ascii=False, separators=(",", ":")),
                        actor_id,
                        server_id,
                    ),
                )
            else:
                db.execute(
                    "UPDATE public.mcp_external_servers SET "
                    "last_sync_status=%s, last_error_code=%s, last_error_message=%s, "
                    "updated_at=now(), updated_by=%s WHERE server_id=%s",
                    (sync_status, err_code, err_msg, actor_id, server_id),
                )
            if record_audit and actor_id:
                self.store.audit(
                    db,
                    actor_id,
                    "mcp_server_discovered",
                    sync_status,
                    target=server_id,
                    reason=err_code or None,
                )
            row = self._ensure_server_row(db, server_id)
            return self._build_server_status(db, config, row)

    def list_servers(self, *, auto_sync_stale: bool = True) -> AdminMcpServersResponse:
        configs = self.configured_servers()
        if not self.feature_enabled:
            return AdminMcpServersResponse(feature_enabled=False, servers=[])
        statuses: list[ExternalMcpServerStatus] = []
        stale_ids: list[str] = []
        with self.store.connect() as db:
            install_v21_mcp_schema(db)
            for server_id, config in configs.items():
                row = self._ensure_server_row(db, server_id)
                if (
                    auto_sync_stale
                    and row["enabled"]
                    and _is_stale(row.get("last_discovered_at"), config.cache_ttl_seconds)
                ):
                    stale_ids.append(server_id)
        for server_id in stale_ids:
            try:
                self.sync_server(server_id)
            except Exception:
                pass
        with self.store.connect() as db:
            install_v21_mcp_schema(db)
            for server_id, config in configs.items():
                row = self._ensure_server_row(db, server_id)
                statuses.append(self._build_server_status(db, config, row))
        return AdminMcpServersResponse(feature_enabled=True, servers=statuses)

    def toggle_server(
        self,
        db,
        server_id: str,
        *,
        enabled: bool,
        actor_id: str,
    ) -> ExternalMcpServerStatus:
        config = self._require_configured(server_id)
        self._ensure_server_row(db, server_id)
        db.execute(
            "UPDATE public.mcp_external_servers SET enabled=%s, updated_at=now(), updated_by=%s "
            "WHERE server_id=%s",
            (enabled, actor_id, server_id),
        )
        self.store.audit(
            db,
            actor_id,
            "mcp_server_toggled",
            "enabled" if enabled else "disabled",
            target=server_id,
        )
        row = self._ensure_server_row(db, server_id)
        return self._build_server_status(db, config, row)

    def approve_tool(
        self,
        db,
        server_id: str,
        remote_name: str,
        *,
        expected_definition_sha256: str,
        actor_id: str,
    ) -> ExternalMcpServerStatus:
        config = self._require_configured(server_id)
        row = self._ensure_server_row(db, server_id)
        status = self._build_server_status(db, config, row)
        target = next((t for t in status.tools if t.remote_name == remote_name), None)
        if target is None:
            raise ServiceError(404, "mcp_tool_not_found", "未在发现清单中找到该外部工具。")
        if not target.eligible_readonly:
            raise ServiceError(
                409,
                "mcp_tool_not_readonly",
                "首版仅允许批准声明为只读（readOnlyHint=true 且非破坏性）的外部 MCP 工具。",
            )
        if target.definition_sha256 != expected_definition_sha256:
            raise ServiceError(
                409,
                "mcp_definition_changed",
                "该工具定义已变化，请核对最新定义摘要后重新批准。",
            )
        db.execute(
            "INSERT INTO public.mcp_external_tool_approvals "
            "(server_id, remote_name, tool_id, approved, approved_definition_sha256, "
            "approved_schema_json, approved_description, approved_title, approved_at, approved_by, "
            "revoked_at, revoked_by) "
            "VALUES (%s,%s,%s,true,%s,%s,%s,%s,now(),%s,NULL,NULL) "
            "ON CONFLICT(server_id, remote_name) DO UPDATE SET "
            "tool_id=EXCLUDED.tool_id, approved=true, "
            "approved_definition_sha256=EXCLUDED.approved_definition_sha256, "
            "approved_schema_json=EXCLUDED.approved_schema_json, "
            "approved_description=EXCLUDED.approved_description, "
            "approved_title=EXCLUDED.approved_title, "
            "approved_at=now(), approved_by=EXCLUDED.approved_by, "
            "revoked_at=NULL, revoked_by=NULL",
            (
                server_id,
                remote_name,
                target.tool_id,
                target.definition_sha256,
                json.dumps(target.input_schema, ensure_ascii=False, separators=(",", ":")),
                target.description,
                target.title,
                actor_id,
            ),
        )
        self.store.audit(
            db,
            actor_id,
            "mcp_tool_approved",
            "ok",
            target=target.tool_id,
            reason=target.definition_sha256[:16],
        )
        return self._build_server_status(db, config, row)

    def revoke_tool(
        self,
        db,
        server_id: str,
        remote_name: str,
        *,
        actor_id: str,
    ) -> ExternalMcpServerStatus:
        config = self._require_configured(server_id)
        row = self._ensure_server_row(db, server_id)
        updated = db.execute(
            "UPDATE public.mcp_external_tool_approvals SET approved=false, "
            "revoked_at=now(), revoked_by=%s WHERE server_id=%s AND remote_name=%s "
            "RETURNING tool_id",
            (actor_id, server_id, remote_name),
        ).fetchone()
        if not updated:
            raise ServiceError(404, "mcp_tool_not_found", "该工具尚未批准。")
        self.store.audit(
            db,
            actor_id,
            "mcp_tool_revoked",
            "ok",
            target=updated["tool_id"],
        )
        return self._build_server_status(db, config, row)

    def approved_tool_entries(self) -> list[ToolCatalogEntry]:
        """仅返回服务已启用、连接正常、已批准且定义摘要未变更的外部只读工具。"""
        if not self.feature_enabled:
            return []
        configs = self.configured_servers()
        if not configs:
            return []
        entries: list[ToolCatalogEntry] = []
        with self.store.connect() as db:
            install_v21_mcp_schema(db)
            for server_id, config in configs.items():
                row = db.execute(
                    "SELECT * FROM public.mcp_external_servers WHERE server_id=%s",
                    (server_id,),
                ).fetchone()
                if not row or not row["enabled"] or row["last_sync_status"] != "ok":
                    continue
                status = self._build_server_status(db, config, dict(row))
                for tool in status.tools:
                    if not (
                        tool.approved
                        and tool.eligible_readonly
                        and not tool.definition_changed
                        and tool.approved_definition_sha256 == tool.definition_sha256
                    ):
                        continue
                    entries.append(
                        ToolCatalogEntry(
                            tool_id=tool.tool_id,
                            title=tool.title,
                            description=(
                                f"[外部 MCP · {config.title} · 只读] "
                                f"{tool.description or tool.title}"
                            ),
                            source="external_mcp",
                            access_scope="external_readonly",
                            side_effect_level="external_readonly",
                            input_schema=tool.input_schema,
                            output_schema=tool.output_schema,
                            server_id=config.id,
                            server_title=config.title,
                            server_host=config.host,
                            remote_name=tool.remote_name,
                            protocol_version=status.negotiated_protocol_version
                            or config.protocol_version,
                            requires_confirmation=True,
                            availability_conditions=(
                                f"外部服务「{config.title}」已启用且协议 "
                                f"{config.protocol_version} 核验通过",
                                "工具已获管理员批准且定义未变更",
                                "每次调用前须由用户确认目标服务及外发字段",
                            ),
                            max_calls_per_turn=2,
                            failure_categories=(
                                "validation",
                                "authorization",
                                "timeout",
                                "rate_limit",
                                "mcp_protocol",
                                "mcp_transport",
                                "upstream",
                            ),
                            definition_sha256=tool.definition_sha256,
                            status_label=f"正在准备外部 MCP「{tool.title}」查询确认…",
                        )
                    )
        return entries

    def approved_previews(self) -> list[ExternalToolPreview]:
        return [
            ExternalToolPreview(
                tool_id=entry.tool_id,
                server_id=entry.server_id or "",
                server_title=entry.server_title or "",
                remote_name=entry.remote_name or "",
                title=entry.title,
                description=entry.description,
                protocol_version=entry.protocol_version or "",
                definition_sha256=entry.definition_sha256,
                requires_confirmation=True,
            )
            for entry in self.approved_tool_entries()
        ]

    def verify_live_execution_authorization(
        self,
        *,
        server_id: str,
        tool_id: str,
        expected_definition_sha256: str,
    ) -> tuple[ExternalMcpServerConfig, ToolCatalogEntry]:
        """实际调用外部 MCP 前再次核对服务启用、工具批准与定义摘要一致性。"""
        config = self._require_configured(server_id)
        for entry in self.approved_tool_entries():
            if entry.server_id == server_id and entry.tool_id == tool_id:
                if entry.definition_sha256 != expected_definition_sha256:
                    raise ServiceError(
                        409,
                        "tool_definition_changed",
                        "该外部工具定义已发生变化，原确认已失效，请重新发起查询。",
                    )
                return config, entry
        raise ServiceError(
            409,
            "tool_authorization_revoked",
            "该外部 MCP 服务已停用或工具授权已撤销，未发起外部请求。",
        )
