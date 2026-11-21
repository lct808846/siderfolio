"""Local task coordination: one inference, bounded queue and manual title priority."""

import queue
import threading
import time
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

from astroagent.conversations import conversation_title, encode, utc_now
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
        self.tasks = queue.PriorityQueue()
        self.sequence = 0
        self.dispatch = ThreadPoolExecutor(max_workers=1, thread_name_prefix="local-title-records")
        self.dispatch_slots = threading.BoundedSemaphore(20)
        self.capacity = threading.BoundedSemaphore(settings.local_model_queue_size + 1)
        self.pending = set()
        self.title_completions = set()
        self.closed = False
        self.results = OrderedDict()
        self.last_identity = {}
        try:
            self.store.recover()
        except Exception:
            pass
        self.worker = threading.Thread(target=self._consume, name="local-inference", daemon=True)
        self.worker.start()

    def _consume(self):
        while not self.closed:
            with self.lock:
                for identifier in list(self.results):
                    if self.results[identifier][0] <= time.monotonic():
                        self.results.pop(identifier, None)
            try:
                _, _, value, text, output_format, title_completion = self.tasks.get(timeout=0.2)
            except queue.Empty:
                continue
            try:
                self._run(value, text, output_format, title_completion)
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
                if title_completion is not None:
                    self._complete_title(title_completion)
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
        state, message = "disabled", "本地助手未启用，继续使用规则标题和原有科研查询路径。"
        if configured and (prefs["enabled"] or probe):
            try:
                if self.pending and not probe:
                    state, message = "busy", "本地任务正在处理；不影响远程科研查询。"
                else:
                    self.last_identity = self.client.identity()
                    state = "ready" if prefs["enabled"] else "disabled"
                    message = (
                        "本地模型身份匹配，可接收明确选择的任务。"
                        if prefs["enabled"]
                        else "本地模型身份匹配；准备记录表并启用后可使用。"
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

    def view(self, identifier):
        value = self.store.get(identifier)
        with self.lock:
            cached = self.results.get(identifier)
            if cached and cached[0] > time.monotonic() and value["state"] == "completed":
                value.update(output=cached[1], output_available=True)
            elif cached:
                self.results.pop(identifier, None)
        return {"task": value}

    def _record(
        self, identifier, action, text, request_hash, automatic=False, source=None, truncated=False
    ):
        with self.store.repo.connection() as db:
            prefs = self.store.preferences(db)
        if not self.settings.local_model_enabled or not self.settings.local_model_digest:
            raise ServiceError(
                409,
                "local_assistant_not_configured",
                "服务端本地模型未配置，不会自动下载或切换到远程。",
            )
        value = LocalTask(
            id=identifier,
            action=action,
            automatic=automatic,
            state="queued",
            created_at=utc_now(),
            input_sha256=digest(text.encode()),
            input_characters=len(text),
            input_truncated=truncated,
            model=self.settings.local_model_name,
            model_digest=self.settings.local_model_digest,
            preferences_revision=prefs["revision"],
            request_sha256=request_hash,
        )
        if source:
            conversation, first, _, _, membership = source
            value = value.model_copy(
                update={
                    "conversation_id": conversation["id"],
                    "turn_id": first,
                    "metadata_revision": conversation["metadata_revision"],
                    "baseline_title": conversation["title"],
                    "membership": membership,
                }
            )
        return value.model_dump()

    def submit(self, identifier, request, source=None):
        text = request.text
        return self._submit(
            self._record(
                identifier,
                request.action,
                text,
                digest(encode(request.model_dump()).encode()),
                source=source,
            ),
            text,
            request.output_format,
        )

    def schedule_title(self, turn):
        # Only a memory enqueue occurs on the chat response path. No model/network/DB wait.
        if (
            not self.settings.local_model_enabled
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
            text = source[2]
            value = self._record(
                str(uuid4()),
                "title",
                text,
                digest((turn_id + ":automatic-title-v1").encode()),
                automatic=True,
                source=source,
                truncated=source[3],
            )
            self._submit(value, text, "paragraph", title_completion=completion)
            # Queue admission is stable even if a fast worker mutates the task state.
            queued = completion.task_id is not None
        except Exception:
            # Optional local assistance must never fail a paid chat or replace its error.
            pass
        finally:
            if not queued:
                self._complete_title(completion)
            self.dispatch_slots.release()

    def _submit(self, value, text, output_format, title_completion=None):
        with self.lock:
            if title_completion is not None and title_completion.cancelled.is_set():
                return None
            if self.closed:
                raise ServiceError(503, "local_assistant_stopping", "本地助手正在关闭。")
            try:
                old = self.store.get(value["id"])
            except ServiceError as exc:
                if exc.status_code != 404:
                    raise
            else:
                if old["request_sha256"] != value["request_sha256"]:
                    raise ServiceError(
                        409, "local_assistant_request_conflict", "请求编号已用于不同输入。"
                    )
                return self.view(value["id"])
            acquired = self.capacity.acquire(blocking=False)
            if not acquired:
                if not value["automatic"]:
                    raise ServiceError(
                        503, "local_assistant_busy", "本地任务队列已满，请稍后手动提交。"
                    )
                value.update(
                    state="skipped",
                    completed_at=utc_now(),
                    error="本地任务队列已满，保留规则标题。",
                )
            try:
                saved, fresh = self.store.create(value)
                if not fresh:
                    if acquired:
                        self.capacity.release()
                    return {"task": saved} if saved else None
                if not acquired:
                    return {"task": saved}
                if title_completion is not None:
                    title_completion.task_id = value["id"]
                self.pending.add(value["id"])
                self.sequence += 1
                self.tasks.put_nowait(
                    (
                        1 if value["automatic"] else 0,
                        self.sequence,
                        saved,
                        text,
                        output_format,
                        title_completion,
                    )
                )
                return {"task": saved}
            except Exception:
                if acquired:
                    self.pending.discard(value["id"])
                    self.capacity.release()
                raise

    def _run(self, value, text, output_format, title_completion=None):
        try:
            with self.lock:
                if self.closed:
                    return
                value["state"] = "running"
                if title_completion is not None and title_completion.cancelled.is_set():
                    value.update(state="skipped", error="命名等待已结束，保留当前简短标题。")
                current = self.store.finish(value)
                if not current or current["state"] != "running":
                    return
            output = None
            try:
                output, usage = self.client.generate(value["action"], text, output_format)
                value.update(state="completed", usage=usage)
            except ServiceError as exc:
                value.update(state="failed", error=exc.error.message)
            except Exception:
                value.update(state="failed", error="本地任务未完成，原内容保留。")
            with self.lock:
                if self.closed:
                    return
                if title_completion is not None and title_completion.cancelled.is_set():
                    value.update(state="skipped", error="命名等待已结束，保留当前简短标题。")
                    output = None
                try:
                    saved = self.store.finish(
                        value, title=output.get("title") if output and value["automatic"] else None
                    )
                except ServiceError:
                    value.update(
                        state="failed",
                        title_applied=False,
                        error="结果未确认保存，规则标题或人工标题保留。",
                    )
                    saved = self.store.finish(value)
                if saved and saved["state"] == "completed" and output:
                    # Manual results remain ephemeral and never enter project archives/backups.
                    self.results[value["id"]] = (time.monotonic() + 600, output)
                    while len(self.results) > 24:
                        self.results.popitem(last=False)
        finally:
            with self.lock:
                self.pending.discard(value["id"])
            self.capacity.release()

    def clear(self):
        with self.lock:
            self.store.clear()
            self.results.clear()

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
            self.results.clear()
            while True:
                try:
                    _, _, value, _, _, title_completion = self.tasks.get_nowait()
                except queue.Empty:
                    break
                self.pending.discard(value["id"])
                self.capacity.release()
                self.tasks.task_done()
        self.dispatch.shutdown(wait=False, cancel_futures=True)
        self.worker.join(timeout=1)
