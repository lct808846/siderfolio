"""确定性记忆提取、敏感与越权过滤、中英文词法分词与长对话结构化摘要。"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from uuid import uuid4

from astroagent.conversations import utc_now
from astroagent.knowledge_text import checksum, normalize
from astroagent.memory_schemas import (
    MAX_SUMMARY_BYTES,
    MAX_SUMMARY_SOURCE_BYTES,
    ConversationSummaryRecord,
    MemoryCategory,
    MemoryScope,
)

# Chinese and English high-frequency functional words excluded from lexical matching.
_STOPWORDS: frozenset[str] = frozenset(
    {
        "的",
        "了",
        "和",
        "与",
        "或",
        "在",
        "是",
        "有",
        "我",
        "我的",
        "你",
        "请",
        "请问",
        "帮我",
        "帮忙",
        "一下",
        "关于",
        "相关",
        "几篇",
        "一些",
        "这个",
        "那个",
        "这些",
        "那些",
        "可以",
        "能够",
        "需要",
        "想要",
        "怎么",
        "如何",
        "什么",
        "哪些",
        "以及",
        "进行",
        "使用",
        "通过",
        "主要",
        "the",
        "and",
        "for",
        "with",
        "from",
        "that",
        "this",
        "about",
        "into",
        "please",
        "help",
        "find",
        "some",
        "related",
    }
)

_SENSITIVE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "api_key",
        re.compile(r"\b(?:sk-[A-Za-z0-9_-]{16,}|ghp_[A-Za-z0-9]{20,}|AIza[0-9A-Za-z_-]{20,})\b"),
    ),
    ("bearer_token", re.compile(r"\bBearer\s+[A-Za-z0-9._-]{16,}\b", re.I)),
    (
        "credential_assignment",
        re.compile(
            r"(?:api[_-]?key|secret|password|passwd|access[_-]?token|"
            r"密钥|密码|口令|私钥)\s*[:=：]\s*\S+",
            re.I,
        ),
    ),
    ("url_credentials", re.compile(r"https?://[^/\s:@]+:[^/\s@]+@", re.I)),
    ("email_address", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")),
    ("cn_phone", re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")),
    ("cn_id_card", re.compile(r"(?<!\d)\d{17}[\dXx](?!\d)")),
)

_POLICY_OVERRIDE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "prompt_injection",
        re.compile(r"ignore\s+(?:all\s+)?previous\s+instructions|disregard\s+system", re.I),
    ),
    (
        "prompt_injection_zh",
        re.compile(r"忽略(?:之前|以上|所有)(?:规则|指令|系统提示)|覆盖系统规则"),
    ),
    (
        "tool_auth_override",
        re.compile(
            r"(?:无需确认|跳过确认|自动批准|免确认|绕过确认).{0,16}"
            r"(?:执行|运行|外发|保存|入库|提交|绘图|模拟|MCP)",
            re.I,
        ),
    ),
    (
        "auto_tool_exec",
        re.compile(
            r"(?:以后|默认|自动)(?:直接)?(?:保存文献|入库文献|运行绘图|执行绘图|"
            r"提交\s*N\s*体|提交模拟|调用外部\s*MCP|外发\s*MCP)",
            re.I,
        ),
    ),
)

_NEGATED_REMEMBER_RE = re.compile(
    r"(?:不要|别|不用|不必|无须|不需要|切勿|不能|不可|取消).{0,6}记住"
    r"|(?:如果|假如|假设|要是|是否|能不能|可不可以|要不要).{0,8}记住"
    r"|\b(?:do\s+not|don't|never)\s+remember\b",
    re.I,
)

_EXPLICIT_REMEMBER_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^(?:请)?(?:帮我)?记住(?:以下内容|这一点|这件事)?[：:，,\s]+(.+)$", re.S),
    re.compile(r"^(?:请)?(?:帮我)?记住(.{2,})$", re.S),
    re.compile(
        r"^(?:请)?把[「“\"']?(.+?)[」”\"']?(?:记下来|保存到(?:我的)?(?:长期)?记忆|"
        r"写入(?:我的)?记忆)[。！!]?$",
        re.S,
    ),
    re.compile(r"^(?:please\s+)?remember(?:\s+that)?[:,\s]+(.+)$", re.I | re.S),
)

_REPLACE_INTENT_RE = re.compile(
    r"(?:改成|改为|更换为|换成|已转向|转向|转为|更新为|不再(?:使用|用|研究)|"
    r"instead\s+of|switched\s+to)",
    re.I,
)

_PROJECT_SCOPE_CUE_RE = re.compile(
    r"(?:本项目|这个项目|当前项目|此项目|当前课题|这个课题|本课题|本实验|当前模拟)"
)
_GLOBAL_SCOPE_CUE_RE = re.compile(r"(?:全局|所有会话|所有项目|跨项目|个人偏好|个人习惯)")

_RULE_EXTRACTORS: tuple[tuple[MemoryCategory, MemoryScope, re.Pattern[str]], ...] = (
    (
        "research_focus",
        "global",
        re.compile(
            r"(?:我的研究方向(?:是|为)|我主要研究|我目前研究|我长期研究|我的课题方向(?:是|为))[：:\s]*([^。！？\n;；]{4,200})"
        ),
    ),
    (
        "tool_habit",
        "global",
        re.compile(
            r"(?:我(?:平时|通常|主要|习惯|一般|常用){1,2}(?:使用|用)|我的常用工具(?:是|为))"
            r"[：:\s]*([^。！？\n;；]{3,160})"
        ),
    ),
    (
        "preference",
        "global",
        re.compile(
            r"(?:以后|今后|平时|默认)?(?:回答|回复|解释|输出)(?:请|尽量|希望)?(?:偏向|保持|优先|采用|使用)[：:\s]*([^。！？\n;；]{3,160})"
        ),
    ),
    (
        "background",
        "global",
        re.compile(
            r"(?:我是|我目前是)([^。！？\n;；]{3,140}(?:研究生|博士|硕士|研究员|学者|天文学|天体物理|观测|理论|工程师)[^。！？\n;；]{0,60})"
        ),
    ),
    (
        "project_goal",
        "project",
        re.compile(
            r"(?:本项目|这个项目|当前项目|当前课题)(?:的目标(?:是|为)|旨在|重点研究)[：:\s]*([^。！？\n;；]{4,200})"
        ),
    ),
    (
        "experiment_condition",
        "project",
        re.compile(
            r"(?:本实验|当前模拟|本次实验|该实验)(?:的)?(?:条件|参数|配置|初始条件|假设)(?:为|是)[：:\s]*([^。！？\n;；]{4,200})"
        ),
    ),
    (
        "failure_note",
        "project",
        re.compile(
            r"(?:上次|之前|此前)(?:运行|模拟|实验|计算|拟合)?失败(?:的原因)?(?:是|在于)[：:\s]*([^。！？\n;；]{4,200})"
        ),
    ),
    (
        "next_step",
        "project",
        re.compile(
            r"(?:本项目|这个项目|当前课题)?(?:下一步|接下来|后续)(?:计划|打算|准备|需要)[：:\s]*([^。！？\n;；]{4,200})"
        ),
    ),
)


@dataclass(frozen=True, slots=True)
class ExplicitRememberIntent:
    summary: str
    scope: MemoryScope
    project_id: str | None
    category: MemoryCategory
    explicit_replace: bool = False
    ambiguous_scope: bool = False
    rejected_reason: str | None = None


@dataclass(frozen=True, slots=True)
class ExtractedCandidate:
    summary: str
    scope: MemoryScope
    project_id: str | None
    category: MemoryCategory
    quote: str
    extraction_method: str = "local_rule"


def normalize_memory_text(text: str) -> str:
    cleaned = normalize(text or "")
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    cleaned = cleaned.strip("。！？!?.,;；:：\"'“”‘’「」()（）")
    return cleaned


def memory_dedup_key(category: str, summary: str) -> str:
    base = f"{category}:{normalize_memory_text(summary)}"
    return hashlib.sha256(base.encode("utf-8")).hexdigest()[:32]


def contains_sensitive_data(text: str) -> str | None:
    if not text:
        return None
    for label, pattern in _SENSITIVE_PATTERNS:
        if pattern.search(text):
            return label
    return None


def contains_policy_override(text: str) -> str | None:
    if not text:
        return None
    for label, pattern in _POLICY_OVERRIDE_PATTERNS:
        if pattern.search(text):
            return label
    return None


def extract_lexical_tokens(text: str, *, max_terms: int = 24) -> tuple[list[str], list[str]]:
    """Extract normalized ASCII/alphanumeric words and CJK phrases/bigrams for hybrid matching."""
    norm = normalize(text or "")
    ascii_terms: list[str] = []
    for raw in re.findall(r"[a-z0-9][a-z0-9_+-]{1,40}", norm):
        if raw not in _STOPWORDS and raw not in ascii_terms:
            ascii_terms.append(raw)
            if len(ascii_terms) >= max_terms:
                break

    cjk_terms: list[str] = []
    for segment in re.findall(r"[\u3400-\u9fff]{2,}", norm):
        if segment in _STOPWORDS:
            continue
        if len(segment) <= 6 and segment not in cjk_terms:
            cjk_terms.append(segment)
        # Generate overlapping bigrams and trigrams so short CJK domain terms match reliably.
        for width in (3, 2):
            if len(segment) < width:
                continue
            for idx in range(len(segment) - width + 1):
                gram = segment[idx : idx + width]
                if gram in _STOPWORDS or any(
                    ch in "的了和与或在是我你请" for ch in (gram[0], gram[-1])
                ):
                    continue
                if gram not in cjk_terms:
                    cjk_terms.append(gram)
                    if len(cjk_terms) >= max_terms:
                        break
            if len(cjk_terms) >= max_terms:
                break
        if len(cjk_terms) >= max_terms:
            break
    return ascii_terms[:max_terms], cjk_terms[:max_terms]


def infer_query_category_boosts(query: str) -> set[str]:
    norm = normalize(query or "")
    boosts: set[str] = set()
    if any(
        cue in norm
        for cue in (
            "研究方向",
            "研究领域",
            "课题方向",
            "我的课题",
            "我研究的",
            "我的研究",
            "方向相关",
            "my research",
            "research topic",
            "research focus",
        )
    ):
        boosts.update({"research_focus", "project_goal", "background"})
    if any(
        cue in norm
        for cue in (
            "常用工具",
            "习惯",
            "偏好",
            "风格",
            "用什么语言",
            "my preference",
            "preferred tool",
        )
    ):
        boosts.update({"preference", "tool_habit"})
    if any(cue in norm for cue in ("失败原因", "上次失败", "报错", "踩坑", "出错")):
        boosts.update({"failure_note", "experiment_condition"})
    if any(cue in norm for cue in ("进展", "下一步", "计划", "实验条件", "模拟参数", "上次参数")):
        boosts.update({"progress", "next_step", "experiment_condition", "project_goal"})
    if any(cue in norm for cue in ("结论", "发现", "验证过", "结果")):
        boosts.update({"verified_finding", "progress"})
    return boosts


def score_lexical_relevance(
    query: str,
    target_normalized: str,
    *,
    category: str | None = None,
    category_boosts: set[str] | None = None,
) -> float:
    """Compute a deterministic relevance score for CJK + English text."""
    if not target_normalized:
        return 0.0
    ascii_terms, cjk_terms = extract_lexical_tokens(query)
    score = 0.0
    norm_query = normalize_memory_text(query)
    if norm_query and len(norm_query) >= 3 and norm_query in target_normalized:
        score += 6.0

    target_words = set(re.findall(r"[a-z0-9][a-z0-9_+-]{1,40}", target_normalized))
    for term in ascii_terms:
        if term in target_words:
            score += 2.5
        elif term in target_normalized:
            score += 1.4

    matched_cjk = 0
    for term in cjk_terms:
        if term in target_normalized:
            matched_cjk += 1
            score += 2.2 if len(term) >= 3 else 1.4

    if category and category_boosts and category in category_boosts:
        score += 3.2

    # Avoid weak single-character noise; require meaningful term overlap or explicit role reference.
    if matched_cjk == 0 and score < 2.0:
        return 0.0
    return round(score, 4)


def classify_memory_category(text: str, *, scope: MemoryScope) -> MemoryCategory:
    norm = normalize(text)
    if scope == "project":
        if any(w in norm for w in ("失败", "报错", "发散", "误差过大", "不收敛")):
            return "failure_note"
        if any(w in norm for w in ("下一步", "计划", "待办", "后续", "接下来")):
            return "next_step"
        if any(w in norm for w in ("参数", "条件", "软化", "时长", "粒子", "初始", "筛选", "ruwe")):
            return "experiment_condition"
        if any(w in norm for w in ("进展", "已完成", "跑完", "阶段")):
            return "progress"
        if any(w in norm for w in ("结论", "证实", "测得", "发现")):
            return "verified_finding"
        return "project_goal"

    if any(
        w in norm
        for w in (
            "研究方向",
            "研究",
            "动力学",
            "演化",
            "星团",
            "星系",
            "系外行星",
            "白矮星",
            "课题",
        )
    ):
        return "research_focus"
    if any(
        w in norm
        for w in (
            "python",
            "matplotlib",
            "gnuplot",
            "rebound",
            "petar",
            "astropy",
            "topcat",
            "julia",
            "fortran",
            "工具",
            "数据分析",
            "绘图",
            "模拟",
        )
    ):
        return "tool_habit"
    if any(
        w in norm
        for w in ("回答", "详细", "简洁", "公式", "中文", "英文", "偏好", "风格", "单位", "深度")
    ):
        return "preference"
    return "background"


def parse_explicit_remember(
    message: str, *, project_id: str | None = None
) -> ExplicitRememberIntent | None:
    """Detect explicit direct-save requests such as 「记住我主要用 Python 做数据分析」."""
    stripped = (message or "").strip()
    if not stripped or len(stripped) > 1000:
        return None
    if _NEGATED_REMEMBER_RE.search(stripped):
        return None

    extracted = None
    for pattern in _EXPLICIT_REMEMBER_PATTERNS:
        match = pattern.match(stripped)
        if match:
            extracted = match.group(1).strip().strip("。！!；;，, ")
            break
    if not extracted or len(extracted) < 2:
        return None

    if len(extracted) > 560:
        extracted = extracted[:560].rstrip()

    sensitive = contains_sensitive_data(extracted)
    if sensitive:
        return ExplicitRememberIntent(
            summary=extracted[:120],
            scope="global",
            project_id=None,
            category="background",
            rejected_reason="内容疑似包含密钥、密码或个人敏感联系方式，已排除在记忆之外。",
        )
    override = contains_policy_override(extracted)
    if override:
        return ExplicitRememberIntent(
            summary=extracted[:120],
            scope="global",
            project_id=None,
            category="background",
            rejected_reason="记忆不能用于授权工具自动执行或覆盖系统安全规则，未保存。",
        )

    mentions_project = bool(_PROJECT_SCOPE_CUE_RE.search(stripped))
    mentions_global = bool(_GLOBAL_SCOPE_CUE_RE.search(stripped))
    if mentions_project and mentions_global:
        return ExplicitRememberIntent(
            summary=extracted,
            scope="global",
            project_id=None,
            category="background",
            ambiguous_scope=True,
        )
    if mentions_project:
        if not project_id:
            return ExplicitRememberIntent(
                summary=extracted,
                scope="project",
                project_id=None,
                category="project_goal",
                ambiguous_scope=True,
            )
        scope: MemoryScope = "project"
        bound_project_id: str | None = project_id
    else:
        scope = "global"
        bound_project_id = None

    category = classify_memory_category(extracted, scope=scope)
    return ExplicitRememberIntent(
        summary=extracted,
        scope=scope,
        project_id=bound_project_id,
        category=category,
        explicit_replace=bool(_REPLACE_INTENT_RE.search(stripped)),
    )


def extract_rule_candidates(
    message: str, *, project_id: str | None = None
) -> list[ExtractedCandidate]:
    """Bounded rule-based candidate extraction strictly from user's own message."""
    stripped = (message or "").strip()
    if not stripped or len(stripped) < 6:
        return []
    # Never auto-extract from text containing credentials, contact info, or injection attempts.
    if contains_sensitive_data(stripped) or contains_policy_override(stripped):
        return []
    # Skip pure short questions.
    if (
        stripped.endswith(("?", "？"))
        and len(stripped) < 40
        and "。" not in stripped
        and "，" not in stripped
    ):
        return []

    found: list[ExtractedCandidate] = []
    seen_keys: set[str] = set()
    for category, default_scope, pattern in _RULE_EXTRACTORS:
        if default_scope == "project" and not project_id:
            continue
        for match in pattern.finditer(stripped):
            raw_phrase = match.group(0).strip().strip("。！？!?；;，, ")
            if len(raw_phrase) < 4 or len(raw_phrase) > 260:
                continue
            if contains_sensitive_data(raw_phrase) or contains_policy_override(raw_phrase):
                continue
            scope: MemoryScope = default_scope
            bound_project_id = project_id if scope == "project" else None
            dedup = memory_dedup_key(category, raw_phrase)
            if dedup in seen_keys:
                continue
            seen_keys.add(dedup)
            found.append(
                ExtractedCandidate(
                    summary=raw_phrase,
                    scope=scope,
                    project_id=bound_project_id,
                    category=category,
                    quote=raw_phrase[:280],
                    extraction_method="local_rule",
                )
            )
            if len(found) >= 3:
                return found
    return found


