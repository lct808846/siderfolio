"""同步会话协调：同会话一轮、全局两轮、终态持久化。"""

import inspect
import logging
import threading

from astroagent.context import PreparedContext
from astroagent.conversations import utc_now
from astroagent.errors import ServiceError
from astroagent.execution import MODEL_TASK_SLOTS
from astroagent.literature_auth import analyze_save_permit
from astroagent.mcp_client import McpAdsAdapter
from astroagent.model_providers import configured_pricing_snapshot
from astroagent.trace_runtime import TraceRecorder, enrich_trace_cost

LOGGER = logging.getLogger(__name__)


class ConversationService:
    def __init__(self, repository):
        self.repository = repository
        self.gate = threading.RLock()
        self.slots = MODEL_TASK_SLOTS
        self.artifacts = None
        self.local_titles = None
        self.literature = None
        self.traces = None

    def delete(self, identifier):
        with self.gate:
            self.repository.delete(identifier)
            if self.artifacts is not None:
                self.artifacts.remove_conversation(identifier)
            if self.traces is not None:
                try:
                    self.traces.delete_conversation(identifier)
                except Exception:
                    pass

    @staticmethod
    def _merge_receipts(turn, persisted):
        seen: set[str] = set()
        merged = []
        sources = list(turn.literature_receipts or [])
        if turn.response is not None and turn.response.literature_receipts:
            sources.extend(turn.response.literature_receipts)
        sources.extend(persisted or [])
        for receipt in sources:
            if receipt.receipt_id not in seen:
                seen.add(receipt.receipt_id)
                merged.append(receipt)
        turn.literature_receipts = merged
        if turn.response is not None:
            turn.response.literature_receipts = list(merged)

    def _apply_turn_enrichment(
        self, turn, persisted_receipts, trace, *, pricing_snapshot=None
    ):
        if persisted_receipts or turn.literature_receipts:
            self._merge_receipts(turn, persisted_receipts)
        if trace is not None:
            if pricing_snapshot is not None:
                pricing, aliases = pricing_snapshot
                trace = enrich_trace_cost(
                    trace, configured_pricing=pricing, model_aliases=aliases
                )
            turn.run_trace = trace
            turn.trace_status = "available"
        elif turn.trace_status == "available":
            turn.run_trace = None
            turn.trace_status = "unavailable"
        return turn

    def enrich_turn(self, conversation_id: str, turn):
        persisted = []
        trace = None
        with self.repository.connection() as db:
            if self.literature is not None:
                try:
                    persisted = self.literature.store.receipts_for_turn_with_db(
                        db, conversation_id, turn.turn_id
                    )
                except Exception:
                    persisted = []
            if self.traces is not None:
                try:
                    trace = self.traces.get_with_db(db, conversation_id, turn.turn_id)
                except Exception:
                    trace = None
        pricing_snapshot = configured_pricing_snapshot() if trace is not None else None
        return self._apply_turn_enrichment(
            turn, persisted, trace, pricing_snapshot=pricing_snapshot
        )

    def turn_enriched(self, conversation_id: str, turn_id: str):
        from astroagent.conversation_schemas import Turn

        with self.repository.connection() as db:
            row = db.execute(
                "SELECT record FROM turns WHERE conversation_id=? AND id=?",
                (conversation_id, turn_id),
            ).fetchone()
            if row is None:
                raise ServiceError(404, "turn_not_found", "轮次不存在。")
            turn = Turn.model_validate_json(row[0])
            persisted = []
            trace = None
            if self.literature is not None:
                try:
                    persisted = self.literature.store.receipts_for_turn_with_db(
                        db, conversation_id, turn.turn_id
                    )
                except Exception:
                    persisted = []
            if self.traces is not None:
                try:
                    trace = self.traces.get_with_db(db, conversation_id, turn.turn_id)
                except Exception:
                    trace = None
        pricing_snapshot = configured_pricing_snapshot() if trace is not None else None
        return self._apply_turn_enrichment(
            turn, persisted, trace, pricing_snapshot=pricing_snapshot
        )

    def bundle(self, identifier: str) -> dict:
        from astroagent.conversation_schemas import Turn

        with self.repository.connection() as db:
            value = self.repository._conversation(db, identifier)
            turns = [
                Turn.model_validate_json(row[0])
                for row in db.execute(
                    "SELECT record FROM turns WHERE conversation_id=? ORDER BY ordinal",
                    (identifier,),
                ).fetchall()
            ]
            receipts_map = {}
            traces_map = {}
            if turns:
                if self.literature is not None:
                    try:
                        receipts_map = self.literature.store.receipts_for_conversation_with_db(
                            db, identifier
                        )
                    except Exception:
                        receipts_map = {}
                if self.traces is not None:
                    try:
                        traces_map = self.traces.get_for_conversation_with_db(db, identifier)
                    except Exception:
                        traces_map = {}
        pricing_snapshot = configured_pricing_snapshot() if traces_map else None
        enriched_turns = [
            self._apply_turn_enrichment(
                turn,
                receipts_map.get(turn.turn_id, []),
                traces_map.get(turn.turn_id),
                pricing_snapshot=pricing_snapshot,
            )
            for turn in turns
        ]
        value["turns"] = [
            {
                **t.model_dump(
                    include={
                        "turn_id",
                        "revision",
                        "message",
                        "model",
                        "execution_status",
                        "received_at",
                        "completed_at",
                    }
                ),
                "response_status": t.response.status if t.response else None,
            }
            for t in enriched_turns
        ]
        return {"conversation": value, "turns": enriched_turns}

    def submit(self, identifier, request, agent_factory, on_event=None):
        with self.gate:
            existing = self.repository.existing(identifier, request)
            if existing is not None:
                existing = self.enrich_turn(identifier, existing)
                return existing, 202 if existing.execution_status == "running" else 200
            if not self.slots.acquire(blocking=False):
                raise ServiceError(
                    503,
                    "conversation_service_busy",
                    "已有两个请求正在处理，请稍后重试。",
                    retryable=True,
                )
            try:
                history = self.repository.history(identifier)
                turn = self.repository.reserve(identifier, request)
            except Exception:
                self.slots.release()
                raise
        title_completion = None
        if self.local_titles is not None:
            try:
                title_completion = self.local_titles.schedule_title(turn)
            except Exception:
                pass
        recorder = TraceRecorder(conversation_id=identifier, turn_id=turn.turn_id)
        failure = None
        try:
            project_sources = None
            knowledge = getattr(self, "knowledge", None)
            if knowledge is not None and hasattr(knowledge, "chat_context"):
                rag_span = recorder.start_span(kind="rag_context", name="项目知识库检索")
                try:
                    project_sources = knowledge.chat_context(identifier, request.message)
                    doc_count = 0
                    if isinstance(project_sources, dict):
                        excerpts = project_sources.get("excerpts") or project_sources.get("documents")
                        if isinstance(excerpts, list):
                            doc_count = len(excerpts)
                    if project_sources:
                        recorder.record_span(
                            span_id=rag_span[0],
                            started_at=rag_span[1],
                            started_mono=rag_span[2],
                            kind="rag_context",
                            name="项目知识库检索",
                            status="ok",
                            transport="internal",
                            provider="pgvector",
                            result_count=doc_count,
                        )
                except Exception:
                    project_sources = None
                    recorder.record_span(
                        span_id=rag_span[0],
                        started_at=rag_span[1],
                        started_mono=rag_span[2],
                        kind="rag_context",
                        name="项目知识库检索",
                        status="error",
                        transport="internal",
                        provider="pgvector",
                        error_code="rag_context_failed",
                    )
            context = PreparedContext(
                history,
                request.message,
                attachments=request.attachments,
                project_sources=project_sources,
                tool_mode=request.tool_mode,
            )
            turn.context = context.record
            agent = agent_factory()
            recorder.astronomy_transport = (
                "mcp" if isinstance(getattr(agent, "ads", None), McpAdsAdapter) else "direct"
            )
            if turn.model is None:
                config = getattr(agent, "settings", None)
                turn.model = getattr(config, "selected_model_id", "") or getattr(
                    config, "deepseek_model", None
                )
            literature_saver = None
            if self.literature is not None:
                permit = analyze_save_permit(
                    request.message,
                    conversation_id=identifier,
                    turn_id=turn.turn_id,
                    client_request_id=request.client_request_id,
                )

                def literature_saver(arguments, current_ads):
                    return self.literature.save_from_agent(
                        permit,
                        arguments,
                        current_batches=current_ads,
                        history_turns=history,
                        ads_service=getattr(agent, "ads", None),
                    )

            converse_params = inspect.signature(agent.converse).parameters
            converse_kwargs = {}
            if on_event is not None and "on_event" in converse_params:
                converse_kwargs["on_event"] = on_event
            if "literature_saver" in converse_params:
                converse_kwargs["literature_saver"] = literature_saver
            if "trace_recorder" in converse_params:
                converse_kwargs["trace_recorder"] = recorder
            turn.response = agent.converse(request.message, context, **converse_kwargs)
            turn.execution_status = "completed"
        except ServiceError as exc:
            failure = exc
            turn.execution_status = "failed"
            turn.error = exc.error
        except Exception:
            failure = ServiceError(
                502, "conversation_execution_failed", "回答未能完成，请查看已保存的状态。"
            )
            turn.execution_status = "failed"
            turn.error = failure.error
        finally:
            if title_completion is not None and turn.execution_status != "completed":
                try:
                    self.local_titles.settle_title(title_completion, wait=False)
                except Exception:
                    title_completion.cancelled.set()
            if self.literature is not None:
                try:
                    persisted = self.literature.store.receipts_for_turn(identifier, turn.turn_id)
                    if persisted or (turn.response and turn.response.literature_receipts):
                        self._merge_receipts(turn, persisted)
                except Exception:
                    pass
            saved_trace = None
            if self.traces is not None:
                trace_overall = (
                    "error"
                    if turn.execution_status != "completed"
                    else "partial"
                    if (turn.response is not None and turn.response.status == "partial")
                    else "error"
                    if (turn.response is not None and turn.response.status == "error")
                    else "ok"
                )
                try:
                    built_trace = recorder.finalize(
                        status=trace_overall,
                        error_code=turn.error.code if turn.error is not None else None,
                    )
                    self.traces.save(built_trace)
                    saved_trace = built_trace
                    turn.trace_status = "available"
                except Exception as exc:
                    LOGGER.warning(
                        "Failed to finalize or persist run trace for turn %s: %s",
                        turn.turn_id,
                        type(exc).__name__,
                    )
                    turn.trace_status = "unavailable"
            turn.run_trace = None
            turn.completed_at = utc_now()
            try:
                turn = self.repository.finish(turn)
            except ServiceError as exc:
                failure = exc
            finally:
                self.slots.release()
            if saved_trace is not None:
                turn.run_trace = saved_trace
        if turn.error and turn.error.code == "turn_result_too_large":
            failure = ServiceError(503, turn.error.code, turn.error.message)
        if failure is not None:
            failure.conversation_id = identifier
            failure.turn_id = turn.turn_id
            raise failure
        return turn, 200
