"""Durable queue and tenant-scoped experiment records."""

import logging
import os
import shutil
import threading
from datetime import UTC, datetime
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.types.json import Jsonb

from astroagent.compute_io import attempts, fresh, read, spool, write
from astroagent.compute_schemas import (
    EPSILON,
    MIN_DISTANCE,
    PETAR_REVISION,
    REBOUND_WHEEL_SHA256,
    WALL_SECONDS,
    ZERO_THRESHOLD,
    G,
    PeTarResult,
    ReboundResult,
    SimulationEngine,
)
from astroagent.errors import ServiceError

LOGGER = logging.getLogger(__name__)
LOCK = 456419927012700
TABLE = "public.compute_tasks"
ACTIVE = {"running", "cancelling"}
LIST_FIELDS = "id,name,state,created_at,updated_at,samples_completed,sample_count"
TASK_FIELDS = LIST_FIELDS + (
    ",source,parameters,parameter_sha256,revision,origin_id,attempt_id,started_at,"
    "finished_at,error,events,request_id,confirmed_revision,lease_until,"
    "account_id,project_id,namespace"
)


def enabled() -> bool:
    return os.getenv("ASTROAGENT_COMPUTE_ENABLED") == "1"


def availability() -> None:
    if not enabled():
        raise ServiceError(503, "compute_disabled", "此部署尚未启用计算任务。")


def lock(db):
    db.execute("SELECT pg_advisory_xact_lock(%s)", (LOCK,))


def remove_project(db, identifier):
    """Use the project transaction, including its final identity check."""
    if (
        db.identity is None
        or not db.raw.execute("SELECT to_regclass('public.compute_tasks')").fetchone()[0]
    ):
        return
    lock(db.raw)
    db.raw.execute(
        f"DELETE FROM {TABLE} WHERE account_id=%s AND namespace=%s AND project_id=%s::uuid",
        (db.identity[0], db.namespace, identifier),
    )


def available_project(db, account_id, namespace, project_id) -> bool:
    user = db.execute(
        "SELECT 1 FROM public.auth_users WHERE id=%s AND namespace=%s AND active AND NOT disabled "
        "FOR SHARE",
        (account_id, namespace),
    ).fetchone()
    if (
        not user
        or not db.execute(
            "SELECT to_regclass(%s) AS relation", (f"{namespace}.projects",)
        ).fetchone()["relation"]
    ):
        return False
    return bool(
        db.execute(
            sql.SQL("SELECT 1 FROM {}.projects WHERE id=%s FOR KEY SHARE").format(
                sql.Identifier(namespace)
            ),
            (str(project_id),),
        ).fetchone()
    )


def worker_ready() -> bool:
    return fresh(spool() / "heartbeat")


def worker_engines() -> list[SimulationEngine]:
    if not worker_ready():
        return []
    return ["rebound", "petar"] if fresh(spool() / "petar-heartbeat") else ["rebound"]


def owner_fields(request, project_id):
    principal = request.state.principal
    return principal["id"], project_id, principal["namespace"]


def summary(db, owner):
    return db.execute(
        f"SELECT {LIST_FIELDS} FROM {TABLE} WHERE account_id=%s AND project_id=%s "
        "AND namespace=%s ORDER BY created_at DESC",
        owner,
    ).fetchall()


def task(db, owner, identifier, *, update=False, result=False):
    row = db.execute(
        f"SELECT {TASK_FIELDS}{',result' if result else ''} FROM {TABLE} WHERE account_id=%s "
        "AND project_id=%s AND namespace=%s AND id=%s" + (" FOR UPDATE" if update else ""),
        (*owner, identifier),
    ).fetchone()
    if row is None:
        raise ServiceError(404, "compute_not_found", "找不到这项计算任务。")
    return row


def event(state):
    return Jsonb([{"state": state, "at": datetime.now(UTC).isoformat()}])


def create(db, owner, draft, origin=None):
    count = db.execute(
        f"SELECT count(*) AS count FROM {TABLE} WHERE account_id=%s",
        (owner[0],),
    ).fetchone()["count"]
    if count >= 40:
        raise ServiceError(409, "compute_limit", "每个账号最多保存 40 项计算记录。")
    return db.execute(
        f"INSERT INTO {TABLE} (id,account_id,project_id,namespace,name,source,origin_id,"
        "parameters,parameter_sha256,sample_count,state,events) "
        f"VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'draft',%s) RETURNING {TASK_FIELDS}",
        (
            uuid4(),
            *owner,
            draft.name,
            draft.source,
            origin,
            Jsonb(draft.parameters.model_dump(exclude_defaults=True)),
            draft.parameters.digest(),
            draft.parameters.samples,
            event("draft"),
        ),
    ).fetchone()


