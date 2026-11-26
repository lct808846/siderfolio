"""Public control plane. Business objects never live in these identity tables."""

import json
import queue
import time
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from psycopg.rows import dict_row

from astroagent.auth_security import cipher, digest, keyed, opaque
from astroagent.errors import ServiceError
from astroagent.feedback import install_feedback_schema
from astroagent.mcp_registry_store import install_v21_mcp_schema

AUTH_LOCK = 831049000
EMAIL_COOLDOWN_SECONDS = 60
DDL = (
    "CREATE TABLE public.auth_meta (key text PRIMARY KEY, value text NOT NULL)",
    (
        "CREATE TABLE public.auth_users (id text PRIMARY KEY, email_key text UNIQUE "
        "NOT NULL, email_display text NOT NULL, username text NOT NULL DEFAULT '', "
        "password_hash text, active boolean "
        "NOT NULL DEFAULT false, disabled boolean NOT NULL DEFAULT false, admin "
        "boolean NOT NULL DEFAULT false, namespace text UNIQUE NOT NULL "
        "CHECK(namespace ~ '^aa_[0-9a-f]{32}$'), generation "
        "integer NOT NULL DEFAULT 0, created_at timestamptz NOT NULL DEFAULT now(), "
        "last_login timestamptz, avatar_updated_at timestamptz, "
        "totp_secret text, totp_pending text, "
        "totp_pending_until timestamptz, totp_step bigint NOT NULL DEFAULT -1)"
    ),
    (
        "CREATE TABLE public.auth_avatars (user_id text PRIMARY KEY REFERENCES "
        "public.auth_users(id) ON DELETE CASCADE, content_type text NOT NULL, "
        "content bytea NOT NULL, updated_at timestamptz NOT NULL DEFAULT now())"
    ),
    (
        "CREATE TABLE public.auth_tokens (hash text PRIMARY KEY, user_id text NOT "
        "NULL REFERENCES public.auth_users(id), purpose text NOT NULL, expires_at "
        "timestamptz NOT NULL, consumed_at timestamptz)"
    ),
    (
        "CREATE TABLE public.auth_sessions (hash text PRIMARY KEY, user_id text NOT "
        "NULL REFERENCES public.auth_users(id), created_at timestamptz NOT NULL "
        "DEFAULT now(), last_seen timestamptz NOT NULL DEFAULT now(), expires_at "
        "timestamptz NOT NULL, revoked boolean NOT NULL DEFAULT false, mfa_at "
        "timestamptz, reauth_at timestamptz, source_hash text, "
        "login_ip text NOT NULL DEFAULT '', last_ip text NOT NULL DEFAULT '', "
        "login_location text NOT NULL DEFAULT '', last_location text NOT NULL DEFAULT '', "
        "country_code text NOT NULL DEFAULT '', network_prefix text NOT NULL DEFAULT '', "
        "device_type text NOT NULL DEFAULT 'unknown', device_name text NOT NULL DEFAULT '', "
        "browser text NOT NULL DEFAULT '', os text NOT NULL DEFAULT '', "
        "user_agent text NOT NULL DEFAULT '', anomaly_reason text NOT NULL DEFAULT '')"
    ),
    "CREATE INDEX auth_session_user ON public.auth_sessions(user_id)",
    (
        "CREATE TABLE public.auth_recovery (hash text PRIMARY KEY, user_id text NOT "
        "NULL REFERENCES public.auth_users(id), consumed_at timestamptz)"
    ),
    (
        "CREATE TABLE public.auth_outbox (id text PRIMARY KEY, user_id text NOT NULL "
        "REFERENCES public.auth_users(id), request_id text UNIQUE NOT NULL, purpose "
        "text NOT NULL, payload text NOT NULL, state text NOT NULL DEFAULT 'pending',"
        " attempts integer NOT NULL DEFAULT 0, available_at timestamptz NOT NULL "
        "DEFAULT now(), lease_until timestamptz, created_at timestamptz NOT NULL "
        "DEFAULT now(), submitted_at timestamptz, error_class text)"
    ),
    (
        "CREATE TABLE public.auth_rates (key text NOT NULL, bucket bigint NOT NULL, "
        "hits integer NOT NULL, expires_at timestamptz NOT NULL, PRIMARY "
        "KEY(key,bucket))"
    ),
    (
        "CREATE TABLE public.auth_attempts (key text PRIMARY KEY, failures integer "
        "NOT NULL, blocked_until timestamptz NOT NULL, last_failure timestamptz NOT "
        "NULL)"
    ),
    (
        "CREATE TABLE public.auth_audit (id bigint GENERATED ALWAYS AS IDENTITY "
        "PRIMARY KEY, actor text, target text, event text NOT NULL, result text NOT "
        "NULL, source text, reason text, created_at timestamptz NOT NULL DEFAULT "
        "now())"
    ),
)


