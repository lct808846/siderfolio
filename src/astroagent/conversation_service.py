"""同步会话协调：同会话一轮、全局两轮、终态持久化。"""

import inspect
import logging
import threading
import time
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from astroagent.context import PreparedContext, select_omitted_completed_turns
from astroagent.conversations import utc_now
from astroagent.errors import ServiceError
from astroagent.execution import MODEL_TASK_SLOTS
from astroagent.external_mcp_client import arguments_digest
from astroagent.literature_auth import analyze_save_permit
from astroagent.mcp_client import McpAdsAdapter
from astroagent.model_providers import configured_pricing_snapshot
from astroagent.skill_schemas import SkillPreferences
from astroagent.skill_store import merge_confirmations_into_turn
from astroagent.skills import resolve_turn_skills
from astroagent.tool_catalog import build_turn_tool_catalog
from astroagent.tool_schemas import (
    ExternalMcpConfirmationRecord,
    ExternalMcpConfirmRequest,
    ExternalMcpProposal,
    ExternalMcpResult,
)
from astroagent.trace_runtime import TraceRecorder, classify_error_code, enrich_trace_cost
from astroagent.trace_schemas import RunSpan
from astroagent.usage import require_storage

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
        self.skills = None
        self.memory = None
        self.external_mcp = None
        self.tables = None

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
            if self.skills is not None:
                try:
                    self.skills.delete_conversation(identifier)
                except Exception:
                    pass
            if self.memory is not None:
                try:
                    self.memory.store.on_conversation_deleted(identifier)
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
        self,
        turn,
        persisted_receipts,
        trace,
        *,
        pricing_snapshot=None,
        external_records=None,
    ):
        if persisted_receipts or turn.literature_receipts:
            self._merge_receipts(turn, persisted_receipts)
        if external_records:
            merge_confirmations_into_turn(turn, external_records)
        if turn.skill_resolution is None and turn.response is not None:
            turn.skill_resolution = turn.response.skill_resolution
        if turn.response is not None:
            if turn.memory_receipts and not turn.response.memory_receipts:
                turn.response.memory_receipts = list(turn.memory_receipts)
            elif turn.response.memory_receipts and not turn.memory_receipts:
                turn.memory_receipts = list(turn.response.memory_receipts)
        if trace is not None:
            if pricing_snapshot is not None:
                pricing, aliases = pricing_snapshot
                trace = enrich_trace_cost(trace, configured_pricing=pricing, model_aliases=aliases)
            turn.run_trace = trace
            turn.trace_status = "available"
        elif turn.trace_status == "available":
            turn.run_trace = None
            turn.trace_status = "unavailable"
        return turn

    def enrich_turn(self, conversation_id: str, turn):
        persisted = []
        trace = None
        external_records = []
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
            if self.skills is not None:
                try:
                    external_records = self.skills.records_for_turn_with_db(
                        db, conversation_id, turn.turn_id
                    )
                except Exception:
                    external_records = []
        pricing_snapshot = configured_pricing_snapshot() if trace is not None else None
        return self._apply_turn_enrichment(
            turn,
            persisted,
            trace,
            pricing_snapshot=pricing_snapshot,
            external_records=external_records,
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
            external_records = []
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
            if self.skills is not None:
                try:
                    external_records = self.skills.records_for_turn_with_db(
                        db, conversation_id, turn.turn_id
                    )
                except Exception:
                    external_records = []
        pricing_snapshot = configured_pricing_snapshot() if trace is not None else None
        return self._apply_turn_enrichment(
            turn,
            persisted,
            trace,
            pricing_snapshot=pricing_snapshot,
            external_records=external_records,
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
            external_map = {}
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
                if self.skills is not None:
                    try:
                        external_map = self.skills.records_for_conversation_with_db(db, identifier)
                    except Exception:
                        external_map = {}
        pricing_snapshot = configured_pricing_snapshot() if traces_map else None
        enriched_turns = [
            self._apply_turn_enrichment(
                turn,
                receipts_map.get(turn.turn_id, []),
                traces_map.get(turn.turn_id),
                pricing_snapshot=pricing_snapshot,
                external_records=external_map.get(turn.turn_id, []),
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
            require_storage()
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
                        excerpts = project_sources.get("excerpts") or project_sources.get(
                            "documents"
                        )
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
            project_id = None
            project_hint = ""
            conversation_title = ""
            if isinstance(project_sources, dict):
                project_id = project_sources.get("project_id")
                project_hint = str(project_sources.get("instructions") or "")
            try:
                with self.repository.connection() as db:
                    crow = db.execute(
                        "SELECT title FROM conversations WHERE id=?",
                        (identifier,),
                    ).fetchone()
                    if crow:
                        conversation_title = str(crow[0] or "")
                    if not project_id and getattr(self, "projects", None) is not None:
                        prow = db.execute(
                            "SELECT project_id FROM project_conversations WHERE conversation_id=?",
                            (identifier,),
                        ).fetchone()
                        if prow:
                            project_id = prow[0]
            except Exception:
                pass

            omitted_completed = select_omitted_completed_turns(history)
            memory_bundle = None
            if self.memory is not None:
                mem_span = recorder.start_span(kind="memory_context", name="记忆与跨会话检索")
                sum_span = (
                    recorder.start_span(kind="conversation_summary", name="长对话历史摘要压缩")
                    if omitted_completed
                    else None
                )
                try:
                    memory_bundle = self.memory.prepare_turn_memory(
                        conversation_id=identifier,
                        project_id=project_id,
                        message=request.message,
                        omitted_completed=omitted_completed,
                    )
                    mtrace = memory_bundle.trace
                    if (
                        mtrace.retrieval_mode != "disabled"
                        or mtrace.memory_count > 0
                        or mtrace.history_count > 0
                    ):
                        recorder.record_span(
                            span_id=mem_span[0],
                            started_at=mem_span[1],
                            started_mono=mem_span[2],
                            kind="memory_context",
                            name="记忆与跨会话检索",
                            status="partial" if mtrace.degraded_reasons else "ok",
                            transport="internal",
                            provider=mtrace.retrieval_mode,
                            result_count=mtrace.memory_count + mtrace.history_count,
                        )
                    if sum_span is not None:
                        recorder.record_span(
                            span_id=sum_span[0],
                            started_at=sum_span[1],
                            started_mono=sum_span[2],
                            kind="conversation_summary",
                            name="长对话历史摘要压缩",
                            status="ok" if memory_bundle.summary is not None else "error",
                            transport="internal",
                            provider=(
                                memory_bundle.summary.generation_mode
                                if memory_bundle.summary is not None
                                else "local_rule"
                            ),
                            result_count=mtrace.summary_covered_count,
                            error_code=(
                                "summary_unavailable" if memory_bundle.summary is None else None
                            ),
                        )
                except Exception:
                    memory_bundle = None
                    recorder.record_span(
                        span_id=mem_span[0],
                        started_at=mem_span[1],
                        started_mono=mem_span[2],
                        kind="memory_context",
                        name="记忆与跨会话检索",
                        status="error",
                        transport="internal",
                        error_code="memory_context_failed",
                    )

            context = PreparedContext(
                history,
                request.message,
                attachments=request.attachments,
                project_sources=project_sources,
                tool_mode=request.tool_mode,
                memory_items=memory_bundle.memories if memory_bundle is not None else None,
                history_snippets=(
                    memory_bundle.history_snippets if memory_bundle is not None else None
                ),
                conversation_summary=memory_bundle.summary if memory_bundle is not None else None,
                memory_trace=memory_bundle.trace if memory_bundle is not None else None,
            )
            turn.context = context.record
            agent = agent_factory()
            astro_transport = (
                "mcp" if isinstance(getattr(agent, "ads", None), McpAdsAdapter) else "direct"
            )
            recorder.astronomy_transport = astro_transport
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

            skill_prefs = (
                self.skills.get_preferences() if self.skills is not None else SkillPreferences()
            )
            external_entries = (
                self.external_mcp.approved_tool_entries() if self.external_mcp is not None else []
            )
            max_tool_calls = getattr(getattr(agent, "settings", None), "agent_max_tool_calls", 6)
            base_catalog = build_turn_tool_catalog(
                astronomy_transport=astro_transport,
                include_literature_save=literature_saver is not None,
                max_calls_per_turn=max_tool_calls,
                external_entries=external_entries,
            )
            memory_hint = memory_bundle.memory_hint if memory_bundle is not None else ""
            skill_defs, skill_resolution = resolve_turn_skills(
                request.message,
                requested_skill_id=getattr(request, "skill_id", None),
                requested_skill_ids=getattr(request, "skill_ids", None),
                preferences=skill_prefs,
                available_tool_ids=set(base_catalog.tool_ids),
                tool_mode=request.tool_mode,
                has_attachments=bool(request.attachments),
                project_hint=project_hint,
                memory_hint=memory_hint,
            )
            if (
                context.memory_trace is not None
                and skill_resolution.matched_reason
                and "记忆协同" in skill_resolution.matched_reason
            ):
                context.memory_trace.skill_assisted_by_memory = True
                turn.context.memory_context = context.memory_trace
            recorder.memory_context = context.memory_trace
            skill_allowed_tools = (
                list(dict.fromkeys(tool for skill in skill_defs for tool in skill.allowed_tools))
                if skill_defs
                else None
            )
            turn_catalog = build_turn_tool_catalog(
                astronomy_transport=astro_transport,
                include_literature_save=literature_saver is not None,
                max_calls_per_turn=max_tool_calls,
                external_entries=external_entries,
                external_max_calls_per_turn=getattr(
                    getattr(self.external_mcp, "local_settings", None),
                    "external_mcp_max_calls_per_turn",
                    2,
                ),
                skill_allowed_tools=skill_allowed_tools,
            )
            skill_resolution.available_tool_ids = turn_catalog.tool_ids
            skill_resolution.tool_manifest_sha256 = turn_catalog.manifest_sha256
            turn.skill_resolution = skill_resolution
            recorder.skill_id = skill_resolution.skill_id
            recorder.skill_title = skill_resolution.skill_title
            recorder.skill_titles = list(skill_resolution.skill_titles)
            recorder.skill_version = skill_resolution.skill_version
            recorder.skill_mode = skill_resolution.selection_mode
            recorder.tool_manifest_sha256 = turn_catalog.manifest_sha256

            if on_event is not None and skill_defs:
                if len(skill_defs) == 1:
                    skill_label = f"已载入技能：{skill_defs[0].title}（v{skill_defs[0].version}）"
                else:
                    skill_label = "已载入技能：" + " + ".join(item.title for item in skill_defs)
                on_event(
                    {
                        "type": "status",
                        "phase": "skill",
                        "label": skill_label,
                    }
                )

            external_mcp_proposer = None
            if self.skills is not None and self.external_mcp is not None:

                def external_mcp_proposer(entry, sanitized_args):
                    self.external_mcp.verify_live_execution_authorization(
                        server_id=entry.server_id or "",
                        tool_id=entry.tool_id,
                        expected_definition_sha256=entry.definition_sha256,
                    )
                    now_dt = datetime.now(UTC)
                    proposal = ExternalMcpProposal(
                        confirmation_id=str(uuid4()),
                        conversation_id=identifier,
                        turn_id=turn.turn_id,
                        project_id=project_id,
                        server_id=entry.server_id or "",
                        server_title=entry.server_title or entry.server_id or "",
                        server_host=entry.server_host,
                        tool_id=entry.tool_id,
                        remote_name=entry.remote_name or "",
                        tool_title=entry.title,
                        protocol_version=entry.protocol_version or "",
                        definition_sha256=entry.definition_sha256,
                        arguments=sanitized_args,
                        arguments_sha256=arguments_digest(sanitized_args),
                        outbound_fields=sorted(sanitized_args.keys()),
                        status="pending_confirmation",
                        expires_at=(now_dt + timedelta(minutes=15)).isoformat(),
                        created_at=now_dt.isoformat(),
                    )
                    self.skills.save_proposal(proposal)
                    return proposal

            resolved_active_project_id = project_id
            if not resolved_active_project_id and getattr(self, "projects", None) is not None:
                try:
                    default_proj = self.projects.repository.default_project()
                    if default_proj:
                        resolved_active_project_id = default_proj["id"]
                except Exception:
                    pass

            project_tables_lister = None
            if getattr(self, "tables", None) is not None:

                def project_tables_lister(
                    requested_pid: str | None = None,
                    current_results: list | None = None,
                ):
                    target_pid = requested_pid or resolved_active_project_id
                    if not target_pid and getattr(self, "projects", None) is not None:
                        target_pid = self.projects.repository.ensure_default()["id"]
                    if not target_pid:
                        raise ServiceError(404, "project_record_not_found", "当前未关联科研项目。")
                    self.tables.sync_conversation_catalog_results(
                        target_pid,
                        identifier,
                        history,
                        current_turn_id=turn.turn_id,
                        current_results=current_results,
                    )
                    return self.tables.list_tables_for_agent(target_pid)

            converse_params = inspect.signature(agent.converse).parameters
            converse_kwargs = {}
            if on_event is not None and "on_event" in converse_params:
                converse_kwargs["on_event"] = on_event
            if "literature_saver" in converse_params:
                converse_kwargs["literature_saver"] = literature_saver
            if "trace_recorder" in converse_params:
                converse_kwargs["trace_recorder"] = recorder
            if "skill_definition" in converse_params:
                converse_kwargs["skill_definition"] = skill_defs or None
            if "skill_resolution" in converse_params:
                converse_kwargs["skill_resolution"] = skill_resolution
            if "tool_catalog" in converse_params:
                converse_kwargs["tool_catalog"] = turn_catalog
            if "external_mcp_proposer" in converse_params:
                converse_kwargs["external_mcp_proposer"] = external_mcp_proposer
            if "project_tables_lister" in converse_params:
                converse_kwargs["project_tables_lister"] = project_tables_lister
            if "active_project_id" in converse_params:
                converse_kwargs["active_project_id"] = resolved_active_project_id
            turn.response = agent.converse(request.message, context, **converse_kwargs)
            if turn.response is not None and turn.response.skill_resolution is None:
                turn.response.skill_resolution = skill_resolution
            turn.execution_status = "completed"
            turn.context = context.record
            recorder.memory_context = context.memory_trace
            if self.memory is not None:
                try:
                    memory_receipts = self.memory.process_completed_turn(
                        conversation_id=identifier,
                        project_id=project_id,
                        turn=turn,
                        conversation_title=conversation_title,
                    )
                    if memory_receipts:
                        turn.memory_receipts = list(memory_receipts)
                        if turn.response is not None:
                            turn.response.memory_receipts = list(memory_receipts)
                except Exception:
                    LOGGER.warning("Post-turn memory processing failed for turn %s", turn.turn_id)
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

    def _append_external_trace_span(
        self,
        conversation_id: str,
        turn_id: str,
        *,
        proposal: ExternalMcpProposal,
        status: str,
        started_at: str,
        duration_ms: int,
        returned_count: int = 0,
        truncated: bool = False,
        error_code: str | None = None,
    ) -> None:
        if self.traces is None:
            return
        try:
            trace = self.traces.get(conversation_id, turn_id)
            if trace is None:
                return
            span = RunSpan(
                span_id=str(uuid4()),
                kind="tool_external_mcp",
                name=f"外部 MCP 调用：{proposal.tool_title}",
                status="ok"
                if status == "ok"
                else "cancelled"
                if status == "cancelled"
                else "error",
                started_at=started_at,
                ended_at=datetime.now(UTC).isoformat(),
                duration_ms=max(0, duration_ms),
                transport="external_mcp",
                tool_source="external_mcp",
                protocol_version=proposal.protocol_version,
                provider=proposal.server_title or proposal.server_id,
                truncated=truncated,
                result_count=returned_count,
                error_code=error_code,
                error_category=classify_error_code(error_code) if error_code else None,
                result_ref={
                    "type": "external_mcp",
                    "confirmation_id": proposal.confirmation_id,
                },
            )
            trace.spans.append(span)
            self.traces.save(trace)
        except Exception:
            LOGGER.warning("Failed to append external MCP span for turn %s", turn_id)

    def confirm_external_mcp(
        self,
        conversation_id: str,
        turn_id: str,
        confirmation_id: str,
        body: ExternalMcpConfirmRequest,
    ) -> ExternalMcpConfirmationRecord:
        if self.skills is None or self.external_mcp is None:
            raise ServiceError(503, "external_mcp_unavailable", "外部 MCP 确认服务暂不可用。")
        self.repository.turn(conversation_id, turn_id)
        with self.gate:
            record, existing_req_id = self.skills.get_confirmation(
                conversation_id, turn_id, confirmation_id
            )
            prop = record.proposal
            # Idempotent replay with same client_request_id returns stored result.
            if (
                existing_req_id
                and existing_req_id == body.client_request_id
                and prop.status in ("executed", "failed")
            ):
                return record
            if prop.status != "pending_confirmation":
                raise ServiceError(
                    409,
                    "confirmation_already_consumed",
                    "该外部查询确认已处理或已取消，无法重复提交。",
                )
            try:
                expires_dt = datetime.fromisoformat(prop.expires_at)
                if expires_dt.tzinfo is None:
                    expires_dt = expires_dt.replace(tzinfo=UTC)
            except ValueError:
                expires_dt = datetime.now(UTC) - timedelta(seconds=1)
            if datetime.now(UTC) > expires_dt:
                prop.status = "expired"
                self.skills.update_confirmation(record)
                raise ServiceError(
                    409,
                    "confirmation_expired",
                    "该外部查询确认已过期，请重新发起查询并核对参数。",
                )
            if (
                body.expected_definition_sha256 != prop.definition_sha256
                or body.expected_arguments_sha256 != prop.arguments_sha256
            ):
                raise ServiceError(
                    409,
                    "confirmation_mismatch",
                    "确认绑定的工具定义或外发参数已变化，请重新核对。",
                )
            # Re-check live admin approval & schema digest before any network I/O.
            config, entry = self.external_mcp.verify_live_execution_authorization(
                server_id=prop.server_id,
                tool_id=prop.tool_id,
                expected_definition_sha256=prop.definition_sha256,
            )

        started_at = datetime.now(UTC).isoformat()
        started_mono = time.monotonic()
        try:
            result = self.external_mcp.client.call_tool(
                config,
                confirmation_id=prop.confirmation_id,
                tool_id=prop.tool_id,
                remote_name=prop.remote_name,
                tool_title=prop.tool_title,
                arguments=prop.arguments,
                input_schema=entry.input_schema,
            )
            prop.status = "executed" if result.status == "success" else "failed"
            updated = ExternalMcpConfirmationRecord(proposal=prop, result=result)
            self.skills.update_confirmation(updated, client_request_id=body.client_request_id)
            self._append_external_trace_span(
                conversation_id,
                turn_id,
                proposal=prop,
                status="ok" if result.status == "success" else "error",
                started_at=started_at,
                duration_ms=result.duration_ms or int((time.monotonic() - started_mono) * 1000),
                returned_count=result.returned_count,
                truncated=result.truncated,
                error_code=result.error_code,
            )
            return updated
        except ServiceError as exc:
            duration_ms = max(0, int((time.monotonic() - started_mono) * 1000))
            prop.status = "failed"
            failed_result = ExternalMcpResult(
                confirmation_id=prop.confirmation_id,
                server_id=prop.server_id,
                server_title=prop.server_title,
                tool_id=prop.tool_id,
                remote_name=prop.remote_name,
                tool_title=prop.tool_title,
                protocol_version=prop.protocol_version,
                status="error",
                summary=exc.error.message,
                executed_at=datetime.now(UTC).isoformat(),
                duration_ms=duration_ms,
                error_code=exc.error.code,
                error_message=exc.error.message,
            )
            updated = ExternalMcpConfirmationRecord(proposal=prop, result=failed_result)
            self.skills.update_confirmation(updated, client_request_id=body.client_request_id)
            self._append_external_trace_span(
                conversation_id,
                turn_id,
                proposal=prop,
                status="error",
                started_at=started_at,
                duration_ms=duration_ms,
                error_code=exc.error.code,
            )
            raise

    def cancel_external_mcp(
        self,
        conversation_id: str,
        turn_id: str,
        confirmation_id: str,
    ) -> ExternalMcpConfirmationRecord:
        if self.skills is None:
            raise ServiceError(503, "external_mcp_unavailable", "外部 MCP 确认服务暂不可用。")
        self.repository.turn(conversation_id, turn_id)
        with self.gate:
            record, _ = self.skills.get_confirmation(conversation_id, turn_id, confirmation_id)
            if record.proposal.status != "pending_confirmation":
                return record
            record.proposal.status = "cancelled"
            self.skills.update_confirmation(record)
            self._append_external_trace_span(
                conversation_id,
                turn_id,
                proposal=record.proposal,
                status="cancelled",
                started_at=datetime.now(UTC).isoformat(),
                duration_ms=0,
            )
            return record
