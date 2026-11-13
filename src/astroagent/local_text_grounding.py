"""Literal conditions and extractive text: the model cannot author scientific facts."""

import re

from astroagent.local_model_schemas import CompactConditionResult

NUMBER = r"[+-]?(?:\d+(?:\.\d+)?|\.\d+)"
UNIT = r"(?:arcmin|角分|′|deg(?:rees)?|度|°)"
NEGATION = r"(?:不要(?:把|查|查询)?|不查|排除|不是|\bnot\s+(?:query\s+)?|\bexclude\s+)\s*"


def grounded_intents(suggestions, source):
    terms = {
        "gaia_query": r"Gaia|DR3",
        "literature_search": r"ADS|论文|文献|papers?|literature",
        "plot": r"画|绘|plot|chart|figure",
        "knowledge_search": r"知识库|已导入|本地文献|knowledge",
    }
    result = [
        kind for kind in suggestions if kind not in terms or re.search(terms[kind], source, re.I)
    ]
    for kind, pattern in terms.items():
        if re.search(pattern, source, re.I) and kind not in result:
            result.append(kind)
    if re.search(r"(?:查|query).*?(?:坐标|coordinates|标识|谱型|光谱)", source, re.I):
        if "object_query" not in result:
            result.append("object_query")
    if not result or re.search(r"不清楚|没确定|未确定|稍后|还没决定", source):
        if "other_or_unclear" not in result:
            result.append("other_or_unclear")
    return list(dict.fromkeys(result))


def literal_conditions(source, suggestions):
    """Conservative supported grammar; absent units/relative years remain ambiguous."""
    found = []

    def add(field, value, unit=None, comparison="unspecified"):
        candidate = (field, value, unit, comparison)
        if candidate not in found:
            found.append(candidate)

    for match in re.finditer(r"(?<![A-Za-z0-9])(?:NGC|IC|M|HD|HIP)\s*\d+(?!\d)", source, re.I):
        prefix = source[max(0, match.start() - 24) : match.start()]
        if not re.search(NEGATION + r"$", prefix, re.I):
            add("object_name", match[0])
    for match in re.finditer(
        r"(?:source[_ ]?id|DR3\s*(?:编号)?)\s*[:=：]?\s*(\d{1,20})(?!\d)", source, re.I
    ):
        add("source_id", match[1])
    if not any(field == "object_name" for field, *_ in found):
        match = re.search(r"查(?:询|找)?\s*([\u4e00-\u9fff]{2,12})(?=的|附近)", source)
        if match and not re.search(r"年|论文|文献|附近|质量|视差|最近|一些", match[1]):
            add("object_name", match[1])

    for field, label in (
        ("ra", r"\bRA\b|赤经"),
        ("dec", r"\bDec\b|赤纬"),
        ("radius", r"半径|radius|附近|周围|within"),
    ):
        for match in re.finditer(
            "(?:" + label + r")\s*[=:：]?\s*(" + NUMBER + r")\s*(" + UNIT + ")?", source, re.I
        ):
            unit = match[2]
            canonical = (
                None
                if unit is None
                else "arcmin"
                if unit.lower() in ("arcmin", "角分", "′")
                else "deg"
            )
            add(field, match[1] if canonical else None, canonical)

    operator = r"(?:<=|>=|[<>≤≥]|不超过|不低于|至少|至多|小于|大于|低于|高于)"
    for field, label in (
        ("ruwe_max", r"RUWE|ruwe_max"),
        ("parallax_snr_min", r"视差信噪比|视差\s*SNR|parallax[_ -]?snr(?:_min)?|\bSNR\b"),
    ):
        for match in re.finditer(
            "(?:" + label + r")\s*(" + operator + r")?\s*(" + NUMBER + ")?", source, re.I
        ):
            comparison = {
                "<": "lt",
                "小于": "lt",
                "低于": "lt",
                "<=": "lte",
                "≤": "lte",
                "不超过": "lte",
                "至多": "lte",
                ">": "gt",
                "大于": "gt",
                "高于": "gt",
                ">=": "gte",
                "≥": "gte",
                "不低于": "gte",
                "至少": "gte",
            }.get(match[1])
            allowed = ("lt", "lte") if field == "ruwe_max" else ("gt", "gte")
            explicit = comparison in allowed and match[2] is not None
            add(
                field,
                match[2] if explicit else None,
                None,
                comparison if explicit else "unspecified",
            )
    year = re.search(r"(?<!\d)(\d{4})\s*年?\s*(?:至|到|to|[-—])\s*(\d{4})(?!\d)", source, re.I)
    if year:
        add("year_start", year[1])
        add("year_end", year[2])
    elif re.search(r"最近|近几年|过去几年|年份.*(?:未|没)|具体年份.*(?:未|没)", source):
        add("year_start", None)
        add("year_end", None)
    if len(found) > 16:
        raise ValueError("Too many literal conditions")
    return CompactConditionResult(conditions=found, suggestions=suggestions)


def source_segments(source):
    # Keep delimiters and scientific expressions; do not split decimal points or ASCII CSV commas.
    parts = re.findall(r".+?(?:[，。；;!?！？\n]+|$)", source, re.S)
    result = [part.strip() for part in parts if part.strip()]
    if not result or len(result) > 64:
        raise ValueError("Source must contain 1 to 64 bounded segments")
    return result


def grounded_text(source, selected, action, output_format):
    parts = source_segments(source)
    if not selected or any(
        type(index) is not int or not 0 <= index < len(parts) for index in selected
    ):
        raise ValueError("Selection must refer only to original segments")
    mandatory = {0}
    for index, part in enumerate(parts):
        if re.search(
            r"\d|不|未|仅|只|未知|不能|候选|近似|已含|来源|摘要|全文|可能|或许|尚|假设|估计|"
            r"cos\(dec\)|\b(?:no|not|only|without|unknown|uncertain|unverified|possibly|candidate|abstract)\b",
            part,
            re.I,
        ):
            mandatory.add(index)
    keep = set(range(len(parts))) if action == "format" else set(selected) | mandatory
    retained = [part for index, part in enumerate(parts) if index in keep]
    if output_format == "paragraph":
        text = "".join(retained)
    else:
        marker = "- " if output_format == "markdown" else "• "
        text = "\n".join(marker + part for part in retained)
    return {"text": text, "warnings": ["仅选取和整理原文，未核验科学内容；摘要仍可能遗漏信息。"]}
