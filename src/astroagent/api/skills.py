"""V2.1 用户侧科研技能目录、个人启停偏好与只读工具目录接口。"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request

from astroagent.api.conversations import get_service
from astroagent.config import LocalSettings, Settings
from astroagent.mcp_client import effective_astronomy_transport
from astroagent.schemas import ErrorResponse
from astroagent.skill_schemas import SkillPreferences, SkillsCatalogResponse
from astroagent.skills import builtin_skills, summarize_skills
from astroagent.tool_catalog import build_turn_tool_catalog
from astroagent.tool_schemas import UserToolCatalogResponse

router = APIRouter(
    prefix="/api/v1/skills",
    tags=["skills"],
    responses={code: {"model": ErrorResponse} for code in (401, 403, 422, 503)},
)

Service = Annotated[object, Depends(get_service)]


def _current_catalog_context(service):
    local = LocalSettings()
    astro_transport = effective_astronomy_transport(local)
    max_calls = Settings().agent_max_tool_calls
    external_entries = (
        service.external_mcp.approved_tool_entries()
        if getattr(service, "external_mcp", None) is not None
        else []
    )
    catalog = build_turn_tool_catalog(
        astronomy_transport=astro_transport,
        include_literature_save=getattr(service, "literature", None) is not None,
        max_calls_per_turn=max_calls,
        external_entries=external_entries,
        external_max_calls_per_turn=local.external_mcp_max_calls_per_turn,
    )
    return catalog


@router.get("", response_model=SkillsCatalogResponse)
def list_skills(service: Service):
    prefs = (
        service.skills.get_preferences() if getattr(service, "skills", None) else SkillPreferences()
    )
    catalog = _current_catalog_context(service)
    skills = summarize_skills(prefs, available_tool_ids=set(catalog.tool_ids))
    previews = (
        service.external_mcp.approved_previews()
        if getattr(service, "external_mcp", None) is not None
        else []
    )
    return SkillsCatalogResponse(
        skills=skills,
        preferences=prefs,
        approved_external_tools=previews,
    )


@router.put("/preferences", response_model=SkillsCatalogResponse)
def update_skill_preferences(body: SkillPreferences, service: Service):
    valid_ids = {skill.id for skill in builtin_skills()}
    filtered = SkillPreferences(
        auto_match=body.auto_match,
        disabled_skill_ids=[sid for sid in body.disabled_skill_ids if sid in valid_ids],
    )
    saved = (
        service.skills.save_preferences(filtered) if getattr(service, "skills", None) else filtered
    )
    catalog = _current_catalog_context(service)
    skills = summarize_skills(saved, available_tool_ids=set(catalog.tool_ids))
    previews = (
        service.external_mcp.approved_previews()
        if getattr(service, "external_mcp", None) is not None
        else []
    )
    return SkillsCatalogResponse(
        skills=skills,
        preferences=saved,
        approved_external_tools=previews,
    )


@router.get("/tools", response_model=UserToolCatalogResponse)
def list_user_tools(request: Request, service: Service):
    del request
    catalog = _current_catalog_context(service)
    return UserToolCatalogResponse(
        tools=catalog.public_items(),
        tool_manifest_sha256=catalog.manifest_sha256,
    )
