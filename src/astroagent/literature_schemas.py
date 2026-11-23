"""天文文献库数据结构、DOI 校验、保存回执与内部入库工具参数。"""

import re
from typing import Literal
from urllib.parse import quote
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator, model_validator

from astroagent.schemas import Source

DOI_PATTERN = re.compile(r"^10\.\d{4,9}/[^\s\"<>\\]+$")
BIBCODE_PATTERN = re.compile(r"^[A-Za-z0-9.&+_-]{4,40}$")
MAX_LITERATURE_BATCH = 10
MAX_LITERATURE_TAGS = 20
MAX_LITERATURE_TAG_LENGTH = 40
MAX_LITERATURE_NOTE_LENGTH = 4000
MAX_LITERATURE_ITEMS_PER_ACCOUNT = 5000


def validate_doi(value: str) -> str | None:
    cleaned = value.strip()
    if cleaned.lower().startswith("https://doi.org/"):
        cleaned = cleaned[16:].strip()
    elif cleaned.lower().startswith("http://doi.org/"):
        cleaned = cleaned[15:].strip()
    elif cleaned.lower().startswith("doi:"):
        cleaned = cleaned[4:].strip()
    if not cleaned or len(cleaned) > 256 or not DOI_PATTERN.fullmatch(cleaned):
        return None
    return cleaned


def verified_doi_urls(dois: list[str]) -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()
    for raw in dois:
        normalized = validate_doi(raw)
        if not normalized or normalized.lower() in seen:
            continue
        seen.add(normalized.lower())
        urls.append(f"https://doi.org/{quote(normalized, safe='/:;()_-')}")
    return urls


def normalize_tags(values: list[str]) -> list[str]:
    cleaned: list[str] = []
    seen: set[str] = set()
    for raw in values:
        tag = " ".join(raw.strip().split())
        if not tag:
            continue
        if len(tag) > MAX_LITERATURE_TAG_LENGTH or "\x00" in tag:
            raise ValueError(f"单个标签长度须在 1–{MAX_LITERATURE_TAG_LENGTH} 字符内且不含非法字符。")
        key = tag.casefold()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(tag)
    if len(cleaned) > MAX_LITERATURE_TAGS:
        raise ValueError(f"每条文献最多设置 {MAX_LITERATURE_TAGS} 个标签。")
    return cleaned


class LiteratureSourceRef(BaseModel):
    conversation_id: str | None = None
    turn_id: str | None = None
    project_id: str | None = None
    snapshot_id: str | None = None
    batch_index: int | None = None
    paper_index: int | None = None
    query: str | None = None
    added_via: Literal["manual", "agent"] = "manual"
    source_available: bool = True


class LiteratureItem(BaseModel):
    id: str
    provider: Literal["ADS"] = "ADS"
    bibcode: str = Field(min_length=1, max_length=64)
    title: str | None = None
    authors: list[str] = Field(default_factory=list)
    year: int | None = Field(default=None, ge=1, le=9999)
    publication: str | None = None
    doi: list[str] = Field(default_factory=list)
    doi_urls: list[str] = Field(default_factory=list)
    abstract: str | None = None
    citation_count: int | None = Field(default=None, ge=0)
    source: Source
    tags: list[str] = Field(default_factory=list)
    note: str = ""
    model_explanation: str | None = None
    origin: LiteratureSourceRef = Field(default_factory=LiteratureSourceRef)
    revision: int = Field(default=1, ge=1)
    created_at: str
    updated_at: str


class LiteratureListResponse(BaseModel):
    items: list[LiteratureItem] = Field(default_factory=list)
    total: int = Field(default=0, ge=0)
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)
    has_more: bool = False
    available_tags: list[str] = Field(default_factory=list)
    available_years: list[int] = Field(default_factory=list)


class LiteratureStatusResponse(BaseModel):
    saved: dict[str, str] = Field(default_factory=dict)


class LiteratureManualAddRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    client_request_id: str
    conversation_id: str | None = None
    turn_id: str | None = None
    project_id: str | None = None
    snapshot_id: str | None = None
    batch_index: StrictInt = Field(default=0, ge=0, le=20)
    paper_indices: list[StrictInt] = Field(default_factory=list, max_length=MAX_LITERATURE_BATCH)
    bibcodes: list[str] = Field(default_factory=list, max_length=MAX_LITERATURE_BATCH)
    tags: list[str] = Field(default_factory=list, max_length=MAX_LITERATURE_TAGS)
    note: str = Field(default="", max_length=MAX_LITERATURE_NOTE_LENGTH)

    @field_validator("client_request_id")
    @classmethod
    def check_request_id(cls, value: str) -> str:
        return str(UUID(value))

    @field_validator("conversation_id", "turn_id", "project_id", "snapshot_id")
    @classmethod
    def check_optional_uuid(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return str(UUID(value))

    @field_validator("paper_indices")
    @classmethod
    def check_indices(cls, values: list[int]) -> list[int]:
        deduped: list[int] = []
        for index in values:
            if index < 1 or index > MAX_LITERATURE_BATCH:
                raise ValueError(f"文献序号须在 1–{MAX_LITERATURE_BATCH} 范围内。")
            if index not in deduped:
                deduped.append(index)
        return deduped

    @field_validator("bibcodes")
    @classmethod
    def check_bibcodes(cls, values: list[str]) -> list[str]:
        deduped: list[str] = []
        for raw in values:
            code = raw.strip()
            if not code or not BIBCODE_PATTERN.fullmatch(code):
                raise ValueError("无效的 ADS bibcode 格式。")
            if code not in deduped:
                deduped.append(code)
        return deduped

    @field_validator("tags")
    @classmethod
    def check_tags(cls, values: list[str]) -> list[str]:
        return normalize_tags(values)

    @model_validator(mode="after")
    def check_origin_and_selection(self):
        has_turn = bool(self.conversation_id and self.turn_id)
        has_snapshot = bool(self.project_id and self.snapshot_id)
        if has_turn == has_snapshot:
            raise ValueError("必须明确提供会话轮次引用或项目快照引用之一。")
        if not self.paper_indices and not self.bibcodes:
            raise ValueError("请至少指定一条文献序号或 bibcode。")
        return self


class LiteratureUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: StrictInt = Field(ge=1)
    tags: list[str] | None = Field(default=None, max_length=MAX_LITERATURE_TAGS)
    note: str | None = Field(default=None, max_length=MAX_LITERATURE_NOTE_LENGTH)

    @field_validator("tags")
    @classmethod
    def check_tags(cls, values: list[str] | None) -> list[str] | None:
        if values is None:
            return None
        return normalize_tags(values)

    @model_validator(mode="after")
    def check_has_update(self):
        if self.tags is None and self.note is None:
            raise ValueError("请提供需要更新的标签或个人备注。")
        if self.note is not None and "\x00" in self.note:
            raise ValueError("备注不能包含空字符。")
        return self


class LiteratureSaveReceiptItem(BaseModel):
    bibcode: str
    item_id: str | None = None
    title: str | None = None
    year: int | None = None
    authors: list[str] = Field(default_factory=list)
    source_url: str | None = None
    status: Literal["added", "already_saved", "rejected", "unverified"]
    reason: str | None = None


class LiteratureSaveReceipt(BaseModel):
    receipt_id: str
    client_request_id: str
    conversation_id: str | None = None
    turn_id: str | None = None
    added_via: Literal["manual", "agent"] = "manual"
    status: Literal["success", "partial", "error"]
    added_count: int = Field(default=0, ge=0)
    already_saved_count: int = Field(default=0, ge=0)
    rejected_count: int = Field(default=0, ge=0)
    replayed: bool = False
    items: list[LiteratureSaveReceiptItem] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    created_at: str


class SaveLiteratureQuery(BaseModel):
    """会话 Agent 内部工具参数：仅允许提交已验证 ADS 批次与位置/bibcode 引用。"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    source_scope: Literal["current_turn", "history_turn"] = Field(
        default="current_turn",
        description=(
            "待保存 ADS 结果所在范围：current_turn 表示本轮 search_ads 返回的批次；"
            "history_turn 表示当前会话历史轮次中已展示的 ADS 批次（须提供 source_turn_id）"
        ),
    )
    source_turn_id: str | None = Field(
        default=None,
        description="当 source_scope=history_turn 时填写该历史轮次的 turn_id（UUID）",
    )
    batch_index: StrictInt = Field(
        default=0,
        ge=0,
        le=9,
        description="该轮次中第几次 ADS 检索结果（0 起，默认 0）",
    )
    paper_indices: list[StrictInt] = Field(
        default_factory=list,
        max_length=MAX_LITERATURE_BATCH,
        description="按该批次返回顺序指定的 1 起文献序号列表（例如 [1, 2, 3] 或 [1, 3]）",
    )
    bibcodes: list[str] = Field(
        default_factory=list,
        max_length=MAX_LITERATURE_BATCH,
        description="可选：待保存条目的真实 ADS bibcode 列表（须真实存在于目标批次中）",
    )
    explanation: str | None = Field(
        default=None,
        max_length=1000,
        description="可选：简短的模型相关性说明（与 ADS 原文摘要、用户个人备注严格分开保存）",
    )
    tags: list[str] = Field(
        default_factory=list,
        max_length=MAX_LITERATURE_TAGS,
        description=(
            "可选：仅当用户当前消息明确要求为新入库文献添加标签时填写（标签须来自用户消息）；"
            "已在库文献将保留原有标签与备注"
        ),
    )

    @field_validator("tags")
    @classmethod
    def check_tags(cls, values: list[str]) -> list[str]:
        return normalize_tags(values)

    @field_validator("source_turn_id")
    @classmethod
    def check_turn_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return str(UUID(value))

    @field_validator("paper_indices")
    @classmethod
    def check_indices(cls, values: list[int]) -> list[int]:
        deduped: list[int] = []
        for index in values:
            if index < 1 or index > MAX_LITERATURE_BATCH:
                raise ValueError(f"paper_indices 中的序号须在 1–{MAX_LITERATURE_BATCH} 之间。")
            if index not in deduped:
                deduped.append(index)
        return deduped

    @field_validator("bibcodes")
    @classmethod
    def check_bibcodes(cls, values: list[str]) -> list[str]:
        deduped: list[str] = []
        for raw in values:
            code = raw.strip()
            if not code or not BIBCODE_PATTERN.fullmatch(code):
                raise ValueError("无效的 bibcode。")
            if code not in deduped:
                deduped.append(code)
        return deduped

    @model_validator(mode="after")
    def check_scope_and_targets(self):
        if self.source_scope == "history_turn" and not self.source_turn_id:
            raise ValueError("引用历史轮次时必须提供 source_turn_id。")
        if self.source_scope == "current_turn" and self.source_turn_id is not None:
            raise ValueError("引用本轮结果时无需提供 source_turn_id。")
        if not self.paper_indices and not self.bibcodes:
            raise ValueError("必须提供至少一个 paper_indices 或 bibcodes 引用。")
        return self
