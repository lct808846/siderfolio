"""Bounds for generated labels; user-authored names retain their independent contract."""

import re

TITLE_MIN_CHARACTERS = 4
TITLE_MAX_CHARACTERS = 18


def conversation_title(message):
    """Immediate short fallback without presenting a partial identifier as a whole value."""
    text = re.sub(r"\s+", " ", message).strip()
    text = re.sub(r"^[#>*\-\s]+", "", text)
    text = re.split(r"[。！？!?]", text, maxsplit=1)[0].strip() or "天文查询"
    if len(text) <= TITLE_MAX_CHARACTERS:
        return text
    prefix = text[: TITLE_MAX_CHARACTERS - 1]
    if re.match(r"[A-Za-z0-9_.:+/-]", text[len(prefix)]):
        prefix = re.sub(r"[A-Za-z0-9_.:+/-]+$", "", prefix)
    prefix = prefix.rstrip(" ,，:：;；")
    return prefix + "…" if prefix else "天文问题查询"
