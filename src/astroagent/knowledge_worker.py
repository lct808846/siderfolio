"""独立进程入口：收到父进程资源限制握手后才读取用户文件。"""

import hashlib
import json
import logging
import os
import sys
from pathlib import Path

MAX_TEXT = 20 * 1024**2


def extract(path, media):
    if media == "text/markdown":
        raw = path.read_bytes()
        text = raw.decode("utf-8-sig")
        if "\x00" in text or len(text.splitlines()) > 200000:
            raise ValueError("markdown_limits")
        if len(text.encode("utf-8")) > MAX_TEXT:
            raise ValueError("text_limit")
        return {
            "extractor": "utf-8-sig/stdlib-v1",
            "page_count": None,
            "line_count": len(text.splitlines()),
            "warnings": [],
            "sources": [
                {
                    "position": 1,
                    "page": None,
                    "state": "text" if text.strip() else "no_text",
                    "text": text,
                    "error": None,
                }
            ],
        }
    from pypdf import PdfReader, __version__

    if __version__ != "6.21.4":
        raise ValueError("extractor_version_unavailable")
    reader = PdfReader(path, strict=True)
    if reader.is_encrypted:
        raise ValueError("encrypted_pdf")
    count = len(reader.pages)
    if count > 500:
        raise ValueError("page_limit")
    sources, warnings, size = [], [], 0
    for position in range(1, count + 1):
        try:
            page = reader.pages[position - 1]
            text = page.extract_text() or ""
            encoded_size = len(text.encode("utf-8"))
            if size + encoded_size > MAX_TEXT:
                raise ValueError("text_limit")
            size += encoded_size
            state, error = ("text" if text.strip() else "no_text"), None
        except (MemoryError, RecursionError):
            raise
        except Exception as exc:
            if str(exc) == "text_limit":
                raise
            text, state, error = "", "failed", "page_extraction_failed"
        sources.append(
            {"position": position, "page": position, "state": state, "text": text, "error": error}
        )
        if state != "text":
            warnings.append(
                f"物理页{position}："
                f"{'未提取到文本（不执行OCR）' if state == 'no_text' else '提取失败'}。"
            )
    return {
        "extractor": f"pypdf/{__version__}/plain-v1",
        "page_count": count,
        "line_count": None,
        "sources": sources,
        "warnings": warnings
        + ["PDF双栏、公式、脚注或表格可能错序或缺漏；物理页定位不保证精确高亮。"],
    }


def main():
    if sys.platform.startswith("linux"):
        import resource

        try:
            resource.setrlimit(resource.RLIMIT_AS, (768 * 1024**2, 768 * 1024**2))
            resource.setrlimit(resource.RLIMIT_CPU, (25, 25))
            resource.setrlimit(resource.RLIMIT_FSIZE, (64 * 1024**2, 64 * 1024**2))
            resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        except (OSError, ValueError):
            return 3
    elif os.name != "nt":
        return 3
    if sys.stdin.buffer.read(1) != b"1":
        return 3
    logging.disable(logging.CRITICAL)
    import socket

    def offline(*args, **kwargs):
        raise RuntimeError("Parser network access is disabled")

    socket.socket = offline
    try:
        result = extract(Path(sys.argv[1]), sys.argv[2])
        for source in result["sources"]:
            source["sha256"] = hashlib.sha256(source["text"].encode("utf-8")).hexdigest()
        result["ok"] = True
    except Exception as exc:
        allowed = {
            "markdown_limits",
            "text_limit",
            "encrypted_pdf",
            "page_limit",
            "extractor_version_unavailable",
        }
        code = str(exc) if str(exc) in allowed else "extraction_failed"
        if isinstance(exc, ModuleNotFoundError):
            code = "extractor_unavailable"
        result = {"ok": False, "error": code}
    data = json.dumps(result, ensure_ascii=False, allow_nan=False).encode("utf-8")
    if len(data) > 64 * 1024**2:
        return 4
    Path(sys.argv[3]).write_bytes(data)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
