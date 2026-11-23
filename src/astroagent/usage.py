"""Persistent per-account admission limits using the existing identity tables."""

import time
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from astroagent.auth_security import keyed
from astroagent.errors import ServiceError

HOUR = 3600
_account = ContextVar("account_usage", default=None)


class AccountLimits(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ASTROAGENT_LIMIT_", extra="forbid")
    model_requests: int = Field(default=120, ge=1, le=10000)
    astronomy_queries: int = Field(default=240, ge=1, le=10000)
    storage_mib: int = Field(default=1024, ge=32, le=65536)
    compute_queued: int = Field(default=2, ge=1, le=20)


@lru_cache(maxsize=1)
def defaults() -> AccountLimits:
    return AccountLimits()


def limits_key(account_id: str) -> str:
    return f"account_limits_v2:{account_id}"


def limits_for(db, account_id: str) -> AccountLimits:
    saved = db.execute(
        "SELECT value FROM public.auth_meta WHERE key=%s", (limits_key(account_id),)
    ).fetchone()
    return AccountLimits.model_validate_json(saved["value"]) if saved else defaults()


@contextmanager
def account_usage(store, principal):
    token = _account.set((store, principal["id"], principal["namespace"]) if principal else None)
    try:
        yield
    finally:
        _account.reset(token)


def _rate_key(store, category, account_id):
    return keyed(store.settings, f"usage-v2:{category}", account_id)


def _window():
    now = time.time()
    bucket = int(now) // HOUR
    return bucket, datetime.fromtimestamp((bucket + 1) * HOUR, UTC)


def _usage(db, key, bucket):
    row = db.execute(
        "SELECT hits FROM public.auth_rates WHERE key=%s AND bucket=%s", (key, bucket)
    ).fetchone()
    return row["hits"] if row else 0


def reserve_request(category: str) -> None:
    account = _account.get()
    if account is None:
        return
    store, account_id, _ = account
    bucket, reset_at = _window()
    key = _rate_key(store, category, account_id)
    with store.connect() as db:
        limit = getattr(limits_for(db, account_id), category)
        admitted = db.execute(
            "INSERT INTO public.auth_rates (key,bucket,hits,expires_at) VALUES (%s,%s,1,%s) "
            "ON CONFLICT(key,bucket) DO UPDATE SET hits=auth_rates.hits+1 "
            "WHERE auth_rates.hits<%s RETURNING hits",
            (key, bucket, reset_at, limit),
        ).fetchone()
        if admitted:
            return
        used = _usage(db, key, bucket)
    label = "模型请求" if category == "model_requests" else "天文查询"
    minutes = max(1, int((reset_at.timestamp() - time.time() + 59) // 60))
    raise ServiceError(
        429,
        f"{category}_quota",
        f"本小时{label}已用 {used}/{limit}，约 {minutes} 分钟后恢复。",
        retryable=True,
    )


def storage_bytes(db, namespace: str) -> int:
    return db.execute(
        "SELECT COALESCE(sum(pg_total_relation_size(c.oid)),0)::bigint AS size "
        "FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
        "WHERE n.nspname=%s AND c.relkind IN ('r','m')",
        (namespace,),
    ).fetchone()["size"]


def require_storage(additional_bytes: int = 0) -> None:
    account = _account.get()
    if account is None:
        return
    store, account_id, namespace = account
    with store.connect() as db:
        limit = limits_for(db, account_id).storage_mib
        used = storage_bytes(db, namespace)
    if used + additional_bytes > limit * 1024**2:
        raise ServiceError(
            409,
            "storage_quota",
            f"账号已用 {used / 1024**2:.1f}/{limit} MiB，空间不足。请清理数据或联系管理员。",
        )


def account_snapshot(db, store, user):
    bucket, reset_at = _window()
    return {
        "limits": limits_for(db, user["id"]),
        "model_requests": _usage(db, _rate_key(store, "model_requests", user["id"]), bucket),
        "astronomy_queries": _usage(db, _rate_key(store, "astronomy_queries", user["id"]), bucket),
        "storage_bytes": storage_bytes(db, user["namespace"]),
        "resets_at": reset_at,
    }