class AuthStore:
    def __init__(self, local, settings):
        self.local, self.settings = local, settings
        self.crypto = cipher(settings)
        self._pool: queue.LifoQueue = queue.LifoQueue(maxsize=8)
        self._closed = False

    def _borrow(self):
        import psycopg
        from psycopg.pq import TransactionStatus

        now = time.monotonic()
        while True:
            try:
                db, returned_at = self._pool.get_nowait()
            except queue.Empty:
                break
            if (
                db.closed
                or (now - returned_at) > 60.0
                or db.info.transaction_status != TransactionStatus.IDLE
            ):
                try:
                    db.close()
                except Exception:
                    pass
                continue
            return db
        try:
            return psycopg.connect(
                self.local.database_url.get_secret_value(),
                row_factory=dict_row,
                connect_timeout=5,
                options="-c search_path=pg_catalog -c statement_timeout=5000 -c lock_timeout=2000",
            )
        except Exception as exc:
            raise ServiceError(
                503, "identity_unavailable", "身份服务暂不可用，请稍后重试。"
            ) from exc

    def _release(self, db, *, healthy: bool) -> None:
        from psycopg.pq import TransactionStatus

        if (
            not healthy
            or self._closed
            or db.closed
            or db.info.transaction_status != TransactionStatus.IDLE
        ):
            try:
                db.close()
            except Exception:
                pass
            return
        try:
            self._pool.put_nowait((db, time.monotonic()))
        except queue.Full:
            try:
                db.close()
            except Exception:
                pass

    def close(self) -> None:
        self._closed = True
        while True:
            try:
                db, _ = self._pool.get_nowait()
            except queue.Empty:
                break
            try:
                db.close()
            except Exception:
                pass

    @contextmanager
    def connect(self):
        db = self._borrow()
        healthy = True
        try:
            with db:
                yield db
        except BaseException:
            healthy = False
            raise
        finally:
            self._release(db, healthy=healthy)

    def check(self):
        with self.connect() as db:
            value = db.execute("SELECT value FROM public.auth_meta WHERE key='version'").fetchone()
            if not value or value["value"] != "1":
                raise ServiceError(503, "identity_not_initialized", "身份服务等待本机初始化。")
            key = db.execute(
                "SELECT value FROM public.auth_meta WHERE key='key_identity'"
            ).fetchone()
            if not key or key["value"] != keyed(self.settings, "key", "identity-v1"):
                raise ServiceError(
                    503, "identity_key_mismatch", "身份服务密钥不匹配，请恢复原密钥。"
                )
            db.execute(
                "ALTER TABLE public.auth_users "
                "ADD COLUMN IF NOT EXISTS username text NOT NULL DEFAULT ''"
            )
            db.execute(
                "ALTER TABLE public.auth_users "
                "ADD COLUMN IF NOT EXISTS avatar_updated_at timestamptz"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS public.auth_avatars (user_id text PRIMARY KEY "
                "REFERENCES public.auth_users(id) ON DELETE CASCADE, content_type text NOT NULL, "
                "content bytea NOT NULL, updated_at timestamptz NOT NULL DEFAULT now())"
            )
            db.execute("ALTER TABLE public.auth_sessions ADD COLUMN IF NOT EXISTS source_hash text")
            for column_ddl in (
                "login_ip text NOT NULL DEFAULT ''",
                "last_ip text NOT NULL DEFAULT ''",
                "login_location text NOT NULL DEFAULT ''",
                "last_location text NOT NULL DEFAULT ''",
                "country_code text NOT NULL DEFAULT ''",
                "network_prefix text NOT NULL DEFAULT ''",
                "device_type text NOT NULL DEFAULT 'unknown'",
                "device_name text NOT NULL DEFAULT ''",
                "browser text NOT NULL DEFAULT ''",
                "os text NOT NULL DEFAULT ''",
                "user_agent text NOT NULL DEFAULT ''",
                "anomaly_reason text NOT NULL DEFAULT ''",
            ):
                db.execute(
                    f"ALTER TABLE public.auth_sessions ADD COLUMN IF NOT EXISTS {column_ddl}"
                )
            install_v21_mcp_schema(db)
            db.execute(
                (
                    "UPDATE public.auth_sessions SET "
                    "expires_at=GREATEST(expires_at, now()+(%s * interval '1 second')) "
                    "WHERE NOT revoked AND expires_at>now()"
                ),
                (self.settings.absolute_seconds,),
            )

    def install(self):
        with self.connect() as db:
            db.execute("SELECT pg_advisory_xact_lock(%s)", (AUTH_LOCK,))
            if db.execute("SELECT to_regclass('public.auth_meta') AS t").fetchone()["t"]:
                raise ServiceError(409, "identity_exists", "身份表已存在，不会覆盖。")
            extensions = db.execute(
                "SELECT e.extname,n.nspname FROM pg_extension e JOIN pg_namespace n ON "
                "n.oid=e.extnamespace WHERE e.extname IN ('vector','pg_trgm')"
            ).fetchall()
            if {(v["extname"], v["nspname"]) for v in extensions} != {
                ("vector", "public"),
                ("pg_trgm", "public"),
            }:
                raise ServiceError(
                    503, "identity_extensions", "请先由本机运维在public安装vector及pg_trgm扩展。"
                )
            for statement in DDL:
                db.execute(statement)
            db.execute(
                "INSERT INTO public.auth_meta VALUES ('version','1'),('key_identity',%s)",
                (keyed(self.settings, "key", "identity-v1"),),
            )
            install_feedback_schema(db)
            install_v21_mcp_schema(db)
            self.audit(db, None, "identity_initialized", "ok")

    def audit(self, db, actor, event, result, target=None, source=None, reason=None):
        db.execute(
            (
                "INSERT INTO public.auth_audit(actor,target,event,result,source,reason) "
                "VALUES (%s,%s,%s,%s,%s,%s)"
            ),
            (actor, target, event, result, source, reason),
        )

    def rate(self, action, source, account="", limit=10, seconds=600, *, account_limit=None):
        exceeded = False
        entries = [("source:" + source, limit)]
        if account:
            entries.insert(0, ("account:" + account, account_limit or limit))
        with self.connect() as db:
            for value, maximum in entries:
                exceeded |= self.increment_rate(db, action, value, seconds) > maximum
            db.execute("DELETE FROM public.auth_rates WHERE expires_at<now()")
        if exceeded:
            raise ServiceError(429, "identity_rate_limit", "操作过于频繁，请稍后再试。")

    def increment_rate(self, db, action, value, seconds):
        now = datetime.now(UTC)
        key = keyed(self.settings, "rate:" + action, value)
        row = db.execute(
            "INSERT INTO public.auth_rates VALUES (%s,%s,1,%s) "
            "ON CONFLICT(key,bucket) DO UPDATE SET hits=auth_rates.hits+1 RETURNING hits",
            (key, int(now.timestamp()) // seconds, now + timedelta(seconds=seconds * 2)),
        ).fetchone()
        return row["hits"]

    def enqueue_mail(self, db, user_id, request_id, payload):
        db.execute(
            "INSERT INTO public.auth_outbox(id,user_id,request_id,purpose,payload) "
            "VALUES (%s,%s,%s,%s,%s)",
            (
                str(uuid4()),
                user_id,
                request_id,
                payload["purpose"],
                self.crypto.encrypt(json.dumps(payload).encode()).decode(),
            ),
        )

    def token(self, db, user, purpose, request_id):
        if db.execute(
            "SELECT 1 FROM public.auth_outbox WHERE request_id=%s", (request_id,)
        ).fetchone():
            return
        db.execute(
            (
                "UPDATE public.auth_tokens SET consumed_at=now() WHERE user_id=%s AND purpose"
                " IN (%s,%s) AND consumed_at IS NULL"
            ),
            (user["id"], purpose, "activate_setup" if purpose == "activate" else purpose),
        )
        db.execute(
            (
                "UPDATE public.auth_outbox SET state='cancelled' WHERE user_id=%s AND "
                "purpose=%s AND state IN ('pending','failed')"
            ),
            (user["id"], purpose),
        )
        token = opaque()
        db.execute(
            "INSERT INTO public.auth_tokens VALUES (%s,%s,%s,%s,NULL)",
            (
                digest(token),
                user["id"],
                purpose,
                datetime.now(UTC) + timedelta(seconds=self.settings.token_seconds),
            ),
        )
        page = "activate" if purpose == "activate" else "reset-password"
        payload = {
            "email": user["email_key"],
            "purpose": purpose,
            "url": f"{self.settings.origin}/{page}#token={token}",
            "minutes": self.settings.token_seconds // 60,
        }
        self.enqueue_mail(db, user["id"], request_id, payload)

    def login_backoff(self, account, source, failed=False):
        blocked = False
        with self.connect() as db:
            for value in ("account:" + account, "source:" + source):
                key = keyed(self.settings, "login-backoff", value)
                if failed:
                    row = db.execute(
                        (
                            "INSERT INTO public.auth_attempts VALUES (%s,1,now()+interval '2 "
                            "seconds',now()) ON CONFLICT(key) DO UPDATE SET failures=CASE WHEN "
                            "auth_attempts.last_failure<now()-interval '1 hour' THEN 1 ELSE "
                            "auth_attempts.failures+1 END, "
                            "blocked_until=now()+least(900,power(2,least(10"
                            ",auth_attempts.failures+1)))*interval '1 second',last_failure=now() "
                            "RETURNING failures"
                        ),
                        (key,),
                    ).fetchone()
                    if row["failures"] in (5, 10, 20):
                        self.audit(
                            db, None, "repeated_login_failures", "throttled", source=key[:24]
                        )
                else:
                    blocked |= bool(
                        db.execute(
                            "SELECT 1 FROM public.auth_attempts "
                            "WHERE key=%s AND blocked_until>now()",
                            (key,),
                        ).fetchone()
                    )
            db.execute("DELETE FROM public.auth_attempts WHERE last_failure<now()-interval '1 day'")
        if blocked:
            raise ServiceError(429, "login_backoff", "请稍候再尝试登录。")

    def clear_login_backoff(self, account):
        with self.connect() as db:
            db.execute(
                "DELETE FROM public.auth_attempts WHERE key=%s",
                (keyed(self.settings, "login-backoff", "account:" + account),),
            )

    def authenticate(self, token, touch=True):
        if not token or len(token) > 256:
            return None
        with self.connect() as db:
            row = db.execute(
                (
                    "SELECT u.*,s.hash AS session_hash,s.mfa_at,s.reauth_at,s.last_seen AS "
                    "session_last_seen,s.created_at AS session_created, "
                    "s.device_name AS session_device_name, s.last_ip AS session_last_ip, "
                    "s.last_location AS session_last_location FROM public.auth_sessions s "
                    "JOIN public.auth_users u ON u.id=s.user_id WHERE s.hash=%s AND NOT s.revoked "
                    "AND s.expires_at>now() AND s.last_seen>now()-(%s * interval '1 second') "
                    "AND u.active AND NOT u.disabled"
                ),
                (digest(token), self.settings.idle_seconds),
            ).fetchone()
            if not row:
                return None
            last_seen = row.get("session_last_seen")
            if touch and (
                last_seen is None or last_seen < datetime.now(UTC) - timedelta(seconds=60)
            ):
                db.execute(
                    (
                        "UPDATE public.auth_sessions SET last_seen=now(), "
                        "expires_at=GREATEST(expires_at, now()+(%s * interval '1 second')) "
                        "WHERE hash=%s"
                    ),
                    (self.settings.absolute_seconds, row["session_hash"]),
                )
            return row

    def refresh_session_client(
        self,
        session_hash,
        client,
        *,
        current_device_name="",
        current_last_ip="",
        current_last_location="",
    ):
        """Backfill missing device metadata on legacy sessions and track roaming IP/location."""
        if not session_hash or client is None:
            return
        needs_device = not (current_device_name or "").strip() and bool(client.device_name)
        needs_ip = bool(client.ip) and client.ip != (current_last_ip or "")
        needs_location = bool(client.location) and client.location != (current_last_location or "")
        if not (needs_device or needs_ip or needs_location):
            return
        with self.connect() as db:
            db.execute(
                (
                    "UPDATE public.auth_sessions SET "
                    "last_ip = CASE WHEN %s <> '' THEN %s ELSE last_ip END, "
                    "last_location = CASE WHEN %s <> '' THEN %s ELSE last_location END, "
                    "login_ip = CASE WHEN login_ip = '' AND %s <> '' THEN %s ELSE login_ip END, "
                    "login_location = CASE WHEN login_location = '' AND %s <> '' "
                    "THEN %s ELSE login_location END, "
                    "country_code = CASE WHEN country_code = '' AND %s <> '' "
                    "THEN %s ELSE country_code END, "
                    "network_prefix = CASE WHEN network_prefix = '' AND %s <> '' "
                    "THEN %s ELSE network_prefix END, "
                    "device_type = CASE WHEN device_name = '' AND %s <> '' "
                    "THEN %s ELSE device_type END, "
                    "device_name = CASE WHEN device_name = '' AND %s <> '' "
                    "THEN %s ELSE device_name END, "
                    "browser = CASE WHEN browser = '' AND %s <> '' THEN %s ELSE browser END, "
                    "os = CASE WHEN os = '' AND %s <> '' THEN %s ELSE os END, "
                    "user_agent = CASE WHEN user_agent = '' AND %s <> '' "
                    "THEN %s ELSE user_agent END "
                    "WHERE hash=%s AND NOT revoked"
                ),
                (
                    client.ip,
                    client.ip,
                    client.location,
                    client.location,
                    client.ip,
                    client.ip,
                    client.location,
                    client.location,
                    client.country_code,
                    client.country_code,
                    client.network_prefix,
                    client.network_prefix,
                    client.device_name,
                    client.device_type,
                    client.device_name,
                    client.device_name,
                    client.browser,
                    client.browser,
                    client.os,
                    client.os,
                    client.user_agent,
                    client.user_agent,
                    session_hash,
                ),
            )

    def security_mail(self, db, user, message, *, subject=None):
        if not self.settings.mail_ready:
            return
        payload = {"email": user["email_key"], "purpose": "security", "message": message}
        if subject:
            payload["subject"] = subject
        identifier = str(uuid4())
        db.execute(
            (
                "INSERT INTO public.auth_outbox(id,user_id,request_id,purpose,payload) VALUES"
                " (%s,%s,%s,'security',%s)"
            ),
            (
                identifier,
                user["id"],
                identifier,
                self.crypto.encrypt(json.dumps(payload).encode()).decode(),
            ),
        )

    def active(self, user_id, generation):
        with self.connect() as db:
            return bool(
                db.execute(
                    (
                        "SELECT 1 FROM public.auth_users WHERE id=%s AND generation=%s "
                        "AND active AND NOT disabled"
                    ),
                    (user_id, generation),
                ).fetchone()
            )

    def session(self, db, user_id, mfa=False, source_hash=None, *, client=None, anomaly_reason=""):
        token = opaque()
        now = datetime.now(UTC)
        db.execute(
            (
                "INSERT INTO public.auth_sessions("
                "hash,user_id,expires_at,mfa_at,reauth_at,source_hash,"
                "login_ip,last_ip,login_location,last_location,country_code,network_prefix,"
                "device_type,device_name,browser,os,user_agent,anomaly_reason"
                ") VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)"
            ),
            (
                digest(token),
                user_id,
                now + timedelta(seconds=self.settings.absolute_seconds),
                now if mfa else None,
                now,
                source_hash,
                client.ip if client else "",
                client.ip if client else "",
                client.location if client else "",
                client.location if client else "",
                client.country_code if client else "",
                client.network_prefix if client else "",
                client.device_type if client else "unknown",
                client.device_name if client else "",
                client.browser if client else "",
                client.os if client else "",
                client.user_agent if client else "",
                anomaly_reason or "",
            ),
        )
        return token

    def revoke(self, db, user_id):
        db.execute("UPDATE public.auth_sessions SET revoked=true WHERE user_id=%s", (user_id,))

    def revoke_others(self, db, user_id, current_session_hash):
        rows = db.execute(
            (
                "UPDATE public.auth_sessions SET revoked=true "
                "WHERE user_id=%s AND hash<>%s AND NOT revoked RETURNING hash"
            ),
            (user_id, current_session_hash),
        ).fetchall()
        return len(rows)

    @staticmethod
    def public_user(user):
        avatar_at = user.get("avatar_updated_at")
        avatar_url = (
            f"/api/v1/auth/avatar?v={int(avatar_at.timestamp() * 1_000_000)}" if avatar_at else ""
        )
        return {
            "id": user["id"],
            "email": user["email_display"],
            "username": (user.get("username") or "").strip() or user["email_display"].split("@")[0],
            "avatar_url": avatar_url,
            "admin": user["admin"],
            "totp_enabled": bool(user["totp_secret"]),
            "mfa_verified": bool(user.get("mfa_at")),
        }
