"""个人天文文献库统一业务服务：手动添加与对话内模型入库共用同一校验与幂等事务。"""

from __future__ import annotations

from astroagent.errors import ServiceError
from astroagent.literature_auth import SavePermit
from astroagent.literature_schemas import (
    LiteratureItem,
    LiteratureListResponse,
    LiteratureManualAddRequest,
    LiteratureSaveReceipt,
    LiteratureSaveReceiptItem,
    LiteratureSourceRef,
    LiteratureUpdateRequest,
    SaveLiteratureQuery,
)
from astroagent.literature_store import LiteratureStore
from astroagent.schemas import LiteratureQuery, PaperData


def _has_verifiable_ads_source(paper: PaperData) -> bool:
    return (
        bool(paper.bibcode and paper.bibcode.strip())
        and paper.source.name == "ADS"
        and paper.source.url.startswith("https://ui.adsabs.harvard.edu/abs/")
    )


class LiteratureService:
    def __init__(self, conversation_service):
        self.conversations = conversation_service
        self.repo = conversation_service.repository
        self.store = LiteratureStore(self.repo)

    def _is_imported_turn(self, turn_id: str) -> bool:
        with self.repo.connection() as db:
            row = db.execute(
                "SELECT 1 FROM imported_turn_origins WHERE turn_id=?",
                (turn_id,),
            ).fetchone()
            return bool(row)

    @staticmethod
    def _verify_via_ads(
        papers: list[tuple[int, PaperData]],
        ads_service,
    ) -> tuple[list[tuple[int, PaperData]], list[LiteratureSaveReceiptItem], list[str]]:
        if ads_service is None:
            rejected = [
                LiteratureSaveReceiptItem(
                    bibcode=paper.bibcode,
                    title=paper.title,
                    year=paper.year,
                    authors=list(paper.authors),
                    status="unverified",
                    reason="该记录来源为导入归档或缺少可核实 ADS 信息，当前无法联网核实。",
                )
                for _, paper in papers
            ]
            return [], rejected, ["未核实的导入文献未写入文献库。"]

        verified: list[tuple[int, PaperData]] = []
        rejected: list[LiteratureSaveReceiptItem] = []
        warnings: list[str] = []
        for pos, paper in papers:
            query = LiteratureQuery(query=f'bibcode:"{paper.bibcode}"', rows=1)
            result = ads_service.search(query)
            matched = next((p for p in result.papers if p.bibcode == paper.bibcode), None)
            if result.status == "success" and matched is not None and _has_verifiable_ads_source(matched):
                verified.append((pos, matched))
            else:
                rejected.append(
                    LiteratureSaveReceiptItem(
                        bibcode=paper.bibcode,
                        title=paper.title,
                        year=paper.year,
                        authors=list(paper.authors),
                        status="unverified",
                        reason=(
                            result.error.message
                            if result.error is not None
                            else "ADS 未能核实该 bibcode，未写入文献库。"
                        ),
                    )
                )
        if rejected:
            warnings.append(f"有 {len(rejected)} 条候选未能通过 ADS 来源核实，未写入文献库。")
        return verified, rejected, warnings

    def list_items(
        self,
        *,
        q: str = "",
        year: int | None = None,
        tag: str = "",
        page: int = 1,
        page_size: int = 20,
    ) -> LiteratureListResponse:
        return self.store.list_items(query=q, year=year, tag=tag, page=page, page_size=page_size)

    def get_item(self, item_id: str) -> LiteratureItem:
        return self.store.get_item(item_id)

    def status_by_bibcodes(self, bibcodes: list[str]) -> dict[str, str]:
        return self.store.lookup_bibcodes(bibcodes)

    def update_item(self, item_id: str, request: LiteratureUpdateRequest) -> LiteratureItem:
        return self.store.update_item(
            item_id,
            expected_revision=request.expected_revision,
            tags=request.tags,
            note=request.note,
        )

    def delete_item(self, item_id: str, expected_revision: int) -> None:
        self.store.delete_item(item_id, expected_revision=expected_revision)

    def add_manual(
        self,
        request: LiteratureManualAddRequest,
        *,
        ads_service=None,
    ) -> LiteratureSaveReceipt:
        needs_reverify = False
        batch = None
        if request.conversation_id and request.turn_id:
            turn = self.repo.turn(request.conversation_id, request.turn_id)
            if turn.response is None or not turn.response.literature_results:
                raise ServiceError(404, "ads_batch_not_found", "该会话轮次中没有可保存的 ADS 检索结果。")
            if request.batch_index >= len(turn.response.literature_results):
                raise ServiceError(404, "ads_batch_not_found", "指定的 ADS 检索批次不存在。")
            batch = turn.response.literature_results[request.batch_index]
            needs_reverify = self._is_imported_turn(request.turn_id)
        elif request.project_id and request.snapshot_id:
            snapshot = self.conversations.projects.snapshot(request.project_id, request.snapshot_id)
            if not snapshot.response.literature_results:
                raise ServiceError(404, "ads_batch_not_found", "该快照中没有可保存的 ADS 检索结果。")
            if request.batch_index >= len(snapshot.response.literature_results):
                raise ServiceError(404, "ads_batch_not_found", "指定的 ADS 检索批次不存在。")
            batch = snapshot.response.literature_results[request.batch_index]
            needs_reverify = snapshot.provenance == "imported_unverified"

        if batch is None or batch.status != "success" or not batch.papers:
            raise ServiceError(422, "ads_batch_unavailable", "所选 ADS 批次未成功返回文献，无法入库。")

        selected: list[tuple[int, PaperData]] = []
        seen: set[int] = set()
        if request.paper_indices:
            for pos in request.paper_indices:
                if pos > len(batch.papers):
                    raise ServiceError(422, "literature_index_invalid", f"文献序号 #{pos} 超出该批次范围。")
                if pos not in seen:
                    seen.add(pos)
                    selected.append((pos, batch.papers[pos - 1]))
        if request.bibcodes:
            by_code = {paper.bibcode: (idx + 1, paper) for idx, paper in enumerate(batch.papers)}
            for code in request.bibcodes:
                if code not in by_code:
                    raise ServiceError(
                        422,
                        "literature_candidate_mismatch",
                        f"bibcode {code} 不在指定的 ADS 检索批次中。",
                    )
                pos, paper = by_code[code]
                if pos not in seen:
                    seen.add(pos)
                    selected.append((pos, paper))

        rejected: list[LiteratureSaveReceiptItem] = []
        warnings: list[str] = []
        unverified = [pair for pair in selected if needs_reverify or not _has_verifiable_ads_source(pair[1])]
        if unverified:
            verified_pairs, rejected, warnings = self._verify_via_ads(unverified, ads_service)
            verified_map = {pos: paper for pos, paper in verified_pairs}
            final_selected = [
                (pos, verified_map[pos])
                for pos, paper in selected
                if (pos in verified_map) or (not needs_reverify and _has_verifiable_ads_source(paper))
            ]
        else:
            final_selected = selected

        candidates = [
            (
                paper,
                LiteratureSourceRef(
                    conversation_id=request.conversation_id,
                    turn_id=request.turn_id,
                    project_id=request.project_id,
                    snapshot_id=request.snapshot_id,
                    batch_index=request.batch_index,
                    paper_index=pos,
                    query=batch.query,
                    added_via="manual",
                    source_available=True,
                ),
            )
            for pos, paper in final_selected
        ]
        scope = (
            f"manual:turn:{request.conversation_id}:{request.turn_id}:{request.batch_index}"
            if request.conversation_id
            else f"manual:snapshot:{request.project_id}:{request.snapshot_id}:{request.batch_index}"
        )
        return self.store.save_candidates(
            client_request_id=request.client_request_id,
            scope=scope,
            candidates=candidates,
            rejected=rejected,
            added_via="manual",
            conversation_id=request.conversation_id,
            turn_id=request.turn_id,
            tags=request.tags,
            note=request.note,
            warnings=warnings,
        )

    def save_from_agent(
        self,
        permit: SavePermit,
        arguments: SaveLiteratureQuery,
        *,
        current_batches: list,
        history_turns: list,
        ads_service=None,
    ) -> LiteratureSaveReceipt:
        history_batches: list[tuple[str, int, object]] = []
        for turn in history_turns:
            if turn.response is None:
                continue
            for idx, batch in enumerate(turn.response.literature_results):
                history_batches.append((turn.turn_id, idx, batch))

        target_turn_id, target_batch_index, target_batch, chosen = permit.verify_and_resolve(
            arguments,
            current_batches=current_batches,
            history_batches=history_batches,
        )
        needs_reverify = (
            arguments.source_scope == "history_turn"
            and target_turn_id is not None
            and self._is_imported_turn(target_turn_id)
        )
        rejected: list[LiteratureSaveReceiptItem] = []
        warnings: list[str] = []
        unverified = [pair for pair in chosen if needs_reverify or not _has_verifiable_ads_source(pair[1])]
        if unverified:
            verified_pairs, rejected, warnings = self._verify_via_ads(unverified, ads_service)
            verified_map = {pos: paper for pos, paper in verified_pairs}
            final_chosen = [
                (pos, verified_map[pos])
                for pos, paper in chosen
                if (pos in verified_map) or (not needs_reverify and _has_verifiable_ads_source(paper))
            ]
        else:
            final_chosen = chosen

        candidates = [
            (
                paper,
                LiteratureSourceRef(
                    conversation_id=permit.conversation_id,
                    turn_id=target_turn_id or permit.turn_id,
                    batch_index=target_batch_index,
                    paper_index=pos,
                    query=target_batch.query,
                    added_via="agent",
                    source_available=True,
                ),
            )
            for pos, paper in final_chosen
        ]
        scope = (
            f"agent:{permit.conversation_id}:{permit.turn_id}:"
            f"{arguments.source_scope}:{target_turn_id}:{target_batch_index}"
        )
        requested_tags = [
            tag
            for tag in arguments.tags
            if permit.raw_message_folded and tag.casefold() in permit.raw_message_folded
        ]
        receipt = self.store.save_candidates(
            client_request_id=permit.client_request_id,
            scope=scope,
            candidates=candidates,
            rejected=rejected,
            added_via="agent",
            conversation_id=permit.conversation_id,
            turn_id=permit.turn_id,
            tags=requested_tags,
            model_explanation=(arguments.explanation or "").strip() or None,
            warnings=warnings,
        )
        permit.consumed = True
        return receipt
