"""Administrator-only provider configuration; responses never include keys."""

from fastapi import APIRouter, Request

from astroagent.api.admin import admin
from astroagent.api.auth import runtime, source
from astroagent.auth_store import AUTH_LOCK
from astroagent.config import Settings
from astroagent.errors import ServiceError
from astroagent.model_providers import (
    DefaultModelInput,
    ProviderInput,
    ProviderRegistry,
    ProviderRevision,
)

router = APIRouter(prefix="/api/v1/admin/model-providers", tags=["model providers"])


def registry(request):
    return ProviderRegistry(runtime(request).store, Settings())


def writable(db, user):
    # Model settings retain session/MFA/role checks without five-minute reauthentication.
    row = db.execute(
        "SELECT u.id FROM public.auth_users u JOIN public.auth_sessions s ON "
        "s.user_id=u.id WHERE u.id=%s AND s.hash=%s AND NOT s.revoked "
        "AND s.expires_at>now() AND s.mfa_at IS NOT NULL AND u.admin AND u.active "
        "AND NOT u.disabled AND u.totp_secret IS NOT NULL FOR UPDATE OF u",
        (user["id"], user["session_hash"]),
    ).fetchone()
    if not row:
        raise ServiceError(403, "access_denied", "当前登录无权修改模型配置，请重新登录。")


@router.get("")
def providers(request: Request):
    admin(request)
    return registry(request).public()


@router.put("")
def save_provider(body: ProviderInput, request: Request):
    service, user = registry(request), admin(request)
    service.store.rate("provider_save", source(request), user["id"], limit=30)
    with service.store.connect() as db:
        db.execute("SELECT pg_advisory_xact_lock(%s)", (AUTH_LOCK,))
        writable(db, user)
        value = service.read(db)
        exists = any(p["id"] == body.id for p in value["providers"])
        if not exists and (len(value["providers"]) >= 16 or body.id == "system"):
            raise ServiceError(422, "provider_limit", "最多保留 16 个服务商，system 为保留标识。")
        provider = service.provider(body, value)
        if exists:
            value["providers"] = [provider if p["id"] == body.id else p for p in value["providers"]]
        else:
            value["providers"].append(provider)
        result = service.save(db, value, body.revision)
        service.store.audit(db, user["id"], "model_provider_saved", "ok", reason=body.id)
    return result


@router.delete("/{provider_id}")
def delete_provider(provider_id: str, body: ProviderRevision, request: Request):
    service, user = registry(request), admin(request)
    service.store.rate("provider_delete", source(request), user["id"], limit=20)
    with service.store.connect() as db:
        db.execute("SELECT pg_advisory_xact_lock(%s)", (AUTH_LOCK,))
        writable(db, user)
        value = service.read(db)
        if not any(p["id"] == provider_id for p in value["providers"]):
            raise ServiceError(404, "provider_not_found", "服务商不存在，请刷新列表。")
        value["providers"] = [p for p in value["providers"] if p["id"] != provider_id]
        result = service.save(db, value, body.revision)
        service.store.audit(db, user["id"], "model_provider_deleted", "ok", reason=provider_id)
    return result


@router.post("/default")
def default_model(body: DefaultModelInput, request: Request):
    service, user = registry(request), admin(request)
    with service.store.connect() as db:
        db.execute("SELECT pg_advisory_xact_lock(%s)", (AUTH_LOCK,))
        writable(db, user)
        value = service.read(db)
        if body.model not in {m.id for m in service.catalog(value).models}:
            raise ServiceError(422, "model_not_enabled", "请先启用服务商并添加此模型。")
        value["default_model"] = body.model
        result = service.save(db, value, body.revision)
        service.store.audit(db, user["id"], "default_model_changed", "ok")
    return result


@router.post("/discover")
def discover_models(body: ProviderInput, request: Request):
    service, user = registry(request), admin(request)
    service.store.rate("provider_discover", source(request), user["id"], limit=10)
    with service.store.connect() as db:
        writable(db, user)
    return service.discover(body)
