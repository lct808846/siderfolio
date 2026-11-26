"""V2.1 Agent 技能契约、个人偏好与轮次解析快照结构。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

SkillSelectionMode = Literal[
    "explicit",
    "auto",
    "disabled",
    "none",
    "ambiguous",
    "auto_disabled",
]


class SkillMetadataSummary(BaseModel):
    id: str
    title: str
    version: str
    category: str = "general"
    description: str
    content_sha256: str
    allowed_tools: list[str] = Field(default_factory=list)
    intent_keywords: list[str] = Field(default_factory=list)
    example_prompts: list[str] = Field(default_factory=list)
    delivery_summary: str = ""
    boundaries: str = ""
    enabled: bool = True
    required_tools_available: bool = True
    unavailable_tools: list[str] = Field(default_factory=list)


class SkillPreferences(BaseModel):
    model_config = ConfigDict(extra="forbid")

    auto_match: bool = True
    disabled_skill_ids: list[str] = Field(default_factory=list, max_length=32)

    @field_validator("disabled_skill_ids")
    @classmethod
    def unique_clean_ids(cls, value: list[str]) -> list[str]:
        cleaned: list[str] = []
        for item in value:
            text = str(item).strip()
            if text and text not in cleaned:
                cleaned.append(text)
        return cleaned


class SkillResolution(BaseModel):
    skill_id: str | None = None
    skill_title: str | None = None
    skill_version: str | None = None
    content_sha256: str | None = None
    selection_mode: SkillSelectionMode = "none"
    matched_reason: str = ""
    candidate_skill_ids: list[str] = Field(default_factory=list)
    available_tool_ids: list[str] = Field(default_factory=list)
    unavailable_tools: list[str] = Field(default_factory=list)
    tool_manifest_sha256: str | None = None
    clarification_note: str | None = None


class ExternalToolPreview(BaseModel):
    tool_id: str
    server_id: str
    server_title: str
    remote_name: str
    title: str
    description: str
    protocol_version: str
    definition_sha256: str
    requires_confirmation: bool = True


class SkillsCatalogResponse(BaseModel):
    skills: list[SkillMetadataSummary] = Field(default_factory=list)
    preferences: SkillPreferences = Field(default_factory=SkillPreferences)
    approved_external_tools: list[ExternalToolPreview] = Field(default_factory=list)
