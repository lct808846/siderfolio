"""Offline, bounded file-to-text conversion. No model call or original-file archive."""

import hashlib
import io
import threading
import zipfile
from pathlib import PurePosixPath
from xml.etree import ElementTree

from astroagent.attachment_schemas import MAX_FILE_BYTES, MAX_TEXT_BYTES, ChatAttachment
from astroagent.errors import ServiceError

PARSER_SLOTS = threading.BoundedSemaphore(2)
MEDIA = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".markdown": "text/markdown",
    ".csv": "text/csv",
    ".tsv": "text/tab-separated-values",
    ".json": "application/json",
}


def word_text(content):
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        if len(archive.infolist()) > 2000:
            raise ValueError("Too many Word members")
        info = archive.getinfo("word/document.xml")
        if info.flag_bits & 1 or info.file_size > 4 * 1024**2:
            raise ValueError("Word XML exceeds limits")
        with archive.open(info) as stream:
            raw = stream.read(4 * 1024**2 + 1)
        if len(raw) > 4 * 1024**2:
            raise ValueError("Word XML exceeds limits")
        xml = raw.decode("utf-8-sig")
        if "<!DOCTYPE" in xml.upper() or "<!ENTITY" in xml.upper():
            raise ValueError("Unsupported Word XML declarations")
        root = ElementTree.fromstring(xml)
    namespace = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    return "\n".join(
        "".join(node.text or "" for node in paragraph.iter(namespace + "t"))
        for paragraph in root.iter(namespace + "p")
    )


def parse_attachment(filename, content):
    name = (filename or "").replace("\\", "/").rsplit("/", 1)[-1].strip()
    media = MEDIA.get(PurePosixPath(name).suffix.lower())
    if not media:
        raise ServiceError(
            415, "attachment_type_unsupported", "支持 PDF、DOCX、TXT、Markdown、CSV、TSV 和 JSON。"
        )
    if not content or len(content) > MAX_FILE_BYTES:
        raise ServiceError(413, "attachment_size_limit", "附件不能为空，单个文件最多 10 MiB。")
    if not name or len(name) > 180 or any(ord(char) < 32 for char in name):
        raise ServiceError(
            422, "attachment_filename_invalid", "文件名无效或过长，请修改后重新选择。"
        )
    if not PARSER_SLOTS.acquire(blocking=False):
        raise ServiceError(
            503, "attachment_parser_busy", "已有文件正在解析，请稍后重试。", retryable=True
        )
    try:
        warnings = []
        if media == "application/pdf":
            if not content.startswith(b"%PDF-"):
                raise ValueError("Invalid PDF header")
            from astroagent.knowledge_parser import parse_document

            product = parse_document(content, media)
            text = "\n\n".join(
                f"[物理页 {source['page']}]\n{source['text']}"
                for source in product["sources"]
                if source["state"] == "text" and source["text"].strip()
            )
            warnings = [str(value)[:300] for value in product.get("warnings", [])[:4]]
        elif media.endswith("wordprocessingml.document"):
            text = word_text(content)
            warnings = ["已提取正文和表格中的文字；图片、公式和版式不包含在附件文本中。"]
        else:
            try:
                text = content.decode("utf-8-sig")
            except UnicodeDecodeError:
                text = content.decode("gb18030")
        if "\x00" in text or not text.strip():
            raise ServiceError(
                422, "attachment_no_text", "未提取到可读文本；扫描图片型文件需先转换为文本。"
            )
        raw = text.encode("utf-8")
        truncated = len(raw) > MAX_TEXT_BYTES
        if truncated:
            text = raw[:MAX_TEXT_BYTES].decode("utf-8", errors="ignore")
            warnings.append("内容较长，这次仅发送前 16 KiB 文本。请以实际阅读范围为准。")
        return ChatAttachment(
            filename=name,
            media_type=media,
            size=len(content),
            sha256=hashlib.sha256(content).hexdigest(),
            text=text,
            truncated=truncated,
            warnings=warnings,
        )
    except ServiceError:
        raise
    except Exception as exc:
        raise ServiceError(
            422, "attachment_parse_failed", "文件未能解析，请确认文件格式、编码及是否加密。"
        ) from exc
    finally:
        PARSER_SLOTS.release()
