"""租户隔离的 PostgreSQL 个人天文文献库与幂等入库回执存储。"""

from __future__ import annotations

import hashlib
import json
from uuid import uuid4

from astroagent.conversations import utc_now
from astroagent.errors import ServiceError
from astroagent.literature_schemas import (
    MAX_LITERATURE_ITEMS_PER_ACCOUNT,
    LiteratureItem,
    LiteratureListResponse,
    LiteratureSaveReceipt,
    LiteratureSaveReceiptItem,
    LiteratureSourceRef,
    verified_doi_urls,
)
from astroagent.schemas import PaperData

DDL = (
    "CREATE TABLE IF NOT EXISTS literature_meta (version INTEGER PRIMARY KEY CHECK (version=1))",
    (
        "CREATE TABLE IF NOT EXISTS literature_items ("
        "id TEXT PRIMARY KEY, "
        "provider TEXT NOT NULL DEFAULT 'ADS', "
        "bibcode TEXT NOT NULL, "
        "title TEXT, "
        "year INTEGER, "
        "revision INTEGER NOT NULL DEFAULT 1, "
        "created_at TEXT NOT NULL, "
        "updated_at TEXT NOT NULL, "
        "record TEXT NOT NULL, "
        "UNIQUE (provider, bibcode))"
    ),
    (
        "CREATE INDEX IF NOT EXISTS idx_literature_items_created "
        "ON literature_items (created_at DESC, id DESC)"
    ),
    "CREATE INDEX IF NOT EXISTS idx_literature_items_year ON literature_items (year)",
    (
        "CREATE TABLE IF NOT EXISTS literature_save_receipts ("
        "id TEXT PRIMARY KEY, "
        "request_key TEXT NOT NULL UNIQUE, "
        "conversation_id TEXT, "
        "turn_id TEXT, "
        "created_at TEXT NOT NULL, "
        "record TEXT NOT NULL)"
    ),
    (
        "CREATE INDEX IF NOT EXISTS idx_literature_receipts_turn "
        "ON literature_save_receipts (conversation_id, turn_id)"
    ),
    "INSERT INTO literature_meta(version) VALUES(1) ON CONFLICT (version) DO NOTHING",
)


def ready(db) -> bool:
    if getattr(db, "dialect", None) != "postgresql":
        return False
    if not db.execute("SELECT to_regclass('literature_meta')").fetchone()[0]:
        return False
    row = db.execute("SELECT version FROM literature_meta").fetchone()
    return bool(row and row[0] == 1)


def used(db) -> int:
    if not ready(db):
        return 0
    return int(
        db.execute(
            "SELECT COALESCE((SELECT SUM(octet_length(record)) FROM literature_items), 0) + "
            "COALESCE((SELECT SUM(octet_length(record)) FROM literature_save_receipts), 0)"
        ).fetchone()[0]
    )


def _dump(model) -> str:
    return json.dumps(model.model_dump(mode="json"), ensure_ascii=False, separators=(",", ":"))


