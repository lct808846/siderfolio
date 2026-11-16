"""User-scoped avatar sanitization and workspace model usage aggregation."""

import io
import json
from datetime import UTC

from PIL import Image, ImageOps, UnidentifiedImageError

from astroagent.config import Settings
from astroagent.errors import ServiceError
from astroagent.local_model_store import ready as local_ready
from astroagent.model_providers import ProviderRegistry
from astroagent.plot_store import ready as plot_ready
from astroagent.profile_schemas import (
    ModelUsageEntry,
    ProfileAccountInfo,
    ProfileSummary,
    WorkspaceUsageStats,
)

MAX_AVATAR_BYTES = 5 * 1024 * 1024
ALLOWED_FORMATS = {"PNG", "JPEG", "WEBP", "GIF"}
AVATAR_SIZE = (256, 256)
MAX_SOURCE_PIXELS = 4096 * 4096


def normalize_avatar(raw: bytes) -> tuple[bytes, str]:
    """Decode raster upload, strip EXIF/polyglot data, and re-encode a 256px PNG."""
    if not raw:
        raise ServiceError(400, "avatar_empty", "请选择有效的图片文件。")
    if len(raw) > MAX_AVATAR_BYTES:
        raise ServiceError(413, "avatar_too_large", "头像图片不能超过 5 MiB。")
    try:
        with Image.open(io.BytesIO(raw)) as opened:
            fmt = (opened.format or "").upper()
            if fmt not in ALLOWED_FORMATS:
                raise ServiceError(
                    422, "invalid_avatar_format", "仅支持 PNG、JPEG、WEBP 或 GIF 图片。"
                )
            if opened.width * opened.height > MAX_SOURCE_PIXELS:
                raise ServiceError(
                    422,
                    "invalid_avatar_image",
                    "头像像素过大，请使用不超过 4096 × 4096 像素的图片。",
                )
            opened.seek(0)
            opened.load()
            oriented = ImageOps.exif_transpose(opened)
            converted = oriented.convert("RGBA" if "A" in oriented.getbands() else "RGB")
            square = ImageOps.fit(converted, AVATAR_SIZE, method=Image.Resampling.LANCZOS)
            output = io.BytesIO()
            square.save(output, format="PNG", optimize=True)
            return output.getvalue(), "image/png"
    except ServiceError:
        raise
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as exc:
        raise ServiceError(
            422, "invalid_avatar_image", "无法读取头像图片，请更换 PNG、JPEG 或 WEBP 文件。"
        ) from exc


def save_user_avatar(identity, user_id: str, raw: bytes) -> str:
    content, content_type = normalize_avatar(raw)
    with identity.store.connect() as db:
        db.execute(
            (
                "INSERT INTO public.auth_avatars(user_id, content_type, content, updated_at) "
                "VALUES (%s, %s, %s, now()) "
                "ON CONFLICT (user_id) DO UPDATE SET "
                "content_type=EXCLUDED.content_type, content=EXCLUDED.content, updated_at=now()"
            ),
            (user_id, content_type, content),
        )
        row = db.execute(
            "UPDATE public.auth_users SET avatar_updated_at=now() "
            "WHERE id=%s RETURNING avatar_updated_at",
            (user_id,),
        ).fetchone()
    ts = int(row["avatar_updated_at"].timestamp() * 1_000_000)
    return f"/api/v1/auth/avatar?v={ts}"


def delete_user_avatar(identity, user_id: str) -> str:
    with identity.store.connect() as db:
        db.execute("DELETE FROM public.auth_avatars WHERE user_id=%s", (user_id,))
        db.execute("UPDATE public.auth_users SET avatar_updated_at=NULL WHERE id=%s", (user_id,))
    return ""


def _iso_utc(value) -> str | None:
    if value is None:
        return None
    if getattr(value, "tzinfo", None) is None:
        return value.replace(tzinfo=UTC).isoformat()
    return value.astimezone(UTC).isoformat()


def _label_map(identity, local_settings) -> dict[str, str]:
    labels: dict[str, str] = {}
    try:
        catalog = ProviderRegistry(identity.store, Settings()).catalog()
        for entry in catalog.models:
            if entry.id and entry.label:
                labels[entry.id] = entry.label
    except Exception:
        pass
    local_name = getattr(local_settings, "local_model_name", "")
    if local_name:
        labels.setdefault(local_name, f"{local_name} (本地助手)")
    return labels