def edit(db, row, draft):
    if row["state"] != "draft" or row["revision"] != draft.expected_revision:
        raise ServiceError(409, "compute_revision", "草稿已更新或已提交，请刷新后核对。")
    return db.execute(
        f"UPDATE {TABLE} SET name=%s,source=%s,parameters=%s,parameter_sha256=%s,sample_count=%s,"
        f"revision=revision+1,updated_at=now() WHERE id=%s RETURNING {TASK_FIELDS}",
        (
            draft.name,
            draft.source,
            Jsonb(draft.parameters.model_dump(exclude_defaults=True)),
            draft.parameters.digest(),
            draft.parameters.samples,
            row["id"],
        ),
    ).fetchone()


def confirm(db, row, confirmation):
    if row["request_id"] == confirmation.request_id:
        if (
            row["parameter_sha256"] == confirmation.parameter_sha256
            and row["confirmed_revision"] == confirmation.expected_revision
        ):
            return row
        raise ServiceError(409, "compute_idempotency", "该请求编号已用于其他参数。")
    if (
        row["state"] != "draft"
        or row["revision"] != confirmation.expected_revision
        or (row["parameter_sha256"] != confirmation.parameter_sha256)
    ):
        raise ServiceError(409, "compute_revision", "请刷新并重新核对待运行的草稿。")
    engines = worker_engines()
    if not engines:
        raise ServiceError(503, "compute_worker_unavailable", "计算 Worker 暂不可用，草稿已保存。")
    if row["parameters"].get("engine", "rebound") not in engines:
        raise ServiceError(503, "compute_engine_unavailable", "所选模拟程序暂不可用，草稿已保存。")
    count = db.execute(
        f"SELECT count(*) AS count FROM {TABLE} WHERE account_id=%s AND state='queued'",
        (row["account_id"],),
    ).fetchone()["count"]
    if count >= 2:
        raise ServiceError(409, "compute_queue_limit", "每个账号最多同时排队 2 项计算。")
    try:
        return db.execute(
            f"UPDATE {TABLE} SET state='queued',request_id=%s,confirmed_revision=%s,"
            "queued_at=now(),updated_at=now(),revision=revision+1,events=events || %s "
            f"WHERE id=%s RETURNING {TASK_FIELDS}",
            (confirmation.request_id, confirmation.expected_revision, event("queued"), row["id"]),
        ).fetchone()
    except psycopg.errors.UniqueViolation as exc:
        raise ServiceError(409, "compute_idempotency", "该请求编号已用于另一项计算。") from exc


def transition(db, row, state, error=None, result=None):
    return db.execute(
        f"UPDATE {TABLE} SET state=%s,error=%s,result=%s,events=events || %s,revision=revision+1,"
        "updated_at=now(),finished_at=CASE WHEN %s='cancelling' THEN NULL ELSE now() END "
        f"WHERE id=%s AND attempt_id IS NOT DISTINCT FROM %s RETURNING {TASK_FIELDS}",
        (
            state,
            error,
            Jsonb(result) if result is not None else None,
            event(state),
            state,
            row["id"],
            row["attempt_id"],
        ),
    ).fetchone()


def cancel(db, row):
    if row["state"] == "queued":
        return transition(db, row, "cancelled")
    if row["state"] == "running":
        return transition(db, row, "cancelling")
    return row


def deletable(db, row):
    if row["state"] in ACTIVE or row["state"] == "queued":
        raise ServiceError(409, "compute_active", "请先取消活动任务，再移除记录。")
    db.execute(f"DELETE FROM {TABLE} WHERE id=%s", (row["id"],))


def validate_result(directory, row):
    engine = row["parameters"].get("engine", "rebound")
    result_type = PeTarResult if engine == "petar" else ReboundResult
    result = result_type.model_validate(read(directory / "result"))
    grid = row["parameters"]["duration"]
    count = row["sample_count"]
    if (
        result.engine != engine
        or len(result.samples) != count
        or (result.gravitational_constant, result.zero_threshold) != (G, ZERO_THRESHOLD)
    ):
        raise ValueError("Execution contract")
    if isinstance(result, ReboundResult):
        if (result.epsilon, result.min_distance, result.rebound_wheel_sha256) != (
            EPSILON,
            MIN_DISTANCE,
            REBOUND_WHEEL_SHA256,
        ):
            raise ValueError("REBOUND configuration")
    elif result.petar_revision != PETAR_REVISION:
        raise ValueError("PeTar revision")
    for index, sample in enumerate(result.samples):
        if len(sample.particles) != len(row["parameters"]["particles"]) or abs(
            sample.time - grid * index / (count - 1)
        ) > 1e-12 * max(1.0, grid):
            raise ValueError("Invalid sample")
    return result.model_dump(mode="json")


