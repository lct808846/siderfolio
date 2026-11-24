"""Feedback routes for authenticated users and the existing admin console."""

from typing import Annotated
from urllib.parse import quote
from uuid import UUID, uuid4

from fastapi import APIRouter, File, Form, Query, Request, UploadFile
from fastapi.responses import Response
from pydantic import AwareDatetime

from astroagent.api.admin import admin, writable
from astroagent.api.auth import actor, runtime, source
from astroagent.errors import ServiceError
from astroagent.feedback import (
    MAX_SCREENSHOT_BYTES,
    SUPPORT_EMAIL,
    FeedbackCategory,
    FeedbackDetail,
    FeedbackPage,
    FeedbackStatus,
    FeedbackUpdate,
    feedback_connection,
    normalize_screenshot,
    queue_feedback_notice,
)

router = APIRouter(prefix="/api/v1/feedback", tags=["feedback"])
admin_router = APIRouter(prefix="/api/v1/admin/feedback", tags=["administration"])
PAGE_SIZE = 20
Page = Annotated[int, Query(ge=1, le=10_000)]
SUMMARY = (
    "id,user_id,category,title,status,created_at,updated_at,"
    "screenshot IS NOT NULL AS has_screenshot"
)


def _not_found():
    return ServiceError(404, "feedback_not_found", "该反馈不存在或无法访问。")


def _login_link(origin, path):
    return f"{origin}/login?next={quote(path, safe='')}"


def _detail(db, feedback_id, owner_id=None):
    row = db.execute(
        f"SELECT {SUMMARY},description FROM public.auth_feedback "
        "WHERE id=%s AND (%s::text IS NULL OR user_id=%s)",
        (feedback_id, owner_id, owner_id),
    ).fetchone()
    if row is None:
        raise _not_found()
    replies = db.execute(
        "SELECT id,body,created_at FROM public.auth_feedback_replies "
        "WHERE feedback_id=%s ORDER BY created_at,id",
        (feedback_id,),
    ).fetchall()
    return FeedbackDetail(**row, replies=replies)


def _page(
    db, page, owner_id=None, category=None, status=None, created_from=None, created_before=None
):
    rows = db.execute(
        f"SELECT {SUMMARY} FROM public.auth_feedback "
        "WHERE (%s::text IS NULL OR user_id=%s) "
        "AND (%s::text IS NULL OR category=%s) AND (%s::text IS NULL OR status=%s) "
        "AND (%s::timestamptz IS NULL OR created_at>=%s) "
        "AND (%s::timestamptz IS NULL OR created_at<%s) "
        "ORDER BY created_at DESC,id LIMIT %s OFFSET %s",
        (
            owner_id,
            owner_id,
            category,
            category,
            status,
            status,
            created_from,
            created_from,
            created_before,
            created_before,
            PAGE_SIZE + 1,
            (page - 1) * PAGE_SIZE,
        ),
    ).fetchall()
    return FeedbackPage(items=rows[:PAGE_SIZE], has_more=len(rows) > PAGE_SIZE)


