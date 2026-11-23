"""No public UI link; every operation also enforces server-side administrator rights."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Query, Request

from astroagent.api.auth import Input, actor, runtime, source
from astroagent.auth_access import administrator
from astroagent.auth_store import AUTH_LOCK
from astroagent.errors import ServiceError
from astroagent.usage import AccountLimits, account_snapshot, limits_key

router = APIRouter(prefix="/api/v1/admin", tags=["administration"])


class UserAction(Input):
    action: Literal["enable", "disable", "grant_admin", "revoke_admin"]
    reason: Literal["user_request", "security_incident", "role_assignment", "account_review"]


class AccountUsage(Input):
    limits: AccountLimits
    model_requests: int
    astronomy_queries: int
    storage_bytes: int
    resets_at: datetime


class ComputeCapacity(Input):
    enabled: bool
    worker_ready: bool
    queued: int
    active: int


def masked(address):
    local, _, domain = address.partition("@")
    return f"{local[:1]}***@{domain}"


def admin(request):
    user = actor(request)
    administrator(user)
    return user


def writable(db, user):
    row = db.execute(
        (
            "SELECT u.* FROM public.auth_users u JOIN public.auth_sessions s ON "
            "s.user_id=u.id WHERE u.id=%s AND s.hash=%s AND NOT s.revoked AND "
            "s.expires_at>now() AND s.reauth_at>now()-interval '5 minutes' AND s.mfa_at "
            "IS NOT NULL AND u.admin AND u.active AND NOT u.disabled AND u.totp_secret IS"
            " NOT NULL FOR UPDATE OF u"
        ),
        (user["id"], user["session_hash"]),
    ).fetchone()
    if not row:
        raise ServiceError(403, "reauth_required", "请先重新认证，再执行管理操作。")


@router.get("/overview")
def overview(request: Request):
    service, _ = runtime(request), admin(request)
    with service.store.connect() as db:
        counts = db.execute(
            "SELECT count(*) AS total,count(*) FILTER(WHERE NOT active) AS "
            "pending,count(*) FILTER(WHERE disabled) AS disabled,count(*) FILTER(WHERE "
            "admin AND active AND NOT disabled) AS administrators FROM public.auth_users"
        ).fetchone()
        mail = db.execute(
            "SELECT state,count(*) AS count FROM public.auth_outbox GROUP BY state"
        ).fetchall()
    return {
        "users": counts,
        "mail_configured": service.settings.mail_ready,
        "registration_available": service.registration_ready,
        "mail": mail,
        "mail_hour_limit": service.settings.mail_hour_limit,
        "registration_limit": service.settings.registration_limit,
    }


@router.get("/users")
def users(request: Request, page: int = Query(default=1, ge=1, le=10000)):
    service, _ = runtime(request), admin(request)
    with service.store.connect() as db:
        rows = db.execute(
            (
                "SELECT id,email_display,active,disabled,admin,created_at,last_login FROM "
                "public.auth_users ORDER BY created_at DESC,id LIMIT 30 OFFSET %s"
            ),
            ((page - 1) * 30,),
        ).fetchall()
    return [
        {
            **{k: v for k, v in row.items() if k != "email_display"},
            "email": masked(row["email_display"]),
        }
        for row in rows
    ]


def quota_target(db, user_id):
    target = db.execute(
        "SELECT id,namespace FROM public.auth_users WHERE id=%s", (str(user_id),)
    ).fetchone()
    if not target:
        raise ServiceError(404, "user_not_found", "目标账号不存在。")
    return target


@router.get("/users/{user_id}/quota", response_model=AccountUsage)
def user_quota(user_id: UUID, request: Request):
    service, _ = runtime(request), admin(request)
    with service.store.connect() as db:
        return account_snapshot(db, service.store, quota_target(db, user_id))


@router.put("/users/{user_id}/quota", response_model=AccountUsage)
def set_user_quota(user_id: UUID, body: AccountLimits, request: Request):
    service, user = runtime(request), admin(request)
    service.store.rate("admin_change", source(request), user["id"], limit=20)
    with service.store.connect() as db:
        writable(db, user)
        target = quota_target(db, user_id)
        db.execute(
            "INSERT INTO public.auth_meta(key,value) VALUES (%s,%s) "
            "ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value",
            (limits_key(target["id"]), body.model_dump_json()),
        )
        service.store.audit(db, user["id"], "quota_updated", "ok", target=target["id"])
        return account_snapshot(db, service.store, target)


@router.get("/capacity", response_model=ComputeCapacity)
def capacity(request: Request):
    from astroagent import compute_tasks

    service, _ = runtime(request), admin(request)
    enabled = compute_tasks.enabled()
    with service.store.connect() as db:
        ready = db.execute("SELECT to_regclass('public.compute_tasks') AS relation").fetchone()
        counts = (
            db.execute(
                "SELECT count(*) FILTER (WHERE state='queued') AS queued, "
                "count(*) FILTER (WHERE state IN ('running','cancelling')) AS active "
                "FROM public.compute_tasks"
            ).fetchone()
            if ready["relation"]
            else {"queued": 0, "active": 0}
        )
    return {"enabled": enabled, "worker_ready": enabled and compute_tasks.worker_ready(), **counts}


@router.patch("/users/{user_id}")
def update_user(user_id: UUID, body: UserAction, request: Request):
    service, user = runtime(request), admin(request)
    service.store.rate("admin_change", source(request), user["id"], limit=20)
    with service.store.connect() as db:
        db.execute("SELECT pg_advisory_xact_lock(%s)", (AUTH_LOCK,))
        writable(db, user)
        target = db.execute(
            "SELECT * FROM public.auth_users WHERE id=%s FOR UPDATE", (str(user_id),)
        ).fetchone()
        if not target:
            raise ServiceError(404, "user_not_found", "目标账号不存在。")
        if str(user_id) == user["id"] and body.action in {"disable", "revoke_admin"}:
            raise ServiceError(409, "self_lockout", "不能禁用或降权当前管理员。")
        if (
            body.action in {"disable", "revoke_admin"}
            and target["admin"]
            and target["active"]
            and not target["disabled"]
        ):
            count = db.execute(
                "SELECT count(*) AS n FROM public.auth_users WHERE admin AND active AND NOT "
                "disabled AND totp_secret IS NOT NULL"
            ).fetchone()["n"]
            if target["totp_secret"] and count <= 1:
                raise ServiceError(409, "last_administrator", "不能禁用或降权最后一位有效管理员。")
        if body.action == "grant_admin" and (not target["active"] or target["disabled"]):
            raise ServiceError(409, "user_not_active", "只能授权已激活且未禁用的账号。")
        field, value = {
            "enable": ("disabled", False),
            "disable": ("disabled", True),
            "grant_admin": ("admin", True),
            "revoke_admin": ("admin", False),
        }[body.action]
        # Field names come exclusively from this finite server-side mapping.
        updated = db.execute(
            f"UPDATE public.auth_users SET {field}=%s,generation=generation+1 "
            "WHERE id=%s RETURNING generation",
            (value, str(user_id)),
        ).fetchone()
        service.store.revoke(db, str(user_id))
        service.store.audit(
            db,
            user["id"],
            "user_" + body.action,
            "ok",
            str(user_id),
            service.source_hash(source(request)),
            body.reason,
        )
    service.tenants.invalidate(str(user_id), updated["generation"])
    return {"message": "账号已更新，其旧会话已撤销。"}


@router.get("/mail")
def mail(request: Request, page: int = Query(default=1, ge=1, le=10000)):
    service, _ = runtime(request), admin(request)
    with service.store.connect() as db:
        return db.execute(
            (
                "SELECT id,purpose,state,attempts,created_at,submitted_at,error_class FROM "
                "public.auth_outbox ORDER BY created_at DESC,id LIMIT 30 OFFSET %s"
            ),
            ((page - 1) * 30,),
        ).fetchall()


@router.post("/mail/{mail_id}/retry")
def retry(mail_id: UUID, request: Request):
    service, user = runtime(request), admin(request)
    service.store.rate("admin_mail_retry", source(request), user["id"], limit=5, seconds=3600)
    with service.store.connect() as db:
        writable(db, user)
        row = db.execute(
            (
                "UPDATE public.auth_outbox SET "
                "state='pending',available_at=now(),attempts=0,error_class=NULL WHERE id=%s "
                "AND state='failed' AND payload<>'' AND created_at>now()-interval '1 day' "
                "RETURNING id"
            ),
            (str(mail_id),),
        ).fetchone()
        if not row:
            raise ServiceError(409, "mail_not_retryable", "该邮件不支持重试，请由用户重新申请。")
        service.store.audit(db, user["id"], "mail_retry", "queued", str(mail_id))
    return {"message": "已排入重试；不代表已送达。"}


@router.get("/audit")
def audit(request: Request, page: int = Query(default=1, ge=1, le=10000)):
    service, _ = runtime(request), admin(request)
    with service.store.connect() as db:
        return db.execute(
            (
                "SELECT id,actor,target,event,result,source,reason,created_at FROM "
                "public.auth_audit ORDER BY id DESC LIMIT 50 OFFSET %s"
            ),
            ((page - 1) * 50,),
        ).fetchall()