class Dispatcher(threading.Thread):
    """Only this API-side thread touches PostgreSQL. The simulator has a spool mount."""

    def __init__(self, store):
        super().__init__(name="compute-dispatcher", daemon=True)
        self.store = store
        self.stop_signal = threading.Event()

    def close(self):
        self.stop_signal.set()
        self.join(timeout=5)

    def run(self):
        had_error = False
        while not self.stop_signal.is_set():
            try:
                self.tick()
                had_error = False
            except psycopg.errors.UndefinedTable:
                pass
            except (OSError, ValueError, psycopg.Error, ServiceError) as exc:
                if not had_error:
                    LOGGER.warning("Compute dispatcher unavailable (%s)", type(exc).__name__)
                had_error = True
            self.stop_signal.wait(1)

    def tick(self):
        root = spool()
        if not root.is_dir():
            return
        with self.store.connect() as db:
            lock(db)
            row = db.execute(
                f"SELECT {TASK_FIELDS} FROM {TABLE} WHERE state IN ('running','cancelling') "
                "FOR UPDATE",
            ).fetchone()
            for directory in attempts(root):
                if row and directory.name == row["attempt_id"].hex:
                    continue
                if (directory / "done").exists() or not (directory / "input").exists():
                    shutil.rmtree(directory)
                else:
                    (directory / "cancel").touch()
            if row:
                self.monitor(db, root, row)
                return
            engines = worker_engines()
            if not engines or attempts(root):
                return
            for candidate in db.execute(
                f"SELECT {TASK_FIELDS} FROM {TABLE} WHERE state='queued' "
                "ORDER BY queued_at,id FOR UPDATE SKIP LOCKED",
            ):
                if not self.project_available(db, candidate):
                    transition(db, candidate, "cancelled", "账号或项目已不可用。")
                    continue
                if candidate["parameters"].get("engine", "rebound") not in engines:
                    continue
                db.execute(
                    f"UPDATE {TABLE} SET state='running',attempt_id=%s,lease_until="
                    "now() + interval '12 seconds',started_at=now(),updated_at=now(),"
                    "revision=revision+1,events=events || %s WHERE id=%s",
                    (uuid4(), event("running"), candidate["id"]),
                )
                break

    @staticmethod
    def project_available(db, row):
        return available_project(db, row["account_id"], row["namespace"], row["project_id"])

    def monitor(self, db, root, row):
        directory = root / row["attempt_id"].hex
        now = datetime.now(UTC)
        if row["state"] == "running" and not self.project_available(db, row):
            row = transition(db, row, "cancelling", "账号或项目已不可用。")
        if (directory / "done").exists():
            self.finish(db, directory, row)
            return
        run_alive = worker_ready() and fresh(directory / "heartbeat")
        if (now > row["lease_until"] and not run_alive) or (
            now - row["started_at"]
        ).total_seconds() > WALL_SECONDS + 15:
            if directory.exists():
                (directory / "cancel").touch()
            transition(db, row, "interrupted", "计算失去响应，已撤销本次运行。")
            return
        if row["state"] == "cancelling":
            if directory.exists() and (directory / "input").exists():
                (directory / "cancel").touch()
            else:
                transition(db, row, "cancelled", row["error"])
                return
        elif worker_ready() and not (directory / "input").exists():
            directory.mkdir(mode=0o700, exist_ok=True)
            write(directory / "input", row["parameters"])
        if worker_ready():
            progress = read(directory / "progress", 128) if (directory / "progress").exists() else 0
            db.execute(
                f"UPDATE {TABLE} SET samples_completed=%s,updated_at=now(),"
                "lease_until=now() + interval '12 seconds' WHERE id=%s AND attempt_id=%s",
                (min(progress, row["sample_count"]), row["id"], row["attempt_id"]),
            )

    @staticmethod
    def finish(db, directory, row):
        state = read(directory / "done", 128)
        if row["state"] == "cancelling":
            transition(db, row, "cancelled", row["error"])
        elif state == "succeeded":
            try:
                result = validate_result(directory, row)
            except (OSError, ValueError):
                transition(db, row, "failed", "计算结果未通过完整性检查，请重新运行。")
                return
            db.execute(
                f"UPDATE {TABLE} SET samples_completed=sample_count WHERE id=%s", (row["id"],)
            )
            transition(db, row, "succeeded", result=result)
        elif state == "interrupted":
            transition(db, row, state, "Worker 重启，本次执行已中断。")
        else:
            failure = (
                read(directory / "failure", 4096)
                if (directory / "failure").exists()
                else ("计算进程提前退出，请减少粒子数、时长或采样数后重试。")
            )
            transition(db, row, "failed", failure)
