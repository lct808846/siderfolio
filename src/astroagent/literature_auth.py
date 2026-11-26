"""服务端基于当前用户原始消息的一次性文献入库授权与范围校验。"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal
from uuid import uuid4

from astroagent.literature_schemas import BIBCODE_PATTERN, MAX_LITERATURE_BATCH, SaveLiteratureQuery

_CN_NUMERALS = {
    "一": 1,
    "二": 2,
    "两": 2,
    "俩": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "十": 10,
}

_QUOTED_SPAN = re.compile(r"(“[^”]*”|\"[^\"]*\"|「[^」]*」|『[^』]*』|'[^']*'|`[^`]*`)")

_NEGATION_PATTERNS = (
    re.compile(
        r"(?:不要|别|不用|不必|无须|无需|暂不|先不|切勿|不要去|不打算|不想|不需要|禁止|不要帮我)"
        r"[^。！？!?\n]{0,24}"
        r"(?:加入|添加|保存|存入|入库|收入|收录|放进|放到|收藏|加进)"
    ),
    re.compile(r"(?:不入库|不保存|不加入|不添加|不收录|别加进去|别存进去)"),
    re.compile(
        r"\b(?:do\s+not|don't|never|without|no\s+need\s+to)\b[^.!?\n]{0,30}"
        r"\b(?:save|add|store|import|bookmark)\b",
        re.I,
    ),
)

_HYPOTHETICAL_OR_QUESTION_PATTERNS = (
    re.compile(
        r"(?:如果|假如|假设|要是|万一|试想)[^。！？!?\n]{0,30}"
        r"(?:加入|添加|保存|存入|入库|收入|收录|放进|放到|加进)"
    ),
    re.compile(
        r"(?:能不能|可以吗|行不行|是否可以|是否能|要不要|怎么|如何|怎样|能否|是否会|会不会)"
        r"[^。！？!?\n]{0,30}"
        r"(?:加入|添加|保存|存入|入库|收入|收录|放进|放到|加进)"
    ),
    re.compile(
        r"(?:加入|添加|保存|存入|入库|收入|收录|放进|放到|加进)"
        r"[^。！？!?\n]{0,20}(?:吗|呢|行吗|可以吗)[？?]?$"
    ),
    re.compile(
        r"\b(?:if\s+i|how\s+(?:do|can|to)|would\s+you|should\s+i|can\s+you\s+explain)\b"
        r"[^.!?\n]{0,40}\b(?:save|add|store)\b",
        re.I,
    ),
)

_SAVE_INTENT_PATTERNS = (
    re.compile(
        r"(?:加入|添加到|添加进|添加至|存入|保存到|保存至|收入|收录到|收录进|放进|放到|收藏到|加进|加到)"
        r"[^。！？!?\n]{0,18}"
        r"(?:(?:我的|个人)(?:天文)?(?:文献|论文)(?:库|管理|列表|夹)?|"
        r"(?:天文)?(?:文献库|文献管理|文献列表|文献夹|库里|库中|里面|进去))"
    ),
    re.compile(
        r"(?:直接|帮我|请|把它|把它们|把这|把那|把前|把第)[^。！？!?\n]{0,24}(?:入库|加进去|存进去|收进去)"
    ),
    re.compile(
        r"(?:入库|(?:加入|添加到|保存到|存入|收藏到)(?:(?:我的|个人)(?:天文)?(?:文献|论文)(?:库|管理)?|"
        r"(?:天文)?(?:文献库|文献管理)))"
    ),
    re.compile(
        r"(?:把|将|从中|其中)[^。！？!?\n]{0,28}"
        r"(?:(?:前|头)\s*(?:\d+|[一二两俩三四五六七八九十]+)\s*(?:篇|条|个)|"
        r"(?:挑选|挑出|选出|精选|筛选|最相关|最符合|最贴合|最合适|"
        r"引用(?:数|次数|量|率)?(?:最高|最多)|被引(?:次数|数|用)?(?:最高|最多)|高引(?:用)?|最新|最近|最早)"
        r"[^。！？!?\n]{0,12}"
        r"(?:\d+|[一二两俩三四五六七八九十]+)\s*(?:篇|条|个)|"
        r"第\s*(?:\d+|[一二两三四五六七八九十]+))"
        r"[^。！？!?\n]{0,16}(?:保存|加入|添加|存入|入库|收录|收藏)"
    ),
    re.compile(
        r"\b(?:save|add|store)\b[^.!?\n]{0,40}\b(?:to|into)\s+(?:my\s+)?"
        r"(?:literature|library|reading\s+list)\b",
        re.I,
    ),
    re.compile(
        r"\b(?:save|add)\s+(?:the\s+)?(?:first|top|most\s+cited|latest|newest|papers?|items?)\b"
        r"[^.!?\n]{0,30}",
        re.I,
    ),
)

_RECENT_REF_PATTERN = re.compile(
    r"(?:刚才|刚刚|上一轮|上轮|上面|上方|刚刚查的|刚查的|刚才那批|上一批|那条\s*ADS|刚才\s*ADS|"
    r"previous|above|last\s+ads|just\s+found)",
    re.I,
)

_SAVE_VERB_PATTERN = re.compile(
    r"(?:加入|添加|保存|存入|入库|收入|收录|放进|放到|收藏|加进|加到|\b(?:save|add|store)\b)",
    re.I,
)

_RANKED_N_PATTERNS = (
    re.compile(
        r"(?:最相关|相关度最高|相关性最高|最符合|最贴合|最合适|最匹配|"
        r"引用(?:数|次数|量|率)?(?:最高|最多)|被引(?:次数|数|用)?(?:最高|最多)|高引(?:用)?|"
        r"最新|最近(?:发表)?|最早|"
        r"最具代表性|最经典|最核心|最关键|最有价值|最值得(?:精读|阅读|关注)|最推荐|精选)"
        r"[^。！？!?\n，,；;]{0,10}?(?:前|头)?\s*(\d+|[一二两俩三四五六七八九十])\s*(?:篇|条|个|份)?"
    ),
    re.compile(
        r"(?:挑选|挑出|选出|筛选|择优(?:选)?|从中选|其中选)"
        r"[^。！？!?\n，,；;]{0,8}?(?:前|头)?\s*(\d+|[一二两俩三四五六七八九十])\s*(?:篇|条|个|份)"
    ),
    re.compile(
        r"\b(?:top\s+)?(\d+)\s+(?:most\s+relevant|best(?:\s+matching)?|most\s+suitable|"
        r"most\s+cited|highest[- ]cited|most\s+recent|latest|newest)\b",
        re.I,
    ),
    re.compile(
        r"\b(?:most\s+relevant|best(?:\s+matching)?|most\s+suitable|"
        r"most\s+cited|highest[- ]cited|most\s+recent|latest|newest)\s+(?:top\s+)?(\d+)\b",
        re.I,
    ),
)

_TOP_N_PATTERNS = (
    re.compile(r"(?:前|头|最前面(?:的)?)\s*(\d+|[一二两俩三四五六七八九十])\s*(?:篇|条|个|份)?"),
    re.compile(r"\b(?:first|top)\s+(\d+)\b", re.I),
)

_RANGE_PATTERN = re.compile(
    r"第\s*(\d+|[一二两三四五六七八九十])\s*(?:到|至|-|~|—)\s*(?:第\s*)?"
    r"(\d+|[一二两三四五六七八九十])\s*(?:篇|条|个)?"
)

_INDEX_LIST_PATTERN = re.compile(
    r"第\s*((?:(?:\d+|[一二两三四五六七八九十])\s*(?:[、,，和与及\s]+(?:第\s*)?)?)+)\s*(?:篇|条|个)?"
)

_EN_INDICES_PATTERN = re.compile(
    r"\b(?:papers?|items?|#)\s*((?:\d+(?:\s*(?:,|and|&)\s*#?\d+)*))",
    re.I,
)

_ALL_BATCH_PATTERN = re.compile(
    r"(?:全部|所有|全都|都|这几篇|那几篇|这批|那批|这些|那些|它们|all\s+of\s+them|all\s+papers|"
    r"save\s+all|add\s+all|save\s+them|add\s+them|save\s+these|add\s+these)",
    re.I,
)

_SINGLE_PATTERN = re.compile(r"(?:这篇|这一篇|那篇|那一片|这一条|this\s+paper|that\s+paper)", re.I)

_EXPLICIT_BIBCODE_PATTERN = re.compile(r"\b(\d{4}[A-Za-z][A-Za-z0-9.&+_-]{10,25})\b")


def _parse_int_token(token: str) -> int | None:
    cleaned = token.strip()
    if cleaned.isdigit():
        return int(cleaned)
    return _CN_NUMERALS.get(cleaned)


def _strip_quotes(text: str) -> str:
    return _QUOTED_SPAN.sub(" ", text)


@dataclass
class SavePermit:
    permit_id: str
    authorized: bool
    conversation_id: str
    turn_id: str
    client_request_id: str
    selection_kind: Literal[
        "none", "top_n", "ranked_n", "indices", "bibcodes", "all_batch", "single"
    ] = "none"
    allowed_indices: list[int] = field(default_factory=list)
    allowed_bibcodes: list[str] = field(default_factory=list)
    max_count: int = 0
    refers_recent: bool = False
    raw_message_folded: str = ""
    deny_reason: str | None = None
    consumed: bool = False

    def verify_and_resolve(
        self,
        arguments: SaveLiteratureQuery,
        *,
        current_batches: list,
        history_batches: list[tuple[str, int, object]],
    ) -> tuple[str | None, int, object, list[tuple[int, object]]]:
        """校验模型提交的候选引用是否在一次性许可范围内，返回目标批次与已核对条目。"""
        if not self.authorized:
            raise PermissionError(
                self.deny_reason or "当前用户消息未包含明确的文献入库授权，已拒绝写入个人文献库。"
            )
        if self.consumed:
            raise PermissionError("本轮一次性文献入库授权已使用，不能在同一轮重复写入。")

        # 1. 解析目标 ADS 批次（严格限定在当前轮或当前会话可访问历史批次）
        target_turn_id: str | None = None
        target_batch_index = arguments.batch_index
        target_batch = None
        if arguments.source_scope == "current_turn":
            if self.selection_kind in {"all_batch", "single", "ranked_n"}:
                successful_current = [
                    b for b in current_batches if b.status == "success" and b.papers
                ]
                if len(successful_current) > 1:
                    raise ValueError(
                        "本轮存在多批 ADS 检索结果，用户指代不唯一；请先确认保存哪一批或具体序号。"
                    )
            if 0 <= target_batch_index < len(current_batches):
                candidate = current_batches[target_batch_index]
                if candidate.status == "success" and candidate.papers:
                    target_turn_id = self.turn_id
                    target_batch = candidate
            if target_batch is None:
                raise ValueError("本轮没有可用的成功 ADS 检索批次可供保存。")
        else:
            # 历史批次：当用户使用模糊指代（如“那几篇”）且历史存在多个批次时拒绝猜测
            if (
                self.selection_kind in {"all_batch", "single", "ranked_n"}
                and not self.refers_recent
            ):
                distinct_batches = [
                    (tid, bidx, batch)
                    for tid, bidx, batch in history_batches
                    if batch.status == "success" and batch.papers
                ]
                if len(distinct_batches) > 1:
                    raise ValueError(
                        "当前会话存在多批历史 ADS 检索结果，用户指代不唯一；"
                        "请先询问用户需要保存哪一批或具体条目，不要猜测入库。"
                    )
            for tid, bidx, batch in history_batches:
                if tid == arguments.source_turn_id and bidx == target_batch_index:
                    if batch.status == "success" and batch.papers:
                        target_turn_id = tid
                        target_batch = batch
                    break
            if target_batch is None:
                raise ValueError("所引用的历史 ADS 批次不存在、无有效结果或不属于当前会话。")

        papers = list(target_batch.papers)
        if not papers:
            raise ValueError("目标 ADS 批次没有可保存的文献。")

        # 2. 按批次顺序解析候选位置
        chosen: list[tuple[int, object]] = []
        seen_positions: set[int] = set()
        if arguments.paper_indices:
            for pos in arguments.paper_indices:
                if pos < 1 or pos > len(papers):
                    raise ValueError(
                        f"文献序号 #{pos} 超出该批次实际返回范围（共 {len(papers)} 篇）。"
                    )
                if pos not in seen_positions:
                    seen_positions.add(pos)
                    chosen.append((pos, papers[pos - 1]))
        if arguments.bibcodes:
            by_code = {paper.bibcode: (idx + 1, paper) for idx, paper in enumerate(papers)}
            for code in arguments.bibcodes:
                if code not in by_code:
                    raise ValueError(f"bibcode {code} 不在目标 ADS 批次中，拒绝写入未核实条目。")
                pos, paper = by_code[code]
                if pos not in seen_positions:
                    seen_positions.add(pos)
                    chosen.append((pos, paper))

        if not chosen:
            raise ValueError("未解析到任何有效候选文献。")
        if len(chosen) > MAX_LITERATURE_BATCH or len(chosen) > self.max_count:
            raise PermissionError(
                f"请求保存 {len(chosen)} 篇，超出用户明确授权的数量上限（{self.max_count} 篇）。"
            )

        # 3. 核对选取规则边界
        if self.selection_kind in {"top_n", "indices"}:
            allowed_set = set(self.allowed_indices)
            out_of_scope = [pos for pos, _ in chosen if pos not in allowed_set]
            if out_of_scope:
                raise PermissionError(
                    f"模型请求的文献序号 {out_of_scope} "
                    f"超出用户明确指定的范围 {self.allowed_indices}。"
                )
        elif self.selection_kind == "bibcodes":
            allowed_codes = set(self.allowed_bibcodes)
            out_of_scope = [p.bibcode for _, p in chosen if p.bibcode not in allowed_codes]
            if out_of_scope:
                raise PermissionError("模型请求的 bibcode 不在用户明确指定的范围内。")
        elif self.selection_kind == "single" and len(chosen) > 1:
            raise PermissionError("用户仅要求保存单篇文献，拒绝批量写入。")

        return target_turn_id, target_batch_index, target_batch, chosen


def analyze_save_permit(
    raw_user_message: str,
    *,
    conversation_id: str,
    turn_id: str,
    client_request_id: str,
) -> SavePermit:
    """仅从当前用户原始消息判定一次性文献入库许可，排除引用、否定、假设和歧义。"""
    base = SavePermit(
        permit_id=str(uuid4()),
        authorized=False,
        conversation_id=conversation_id,
        turn_id=turn_id,
        client_request_id=client_request_id,
        raw_message_folded=(raw_user_message or "").casefold(),
    )
    cleaned = _strip_quotes(raw_user_message or "").strip()
    if not cleaned:
        base.deny_reason = "用户消息为空，无文献入库授权。"
        return base

    for pattern in _NEGATION_PATTERNS:
        if pattern.search(cleaned):
            base.deny_reason = "用户消息包含否定保存表达，未授予文献入库权限。"
            return base

    for pattern in _HYPOTHETICAL_OR_QUESTION_PATTERNS:
        if pattern.search(cleaned):
            base.deny_reason = "用户消息属于假设或询问句式，未授予文献入库权限。"
            return base

    if not any(pattern.search(cleaned) for pattern in _SAVE_INTENT_PATTERNS):
        base.deny_reason = "用户消息仅检索或讨论文献，未包含明确的入库请求。"
        return base

    refers_recent = bool(_RECENT_REF_PATTERN.search(cleaned))

    # 1. 优先匹配显式 bibcode
    bibcodes = [
        match.group(1)
        for match in _EXPLICIT_BIBCODE_PATTERN.finditer(cleaned)
        if BIBCODE_PATTERN.fullmatch(match.group(1))
    ]
    if bibcodes:
        deduped = list(dict.fromkeys(bibcodes))[:MAX_LITERATURE_BATCH]
        base.authorized = True
        base.selection_kind = "bibcodes"
        base.allowed_bibcodes = deduped
        base.max_count = len(deduped)
        base.refers_recent = refers_recent
        return base

    # 2. 优先匹配按相关性/条件筛选的“最相关的（前）N 篇 / 挑选 N 篇”（限定在含保存动作的分句内）
    save_clauses = [
        clause
        for clause in re.split(r"[。！？!?；;\n]+", cleaned)
        if _SAVE_VERB_PATTERN.search(clause)
    ]
    ranked_targets = save_clauses or [cleaned]
    for target in ranked_targets:
        for pattern in _RANKED_N_PATTERNS:
            match = pattern.search(target)
            if match:
                count = _parse_int_token(match.group(1))
                if count is not None and 1 <= count <= MAX_LITERATURE_BATCH:
                    base.authorized = True
                    base.selection_kind = "ranked_n"
                    base.max_count = count
                    base.refers_recent = refers_recent
                    return base

    # 3. 匹配严格按列表顺序的“前 N 篇 / first N”
    for pattern in _TOP_N_PATTERNS:
        match = pattern.search(cleaned)
        if match:
            count = _parse_int_token(match.group(1))
            if count is not None and 1 <= count <= MAX_LITERATURE_BATCH:
                base.authorized = True
                base.selection_kind = "top_n"
                base.allowed_indices = list(range(1, count + 1))
                base.max_count = count
                base.refers_recent = refers_recent
                return base

    # 3. 匹配范围“第 1 到 3 篇 / 第 2-4 篇”
    range_match = _RANGE_PATTERN.search(cleaned)
    if range_match:
        start = _parse_int_token(range_match.group(1))
        end = _parse_int_token(range_match.group(2))
        if start is not None and end is not None and 1 <= start <= end <= MAX_LITERATURE_BATCH:
            indices = list(range(start, end + 1))
            base.authorized = True
            base.selection_kind = "indices"
            base.allowed_indices = indices
            base.max_count = len(indices)
            base.refers_recent = refers_recent
            return base

    # 4. 匹配离散序号“第 1、3 篇 / 第1和第3篇 / papers 1, 3”
    parsed_indices: list[int] = []
    for match in _INDEX_LIST_PATTERN.finditer(cleaned):
        for tok in re.findall(r"\d+|[一二两三四五六七八九十]", match.group(1)):
            value = _parse_int_token(tok)
            if (
                value is not None
                and 1 <= value <= MAX_LITERATURE_BATCH
                and value not in parsed_indices
            ):
                parsed_indices.append(value)
    if not parsed_indices:
        for match in _EN_INDICES_PATTERN.finditer(cleaned):
            for tok in re.findall(r"\d+", match.group(1)):
                value = int(tok)
                if 1 <= value <= MAX_LITERATURE_BATCH and value not in parsed_indices:
                    parsed_indices.append(value)
    if parsed_indices:
        base.authorized = True
        base.selection_kind = "indices"
        base.allowed_indices = parsed_indices
        base.max_count = len(parsed_indices)
        base.refers_recent = refers_recent
        return base

    # 5. 匹配单篇指代
    if _SINGLE_PATTERN.search(cleaned):
        base.authorized = True
        base.selection_kind = "single"
        base.max_count = 1
        base.refers_recent = refers_recent
        return base

    # 6. 匹配整批指代（例如“全部加入”“把那几篇加进去”——若历史存在多批将在执行前拒绝）
    if _ALL_BATCH_PATTERN.search(cleaned):
        base.authorized = True
        base.selection_kind = "all_batch"
        base.max_count = MAX_LITERATURE_BATCH
        base.refers_recent = refers_recent
        return base

    base.deny_reason = "未指明要保存的具体文献序号或范围，请明确说明条目后再保存。"
    return base