def _request_key(
    client_request_id: str,
    scope: str,
    bibcodes: list[str],
) -> str:
    payload = json.dumps(
        {"client_request_id": client_request_id, "scope": scope, "bibcodes": bibcodes},
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class LiteratureStore:
    def __init__(self, repo):
        self.repo = repo

    def initialize(self) -> None:
        with self.repo.connection() as db, self.repo.transaction(db):
            for statement in DDL:
                db.execute(statement)

    def _ensure_ready(self, db) -> None:
        if not ready(db):
            for statement in DDL:
                db.execute(statement)

    @staticmethod
    def _decorate_origin(db, item: LiteratureItem) -> LiteratureItem:
        origin = item.origin
        available = True
        if origin.conversation_id:
            row = db.execute(
                "SELECT 1 FROM conversations WHERE id=?",
                (origin.conversation_id,),
            ).fetchone()
            available = bool(row)
        elif origin.snapshot_id and origin.project_id:
            row = db.execute(
                "SELECT 1 FROM snapshots WHERE id=? AND project_id=?",
                (origin.snapshot_id, origin.project_id),
            ).fetchone()
            available = bool(row)
        if origin.source_available != available:
            return item.model_copy(
                update={"origin": origin.model_copy(update={"source_available": available})}
            )
        return item

    def lookup_bibcodes(self, bibcodes: list[str]) -> dict[str, str]:
        cleaned = [code.strip() for code in bibcodes if code and code.strip()][:50]
        if not cleaned:
            return {}
        with self.repo.connection() as db:
            if not ready(db):
                return {}
            placeholders = ",".join("?" for _ in cleaned)
            rows = db.execute(
                f"SELECT bibcode, id FROM literature_items WHERE provider='ADS' "
                f"AND bibcode IN ({placeholders})",
                tuple(cleaned),
            ).fetchall()
            return {row[0]: row[1] for row in rows}

    def list_items(
        self,
        *,
        query: str = "",
        year: int | None = None,
        tag: str = "",
        page: int = 1,
        page_size: int = 20,
    ) -> LiteratureListResponse:
        page = max(1, page)
        page_size = max(1, min(100, page_size))
        with self.repo.connection() as db:
            if not ready(db):
                return LiteratureListResponse(page=page, page_size=page_size)
            rows = db.execute(
                "SELECT record FROM literature_items ORDER BY created_at DESC, id DESC"
            ).fetchall()
            all_items = [LiteratureItem.model_validate_json(row[0]) for row in rows]
            available_tags_map: dict[str, str] = {}
            available_years_set: set[int] = set()
            for item in all_items:
                if item.year is not None:
                    available_years_set.add(item.year)
                for entry_tag in item.tags:
                    available_tags_map.setdefault(entry_tag.casefold(), entry_tag)

            q = query.strip().casefold()
            tag_filter = tag.strip().casefold()
            filtered: list[LiteratureItem] = []
            for item in all_items:
                if year is not None and item.year != year:
                    continue
                if tag_filter and not any(t.casefold() == tag_filter for t in item.tags):
                    continue
                if q:
                    haystack = " ".join(
                        [
                            item.bibcode,
                            item.title or "",
                            " ".join(item.authors),
                            item.publication or "",
                            " ".join(item.doi),
                            " ".join(item.tags),
                            item.note,
                        ]
                    ).casefold()
                    if q not in haystack:
                        continue
                filtered.append(item)

            total = len(filtered)
            start = (page - 1) * page_size
            window = [self._decorate_origin(db, item) for item in filtered[start : start + page_size]]
            return LiteratureListResponse(
                items=window,
                total=total,
                page=page,
                page_size=page_size,
                has_more=start + len(window) < total,
                available_tags=sorted(available_tags_map.values(), key=str.casefold),
                available_years=sorted(available_years_set, reverse=True),
            )

    def get_item(self, item_id: str) -> LiteratureItem:
        with self.repo.connection() as db:
            if not ready(db):
                raise ServiceError(404, "literature_not_found", "文献库中不存在该条目。")
            row = db.execute(
                "SELECT record FROM literature_items WHERE id=?",
                (item_id,),
            ).fetchone()
            if row is None:
                raise ServiceError(404, "literature_not_found", "文献库中不存在该条目。")
            return self._decorate_origin(db, LiteratureItem.model_validate_json(row[0]))

    def update_item(
        self,
        item_id: str,
        *,
        expected_revision: int,
        tags: list[str] | None,
        note: str | None,
    ) -> LiteratureItem:
        with self.repo.connection() as db, self.repo.transaction(db):
            self._ensure_ready(db)
            row = db.execute(
                "SELECT record, revision FROM literature_items WHERE id=? FOR UPDATE",
                (item_id,),
            ).fetchone()
            if row is None:
                raise ServiceError(404, "literature_not_found", "文献库中不存在该条目。")
            current = LiteratureItem.model_validate_json(row[0])
            if row[1] != expected_revision or current.revision != expected_revision:
                raise ServiceError(
                    409,
                    "literature_revision_conflict",
                    "文献条目已被其他操作更新，请刷新后重试。",
                )
            now = utc_now()
            updated = current.model_copy(
                update={
                    "tags": current.tags if tags is None else tags,
                    "note": current.note if note is None else note,
                    "revision": current.revision + 1,
                    "updated_at": now,
                }
            )
            db.execute(
                "UPDATE literature_items SET revision=?, updated_at=?, record=? WHERE id=?",
                (updated.revision, now, _dump(updated), item_id),
            )
            return self._decorate_origin(db, updated)

    def delete_item(self, item_id: str, *, expected_revision: int) -> None:
        with self.repo.connection() as db, self.repo.transaction(db):
            self._ensure_ready(db)
            row = db.execute(
                "SELECT revision FROM literature_items WHERE id=? FOR UPDATE",
                (item_id,),
            ).fetchone()
            if row is None:
                raise ServiceError(404, "literature_not_found", "文献库中不存在该条目。")
            if row[0] != expected_revision:
                raise ServiceError(
                    409,
                    "literature_revision_conflict",
                    "文献条目已被其他操作更新，请刷新后再移除。",
                )
            db.execute("DELETE FROM literature_items WHERE id=?", (item_id,))

    def save_candidates(
        self,
        *,
        client_request_id: str,
        scope: str,
        candidates: list[tuple[PaperData, LiteratureSourceRef]],
        rejected: list[LiteratureSaveReceiptItem],
        added_via: str,
        conversation_id: str | None,
        turn_id: str | None,
        tags: list[str] | None = None,
        note: str = "",
        model_explanation: str | None = None,
        warnings: list[str] | None = None,
    ) -> LiteratureSaveReceipt:
        key_codes = [paper.bibcode for paper, _ in candidates] + [
            f"rejected:{item.bibcode}" for item in rejected
        ]
        req_key = _request_key(client_request_id, scope, key_codes)
        with self.repo.connection() as db, self.repo.transaction(db):
            self._ensure_ready(db)
            existing_receipt = db.execute(
                "SELECT record FROM literature_save_receipts WHERE request_key=?",
                (req_key,),
            ).fetchone()
            if existing_receipt is not None:
                parsed = LiteratureSaveReceipt.model_validate_json(existing_receipt[0])
                return parsed.model_copy(update={"replayed": True})

            total_existing = int(
                db.execute("SELECT COUNT(*) FROM literature_items").fetchone()[0]
            )
            now = utc_now()
            receipt_items: list[LiteratureSaveReceiptItem] = []
            added_count = 0
            already_saved_count = 0
            rejected_count = 0
            extra_warnings = list(warnings or ())

            for paper, origin in candidates:
                existing = db.execute(
                    "SELECT id, record FROM literature_items WHERE provider='ADS' AND bibcode=?",
                    (paper.bibcode,),
                ).fetchone()
                if existing is not None:
                    existing_item = LiteratureItem.model_validate_json(existing[1])
                    already_saved_count += 1
                    receipt_items.append(
                        LiteratureSaveReceiptItem(
                            bibcode=paper.bibcode,
                            item_id=existing_item.id,
                            title=existing_item.title or paper.title,
                            year=existing_item.year or paper.year,
                            authors=existing_item.authors or list(paper.authors),
                            source_url=existing_item.source.url,
                            status="already_saved",
                            reason="已在文献库中，保留原有标签与备注。",
                        )
                    )
                    continue

                if total_existing + added_count >= MAX_LITERATURE_ITEMS_PER_ACCOUNT:
                    rejected_count += 1
                    extra_warnings.append(
                        f"个人文献库已达上限（{MAX_LITERATURE_ITEMS_PER_ACCOUNT} 篇），部分条目未写入。"
                    )
                    receipt_items.append(
                        LiteratureSaveReceiptItem(
                            bibcode=paper.bibcode,
                            title=paper.title,
                            year=paper.year,
                            authors=list(paper.authors),
                            source_url=paper.source.url,
                            status="rejected",
                            reason="个人文献库条目数量已达上限。",
                        )
                    )
                    continue

                item_id = str(uuid4())
                item = LiteratureItem(
                    id=item_id,
                    provider="ADS",
                    bibcode=paper.bibcode,
                    title=paper.title,
                    authors=list(paper.authors),
                    year=paper.year,
                    publication=paper.publication,
                    doi=list(paper.doi),
                    doi_urls=verified_doi_urls(list(paper.doi)),
                    abstract=paper.abstract,
                    citation_count=paper.citation_count,
                    source=paper.source,
                    tags=list(tags or ()),
                    note=note,
                    model_explanation=model_explanation,
                    origin=origin,
                    revision=1,
                    created_at=now,
                    updated_at=now,
                )
                inserted = db.execute(
                    "INSERT INTO literature_items "
                    "(id,provider,bibcode,title,year,revision,created_at,updated_at,record) "
                    "VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT (provider, bibcode) DO NOTHING "
                    "RETURNING id",
                    (
                        item.id,
                        item.provider,
                        item.bibcode,
                        item.title,
                        item.year,
                        item.revision,
                        item.created_at,
                        item.updated_at,
                        _dump(item),
                    ),
                ).fetchone()
                if inserted is None:
                    winner = db.execute(
                        "SELECT id, record FROM literature_items WHERE provider='ADS' AND bibcode=?",
                        (paper.bibcode,),
                    ).fetchone()
                    winner_item = LiteratureItem.model_validate_json(winner[1]) if winner else item
                    already_saved_count += 1
                    receipt_items.append(
                        LiteratureSaveReceiptItem(
                            bibcode=paper.bibcode,
                            item_id=winner_item.id,
                            title=winner_item.title,
                            year=winner_item.year,
                            authors=winner_item.authors,
                            source_url=winner_item.source.url,
                            status="already_saved",
                            reason="已在文献库中，保留原有标签与备注。",
                        )
                    )
                else:
                    added_count += 1
                    receipt_items.append(
                        LiteratureSaveReceiptItem(
                            bibcode=paper.bibcode,
                            item_id=item.id,
                            title=item.title,
                            year=item.year,
                            authors=item.authors,
                            source_url=item.source.url,
                            status="added",
                        )
                    )

            for item in rejected:
                rejected_count += 1
                receipt_items.append(item)

            if added_count + already_saved_count > 0 and rejected_count == 0:
                status = "success"
            elif added_count + already_saved_count > 0:
                status = "partial"
            else:
                status = "error"

            receipt = LiteratureSaveReceipt(
                receipt_id=str(uuid4()),
                client_request_id=client_request_id,
                conversation_id=conversation_id,
                turn_id=turn_id,
                added_via="agent" if added_via == "agent" else "manual",
                status=status,
                added_count=added_count,
                already_saved_count=already_saved_count,
                rejected_count=rejected_count,
                replayed=False,
                items=receipt_items,
                warnings=extra_warnings,
                created_at=now,
            )
            db.execute(
                "INSERT INTO literature_save_receipts "
                "(id,request_key,conversation_id,turn_id,created_at,record) "
                "VALUES (?,?,?,?,?,?)",
                (
                    receipt.receipt_id,
                    req_key,
                    conversation_id,
                    turn_id,
                    now,
                    _dump(receipt),
                ),
            )
            return receipt

    @staticmethod
    def receipts_for_turn_with_db(
        db, conversation_id: str, turn_id: str
    ) -> list[LiteratureSaveReceipt]:
        if not ready(db):
            return []
        rows = db.execute(
            "SELECT record FROM literature_save_receipts "
            "WHERE conversation_id=? AND turn_id=? ORDER BY created_at ASC, id ASC",
            (conversation_id, turn_id),
        ).fetchall()
        return [LiteratureSaveReceipt.model_validate_json(row[0]) for row in rows]

    @staticmethod
    def receipts_for_conversation_with_db(
        db, conversation_id: str
    ) -> dict[str, list[LiteratureSaveReceipt]]:
        if not ready(db):
            return {}
        rows = db.execute(
            "SELECT turn_id, record FROM literature_save_receipts "
            "WHERE conversation_id=? ORDER BY created_at ASC, id ASC",
            (conversation_id,),
        ).fetchall()
        grouped: dict[str, list[LiteratureSaveReceipt]] = {}
        for row in rows:
            tid = row[0]
            if not tid:
                continue
            grouped.setdefault(tid, []).append(LiteratureSaveReceipt.model_validate_json(row[1]))
        return grouped

    def receipts_for_turn(self, conversation_id: str, turn_id: str) -> list[LiteratureSaveReceipt]:
        with self.repo.connection() as db:
            return self.receipts_for_turn_with_db(db, conversation_id, turn_id)
