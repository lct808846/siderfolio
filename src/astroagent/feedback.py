"""Private feedback records and bounded, sanitized screenshot storage."""

import io
import logging
from contextlib import contextmanager
from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from PIL import Image, ImageOps, UnidentifiedImageError
from pydantic import AwareDatetime, BaseModel, ConfigDict, StringConstraints, field_validator

from astroagent.errors import ServiceError

MAX_SCREENSHOT_BYTES = 5 * 1024 * 1024
SUPPORT_EMAIL = "support@siderfolio.com"
FeedbackCategory = Literal["bug", "suggestion", "usage", "calculation", "other"]
FeedbackStatus = Literal["pending", "in_progress", "resolved", "closed"]
logger = logging.getLogger(__name__)

FEEDBACK_DDL = (
    """
    CREATE TABLE public.auth_feedback (
        id uuid PRIMARY KEY,
        user_id text NOT NULL REFERENCES public.auth_users(id) ON DELETE CASCADE,
        request_id uuid NOT NULL,
        category text NOT NULL
            CHECK (category IN ('bug','suggestion','usage','calculation','other')),
        title text NOT NULL CHECK (char_length(title) BETWEEN 1 AND 120),
        description text NOT NULL CHECK (char_length(description) BETWEEN 1 AND 4000),
        status text NOT NULL DEFAULT 'pending'
            CHECK (status IN ('pending','in_progress','resolved','closed')),
        screenshot bytea CHECK (octet_length(screenshot) BETWEEN 1 AND 5242880),
        created_at timestamptz NOT NULL DEFAULT now(),
        updated_at timestamptz NOT NULL DEFAULT now(),
        UNIQUE (user_id, request_id)
    )
    """,
    "CREATE INDEX auth_feedback_user_created ON public.auth_feedback(user_id,created_at DESC,id)",
    "CREATE INDEX auth_feedback_created ON public.auth_feedback(created_at DESC,id)",
    """
    CREATE TABLE public.auth_feedback_replies (
        feedback_id uuid NOT NULL REFERENCES public.auth_feedback(id) ON DELETE CASCADE,
        id uuid NOT NULL,
        admin_id text NOT NULL REFERENCES public.auth_users(id),
        body text NOT NULL CHECK (char_length(body) BETWEEN 1 AND 2000),
        created_at timestamptz NOT NULL DEFAULT now(),
        PRIMARY KEY (feedback_id,id)
    )
    """,
)


class FeedbackSummary(BaseModel):
    id: UUID
    user_id: str
    category: FeedbackCategory
    title: str
    status: FeedbackStatus
    has_screenshot: bool
    created_at: datetime
    updated_at: datetime


class FeedbackReply(BaseModel):
    id: UUID
    body: str
    created_at: datetime


class FeedbackDetail(FeedbackSummary):
    description: str
    replies: list[FeedbackReply]


class FeedbackPage(BaseModel):
    items: list[FeedbackSummary]
    has_more: bool


class FeedbackUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    status: FeedbackStatus
    expected_updated_at: AwareDatetime
    request_id: UUID
    reply: (
        Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]
        | None
    ) = None

    @field_validator("reply")
    @classmethod
    def plain_reply(cls, value):
        if value is not None and "\0" in value:
            raise ValueError("Invalid control character")
        return value


def install_feedback_schema(db):
    if db.execute(
        "SELECT 1 FROM public.auth_meta WHERE key='feedback_schema' AND value='1'"
    ).fetchone():
        return False
    for statement in FEEDBACK_DDL:
        db.execute(statement)
    db.execute("INSERT INTO public.auth_meta VALUES ('feedback_schema','1')")
    return True


@contextmanager
def feedback_connection(store):
    with store.connect() as db:
        if not db.execute(
            "SELECT 1 FROM public.auth_meta WHERE key='feedback_schema' AND value='1'"
        ).fetchone():
            raise ServiceError(503, "feedback_unavailable", "反馈服务尚未启用，请联系技术支持。")
        yield db


def normalize_screenshot(raw: bytes) -> bytes:
    if len(raw) > MAX_SCREENSHOT_BYTES:
        raise ServiceError(413, "feedback_screenshot_large", "截图不得超过 5 MiB。")
    try:
        with Image.open(io.BytesIO(raw), formats=("PNG", "JPEG", "WEBP")) as opened:
            if (
                max(opened.size) > 4096
                or opened.width * opened.height > 12 * 1024 * 1024
                or getattr(opened, "n_frames", 1) != 1
            ):
                raise ServiceError(
                    422,
                    "feedback_screenshot_size",
                    "请上传不超过 4096 像素边长和 1200 万像素的静态截图。",
                )
            oriented = ImageOps.exif_transpose(opened)
            sanitized = oriented.convert("RGBA" if oriented.has_transparency_data else "RGB")
            sanitized.info.clear()
            output = io.BytesIO()
            sanitized.save(output, format="PNG", compress_level=4)
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as exc:
        raise ServiceError(
            422, "feedback_screenshot_invalid", "请选择有效的 PNG、JPEG 或 WebP 截图。"
        ) from exc
    if output.tell() > MAX_SCREENSHOT_BYTES:
        raise ServiceError(
            413, "feedback_screenshot_large", "处理后的截图超过 5 MiB，请裁剪后重试。"
        )
    return output.getvalue()


def queue_feedback_notice(store, db, user_id, address, purpose, request_id, text):
    if not store.settings.feedback_mail_ready:
        return
    try:
        with db.transaction():
            store.enqueue_mail(
                db,
                user_id,
                f"{purpose}:{request_id}",
                {
                    "email": address,
                    "purpose": purpose,
                    "message": text,
                },
            )
    except Exception:
        logger.warning("Feedback was stored, but the notification could not be queued")