def _accumulate_model(
    buckets: dict[str, dict],
    model_id: str,
    channel: str,
    ok: bool,
    timestamp: str | None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    total_tokens: int | None = None,
):
    key = (model_id or "").strip() or "未记录模型"
    entry = buckets.setdefault(
        key,
        {
            "model": key,
            "calls": 0,
            "succeeded": 0,
            "failed": 0,
            "chat_calls": 0,
            "plot_calls": 0,
            "rag_calls": 0,
            "local_calls": 0,
            "input_tokens": None,
            "output_tokens": None,
            "total_tokens": None,
            "last_used_at": None,
        },
    )
    entry["calls"] += 1
    if ok:
        entry["succeeded"] += 1
    else:
        entry["failed"] += 1
    field = f"{channel}_calls"
    if field in entry:
        entry[field] += 1
    if timestamp and (entry["last_used_at"] is None or timestamp > entry["last_used_at"]):
        entry["last_used_at"] = timestamp
    if isinstance(input_tokens, int) and input_tokens >= 0:
        entry["input_tokens"] = (entry["input_tokens"] or 0) + input_tokens
    if isinstance(output_tokens, int) and output_tokens >= 0:
        entry["output_tokens"] = (entry["output_tokens"] or 0) + output_tokens
    if isinstance(total_tokens, int) and total_tokens >= 0:
        entry["total_tokens"] = (entry["total_tokens"] or 0) + total_tokens


