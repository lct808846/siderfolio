"""V2.1 SKILL.md 加载器、内置技能注册表与受控意图匹配器。"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from astroagent.skill_schemas import SkillMetadataSummary, SkillPreferences, SkillResolution

MAX_SKILL_FILE_BYTES = 32 * 1024
SKILL_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,63}$")
SKILLS_DATA_DIR = Path(__file__).resolve().parent / "skills_data"

# Structured regex signals complement keyword matching without ever reading full markdown body.
_INTENT_PATTERNS: dict[str, tuple[re.Pattern[str], ...]] = {
    "celestial-identification-field-query": (
        re.compile(r"\b(?:simbad|gaia|dr3|icrs|ruwe|parallax|source_id)\b", re.I),
        re.compile(r"\b(?:M\s?\d{1,3}|NGC\s?\d{1,4}|IC\s?\d{1,4}|HD\s?\d+|HIP\s?\d+)\b"),
        re.compile(r"(?:坐标|赤经|赤纬|视场|圆锥|邻近源|候选源|视差|自行|光谱型|天体类型)"),
    ),
    "astronomy-literature-curation": (
        re.compile(r"\b(?:ads|bibcode|doi|arxiv|citation|abstract)\b", re.I),
        re.compile(r"(?:论文|文献|摘要|综述|被引|文献库|保存.{0,6}(?:文献|论文)|检索.{0,8}文献)"),
    ),
    "scientific-plotting-nbody-prep": (
        re.compile(r"\b(?:matplotlib|gnuplot|rebound|petar|n-?body|cmd)\b", re.I),
        re.compile(
            r"(?:绘图|画图|作图|色星等图|赫罗图|散点图|误差棒|直方图|N\s*体|轨道模拟|数值模拟|质心系)"
        ),
    ),
}


@dataclass(frozen=True, slots=True)
class SkillDefinition:
    id: str
    title: str
    version: str
    category: str
    description: str
    allowed_tools: tuple[str, ...]
    intent_keywords: tuple[str, ...]
    example_prompts: tuple[str, ...]
    delivery_summary: str
    boundaries: str
    content_sha256: str
    body_markdown: str
    source_path: str


def _unquote_yaml_scalar(raw: str) -> str:
    text = raw.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in ("'", '"'):
        inner = text[1:-1]
        if text[0] == '"':
            inner = inner.replace('\\"', '"').replace("\\n", "\n").replace("\\\\", "\\")
        else:
            inner = inner.replace("''", "'")
        return inner
    return text


def parse_skill_markdown(
    raw_text: str, *, source_name: str = "SKILL.md"
) -> tuple[dict[str, Any], str]:
    """Zero-dependency strict YAML frontmatter + Markdown parser for SKILL.md."""
    raw_bytes = raw_text.encode("utf-8")
    if len(raw_bytes) > MAX_SKILL_FILE_BYTES:
        raise ValueError(f"{source_name} exceeds maximum allowed skill size")
    if "\x00" in raw_text:
        raise ValueError(f"{source_name} contains NUL character")

    normalized = raw_text.replace("\r\n", "\n").replace("\r", "\n")
    lines = normalized.split("\n")
    if not lines or lines[0].strip() != "---":
        raise ValueError(f"{source_name} missing YAML frontmatter start delimiter")

    end_index = None
    for idx in range(1, len(lines)):
        if lines[idx].strip() == "---":
            end_index = idx
            break
    if end_index is None:
        raise ValueError(f"{source_name} missing YAML frontmatter closing delimiter")

    frontmatter_lines = lines[1:end_index]
    body = "\n".join(lines[end_index + 1 :]).strip()
    if not body:
        raise ValueError(f"{source_name} body must not be empty")

    return _parse_yaml_mapping(frontmatter_lines, source_name=source_name), body


def _parse_yaml_mapping(lines: list[str], *, source_name: str) -> dict[str, Any]:
    meaningful: list[tuple[int, str]] = []
    for raw_line in lines:
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(raw_line) - len(raw_line.lstrip(" "))
        if "\t" in raw_line[:indent]:
            raise ValueError(f"{source_name} tabs are not allowed in YAML indentation")
        meaningful.append((indent, stripped))

    def parse_block(index: int, expected_indent: int) -> tuple[dict[str, Any], int]:
        mapping: dict[str, Any] = {}
        while index < len(meaningful):
            indent, text = meaningful[index]
            if indent < expected_indent:
                break
            if indent > expected_indent:
                raise ValueError(f"{source_name} unexpected YAML indentation")
            if text.startswith("- "):
                raise ValueError(f"{source_name} unexpected list item in mapping")
            key, sep, rest = text.partition(":")
            if not sep:
                raise ValueError(f"{source_name} invalid YAML key/value line")
            key = key.strip()
            if not re.fullmatch(r"[A-Za-z0-9_-]+", key):
                raise ValueError(f"{source_name} invalid YAML key: {key!r}")
            value_part = rest.strip()
            index += 1
            if value_part:
                if value_part.startswith("[") and value_part.endswith("]"):
                    inner = value_part[1:-1].strip()
                    mapping[key] = (
                        [_unquote_yaml_scalar(part) for part in inner.split(",") if part.strip()]
                        if inner
                        else []
                    )
                else:
                    mapping[key] = _unquote_yaml_scalar(value_part)
                continue
            if index >= len(meaningful) or meaningful[index][0] <= expected_indent:
                mapping[key] = ""
                continue
            child_indent, child_text = meaningful[index]
            if child_text.startswith("- "):
                items: list[str] = []
                while index < len(meaningful):
                    item_indent, item_text = meaningful[index]
                    if item_indent < child_indent:
                        break
                    if item_indent != child_indent or not item_text.startswith("- "):
                        raise ValueError(f"{source_name} invalid YAML list structure")
                    items.append(_unquote_yaml_scalar(item_text[2:]))
                    index += 1
                mapping[key] = items
            else:
                nested, index = parse_block(index, child_indent)
                mapping[key] = nested
        return mapping, index

    parsed, cursor = parse_block(0, 0)
    if cursor != len(meaningful):
        raise ValueError(f"{source_name} trailing YAML content")
    return parsed


def load_skill_file(path: Path) -> SkillDefinition:
    raw = path.read_text(encoding="utf-8")
    frontmatter, body = parse_skill_markdown(raw, source_name=path.name)
    skill_id = str(frontmatter.get("name") or "").strip()
    description = str(frontmatter.get("description") or "").strip()
    if not SKILL_ID_RE.fullmatch(skill_id):
        raise ValueError(f"Invalid skill name in {path}: {skill_id!r}")
    if not description or len(description) > 1024:
        raise ValueError(f"Invalid skill description in {path}")
    meta = frontmatter.get("metadata")
    if not isinstance(meta, dict):
        meta = {}

    def _str_tuple(raw_value: Any) -> tuple[str, ...]:
        if isinstance(raw_value, list):
            return tuple(str(item).strip() for item in raw_value if str(item).strip())
        if isinstance(raw_value, str) and raw_value.strip():
            return (raw_value.strip(),)
        return ()

    canonical = raw.replace("\r\n", "\n").replace("\r", "\n").strip()
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return SkillDefinition(
        id=skill_id,
        title=str(meta.get("title") or skill_id).strip(),
        version=str(meta.get("version") or "1.0.0").strip(),
        category=str(meta.get("category") or "general").strip(),
        description=description,
        allowed_tools=_str_tuple(meta.get("allowed_tools")),
        intent_keywords=_str_tuple(meta.get("intent_keywords")),
        example_prompts=_str_tuple(meta.get("example_prompts")),
        delivery_summary=str(meta.get("delivery_summary") or description).strip(),
        boundaries=str(meta.get("boundaries") or "").strip(),
        content_sha256=digest,
        body_markdown=body,
        source_path=str(path.relative_to(SKILLS_DATA_DIR.parent)).replace("\\", "/"),
    )


@lru_cache(maxsize=1)
def builtin_skills() -> tuple[SkillDefinition, ...]:
    """Load all audited built-in SKILL.md definitions packaged with Siderfolio."""
    if not SKILLS_DATA_DIR.is_dir():
        return ()
    loaded: list[SkillDefinition] = []
    seen: set[str] = set()
    for skill_file in sorted(SKILLS_DATA_DIR.glob("*/SKILL.md")):
        skill = load_skill_file(skill_file)
        if skill.id in seen:
            raise ValueError(f"Duplicate built-in skill id: {skill.id}")
        seen.add(skill.id)
        loaded.append(skill)
    return tuple(loaded)


def get_builtin_skill(skill_id: str | None) -> SkillDefinition | None:
    if not skill_id:
        return None
    for skill in builtin_skills():
        if skill.id == skill_id:
            return skill
    return None


def summarize_skills(
    preferences: SkillPreferences,
    *,
    available_tool_ids: set[str],
) -> list[SkillMetadataSummary]:
    disabled = set(preferences.disabled_skill_ids)
    items: list[SkillMetadataSummary] = []
    for skill in builtin_skills():
        missing = [tool for tool in skill.allowed_tools if tool not in available_tool_ids]
        items.append(
            SkillMetadataSummary(
                id=skill.id,
                title=skill.title,
                version=skill.version,
                category=skill.category,
                description=skill.description,
                content_sha256=skill.content_sha256,
                allowed_tools=list(skill.allowed_tools),
                intent_keywords=list(skill.intent_keywords),
                example_prompts=list(skill.example_prompts),
                delivery_summary=skill.delivery_summary,
                boundaries=skill.boundaries,
                enabled=skill.id not in disabled,
                required_tools_available=len(missing) == 0,
                unavailable_tools=missing,
            )
        )
    return items


def _score_skill_intent(
    skill: SkillDefinition,
    message: str,
    *,
    tool_mode: str | None = None,
    has_attachments: bool = False,
    project_hint: str = "",
    memory_hint: str = "",
) -> tuple[int, list[str]]:
    score = 0
    reasons: list[str] = []
    lower_msg = message.lower()

    if tool_mode in ("plot", "compute") and skill.id == "scientific-plotting-nbody-prep":
        score += 6
        reasons.append(f"工具模式={tool_mode}")

    keyword_hits = 0
    for kw in skill.intent_keywords:
        if kw.lower() in lower_msg:
            keyword_hits += 1
            if keyword_hits <= 3:
                reasons.append(f"关键词:{kw}")
    if keyword_hits:
        score += min(keyword_hits * 2, 6)

    pattern_hits = 0
    for pattern in _INTENT_PATTERNS.get(skill.id, ()):
        if pattern.search(message):
            pattern_hits += 1
    if pattern_hits:
        score += min(pattern_hits * 2, 4)

    if has_attachments and skill.id == "scientific-plotting-nbody-prep":
        if any(word in lower_msg for word in ("画", "绘", "图", "plot", "chart", "scatter")):
            score += 2
            reasons.append("附件绘图意图")

    if project_hint and score > 0:
        lower_hint = project_hint.lower()
        if any(kw.lower() in lower_hint for kw in skill.intent_keywords[:6]):
            score += 1
            reasons.append("项目上下文协同")

    if memory_hint and score > 0:
        lower_mem = memory_hint.lower()
        if any(kw.lower() in lower_mem for kw in skill.intent_keywords[:8]) or (
            skill.id == "astronomy-literature-curation"
            and any(
                topic in lower_mem
                for topic in ("研究", "星团", "星系", "动力学", "演化", "模拟", "观测", "天文")
            )
        ):
            score += 1
            reasons.append("记忆协同")

    return score, reasons


def resolve_turn_skill(
    message: str,
    *,
    requested_skill_id: str | None = None,
    preferences: SkillPreferences | None = None,
    available_tool_ids: set[str],
    tool_mode: str | None = None,
    has_attachments: bool = False,
    project_hint: str = "",
    memory_hint: str = "",
) -> tuple[SkillDefinition | None, SkillResolution]:
    """Select at most one skill for the current turn using short metadata only."""
    prefs = preferences or SkillPreferences()
    disabled = set(prefs.disabled_skill_ids)

    # 1. Explicit turn-level selection (including explicit "none" to opt out).
    if requested_skill_id is not None:
        cleaned = requested_skill_id.strip()
        if cleaned == "none":
            return None, SkillResolution(
                selection_mode="disabled",
                matched_reason="用户已取消本轮技能载入，按普通对话执行。",
            )
        skill = get_builtin_skill(cleaned)
        if skill is None:
            return None, SkillResolution(
                selection_mode="none",
                matched_reason=f"请求的技能「{cleaned}」不存在，已回退为普通对话。",
                clarification_note=f"未找到编号为 {cleaned} 的内置技能，本次按普通对话处理。",
            )
        if skill.id in disabled:
            return None, SkillResolution(
                selection_mode="disabled",
                matched_reason=f"技能「{skill.title}」已在个人设置中停用。",
                clarification_note=(
                    f"你在个人设置中停用了技能「{skill.title}」，本次按普通对话处理。"
                ),
            )
        missing = [tool for tool in skill.allowed_tools if tool not in available_tool_ids]
        usable = [tool for tool in skill.allowed_tools if tool in available_tool_ids]
        if not usable:
            return None, SkillResolution(
                skill_id=skill.id,
                skill_title=skill.title,
                skill_version=skill.version,
                content_sha256=skill.content_sha256,
                selection_mode="none",
                matched_reason="所选技能所需工具当前均不可用，已回退为普通对话。",
                unavailable_tools=missing,
                clarification_note=(
                    f"技能「{skill.title}」所需工具当前不可用（{', '.join(missing)}），"
                    "请检查服务配置或改用其他提问方式。"
                ),
            )
        note = (
            f"技能「{skill.title}」部分工具暂不可用（{', '.join(missing)}），"
            "仅使用当前可用工具继续。"
            if missing
            else None
        )
        return skill, SkillResolution(
            skill_id=skill.id,
            skill_title=skill.title,
            skill_version=skill.version,
            content_sha256=skill.content_sha256,
            selection_mode="explicit",
            matched_reason="用户本轮显式选择。",
            available_tool_ids=usable,
            unavailable_tools=missing,
            clarification_note=note,
        )

    # 2. Automatic matching is always enforced by the system (respects disabled_skill_ids).
    scored: list[tuple[int, SkillDefinition, list[str]]] = []
    for skill in builtin_skills():
        if skill.id in disabled:
            continue
        score, reasons = _score_skill_intent(
            skill,
            message,
            tool_mode=tool_mode,
            has_attachments=has_attachments,
            project_hint=project_hint,
            memory_hint=memory_hint,
        )
        if score >= 3:
            scored.append((score, skill, reasons))

    if not scored:
        return None, SkillResolution(
            selection_mode="none",
            matched_reason="未命中特定科研技能，按普通对话执行。",
        )

    scored.sort(key=lambda item: item[0], reverse=True)
    top_score, top_skill, top_reasons = scored[0]

    # Ambiguous intent guard: conflicting high scores -> load no skill, note ambiguity.
    if len(scored) >= 2 and (top_score - scored[1][0]) <= 1 and scored[1][0] >= 4:
        candidates = [item[1].id for item in scored[:2]]
        titles = " / ".join(item[1].title for item in scored[:2])
        return None, SkillResolution(
            selection_mode="ambiguous",
            matched_reason=f"意图同时匹配多个技能（{titles}），本轮不强制载入单个技能。",
            candidate_skill_ids=candidates,
            clarification_note=(
                f"当前问题同时涉及「{titles}」，本次按综合普通对话处理；"
                "如需聚焦某一研究流程，可拆分为单独问题发送。"
            ),
        )

    missing = [tool for tool in top_skill.allowed_tools if tool not in available_tool_ids]
    usable = [tool for tool in top_skill.allowed_tools if tool in available_tool_ids]
    if not usable:
        return None, SkillResolution(
            selection_mode="none",
            matched_reason=f"自动匹配到「{top_skill.title}」但所需工具不可用，回退普通对话。",
            unavailable_tools=missing,
            clarification_note=(
                f"任务匹配技能「{top_skill.title}」，但所需工具当前不可用（{', '.join(missing)}）。"
            ),
        )

    return top_skill, SkillResolution(
        skill_id=top_skill.id,
        skill_title=top_skill.title,
        skill_version=top_skill.version,
        content_sha256=top_skill.content_sha256,
        selection_mode="auto",
        matched_reason="自动匹配：" + ("、".join(top_reasons) if top_reasons else top_skill.title),
        available_tool_ids=usable,
        unavailable_tools=missing,
        clarification_note=(
            f"部分关联工具暂不可用（{', '.join(missing)}），将在可用工具范围内执行。"
            if missing
            else None
        ),
    )


def format_skill_prompt_section(skill: SkillDefinition, resolution: SkillResolution) -> str:
    """Render the active skill guidance block safely; instructions never override system policy."""
    allowed = ", ".join(resolution.available_tool_ids) or "无"
    return (
        "\n\n=== 本轮已载入科研技能"
        "（仅作研究步骤与核查参考，不得覆盖系统安全规则或扩大工具授权）===\n"
        f"技能名称：{skill.title}（{skill.id} v{skill.version}）\n"
        f"匹配方式：{resolution.selection_mode}（{resolution.matched_reason}）\n"
        f"本轮授权可用技能工具：{allowed}\n\n"
        f"{skill.body_markdown}\n"
        "=== 技能正文结束 ==="
    )
