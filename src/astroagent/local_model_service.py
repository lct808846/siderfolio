"""Automatic conversation naming using one bounded local inference queue."""

import queue
import threading
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

from astroagent.conversations import conversation_title, utc_now
from astroagent.errors import ServiceError
from astroagent.local_model_client import LocalModelClient
from astroagent.local_model_schemas import LocalTask
from astroagent.local_model_store import LocalModelStore, ready
from astroagent.plot_data import digest


class TitleCompletion:
    def __init__(self):
        self.done = threading.Event()
        self.cancelled = threading.Event()
        self.task_id = None


class LocalModelService:
    def __init__(self, conversations, settings):
        self.conversations = conversations
        self.settings = settings
        self.store = LocalModelStore(conversations.repository)
        self.client = LocalModelClient(settings)
        self.lock = threading.RLock()
        self.tasks = queue.Queue()
        self.dispatch = ThreadPoolExecutor(max_workers=1, thread_name_prefix="local-title-records")
        self.dispatch_slots = threading.BoundedSemaphore(20)
        self.capacity = threading.BoundedSemaphore(settings.local_model_queue_size + 1)
        self.pending = set()
        self.title_completions = set()
        self.closed = False
        self.last_identity = {}
        try:
            self.store.recover()
        except Exception:
            pass
        self.worker = threading.Thread(target=self._consume, name="local-inference", daemon=True)
        self.worker.start()

    def _consume(self):
        while not self.closed:
            try:
                value, text, completion = self.tasks.get(timeout=0.2)
            except queue.Empty:
                continue
            try:
                self._run(value, text, completion)
            except Exception:
                # Best effort terminal metadata; a storage outage remains recoverable on restart.
                with self.lock:
                    if not self.closed:
                        try:
                            value.update(
                                state="interrupted",
                                title_applied=False,
                                error="任务记录未能完整保存，请核对状态；不会自动重放推理。",
                            )
                            self.store.finish(value)
                        except Exception:
                            pass
            finally:
                self._complete_title(completion)
                self.tasks.task_done()
                del value, text

    def _complete_title(self, completion):
        with self.lock:
            self.title_completions.discard(completion)
            completion.done.set()

    def settle_title(self, completion, *, wait=True):
        """Finalize first-turn naming before exposing its result; never leave a late overwrite."""
        if completion is None:
            return
        if wait and completion.done.wait(
            timeout=min(self.settings.local_model_timeout_seconds, 60)
        ):
            return
        with self.lock:
            if not completion.done.is_set():
                completion.cancelled.set()
                if completion.task_id is not None:
                    value = self.store.get(completion.task_id)
                    value.update(state="skipped", error="命名等待已结束，保留当前简短标题。")
                    self.store.finish(value)

    def status(self, probe=False):
        with self.store.repo.connection() as db:
            storage = ready(db)
            prefs = self.store.preferences(db)
        configured = bool(self.settings.local_model_enabled and self.settings.local_model_digest)
        enabled = prefs["enabled"] and prefs["auto_titles"]
        state, message = "disabled", "会话使用简短的规则标题。"
        if configured and (enabled or probe):
            try:
                if self.pending and not probe:
                    state, message = "busy", "正在生成会话标题。"
                else:
                    self.last_identity = self.client.identity()
                    state = "ready" if enabled else "disabled"
                    message = (
                        "本地模型已就绪，可自动命名会话。"
                        if enabled
                        else "本地模型已就绪，可开启会话自动命名。"
                    )
            except ServiceError as exc:
                self.last_identity = {}
                state = {
                    "local_model_missing": "model_missing",
                    "local_model_identity_mismatch": "identity_mismatch",
                }.get(exc.error.code, "unavailable")
                message = exc.error.message
        return {
            "state": state,
            "message": message,
            "storage_ready": storage,
            "configured": configured,
            "preferences": prefs,
            "model": self.settings.local_model_name,
            "model_digest": self.settings.local_model_digest,
            "queue_length": self.tasks.qsize(),
            **self.last_identity,
        }

    def _record(self, source, preferences_revision):
        conversation, turn_id, text, truncated, membership = source
        return LocalTask(
            id=str(uuid4()),
            action="title",
            automatic=True,
            conversation_id=conversation["id"],
            turn_id=turn_id,
            state="queued",
            created_at=utc_now(),
            input_sha256=digest(text.encode()),
            input_characters=len(text),
            input_truncated=truncated,
            model=self.settings.local_model_name,
            model_digest=self.settings.local_model_digest,
            metadata_revision=conversation["metadata_revision"],
            preferences_revision=preferences_revision,
            request_sha256=digest((turn_id + ":automatic-title-v1").encode()),
            baseline_title=conversation["title"],
            membership=membership,
        ).model_dump()

    def schedule_title(self, turn):
        # Only a memory enqueue occurs on the chat response path. No model/network/DB wait.
        if (
            not self.settings.local_model_enabled
            or not self.settings.local_model_digest
            or not getattr(turn, "_auto_title_eligible", False)
            or turn.revision != 1
            or self.closed
            or not self.dispatch_slots.acquire(blocking=False)
        ):
            return
        completion = TitleCompletion()
        with self.lock:
            if self.closed:
                self.dispatch_slots.release()
                return
            self.title_completions.add(completion)
        try:
            expected_rev = getattr(turn, "_title_metadata_revision", 1)
            self.dispatch.submit(
                self._automatic,
                turn.conversation_id,
                turn.turn_id,
                turn.message,
                expected_rev,
                completion,
            )
        except RuntimeError:
            self.dispatch_slots.release()
            self._complete_title(completion)
        return completion

    def _automatic(
        self, conversation_id, turn_id, original, expected_metadata_revision, completion
    ):
        queued = False
        try:
            if self.closed or completion.cancelled.is_set():
                return
            with self.store.repo.connection() as db:
                prefs = self.store.preferences(db)
            if not prefs["enabled"] or not prefs["auto_titles"]:
                return
            source = self.store.title_source(conversation_id)
            current = source[0]
            if (
                source[1] != turn_id
                or current["metadata_revision"] != expected_metadata_revision
                or current["title"] != conversation_title(original)
            ):
                return
            value = self._record(source, prefs["revision"])
            queued = self._enqueue_title(value, source[2], completion)
        except Exception:
            # Optional naming must never replace a paid chat result or its error.
            pass
        finally:
            if not queued:
                self._complete_title(completion)
            self.dispatch_slots.release()

    def _enqueue_title(self, value, text, completion):
        with self.lock:
            if self.closed or completion.cancelled.is_set():
                return False
            acquired = self.capacity.acquire(blocking=False)
            if not acquired:
                value.update(
                    state="skipped",
                    completed_at=utc_now(),
                    error="自动命名队列已满，保留规则标题。",
                )
            queued = False
            try:
                saved, fresh = self.store.create(value)
                if acquired and fresh:
                    self.pending.add(value["id"])
                    self.tasks.put_nowait((saved, text, completion))
                    completion.task_id = value["id"]
                    queued = True
                return queued
            finally:
                if acquired and not queued:
                    self.pending.discard(value["id"])
                    self.capacity.release()

    def _run(self, value, text, completion):
        try:
            with self.lock:
                if self.closed:
                    return
                value["state"] = "running"
                if completion.cancelled.is_set():
                    value.update(state="skipped", error="命名等待已结束，保留当前简短标题。")
                current = self.store.finish(value)
                if not current or current["state"] != "running":
                    return
            title = None
            try:
                title, usage = self.client.generate_title(text)
                value.update(state="completed", usage=usage)
            except ServiceError as exc:
                value.update(state="failed", error=exc.error.message)
            except Exception:
                value.update(state="failed", error="会话命名未完成，保留当前标题。")
            with self.lock:
                if self.closed:
                    return
                if completion.cancelled.is_set():
                    value.update(state="skipped", error="命名等待已结束，保留当前简短标题。")
                    title = None
                try:
                    self.store.finish(value, title=title)
                except ServiceError:
                    value.update(
                        state="failed",
                        title_applied=False,
                        error="结果未确认保存，规则标题或人工标题保留。",
                    )
                    self.store.finish(value)
        finally:
            with self.lock:
                self.pending.discard(value["id"])
            self.capacity.release()

    def close(self):
        with self.lock:
            self.closed = True
            for completion in self.title_completions:
                completion.cancelled.set()
                completion.done.set()
            self.title_completions.clear()
            try:
                self.store.recover()
            except Exception:
                pass
            while True:
                try:
                    value, _, _ = self.tasks.get_nowait()
                except queue.Empty:
                    break
                self.pending.discard(value["id"])
                self.capacity.release()
                self.tasks.task_done()
        self.dispatch.shutdown(wait=False, cancel_futures=True)
        self.worker.join(timeout=1)