def build_profile_summary(identity, user, service) -> ProfileSummary:
    with identity.store.connect() as db:
        row = db.execute(
            "SELECT created_at, last_login, avatar_updated_at FROM public.auth_users WHERE id=%s",
            (user["id"],),
        ).fetchone()
        sessions_count = db.execute(
            (
                "SELECT count(*) AS n FROM public.auth_sessions WHERE user_id=%s AND NOT revoked "
                "AND expires_at>now() AND last_seen>now()-(%s * interval '1 second')"
            ),
            (user["id"], identity.settings.idle_seconds),
        ).fetchone()["n"]

    public = identity.store.public_user(user)
    account = ProfileAccountInfo(
        id=public["id"],
        email=public["email"],
        username=public["username"],
        avatar_url=public["avatar_url"],
        admin=public["admin"],
        totp_enabled=public["totp_enabled"],
        mfa_verified=public["mfa_verified"],
        created_at=_iso_utc(row["created_at"] if row else None) or "",
        last_login=_iso_utc(row["last_login"] if row else None),
        active_sessions=int(sessions_count),
    )

    labels = _label_map(identity, service.repository.settings)
    model_buckets: dict[str, dict] = {}
    conversations_count = turns_count = completed_turns = failed_turns = 0
    projects_count = snapshots_count = workflows_count = knowledge_documents_count = 0
    plot_datasets_count = plot_operations_count = rag_answers_count = local_tasks_count = 0
    simbad_queries = ads_queries = gaia_queries = 0
    used_bytes = 0
    storage_ready = False

    def _as_int(value) -> int | None:
        return value if isinstance(value, int) and not isinstance(value, bool) else None

    with service.repository.connection() as db:
        storage_ready = bool(db.execute("SELECT to_regclass('conversations')").fetchone()[0])
        if storage_ready:
            conversations_count = db.execute("SELECT count(*) FROM conversations").fetchone()[0]
            projects_count = db.execute("SELECT count(*) FROM projects").fetchone()[0]
            snapshots_count = db.execute("SELECT count(*) FROM snapshots").fetchone()[0]
            workflows_count = db.execute("SELECT count(*) FROM workflows").fetchone()[0]
            knowledge_documents_count = db.execute(
                "SELECT count(*) FROM knowledge_documents"
            ).fetchone()[0]
            used_bytes = int(service.repository._used(db))

            for row in db.execute("SELECT record FROM turns"):
                turns_count += 1
                record = json.loads(row[0])
                status = record.get("execution_status")
                ok = status == "completed"
                if ok:
                    completed_turns += 1
                elif status in {"failed", "interrupted"}:
                    failed_turns += 1
                if status in {"completed", "failed", "interrupted"}:
                    _accumulate_model(
                        model_buckets,
                        record.get("model") or "",
                        "chat",
                        ok,
                        record.get("received_at"),
                    )
                response = record.get("response") or {}
                simbad_queries += len(response.get("results") or ())
                ads_queries += len(response.get("literature_results") or ())
                gaia_queries += len(response.get("gaia_results") or ())

            if plot_ready(db):
                plot_datasets_count = db.execute("SELECT count(*) FROM plot_datasets").fetchone()[0]
                plot_operations_count = db.execute(
                    "SELECT count(*) FROM plot_operations"
                ).fetchone()[0]
                for row in db.execute("SELECT record FROM plot_operations WHERE kind='plan'"):
                    op = json.loads(row[0])
                    if op.get("state") not in {"completed", "failed", "interrupted"}:
                        continue
                    req = op.get("request") or {}
                    usage = op.get("model_usage") or {}
                    inp = _as_int(usage.get("input_tokens"))
                    out = _as_int(usage.get("output_tokens"))
                    tot = _as_int(usage.get("total_tokens"))
                    if tot is None and (inp is not None or out is not None):
                        tot = (inp or 0) + (out or 0)
                    _accumulate_model(
                        model_buckets,
                        req.get("model_id") or req.get("model") or "绘图方案模型",
                        "plot",
                        op.get("state") == "completed",
                        op.get("created_at"),
                        input_tokens=inp,
                        output_tokens=out,
                        total_tokens=tot,
                    )

            if db.execute("SELECT to_regclass('rag_answers')").fetchone()[0]:
                for row in db.execute("SELECT record FROM rag_answers"):
                    rag_answers_count += 1
                    rag = json.loads(row[0])
                    if rag.get("state") not in {"completed", "failed", "interrupted"}:
                        continue
                    _accumulate_model(
                        model_buckets,
                        rag.get("model") or "",
                        "rag",
                        rag.get("state") == "completed",
                        rag.get("created_at"),
                    )

            if local_ready(db):
                for row in db.execute("SELECT record FROM local_assistant_tasks"):
                    local_tasks_count += 1
                    task = json.loads(row[0])
                    if task.get("state") not in {"completed", "failed", "interrupted"}:
                        continue
                    usage = task.get("usage") or {}
                    inp = _as_int(usage.get("prompt_eval_count"))
                    out = _as_int(usage.get("eval_count"))
                    tot = (inp or 0) + (out or 0) if (inp is not None or out is not None) else None
                    _accumulate_model(
                        model_buckets,
                        task.get("model") or "",
                        "local",
                        task.get("state") == "completed",
                        task.get("created_at"),
                        input_tokens=inp,
                        output_tokens=out,
                        total_tokens=tot,
                    )

    models = [
        ModelUsageEntry(
            **{
                **item,
                "label": labels.get(item["model"], item["model"]),
            }
        )
        for item in sorted(
            model_buckets.values(),
            key=lambda v: (v["calls"], v["last_used_at"] or ""),
            reverse=True,
        )
    ]
    token_values = [m.total_tokens for m in models if m.total_tokens is not None]
    known_total_tokens = sum(token_values) if token_values else None
    total_calls = sum(m.calls for m in models)

    return ProfileSummary(
        account=account,
        total_model_calls=total_calls,
        distinct_models_count=len(models),
        known_total_tokens=known_total_tokens,
        models=models,
        workspace=WorkspaceUsageStats(
            conversations_count=conversations_count,
            turns_count=turns_count,
            completed_turns=completed_turns,
            failed_turns=failed_turns,
            projects_count=projects_count,
            snapshots_count=snapshots_count,
            workflows_count=workflows_count,
            knowledge_documents_count=knowledge_documents_count,
            plot_datasets_count=plot_datasets_count,
            plot_operations_count=plot_operations_count,
            rag_answers_count=rag_answers_count,
            local_tasks_count=local_tasks_count,
            simbad_queries=simbad_queries,
            ads_queries=ads_queries,
            gaia_queries=gaia_queries,
            used_bytes=used_bytes,
            budget_bytes=service.repository.settings.storage_bytes,
            storage_ready=storage_ready,
        ),
    )
