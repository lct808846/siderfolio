"""V1.5 local-only assistance. Suggestions never authorize scientific tools."""

from typing import Literal

from pydantic import Field, field_validator

from astroagent.conversation_titles import TITLE_MAX_CHARACTERS, TITLE_MIN_CHARACTERS
from astroagent.project_schemas import Contract, Digest, Identifier

Action = Literal["title", "summary", "format", "extract"]
ConditionName = Literal[
    "object_name",
    "source_id",
    "ra",
    "dec",
    "radius",
    "year_start",
    "year_end",
    "ruwe_max",
    "parallax_snr_min",
]
Intent = Literal[
    "object_query",
    "literature_search",
    "gaia_query",
    "plot",
    "knowledge_search",
    "other_or_unclear",
]


class LocalPreferences(Contract):
    revision: int = Field(default=0, ge=0)
    enabled: bool = False
    auto_titles: bool = False


class LocalPreferenceUpdate(Contract):
    expected_revision: int = Field(ge=0)
    enabled: bool
    auto_titles: bool


class LocalInitialize(Contract):
    confirm_create_tables: Literal[True]


class LocalClear(Contract):
    confirm_clear_records: Literal[True]


class LocalProbe(Contract):
    pass


class LocalTaskRequest(Contract):
    action: Action
    text: str = Field(min_length=1, max_length=4000)
    output_format: Literal["paragraph", "bullets", "markdown"] = "bullets"

    @field_validator("text")
    @classmethod
    def bounded_input(cls, value):
        if not value.strip() or len(value.encode("utf-8")) > 4096 or "\x00" in value:
            raise ValueError("Input must be nonblank UTF-8 text within 4 KiB")
        return value


class TitleResult(Contract):
    title: str = Field(min_length=TITLE_MIN_CHARACTERS, max_length=TITLE_MAX_CHARACTERS)


class TextResult(Contract):
    text: str = Field(min_length=1, max_length=4000)
    warnings: list[str] = Field(default_factory=list, max_length=8)


class SourceCondition(Contract):
    field: ConditionName
    status: Literal["explicit", "ambiguous"]
    value: str | None = Field(max_length=128)
    unit: Literal["deg", "arcmin", "mas", "mas/yr", "year"] | None
    comparison: Literal["eq", "lt", "lte", "gt", "gte", "unspecified"]
    evidence: str = Field(min_length=1, max_length=500)


class TaskSuggestion(Contract):
    kind: Intent
    evidence: str = Field(min_length=1, max_length=500)


class ConditionResult(Contract):
    conditions: list[SourceCondition] = Field(max_length=16)
    suggestions: list[TaskSuggestion] = Field(min_length=1, max_length=6)
    missing: list[ConditionName] = Field(max_length=9)
    clarification: list[str] = Field(max_length=6)


class CompactConditionResult(Contract):
    """Typed literal field carrier; evidence is rebuilt and checked by the server."""

    conditions: list[
        tuple[
            ConditionName,
            str | None,
            Literal["deg", "arcmin", "mas", "mas/yr", "year"] | None,
            Literal["eq", "lt", "lte", "gt", "gte", "unspecified"],
        ]
    ] = Field(max_length=16)
    suggestions: list[Intent] = Field(min_length=1, max_length=6)


class IntentResult(Contract):
    suggestions: list[Intent] = Field(min_length=1, max_length=6)


class TextSelection(Contract):
    selected: list[int] = Field(min_length=1, max_length=64)


class LocalTask(Contract):
    id: Identifier
    action: Action
    automatic: bool
    conversation_id: Identifier | None = None
    turn_id: Identifier | None = None
    state: Literal[
        "queued", "running", "completed", "failed", "interrupted", "superseded", "skipped"
    ]
    created_at: str
    completed_at: str | None = None
    input_sha256: Digest
    input_characters: int
    input_truncated: bool
    model: str
    model_digest: str
    metadata_revision: int | None = None
    preferences_revision: int
    request_sha256: Digest
    baseline_title: str | None = None
    membership: str | None = None
    error: str | None = None
    title_applied: bool = False
    output: dict | None = None
    output_available: bool = False
    usage: dict = Field(default_factory=dict)


class LocalTaskView(Contract):
    task: LocalTask
    warning: str = "本地助手结果可能遗漏信息，请自行核对；文本按原文重建，建议不会自动执行工具。"


class LocalStatus(Contract):
    title_max_characters: int = TITLE_MAX_CHARACTERS
    state: Literal["disabled", "unavailable", "model_missing", "identity_mismatch", "ready", "busy"]
    storage_ready: bool
    configured: bool
    preferences: LocalPreferences
    model: str
    model_digest: str
    family: str | None = None
    quantization: str | None = None
    parameter_size: str | None = None
    queue_length: int = 0
    message: str
    resource_hint: str = "约4B参数的本地模型；实际内存、显存、速度和生成质量需在本机验收。"
