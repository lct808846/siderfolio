"""有位置的原文分段与确定性词法规则；索引副本不会冒充原文。"""

import bisect
import hashlib
import re
import unicodedata
from uuid import UUID, uuid5

INDEX_VERSION = "nfkc-casefold-fts5-v1"
MAX_TEXT_BYTES = 20 * 1024**2
MAX_UNITS = 25000
HAN = re.compile(r"[\u3400-\u9fff\uf900-\ufaff\u3040-\u30ff\uac00-\ud7af]")


def checksum(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def normalize(text):
    return unicodedata.normalize("NFKC", text).casefold()


def query_terms(text):
    terms = list(dict.fromkeys(re.findall(r"\w+", normalize(text))))
    if not terms or len(terms) > 16 or any(len(term) > 100 for term in terms):
        raise ValueError("请输入1至16个明确关键词，每词不超过100字符。")
    return terms


def matches(text, terms):
    words = set(re.findall(r"\w+", text))
    return all(term in text if HAN.search(term) else term in words for term in terms)


def segment(sources, version, project_id, document_id):
    units = []
    for source in sources:
        text = source["text"]
        if not text or source["state"] != "text":
            continue
        line_starts = [0, *(m.end() for m in re.finditer(r"\r\n|\r|\n", text))]
        headings, path, fenced = [], [], False
        if source["page"] is None:
            offset = 0
            for line in text.splitlines(keepends=True):
                if re.match(r"^\s{0,3}(```|~~~)", line):
                    fenced = not fenced
                heading = None if fenced else re.match(r"^ {0,3}(#{1,6})\s+(.+?)\s*#*\s*$", line)
                if heading:
                    level = len(heading[1])
                    path = path[: level - 1] + [heading[2][:300]]
                    headings.append((offset, list(path)))
                offset += len(line)
        begin = 0
        while begin < len(text):
            end = min(begin + 1200, len(text))
            if end < len(text):
                boundary = max(
                    text.rfind("\n", begin + 600, end), text.rfind(" ", begin + 600, end)
                )
                if boundary > begin:
                    end = boundary + 1
            excerpt = text[begin:end]
            if excerpt.strip():
                heading_path = []
                for position, value in headings:
                    if position > begin:
                        break
                    heading_path = value
                digest = checksum(excerpt)
                unit_id = str(uuid5(UUID(version), f"{source['position']}:{begin}:{end}:{digest}"))
                units.append(
                    {
                        "id": unit_id,
                        "project_id": project_id,
                        "document_id": document_id,
                        "version_id": version,
                        "source_position": source["position"],
                        "ordinal": len(units),
                        "text": excerpt,
                        "sha256": digest,
                        "char_start": begin,
                        "char_end": end,
                        "page": source["page"],
                        "line_start": bisect.bisect_right(line_starts, begin)
                        if source["page"] is None
                        else None,
                        "line_end": bisect.bisect_right(line_starts, end - 1)
                        if source["page"] is None
                        else None,
                        "heading_path": heading_path,
                    }
                )
                if len(units) > MAX_UNITS:
                    raise ValueError("分段数量超过25000，未将截断文本标为完整索引。")
            if end == len(text):
                break
            begin = max(begin + 1, end - 120)
    return units
