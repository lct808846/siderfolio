"""同步会话协调：同会话一轮、全局两轮、终态持久化。"""

import threading

from astroagent.context import PreparedContext
from astroagent.conversations import utc_now
from astroagent.errors import ServiceError
from astroagent.execution import MODEL_TASK_SLOTS


class ConversationService:
    def __init__(self, repository):
        self.repository = repository
        self.gate = threading.RLock()
        self.slots = MODEL_TASK_SLOTS
        self.artifacts = None
        self.local_assistant = None

    def delete(self, identifier):
        with self.gate:
            self.repository.delete(identifier)
            if self.artifacts is not None:
                self.artifacts.remove_conversation(identifier)

    def submit(self, identifier, request, agent_factory):
        with self.gate:
            existing = self.repository.existing(identifier, request)
            if existing is not None:
                return existing, 202 if existing.execution_status == "running" else 200
            if not self.slots.acquire(blocking=False):
                raise ServiceError(
                    503,
                    "conversation_service_busy",
                    "已有两轮正在处理，请稍后重试。",
                    retryable=True,
                )
            try:
                history = self.repository.history(identifier)
                turn = self.repository.reserve(identifier, request)
            except Exception:
                self.slots.release()
                raise
        title_completion = None
        if self.local_assistant is not None:
            try:
                title_completion = self.local_assistant.schedule_title(turn)
            except Exception:
                pass
        failure = None
        try:
            context = PreparedContext(history, request.message, attachments=request.attachments)
            turn.context = context.record
            agent = agent_factory()
            if turn.model is None:
                config = getattr(agent, "settings", None)
                turn.model = getattr(config, "selected_model_id", "") or getattr(
                    config, "deepseek_model", None
                )
            turn.response = agent.converse(request.message, context)
            turn.execution_status = "completed"
        except ServiceError as exc:
            failure = exc
            turn.execution_status = "failed"
            turn.error = exc.error
        except Exception:
            failure = ServiceError(
                502, "conversation_execution_failed", "本轮未能完成，请查看已保存状态。"
            )
            turn.execution_status = "failed"
            turn.error = failure.error
        finally:
            if title_completion is not None:
                try:
                    self.local_assistant.settle_title(
                        title_completion, wait=turn.execution_status == "completed"
                    )
                except Exception:
                    title_completion.cancelled.set()
            turn.completed_at = utc_now()
            try:
                turn = self.repository.finish(turn)
            except ServiceError as exc:
                failure = exc
            finally:
                self.slots.release()
        if turn.error and turn.error.code == "turn_result_too_large":
            failure = ServiceError(503, turn.error.code, turn.error.message)
        if failure is not None:
            failure.conversation_id = identifier
            failure.turn_id = turn.turn_id
            raise failure
        return turn, 200
