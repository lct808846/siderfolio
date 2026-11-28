"""Offline, bounded file-to-text and image sanitization. No model call or original-file archive."""

import base64
import hashlib
import io
import threading
import zipfile
from pathlib import PurePosixPath
from xml.etree import ElementTree

from astroagent.attachment_schemas import (
    IMAGE_MEDIA_TYPES,
    MAX_FILE_BYTES,
    MAX_TEXT_BYTES,
    ChatAttachment,
)
from astroagent.errors import ServiceError

PARSER_SLOTS = threading.BoundedSemaphore(2)
MAX_IMAGE_EDGE = 1600
MAX_IMAGE_PIXELS = 40_000_000
MAX_ENCODED_IMAGE_BYTES = 750 * 1024
MEDIA = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".markdown": "text/markdown",
    ".csv": "text/csv",
    ".tsv": "text/tab-separated-values",
    ".json": "application/json",
    ".fits": "application/fits",
    ".fit": "application/fits",
    ".vot": "application/x-votable+xml",
    ".ecsv": "text/x-ecsv",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
}


def _sanitize_image_attachment(name: str, content: bytes, declared_media: str) -> ChatAttachment:
    from PIL import Image, ImageOps

    previous_limit = Image.MAX_IMAGE_PIXELS
    Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS
    try:
        with Image.open(io.BytesIO(content)) as probe:
            probe.verify()
        with Image.open(io.BytesIO(content)) as opened:
            img = ImageOps.exif_transpose(opened)
            if getattr(img, "is_animated", False):
                img.seek(0)
            orig_w, orig_h = img.size
            if orig_w <= 0 or orig_h <= 0 or orig_w * orig_h > MAX_IMAGE_PIXELS:
                raise ValueError("Invalid image dimensions")

            warnings: list[str] = []
            resized = False
            if max(orig_w, orig_h) > MAX_IMAGE_EDGE:
                img.thumbnail((MAX_IMAGE_EDGE, MAX_IMAGE_EDGE), Image.Resampling.LANCZOS)
                resized = True

            has_alpha = img.mode in ("RGBA", "LA") or (
                img.mode == "P" and "transparency" in img.info
            )
            work = img.convert("RGBA" if has_alpha else "RGB")

            def encode_candidate(candidate, fmt: str, quality: int = 86) -> bytes:
                buf = io.BytesIO()
                if fmt == "PNG":
                    candidate.save(buf, format="PNG", optimize=True)
                elif fmt == "WEBP":
                    candidate.save(buf, format="WEBP", quality=quality, method=4)
                else:
                    rgb = candidate.convert("RGB")
                    if candidate.mode == "RGBA":
                        bg = Image.new("RGB", candidate.size, (255, 255, 255))
                        bg.paste(candidate, mask=candidate.getchannel("A"))
                        rgb = bg
                    rgb.save(buf, format="JPEG", quality=quality, optimize=True)
                return buf.getvalue()

            out_bytes: bytes | None = None
            out_media = declared_media
            if declared_media == "image/png" or has_alpha:
                png_bytes = encode_candidate(work, "PNG")
                if len(png_bytes) <= MAX_ENCODED_IMAGE_BYTES:
                    out_bytes = png_bytes
                    out_media = "image/png"
                else:
                    webp_bytes = encode_candidate(work, "WEBP", quality=86)
                    if len(webp_bytes) <= MAX_ENCODED_IMAGE_BYTES:
                        out_bytes = webp_bytes
                        out_media = "image/webp"

            if out_bytes is None:
                for edge in (None, 1280, 960):
                    target = work
                    if edge is not None and max(work.size) > edge:
                        target = work.copy()
                        target.thumbnail((edge, edge), Image.Resampling.LANCZOS)
                        resized = True
                    for q in (88, 80, 72):
                        jpg_bytes = encode_candidate(target, "JPEG", quality=q)
                        if len(jpg_bytes) <= MAX_ENCODED_IMAGE_BYTES:
                            out_bytes = jpg_bytes
                            out_media = "image/jpeg"
                            work = target
                            break
                    if out_bytes is not None:
                        break

            if out_bytes is None:
                raise ServiceError(
                    413,
                    "attachment_image_too_large",
                    "图片压缩后仍超出单图发送上限，请适当裁剪或降低分辨率后重试。",
                )

            width, height = work.size
            if resized:
                warnings.append(
                    f"原图 {orig_w}×{orig_h} 已优化缩放为 {width}×{height} 以便模型识别与传输。"
                )
            data_url = f"data:{out_media};base64,{base64.b64encode(out_bytes).decode('ascii')}"
            return ChatAttachment(
                filename=name,
                media_type=out_media,
                size=len(content),
                sha256=hashlib.sha256(content).hexdigest(),
                text=f"[图片附件：{name}，尺寸 {width}×{height}，格式 {out_media}]",
                truncated=False,
                warnings=warnings,
                image_data_url=data_url,
                image_width=width,
                image_height=height,
            )
    finally:
        Image.MAX_IMAGE_PIXELS = previous_limit


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
            415,
            "attachment_type_unsupported",
            "支持图片（PNG、JPG、WebP、GIF）、天文数据表（FITS、VOTable、ECSV）"
            "及 PDF、DOCX、TXT、Markdown、CSV、TSV、JSON。",
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
        if media in IMAGE_MEDIA_TYPES:
            return _sanitize_image_attachment(name, content, media)
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
        elif media in ("application/fits", "application/x-votable+xml", "text/x-ecsv"):
            from astroagent.table_io import summarize_astro_table_attachment

            text, warnings = summarize_astro_table_attachment(content, name)
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
