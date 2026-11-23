"""Identity runtime and per-account service graphs, including background workers."""

import re
import threading
from uuid import UUID

from psycopg import sql

from astroagent.auth_config import AuthSettings
from astroagent.auth_mail import MailWorker
from astroagent.auth_security import PASSWORDS, blocklist, keyed, normalize_client_source, opaque
from astroagent.auth_store import AUTH_LOCK, AuthStore
from astroagent.errors import ServiceError
from astroagent.postgres import PostgresRepository


class TenantServices:
    def __init__(self, store, local, control_guard):
        self.store, self.local = store, local
        self.control_guard = control_guard
        self.services = {}
        self.lock = threading.RLock()

    def for_user(self, user):
        self.control_guard()
        identifier = str(UUID(user["id"]))
        with self.lock:
            existing = self.services.get(identifier)
            if existing and existing.identity_generation != user["generation"]:
                self._close(identifier)
                existing = None
            if existing:
                if existing.repository.namespace != user["namespace"]:
                    raise ServiceError(503, "ownership_changed", "数据归属已改变，请重启服务。")
                return existing
            if len(self.services) >= self.store.settings.tenant_limit:
                raise ServiceError(503, "tenant_capacity", "本机活动用户容量已满，请联系管理员。")
            namespace = user["namespace"]
            if not re.fullmatch(r"aa_[0-9a-f]{32}", namespace):
                raise ServiceError(503, "ownership_invalid", "数据归属配置无效，业务访问已关闭。")
            settings = self.local.model_copy(
                update={"data_dir": self.local.data_dir / "accounts" / identifier}
            )
            with self.store.connect() as db:
                db.execute("SELECT pg_advisory_xact_lock(%s)", (AUTH_LOCK,))
                if not db.execute(
                    (
                        "SELECT 1 FROM public.auth_users WHERE id=%s AND active "
                        "AND NOT disabled AND namespace=%s"
                    ),
                    (identifier, namespace),
                ).fetchone():
                    raise ServiceError(403, "account_unavailable", "账号暂不可用。")
                db.execute(
                    sql.SQL("CREATE SCHEMA IF NOT EXISTS {} AUTHORIZATION CURRENT_USER").format(
                        sql.Identifier(namespace)
                    )
                )
                db.execute(
                    sql.SQL("REVOKE ALL ON SCHEMA {} FROM PUBLIC").format(sql.Identifier(namespace))
                )

            def authorized():
                self.control_guard()
                return self.store.active(identifier, user["generation"])

            repository = PostgresRepository(
                settings,
                namespace=namespace,
                identity_guard=authorized,
                identity=(identifier, user["generation"]),
            )
            try:
                repository.initialize(create=True)
                from astroagent.services import compose

                service = compose(repository, settings)
                service.identity_generation = user["generation"]
                # These are private tenant tables, not global operational settings.
                service.plotting.store.initialize()
                service.local_titles.store.initialize()
                service.literature.store.initialize()
                service.traces.initialize()
            except BaseException:
                repository.close()
                raise
            self.services[identifier] = service
            return service

    def _close(self, identifier):
        service = self.services.pop(identifier, None)
        if service:
            service.local_titles.close()
            service.repository.close()

    def invalidate(self, identifier, generation):
        with self.lock:
            service = self.services.get(identifier)
            if service and service.identity_generation != generation:
                self._close(identifier)

    def close(self):
        with self.lock:
            for identifier in list(self.services):
                self._close(identifier)


class IdentityRuntime:
    def __init__(self, local):
        self.settings = AuthSettings()
        self.store = AuthStore(local, self.settings)
        self.store.check()
        # This lifetime lock makes the offline ownership command refuse live migration.
        self.lock_connection = self.store.connect()
        self.guard = self.lock_connection.__enter__()
        if not self.guard.execute(
            "SELECT pg_try_advisory_lock(%s) AS ok", (AUTH_LOCK + 1,)
        ).fetchone()["ok"]:
            self.lock_connection.__exit__(None, None, None)
            raise ServiceError(503, "identity_in_use", "只允许一个身份服务进程。")
        self.guard.commit()
        self.control_mutex = threading.Lock()
        try:
            self.dummy_hash = PASSWORDS.hash(opaque())
            self.tenants = TenantServices(self.store, local, self.ensure_control_lock)
            self.mail = MailWorker(self.store, self.ensure_control_lock)
            self.mail.start()
        except BaseException as exc:
            self.lock_connection.__exit__(type(exc), exc, exc.__traceback__)
            raise

    @property
    def registration_ready(self):
        return self.settings.registration_enabled and self.email_ready

    @property
    def email_ready(self):
        if (
            not self.settings.mail_ready
            or not self.settings.password_blocklist
            or not self.settings.password_blocklist_sha256
        ):
            return False
        try:
            return bool(
                blocklist(self.settings.password_blocklist, self.settings.password_blocklist_sha256)
            )
        except ServiceError:
            return False

    def csrf(self, value):
        return keyed(self.settings, "csrf", value)

    def ensure_control_lock(self):
        with self.control_mutex:
            try:
                if self.guard.closed:
                    raise RuntimeError("Identity lock connection was lost")
                self.guard.execute("SELECT 1")
                self.guard.commit()
            except Exception as exc:
                raise ServiceError(
                    503, "identity_lock_lost", "身份服务锁已失效，请重启服务；业务访问已关闭。"
                ) from exc

    def source_hash(self, value):
        return keyed(self.settings, "source", normalize_client_source(value))[:24]

    def close(self):
        self.mail.close()
        self.tenants.close()
        self.store.close()
        self.lock_connection.__exit__(None, None, None)
