"""V2.1 统一服务端工具目录：单一来源生成模型工具定义、执行白名单与摘要。"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

from astroagent.literature_schemas import SaveLiteratureQuery
from astroagent.schemas import (
    GaiaQuery,
    LiteratureQuery,
    NBodyProposalQuery,
    ObjectQuery,
    PlotProposalQuery,
)
from astroagent.table_schemas import (
    ProjectTablesListQuery,
    TableAnalysisProposalQuery,
    VizierQuery,
)
from astroagent.tool_schemas import (
    ToolAccessScope,
    ToolCatalogItem,
    ToolSideEffectLevel,
    ToolSource,
)

BUILTIN_TOOL_NAMES = frozenset(
    {
        "query_simbad",
        "search_ads",
        "query_gaia",
        "query_vizier",
        "list_project_tables",
        "prepare_table_analysis",
        "prepare_nbody_simulation",
        "prepare_scientific_plot",
        "save_literature",
    }
)

EXTERNAL_TOOL_ID_RE = re.compile(r"^mcp__([a-z][a-z0-9_-]{1,31})__([A-Za-z0-9_.-]{1,64})$")


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def compute_tool_definition_sha256(
    *,
    name: str,
    description: str,
    input_schema: dict[str, Any],
    output_schema: dict[str, Any] | None = None,
    annotations: dict[str, Any] | None = None,
) -> str:
    payload = {
        "name": name,
        "description": description,
        "input_schema": input_schema,
        "output_schema": output_schema,
        "annotations": annotations,
    }
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def make_external_tool_id(server_id: str, remote_name: str) -> str:
    """Create a collision-free model-safe tool ID isolated by server_id."""
    safe_remote = re.sub(r"[^A-Za-z0-9_-]", "_", remote_name)
    candidate = f"mcp__{server_id}__{safe_remote}"
    if candidate in BUILTIN_TOOL_NAMES:
        raise ValueError("External tool name collides with built-in tool")
    if len(candidate) > 64:
        suffix = hashlib.sha256(f"{server_id}:{remote_name}".encode()).hexdigest()[:8]
        candidate = f"mcp__{server_id[:16]}__{safe_remote[:28]}_{suffix}"
    return candidate


@dataclass(frozen=True, slots=True)
class ToolCatalogEntry:
    tool_id: str
    title: str
    description: str
    source: ToolSource
    access_scope: ToolAccessScope
    side_effect_level: ToolSideEffectLevel
    input_schema: dict[str, Any]
    input_model: type[BaseModel] | None = None
    output_schema: dict[str, Any] | None = None
    server_id: str | None = None
    server_title: str | None = None
    server_host: str = ""
    remote_name: str | None = None
    protocol_version: str | None = None
    requires_confirmation: bool = False
    availability_conditions: tuple[str, ...] = ()
    max_calls_per_turn: int = 6
    failure_categories: tuple[str, ...] = ()
    definition_sha256: str = ""
    status_label: str = ""

    def to_model_tool_definition(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.tool_id,
                "description": self.description,
                "parameters": self.input_schema,
            },
        }

    def to_public_item(
        self, *, available: bool = True, unavailable_reason: str | None = None
    ) -> ToolCatalogItem:
        return ToolCatalogItem(
            tool_id=self.tool_id,
            title=self.title,
            description=self.description,
            source=self.source,
            server_id=self.server_id,
            server_title=self.server_title,
            remote_name=self.remote_name,
            protocol_version=self.protocol_version,
            access_scope=self.access_scope,
            side_effect_level=self.side_effect_level,
            requires_confirmation=self.requires_confirmation,
            availability_conditions=list(self.availability_conditions),
            available=available,
            unavailable_reason=unavailable_reason,
            max_calls_per_turn=self.max_calls_per_turn,
            failure_categories=list(self.failure_categories),
            definition_sha256=self.definition_sha256,
        )


def builtin_tool_entries(
    *,
    astronomy_transport: str = "direct",
    include_literature_save: bool = True,
    max_calls_per_turn: int = 6,
) -> list[ToolCatalogEntry]:
    astro_source: ToolSource = "local_mcp" if astronomy_transport == "mcp" else "builtin"
    astro_proto = "2026-07-28" if astronomy_transport == "mcp" else None
    specs: list[
        tuple[
            str,
            str,
            str,
            ToolSource,
            ToolAccessScope,
            ToolSideEffectLevel,
            type[BaseModel],
            bool,
            tuple[str, ...],
            tuple[str, ...],
            str,
            str | None,
        ]
    ] = [
        (
            "query_simbad",
            "SIMBAD 天体查询",
            "按天体名称或标识符查询 SIMBAD，返回真实坐标、类型、光谱及来源。",
            astro_source,
            "account_readonly",
            "readonly",
            ObjectQuery,
            False,
            ("天体名称或标识符明确", "符合每轮调用预算"),
            ("validation", "not_found", "timeout", "upstream", "mcp_subprocess", "mcp_protocol"),
            "正在查询 SIMBAD 天体数据库…",
            astro_proto,
        ),
        (
            "search_ads",
            "NASA ADS 文献检索",
            "检索真实 ADS 天文文献；返回单页书目信息、摘要、检索条件与来源。",
            astro_source,
            "account_readonly",
            "readonly",
            LiteratureQuery,
            False,
            ("服务端已配置 ADS API Token", "检索条件有效且在分页上限内"),
            (
                "validation",
                "not_found",
                "timeout",
                "rate_limit",
                "upstream",
                "mcp_subprocess",
                "mcp_protocol",
            ),
            "正在检索 NASA ADS 天文文献…",
            astro_proto,
        ),
        (
            "query_gaia",
            "Gaia DR3 星表查询",
            "按 DR3 编号或有界 ICRS 圆锥查询 Gaia，返回测量、统计、条件和来源。",
            astro_source,
            "account_readonly",
            "readonly",
            GaiaQuery,
            False,
            ("提供合法 DR3 source_id 或 ICRS 坐标与半径（<=30 角分）", "符合每轮调用预算"),
            ("validation", "not_found", "timeout", "upstream", "mcp_subprocess", "mcp_protocol"),
            "正在查询 Gaia DR3 星表数据…",
            astro_proto,
        ),
        (
            "query_vizier",
            "VizieR 星表检索",
            (
                "只读检索 CDS VizieR 星表（内置 2MASS、AllWISE、Pan-STARRS、"
                "LAMOST、Cantat-Gaudin+2020 等预设或指定合法星表 ID），"
                "返回真实列单位、参考历元、截断状态与 CDS 来源链接。"
            ),
            astro_source,
            "account_readonly",
            "readonly",
            VizierQuery,
            False,
            ("提供合法 VizieR 星表编号及 ICRS 坐标或天体名", "符合每轮调用预算"),
            ("validation", "not_found", "timeout", "upstream", "mcp_subprocess", "mcp_protocol"),
            "正在检索 CDS VizieR 星表…",
            astro_proto,
        ),
        (
            "list_project_tables",
            "列出项目数据表",
            "只读列出当前科研项目中已保存的天文数据表编号（dataset_id）、行数、列名、数据类型、物理单位与参考历元。",
            "builtin",
            "account_readonly",
            "readonly",
            ProjectTablesListQuery,
            False,
            ("当前处于科研项目或个人空间上下文",),
            ("validation", "authorization", "not_found"),
            "正在读取项目数据表清单…",
            None,
        ),
        (
            "prepare_table_analysis",
            "天文数据表确定性分析方案",
            (
                "基于项目内真实数据表构建统计检验、白名单筛选/派生列、坐标变换、交叉匹配或曲线拟合参数方案，"
                "在对话中生成交互式确认卡片，由用户核对并确认由服务端 Astropy/SciPy 执行。"
            ),
            "builtin",
            "project_draft",
            "draft_only",
            TableAnalysisProposalQuery,
            True,
            (
                "引用 list_project_tables 返回的真实 dataset_id 与列名",
                "仅生成草案，实际运算由用户在原卡片确认",
            ),
            ("validation",),
            "正在构建天文数据表确定性分析方案…",
            None,
        ),
        (
            "prepare_nbody_simulation",
            "N 体模拟参数方案",
            (
                "根据用户需求自动计算并生成孤立牛顿 N 体模拟参数方案（REBOUND 或 PeTar），"
                "固定单位 AU、yr、M_sun、AU/yr（G=4*pi^2），在对话中交由用户核对、修改并确认运行。"
            ),
            "builtin",
            "project_draft",
            "draft_only",
            NBodyProposalQuery,
            True,
            ("2–128 粒子孤立点质量参数合法", "仅生成草案，实际运行由用户在原卡片确认"),
            ("validation",),
            "正在构建 N 体模拟初始条件与参数方案…",
            None,
        ),
        (
            "prepare_scientific_plot",
            "科研绘图方案与脚本",
            (
                "基于本轮或历史 Gaia 查询结果或用户 CSV/TSV 附件生成独立 Python(Matplotlib) 或 "
                "Gnuplot 科研绘图方案与脚本，在对话中交由用户核对、修改并确认在隔离容器中出图。"
            ),
            "builtin",
            "project_draft",
            "draft_only",
            PlotProposalQuery,
            True,
            ("引用真实 Gaia/附件数据列", "仅生成草案，实际出图由用户在原卡片确认"),
            ("validation",),
            "正在生成科研绘图方案与脚本…",
            None,
        ),
    ]
    if include_literature_save:
        specs.append(
            (
                "save_literature",
                "个人文献库直接入库",
                (
                    "仅在用户当前消息明确要求保存或加入文献库且目标范围唯一确定时调用。"
                    "仅提交可核对的 ADS 批次与 1 起序号或真实 bibcode 引用；由服务端校验并入库。"
                ),
                "builtin",
                "account_write",
                "internal_write",
                SaveLiteratureQuery,
                False,
                ("用户当前消息明确要求保存且条目范围唯一", "仅限已核验的 ADS 检索结果"),
                ("validation", "authorization", "not_found", "storage"),
                "正在核验并写入个人文献库…",
                None,
            )
        )

    entries: list[ToolCatalogEntry] = []
    for (
        tool_id,
        title,
        description,
        source,
        access_scope,
        side_effect_level,
        model_cls,
        requires_confirmation,
        conditions,
        failures,
        label,
        proto,
    ) in specs:
        schema = model_cls.model_json_schema()
        digest = compute_tool_definition_sha256(
            name=tool_id,
            description=description,
            input_schema=schema,
        )
        entries.append(
            ToolCatalogEntry(
                tool_id=tool_id,
                title=title,
                description=description,
                source=source,
                access_scope=access_scope,
                side_effect_level=side_effect_level,
                input_schema=schema,
                input_model=model_cls,
                protocol_version=proto,
                requires_confirmation=requires_confirmation,
                availability_conditions=conditions,
                max_calls_per_turn=max_calls_per_turn,
                failure_categories=failures,
                definition_sha256=digest,
                status_label=label,
            )
        )
    return entries


class TurnToolCatalog:
    """Immutable per-turn tool catalog powering both model definitions and execution allowlist."""

    def __init__(
        self,
        entries: list[ToolCatalogEntry],
        *,
        external_max_calls_per_turn: int = 2,
    ):
        by_id: dict[str, ToolCatalogEntry] = {}
        ordered: list[ToolCatalogEntry] = []
        for entry in entries:
            if entry.tool_id in by_id:
                continue
            by_id[entry.tool_id] = entry
            ordered.append(entry)
        self._entries = tuple(ordered)
        self._by_id = by_id
        self.external_max_calls_per_turn = max(1, min(external_max_calls_per_turn, 4))
        manifest_payload = [
            {
                "tool_id": item.tool_id,
                "source": item.source,
                "definition_sha256": item.definition_sha256,
            }
            for item in self._entries
        ]
        self.manifest_sha256 = hashlib.sha256(
            canonical_json(manifest_payload).encode("utf-8")
        ).hexdigest()

    @property
    def entries(self) -> tuple[ToolCatalogEntry, ...]:
        return self._entries

    @property
    def tool_ids(self) -> list[str]:
        return [entry.tool_id for entry in self._entries]

    def get(self, tool_id: str) -> ToolCatalogEntry | None:
        return self._by_id.get(tool_id)

    def model_tool_definitions(self) -> list[dict[str, Any]]:
        return [entry.to_model_tool_definition() for entry in self._entries]

    def public_items(self) -> list[ToolCatalogItem]:
        return [entry.to_public_item() for entry in self._entries]

    def label_for(self, tool_id: str) -> str:
        entry = self._by_id.get(tool_id)
        if entry is None:
            return f"正在调用 {tool_id}…"
        if entry.status_label:
            return entry.status_label
        if entry.source == "external_mcp":
            return f"正在准备外部 MCP 查询「{entry.title}」确认参数…"
        return f"正在调用 {entry.title}…"


def build_turn_tool_catalog(
    *,
    astronomy_transport: str = "direct",
    include_literature_save: bool = False,
    max_calls_per_turn: int = 6,
    external_entries: list[ToolCatalogEntry] | None = None,
    external_max_calls_per_turn: int = 2,
    skill_allowed_tools: tuple[str, ...] | list[str] | None = None,
) -> TurnToolCatalog:
    """Compute the exact intersection of server catalog, user context, and active skill scope."""
    builtins = builtin_tool_entries(
        astronomy_transport=astronomy_transport,
        include_literature_save=include_literature_save,
        max_calls_per_turn=max_calls_per_turn,
    )
    if skill_allowed_tools is not None:
        allowed_set = set(skill_allowed_tools)
        builtins = [entry for entry in builtins if entry.tool_id in allowed_set]

    combined = list(builtins)
    if external_entries:
        for ext in external_entries:
            if ext.tool_id in BUILTIN_TOOL_NAMES or ext.source != "external_mcp":
                continue
            combined.append(ext)

    return TurnToolCatalog(
        combined,
        external_max_calls_per_turn=external_max_calls_per_turn,
    )
