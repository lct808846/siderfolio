"""Automatic conversation naming using the local model."""

from typing import Literal

from pydantic import Field

from astroagent.conversation_titles import TITLE_MAX_CHARACTERS, TITLE_MIN_CHARACTERS
from astroagent.project_schemas import Contract, Digest, Identifier


class LocalPreferences(Contract):
    revision: int = Field(default=0, ge=0)
    enabled: bool = False
    auto_titles: bool = False


class LocalPreferenceUpdate(Contract):
    expected_revision: int = Field(ge=0)
    enabled: bool
    auto_titles: bool


class LocalProbe(Contract):
    pass


class TitleResult(Contract):
    title: str = Field(min_length=TITLE_MIN_CHARACTERS, max_length=TITLE_MAX_CHARACTERS)


class LocalTask(Contract):
    id: Identifier
    action: Literal["title"]
    automatic: Literal[True]
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
