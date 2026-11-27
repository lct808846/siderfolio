"""Bounded user-supplied attachment text or sanitized image, stored with its conversation turn."""

import base64
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

MAX_FILE_BYTES = 10 * 1024**2
MAX_TEXT_BYTES = 16 * 1024
MAX_IMAGE_DATA_URL_CHARS = 1_100_000
IMAGE_MEDIA_TYPES = frozenset({"image/png", "image/jpeg", "image/webp", "image/gif"})
_IMAGE_DATA_URL_RE = re.compile(r"^data:(image/(?:png|jpeg|webp|gif));base64,([A-Za-z0-9+/=]+)$")


class ChatAttachment(BaseModel):
    model_config = ConfigDict(extra="forbid")
    filename: str = Field(min_length=1, max_length=180)
    media_type: Literal[
        "application/pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "text/plain",
        "text/markdown",
        "text/csv",
        "text/tab-separated-values",
        "application/json",
        "image/png",
        "image/jpeg",
        "image/webp",
        "image/gif",
    ]
    size: int = Field(gt=0, le=MAX_FILE_BYTES)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    text: str = Field(min_length=1, max_length=MAX_TEXT_BYTES)
    truncated: bool = False
    warnings: list[str] = Field(default_factory=list, max_length=6)
    image_data_url: str | None = Field(default=None, max_length=MAX_IMAGE_DATA_URL_CHARS)
    image_width: int | None = Field(default=None, gt=0, le=16384)
    image_height: int | None = Field(default=None, gt=0, le=16384)

    @field_validator("filename")
    @classmethod
    def safe_name(cls, value):
        if any(ord(char) < 32 for char in value) or "/" in value or "\\" in value:
            raise ValueError("A plain filename is required")
        return value

    @field_validator("text")
    @classmethod
    def bounded_text(cls, value):
        if not value.strip() or len(value.encode("utf-8")) > MAX_TEXT_BYTES:
            raise ValueError("Attachment text is empty or exceeds its byte budget")
        return value

    @field_validator("image_data_url")
    @classmethod
    def valid_image_data_url(cls, value):
        if value is None:
            return None
        match = _IMAGE_DATA_URL_RE.fullmatch(value)
        if not match:
            raise ValueError("Image attachment must use a supported base64 data URL")
        try:
            base64.b64decode(match.group(2), validate=True)
        except Exception as exc:
            raise ValueError("Image attachment base64 payload is invalid") from exc
        return value

    @field_validator("warnings")
    @classmethod
    def bounded_warnings(cls, values):
        if any(len(value) > 300 for value in values):
            raise ValueError("Attachment warning is too long")
        return values