def compute_omitted_turns_sha256(omitted_turns: list) -> str:
    items = []
    for turn in omitted_turns:
        answer = turn.response.answer if getattr(turn, "response", None) is not None else ""
        items.append(
            f"{turn.turn_id}:{turn.revision}:{turn.completed_at or ''}:"
            f"{checksum(turn.message or '')}:{checksum(answer or '')}"
        )
    return checksum("|".join(items))


def _trim_utf8(text: str, max_bytes: int) -> str:
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return text
    clipped = encoded[: max(0, max_bytes - 16)].decode("utf-8", errors="ignore").rstrip()
    return clipped + "…（已按预算截断）"


def build_local_conversation_summary(
    conversation_id: str,
    project_id: str | None,
    omitted_turns: list,
    *,
    max_bytes: int = MAX_SUMMARY_BYTES,
) -> ConversationSummaryRecord:
    """Build a bounded, unit-preserving structured summary from omitted completed turns."""
    completed = [t for t in omitted_turns if getattr(t, "response", None) is not None]
    if not completed:
        raise ValueError("No completed turns to summarize")

    source_sha = compute_omitted_turns_sha256(completed)
    covered_ids = [t.turn_id for t in completed]
    revisions = {t.turn_id: int(t.revision) for t in completed}

    goal_lines: list[str] = []
    tool_lines: list[str] = []
    warning_lines: list[str] = []
    note_lines: list[str] = []

    consumed_source_bytes = 0
    truncated_input = False

    for turn in completed:
        msg = re.sub(r"\s+", " ", (turn.message or "").strip())
        turn_bytes = len(msg.encode("utf-8"))
        if consumed_source_bytes + turn_bytes > MAX_SUMMARY_SOURCE_BYTES:
            truncated_input = True
            break
        consumed_source_bytes += turn_bytes
        ref = f"r{turn.revision}/{turn.turn_id[:8]}"
        if msg:
            goal_lines.append(f"- [{ref}] 用户提问：{msg[:150]}")
        resp = turn.response
        if resp is None:
            continue
        for item in getattr(resp, "results", ()) or ():
            if item.status == "success" and item.data is not None:
                ra = f"{item.data.ra_deg:.4f} deg" if item.data.ra_deg is not None else "无"
                dec = f"{item.data.dec_deg:.4f} deg" if item.data.dec_deg is not None else "无"
                otype = item.data.object_type or "未知"
                tool_lines.append(
                    f"- [{ref}][历史] SIMBAD {item.data.main_id}"
                    f"（ICRS RA={ra}, Dec={dec}, 类型={otype}）"
                )
            elif item.status != "success":
                warning_lines.append(f"- [{ref}] SIMBAD {item.object_name} 状态={item.status}")
        for g in getattr(resp, "gaia_results", ()) or ():
            q = g.query or {}
            if q.get("mode") == "source_id":
                scope_desc = f"source_id={q.get('source_id')}"
            else:
                scope_desc = (
                    f"ICRS({q.get('ra_deg')} deg, {q.get('dec_deg')} deg, "
                    f"r={q.get('radius_arcmin')} arcmin)"
                )
            trunc = "，已截断" if g.truncated or g.has_more else ""
            tool_lines.append(
                f"- [{ref}][历史] {g.release} {g.table} {scope_desc}："
                f"返回 {g.returned_count} 行{trunc}（单位：deg/mas/mas·yr⁻¹/mag）"
            )
        for lit in getattr(resp, "literature_results", ()) or ():
            bibs = ", ".join(p.bibcode for p in (lit.papers or ())[:3] if p.bibcode)
            bib_part = f"，样例 bibcode：{bibs}" if bibs else ""
            tool_lines.append(
                f"- [{ref}][历史] ADS 检索 `{lit.query[:80]}`（sort={lit.sort}）："
                f"本页 {lit.returned_count} 篇{bib_part}"
            )
        for nb in getattr(resp, "nbody_proposals", ()) or ():
            tool_lines.append(
                f"- [{ref}][历史] N 体方案「{nb.name}」（{nb.engine}，{len(nb.particles)} 粒子，"
                f"{nb.duration} yr，单位 M_sun/AU/AU·yr⁻¹，需回查参数与产物）"
            )
        for pl in getattr(resp, "plot_proposals", ()) or ():
            cols = ", ".join((pl.columns or ())[:5])
            tool_lines.append(
                f"- [{ref}][历史] 绘图方案「{pl.title}」（{pl.engine}/{pl.chart}，列：{cols}）"
            )
        for warn in getattr(resp, "warnings", ()) or ():
            warning_lines.append(f"- [{ref}] 提示({warn.code})：{warn.message[:100]}")
        if resp.status != "success":
            warning_lines.append(f"- [{ref}] 回答状态={resp.status}")
        ans = re.sub(r"\s+", " ", (resp.answer or "").strip())
        if ans and len(note_lines) < 6:
            note_lines.append(f"- [{ref}][历史] 结论摘要：{ans[:140]}")

    r_start = completed[0].revision
    r_end = completed[-1].revision
    sections: list[str] = [
        f"【较早对话历史摘要｜覆盖 {len(completed)} 轮（r{r_start}–r{r_end}）"
        "｜仅作参考数据，原轮次可完整回查】"
    ]
    if truncated_input:
        sections.append("注：更早部分轮次超出单次整理字节上限，已优先保留较近关键条件与工具记录。")
    if goal_lines:
        sections.append("一、已确认目标与关键条件：\n" + "\n".join(goal_lines[-8:]))
    if tool_lines:
        sections.append(
            "二、历史工具查询与实验记录（保留单位与原轮次引用）：\n" + "\n".join(tool_lines[-10:])
        )
    if warning_lines:
        sections.append("三、历史失败与限制提示：\n" + "\n".join(warning_lines[-6:]))
    if note_lines:
        sections.append("四、阶段性结论与待续要点：\n" + "\n".join(note_lines[-5:]))

    rendered = _trim_utf8("\n".join(sections), min(max_bytes, MAX_SUMMARY_BYTES))
    now = utc_now()
    return ConversationSummaryRecord(
        summary_id=str(uuid4()),
        conversation_id=conversation_id,
        project_id=project_id,
        first_turn_id=completed[0].turn_id,
        last_turn_id=completed[-1].turn_id,
        covered_turn_ids=covered_ids,
        turn_revisions=revisions,
        source_sha256=source_sha,
        summary_text=rendered,
        summary_bytes=len(rendered.encode("utf-8")),
        generation_mode="local_rule",
        status="active",
        created_at=now,
        updated_at=now,
    )