def _screenshot(db, feedback_id, owner_id=None):
    row = db.execute(
        "SELECT screenshot FROM public.auth_feedback "
        "WHERE id=%s AND (%s::text IS NULL OR user_id=%s)",
        (feedback_id, owner_id, owner_id),
    ).fetchone()
    if row is None or row["screenshot"] is None:
        raise _not_found()
    return Response(
        row["screenshot"],
        media_type="image/png",
        headers={
            "Content-Disposition": 'inline; filename="screenshot.png"',
            "Content-Security-Policy": "default-src 'none'; sandbox",
            "Cross-Origin-Resource-Policy": "same-origin",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("", response_model=FeedbackPage)
def list_feedback(request: Request, page: Page = 1):
    service, user = runtime(request), actor(request)
    with feedback_connection(service.store) as db:
        return _page(db, page, owner_id=user["id"])


@router.post("", response_model=FeedbackDetail, status_code=201)
def submit_feedback(
    request: Request,
    request_id: Annotated[UUID, Form()],
    category: Annotated[FeedbackCategory, Form()],
    title: Annotated[str, Form(min_length=1, max_length=120)],
    description: Annotated[str, Form(min_length=1, max_length=4000)],
    screenshot: Annotated[UploadFile | None, File()] = None,
):
    service, user = runtime(request), actor(request)
    title, description = title.strip(), description.strip()
    if not title or not description or "\0" in title or "\0" in description:
        raise ServiceError(422, "feedback_invalid", "请填写有效的标题和详细描述。")
    with feedback_connection(service.store) as db:
        previous = db.execute(
            "SELECT id FROM public.auth_feedback WHERE user_id=%s AND request_id=%s",
            (user["id"], request_id),
        ).fetchone()
        if previous:
            return _detail(db, previous["id"], user["id"])
    client = source(request)
    service.store.rate(
        "feedback-submit", client, user["id"], limit=20, account_limit=5, seconds=86400
    )
    image = (
        normalize_screenshot(screenshot.file.read(MAX_SCREENSHOT_BYTES + 1)) if screenshot else None
    )
    feedback_id = uuid4()
    with feedback_connection(service.store) as db:
        created = db.execute(
            "INSERT INTO public.auth_feedback"
            "(id,user_id,request_id,category,title,description,screenshot) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s) "
            "ON CONFLICT (user_id,request_id) DO NOTHING RETURNING id",
            (feedback_id, user["id"], request_id, category, title, description, image),
        ).fetchone()
        if created:
            link = _login_link(service.settings.origin, f"/admin?section=feedback&id={feedback_id}")
            queue_feedback_notice(
                service.store,
                db,
                user["id"],
                SUPPORT_EMAIL,
                "feedback_received",
                feedback_id,
                f"收到新反馈。\n编号 {feedback_id}\n\n请登录管理控制台查看详情。\n{link}",
            )
        else:
            feedback_id = db.execute(
                "SELECT id FROM public.auth_feedback WHERE user_id=%s AND request_id=%s",
                (user["id"], request_id),
            ).fetchone()["id"]
        return _detail(db, feedback_id, user["id"])


@router.get("/{feedback_id}", response_model=FeedbackDetail)
def feedback_detail(feedback_id: UUID, request: Request):
    service, user = runtime(request), actor(request)
    with feedback_connection(service.store) as db:
        return _detail(db, feedback_id, user["id"])


@router.get(
    "/{feedback_id}/screenshot",
    response_class=Response,
    responses={200: {"content": {"image/png": {}}}},
)
def feedback_screenshot(feedback_id: UUID, request: Request):
    service, user = runtime(request), actor(request)
    with feedback_connection(service.store) as db:
        return _screenshot(db, feedback_id, user["id"])


@admin_router.get("", response_model=FeedbackPage)
def list_all_feedback(
    request: Request,
    page: Page = 1,
    category: FeedbackCategory | None = None,
    status: FeedbackStatus | None = None,
    created_from: AwareDatetime | None = None,
    created_before: AwareDatetime | None = None,
):
    admin(request)
    if created_from and created_before and created_from >= created_before:
        raise ServiceError(422, "feedback_date_range", "结束日期须晚于起始日期。")
    with feedback_connection(runtime(request).store) as db:
        return _page(
            db,
            page,
            category=category,
            status=status,
            created_from=created_from,
            created_before=created_before,
        )


@admin_router.get("/{feedback_id}", response_model=FeedbackDetail)
def admin_feedback_detail(feedback_id: UUID, request: Request):
    admin(request)
    with feedback_connection(runtime(request).store) as db:
        return _detail(db, feedback_id)


@admin_router.get(
    "/{feedback_id}/screenshot",
    response_class=Response,
    responses={200: {"content": {"image/png": {}}}},
)
def admin_feedback_screenshot(feedback_id: UUID, request: Request):
    admin(request)
    with feedback_connection(runtime(request).store) as db:
        return _screenshot(db, feedback_id)


@admin_router.patch("/{feedback_id}", response_model=FeedbackDetail)
def handle_feedback(feedback_id: UUID, body: FeedbackUpdate, request: Request):
    service, user = runtime(request), admin(request)
    service.store.rate("feedback-admin", source(request), user["id"], limit=30, seconds=3600)
    with feedback_connection(service.store) as db:
        writable(db, user)
        current = db.execute(
            "SELECT user_id,status,updated_at FROM public.auth_feedback WHERE id=%s FOR UPDATE",
            (feedback_id,),
        ).fetchone()
        if current is None:
            raise _not_found()
        if (
            body.reply
            and db.execute(
                "SELECT 1 FROM public.auth_feedback_replies WHERE feedback_id=%s AND id=%s",
                (feedback_id, body.request_id),
            ).fetchone()
        ):
            return _detail(db, feedback_id)
        if not body.reply and current["status"] == body.status:
            return _detail(db, feedback_id)
        if current["updated_at"] != body.expected_updated_at:
            raise ServiceError(409, "feedback_changed", "反馈已经更新，请重新打开详情后再处理。")
        db.execute(
            "UPDATE public.auth_feedback SET status=%s,updated_at=clock_timestamp() WHERE id=%s",
            (body.status, feedback_id),
        )
        if body.reply:
            db.execute(
                "INSERT INTO public.auth_feedback_replies(feedback_id,id,admin_id,body) "
                "VALUES (%s,%s,%s,%s)",
                (feedback_id, body.request_id, user["id"], body.reply),
            )
            target = db.execute(
                "SELECT email_key FROM public.auth_users WHERE id=%s AND active AND NOT disabled",
                (current["user_id"],),
            ).fetchone()
            if target:
                link = _login_link(service.settings.origin, f"/feedback?id={feedback_id}")
                queue_feedback_notice(
                    service.store,
                    db,
                    current["user_id"],
                    target["email_key"],
                    "feedback_reply",
                    body.request_id,
                    f"你的反馈有新回复。\n编号 {feedback_id}\n\n请登录后查看。\n{link}",
                )
        service.store.audit(
            db, user["id"], "feedback_handled", "ok", str(feedback_id), reason=body.status
        )
        return _detail(db, feedback_id)
