"""V2.3 项目天文数据表管理、确定性分析算子编排、绘图桥接与复现导出服务。"""

from __future__ import annotations

import io
import json
from uuid import NAMESPACE_URL, uuid4, uuid5
from zipfile import ZIP_DEFLATED, ZipFile

from pydantic import BaseModel, ConfigDict

from astroagent.conversations import encode, utc_now
from astroagent.errors import ServiceError
from astroagent.gaia import GAIA_UNITS
from astroagent.plot_data import MAX_DATA as PLOT_MAX_DATA
from astroagent.plot_data import MAX_ROWS as PLOT_MAX_ROWS
from astroagent.plot_data import dataset as build_plot_dataset
from astroagent.plot_schemas import PlotDataset
from astroagent.plot_store import PlotStore
from astroagent.plot_store import ready as plot_ready
from astroagent.table_io import (
    SCIENTIFIC_BOUNDARY_WARNINGS,
    ParsedTable,
    _infer_column_meta,
    export_table_bytes,
    inspect_table_bytes,
    parse_table_bytes,
    sha256_hex,
    table_to_csv_bytes,
)
from astroagent.table_ops import (
    OperatorOutcome,
    run_coordinates,
    run_crossmatch,
    run_filter_derive,
    run_fit,
    run_stats,
)
from astroagent.table_schemas import (
    AnalysisDataset,
    AnalysisRunRecord,
    AnalysisRunResponse,
    CoordinatesOperatorRequest,
    CrossmatchOperatorRequest,
    FilterDeriveOperatorRequest,
    FitOperatorRequest,
    Identifier,
    OperatorName,
    ProjectTablesPage,
    StatsOperatorRequest,
    TableColumnMeta,
    TableImportGaiaRequest,
    TableImportVizierTurnRequest,
    TableInspectResponse,
    TableLineage,
    TablePreviewResponse,
    VizierPreset,
    VizierQueryHttpRequest,
    VizierQueryHttpResponse,
    VizierQueryResult,
)
from astroagent.table_store import TableStore
from astroagent.vizier import VizierService, list_presets, vizier_result_to_parsed_table


class SendToPlotResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plot_dataset: PlotDataset
    project_id: Identifier
    source_dataset_id: Identifier
    plot_url: str


class TableService:
    def __init__(self, conversations, settings):
        self.conversations = conversations
        self.settings = settings
        self.store = TableStore(conversations.repository)
        self.plot_store = PlotStore(conversations.repository)

    def vizier_presets(self) -> list[VizierPreset]:
        return list_presets()

    def query_vizier(
        self,
        request: VizierQueryHttpRequest,
        *,
        vizier_service: VizierService | None = None,
    ) -> VizierQueryHttpResponse:
        service = vizier_service or VizierService(timeout=self.settings.vizier_timeout_seconds)
        result = service.query(request)
        saved_dataset: AnalysisDataset | None = None
        if (
            request.save_to_project
            and request.project_id
            and result.status == "success"
            and result.rows
        ):
            parsed = vizier_result_to_parsed_table(result)
            raw_bytes = encode(result.model_dump(mode="json")).encode("utf-8")
            ds_name = (
                request.dataset_name or f"VizieR {result.catalog_id} ({result.returned_count}行)"
            )
            saved_dataset = self.store.save_dataset(
                dataset_id=str(uuid4()),
                project_id=request.project_id,
                name=ds_name,
                source="vizier",
                source_sha256=sha256_hex(raw_bytes),
                parsed=parsed,
                lineage=TableLineage(
                    source="vizier",
                    parent_dataset_ids=[],
                    origin={
                        "catalog_id": result.catalog_id,
                        "catalog_title": result.catalog_title,
                        "query": result.query,
                        "adql": result.adql,
                        "cds_url": result.cds_url,
                        "retrieved_at": result.source.retrieved_at.isoformat(),
                    },
                ),
            )
        return VizierQueryHttpResponse(result=result, saved_dataset=saved_dataset)

    def list_project(self, project_id: str) -> ProjectTablesPage:
        return ProjectTablesPage(
            datasets=self.store.list_datasets(project_id),
            runs=self.store.list_runs(project_id),
        )

    def list_tables_for_agent(self, project_id: str) -> dict:
        datasets = self.store.list_datasets(project_id)
        return {
            "project_id": project_id,
            "count": len(datasets),
            "tables": [
                {
                    "dataset_id": ds.id,
                    "name": ds.name,
                    "source": ds.source,
                    "format": ds.format,
                    "row_count": ds.row_count,
                    "column_count": ds.column_count,
                    "coordinate_frame": ds.coordinate_frame,
                    "ref_epoch": ds.ref_epoch,
                    "columns": [
                        {
                            "name": col.name,
                            "kind": col.kind,
                            "unit": col.unit,
                            "missing": col.missing,
                        }
                        for col in ds.columns
                    ],
                }
                for ds in datasets
            ],
        }

    def inspect_upload(self, filename: str, raw: bytes) -> TableInspectResponse:
        return inspect_table_bytes(raw, filename)

    def upload_dataset(
        self,
        *,
        project_id: str,
        filename: str,
        raw: bytes,
        name: str | None = None,
        hdu_index: int | None = None,
        selected_columns: list[str] | None = None,
    ) -> AnalysisDataset:
        parsed = parse_table_bytes(
            raw,
            filename,
            hdu_index=hdu_index,
            selected_columns=selected_columns,
        )
        clean_name = (name or filename).strip()[:128] or "上传数据表"
        return self.store.save_dataset(
            dataset_id=str(uuid4()),
            project_id=project_id,
            name=clean_name,
            source="upload",
            source_sha256=sha256_hex(raw),
            parsed=parsed,
            lineage=TableLineage(
                source="upload",
                parent_dataset_ids=[],
                origin={
                    "filename": filename,
                    "hdu_index": hdu_index,
                    "selected_columns": selected_columns,
                },
            ),
        )

    def import_from_gaia(self, project_id: str, req: TableImportGaiaRequest) -> AnalysisDataset:
        if req.source_kind == "snapshot":
            assert req.snapshot_id is not None
            snap = self.store.projects.snapshot(project_id, req.snapshot_id)
            results = snap["response"].get("gaia_results") or []
            origin_meta = {
                "source_kind": "snapshot",
                "snapshot_id": req.snapshot_id,
                "snapshot_name": snap["name"],
            }
            raw_bytes = encode(snap).encode("utf-8")
            default_name = f"Gaia · {snap['name']}"
        else:
            assert req.conversation_id is not None and req.turn_id is not None
            turn = self.conversations.repository.turn(req.conversation_id, req.turn_id)
            if turn.execution_status != "completed" or turn.response is None:
                raise ServiceError(
                    422, "table_turn_unavailable", "请等待 Gaia 查询完整完成后再导入数据表。"
                )
            results = [r.model_dump(mode="json") for r in turn.response.gaia_results]
            origin_meta = {
                "source_kind": "turn",
                "conversation_id": req.conversation_id,
                "turn_id": req.turn_id,
            }
            raw_bytes = encode(turn.response.model_dump(mode="json")).encode("utf-8")
            default_name = "Gaia DR3 查询表"

        if (
            not 0 <= req.query_index < len(results)
            or results[req.query_index].get("status") != "success"
        ):
            raise ServiceError(
                422, "table_gaia_unavailable", "指定的 Gaia 查询批次未成功或无可用数据。"
            )
        result = results[req.query_index]
        data_rows = result.get("data") or []
        if not data_rows:
            raise ServiceError(422, "table_gaia_empty", "该 Gaia 查询结果不包含任何数据行。")

        parsed = self._parsed_table_from_gaia_rows(data_rows)
        return self.store.save_dataset(
            dataset_id=str(uuid4()),
            project_id=project_id,
            name=(req.name or default_name)[:128],
            source="gaia_snapshot" if req.source_kind == "snapshot" else "gaia_turn",
            source_sha256=sha256_hex(raw_bytes),
            parsed=parsed,
            lineage=TableLineage(
                source="gaia_snapshot" if req.source_kind == "snapshot" else "gaia_turn",
                parent_dataset_ids=[],
                origin={
                    **origin_meta,
                    "query_index": req.query_index,
                    "query": result.get("query"),
                },
            ),
        )

    @staticmethod
    def _parsed_table_from_gaia_rows(data_rows: list[dict]) -> ParsedTable:
        col_names = [k for k, v in data_rows[0].items() if not isinstance(v, (dict, list))]
        str_rows = [
            ["" if row.get(k) is None else str(row[k]) for k in col_names] for row in data_rows
        ]
        norm_rows = [[cell if cell != "" else None for cell in r] for r in str_rows]
        col_metas = [
            _infer_column_meta(
                col_name,
                [r[idx] for r in norm_rows],
                unit=GAIA_UNITS.get(col_name),
            )
            for idx, col_name in enumerate(col_names)
        ]
        return ParsedTable(
            columns=col_metas,
            rows=norm_rows,
            format="ecsv",
            coordinate_frame="ICRS",
            ref_epoch="J2016.0",
            header_meta={"RELEASE": "Gaia DR3", "TABLE": "gaiadr3.gaia_source"},
            warnings=list(SCIENTIFIC_BOUNDARY_WARNINGS),
        )

    def sync_conversation_catalog_results(
        self,
        project_id: str,
        conversation_id: str,
        turns: list,
        *,
        current_turn_id: str | None = None,
        current_results: list | None = None,
    ) -> None:
        """Lazily and idempotently materialize Gaia/VizieR turn results for table analysis."""
        from astroagent.schemas import GaiaQueryResult

        turn_batches: list[tuple[str, list, list]] = []
        if current_turn_id and current_results:
            cur_gaia = [r for r in current_results if isinstance(r, GaiaQueryResult)]
            cur_vizier = [r for r in current_results if isinstance(r, VizierQueryResult)]
            if cur_gaia or cur_vizier:
                turn_batches.append((current_turn_id, cur_gaia, cur_vizier))

        for hist_turn in reversed(turns[-12:]):
            if getattr(hist_turn, "execution_status", None) != "completed":
                continue
            resp = getattr(hist_turn, "response", None)
            if resp is None:
                continue
            gaia_items = list(getattr(resp, "gaia_results", None) or [])
            vizier_items = list(getattr(resp, "vizier_results", None) or [])
            if gaia_items or vizier_items:
                turn_batches.append((hist_turn.turn_id, gaia_items, vizier_items))

        for turn_id, gaia_items, vizier_items in turn_batches:
            for idx, g in enumerate(gaia_items):
                if getattr(g, "status", None) != "success":
                    continue
                g_dict = g.model_dump(mode="json")
                data_rows = g_dict.get("data") or []
                if not data_rows:
                    continue
                query = g_dict.get("query") or {}
                if (
                    query.get("mode") == "cone"
                    and query.get("ra_deg") is not None
                    and query.get("dec_deg") is not None
                ):
                    name = (
                        f"Gaia DR3 (RA {float(query['ra_deg']):.2f}°, "
                        f"Dec {float(query['dec_deg']):.2f}°, {len(data_rows)}行)"
                    )
                elif query.get("source_id"):
                    name = f"Gaia DR3 {query['source_id']}"
                else:
                    name = f"Gaia DR3 ({len(data_rows)}行)"
                dataset_id = str(
                    uuid5(NAMESPACE_URL, f"siderfolio:table:{project_id}:{turn_id}:gaia:{idx}")
                )
                try:
                    self.store.save_dataset(
                        dataset_id=dataset_id,
                        project_id=project_id,
                        name=name[:128],
                        source="gaia_turn",
                        source_sha256=sha256_hex(encode(g_dict).encode("utf-8")),
                        parsed=self._parsed_table_from_gaia_rows(data_rows),
                        lineage=TableLineage(
                            source="gaia_turn",
                            parent_dataset_ids=[],
                            origin={
                                "source_kind": "turn",
                                "conversation_id": conversation_id,
                                "turn_id": turn_id,
                                "query_index": idx,
                                "query": query,
                                "auto_synced": True,
                            },
                        ),
                    )
                except ServiceError:
                    continue

            for idx, v in enumerate(vizier_items):
                if getattr(v, "status", None) != "success" or not getattr(v, "rows", None):
                    continue
                v_dict = v.model_dump(mode="json")
                dataset_id = str(
                    uuid5(NAMESPACE_URL, f"siderfolio:table:{project_id}:{turn_id}:vizier:{idx}")
                )
                try:
                    self.store.save_dataset(
                        dataset_id=dataset_id,
                        project_id=project_id,
                        name=f"VizieR {v.catalog_id} ({v.returned_count}行)"[:128],
                        source="vizier",
                        source_sha256=sha256_hex(encode(v_dict).encode("utf-8")),
                        parsed=vizier_result_to_parsed_table(v),
                        lineage=TableLineage(
                            source="vizier",
                            parent_dataset_ids=[],
                            origin={
                                "conversation_id": conversation_id,
                                "turn_id": turn_id,
                                "query_index": idx,
                                "catalog_id": v.catalog_id,
                                "adql": v.adql,
                                "auto_synced": True,
                            },
                        ),
                    )
                except ServiceError:
                    continue

    def import_from_vizier_turn(
        self, project_id: str, req: TableImportVizierTurnRequest
    ) -> AnalysisDataset:
        turn = self.conversations.repository.turn(req.conversation_id, req.turn_id)
        if turn.execution_status != "completed" or turn.response is None:
            raise ServiceError(
                422, "table_turn_unavailable", "请等待 VizieR 查询完整完成后再导入。"
            )
        results = getattr(turn.response, "vizier_results", None) or []
        if not 0 <= req.query_index < len(results):
            raise ServiceError(422, "table_vizier_unavailable", "指定的 VizieR 查询批次不存在。")
        res: VizierQueryResult = results[req.query_index]
        if res.status != "success" or not res.rows:
            raise ServiceError(422, "table_vizier_empty", "该 VizieR 查询结果为空或未成功。")
        parsed = vizier_result_to_parsed_table(res)
        raw_bytes = encode(res.model_dump(mode="json")).encode("utf-8")
        return self.store.save_dataset(
            dataset_id=str(uuid4()),
            project_id=project_id,
            name=(req.name or f"VizieR {res.catalog_id} ({res.returned_count}行)")[:128],
            source="vizier",
            source_sha256=sha256_hex(raw_bytes),
            parsed=parsed,
            lineage=TableLineage(
                source="vizier",
                parent_dataset_ids=[],
                origin={
                    "conversation_id": req.conversation_id,
                    "turn_id": req.turn_id,
                    "query_index": req.query_index,
                    "catalog_id": res.catalog_id,
                    "adql": res.adql,
                },
            ),
        )

    def get_dataset(self, project_id: str, dataset_id: str) -> AnalysisDataset:
        return self.store.get_dataset(project_id, dataset_id)

    def preview_dataset(
        self, project_id: str, dataset_id: str, *, offset: int = 0, limit: int = 50
    ) -> TablePreviewResponse:
        bounded_limit = max(1, min(limit, 200))
        bounded_offset = max(0, offset)
        ds, parsed, _ = self.store.get_dataset_with_data(project_id, dataset_id)
        return TablePreviewResponse(
            dataset_id=ds.id,
            offset=bounded_offset,
            limit=bounded_limit,
            total_rows=ds.row_count,
            columns=ds.columns,
            rows=parsed.rows[bounded_offset : bounded_offset + bounded_limit],
        )

    def delete_dataset(self, project_id: str, dataset_id: str) -> None:
        self.store.delete_dataset(project_id, dataset_id)

    def run_operator(
        self,
        project_id: str,
        operator: OperatorName,
        raw_payload: dict,
    ) -> AnalysisRunResponse:
        req_hash = sha256_hex(encode(raw_payload).encode("utf-8"))
        run_id = str(uuid4())
        save_derived = False
        derived_name: str | None = None
        input_ids: list[str] = []
        outcome: OperatorOutcome

        if operator == "stats":
            req = StatsOperatorRequest.model_validate(raw_payload)
            ds, parsed, _ = self.store.get_dataset_with_data(project_id, req.dataset_id)
            input_ids = [ds.id]
            other_parsed: ParsedTable | None = None
            if req.ks_other_dataset_id:
                other_ds, other_parsed, _ = self.store.get_dataset_with_data(
                    project_id, req.ks_other_dataset_id
                )
                input_ids.append(other_ds.id)
            outcome = run_stats(parsed, req, other_table=other_parsed)
        elif operator == "filter_derive":
            req = FilterDeriveOperatorRequest.model_validate(raw_payload)
            ds, parsed, _ = self.store.get_dataset_with_data(project_id, req.dataset_id)
            input_ids = [ds.id]
            save_derived = req.save_derived
            derived_name = req.derived_name or f"{ds.name} · 筛选/派生"
            outcome = run_filter_derive(parsed, req)
        elif operator == "coordinates":
            req = CoordinatesOperatorRequest.model_validate(raw_payload)
            ds, parsed, _ = self.store.get_dataset_with_data(project_id, req.dataset_id)
            input_ids = [ds.id]
            save_derived = req.save_derived
            derived_name = req.derived_name or f"{ds.name} · 坐标变换"
            outcome = run_coordinates(parsed, req)
        elif operator == "crossmatch":
            req = CrossmatchOperatorRequest.model_validate(raw_payload)
            left_ds, left_parsed, _ = self.store.get_dataset_with_data(
                project_id, req.left_dataset_id
            )
            right_ds, right_parsed, _ = self.store.get_dataset_with_data(
                project_id, req.right_dataset_id
            )
            input_ids = [left_ds.id, right_ds.id]
            save_derived = req.save_derived
            derived_name = req.derived_name or f"{left_ds.name} × {right_ds.name}"
            outcome = run_crossmatch(left_parsed, right_parsed, req)
        elif operator == "fit":
            req = FitOperatorRequest.model_validate(raw_payload)
            ds, parsed, _ = self.store.get_dataset_with_data(project_id, req.dataset_id)
            input_ids = [ds.id]
            save_derived = req.save_derived
            derived_name = req.derived_name or f"{ds.name} · {req.model}拟合"
            outcome = run_fit(parsed, req)
        else:
            raise ServiceError(422, "table_operator_unsupported", f"不支持的算子：{operator}")

        output_dataset: AnalysisDataset | None = None
        if save_derived and outcome.derived_table is not None:
            output_dataset = self.store.save_dataset(
                dataset_id=str(uuid4()),
                project_id=project_id,
                name=(derived_name or "派生数据表")[:128],
                source="derived",
                source_sha256=req_hash,
                parsed=outcome.derived_table,
                lineage=TableLineage(
                    source="derived",
                    parent_dataset_ids=input_ids,
                    operator=operator,
                    run_id=run_id,
                    origin={"parameters": raw_payload},
                ),
                warnings=outcome.warnings,
            )

        run_record = AnalysisRunRecord(
            id=run_id,
            project_id=project_id,
            operator=operator,
            state="completed",
            request_sha256=req_hash,
            input_dataset_ids=input_ids,
            output_dataset_id=output_dataset.id if output_dataset else None,
            parameters=raw_payload,
            summary=outcome.summary,
            warnings=outcome.warnings,
            software=outcome.software or {},
            created_at=utc_now(),
        )
        saved_run = self.store.save_run(run_record)
        preview_rows = outcome.derived_table.rows[:50] if outcome.derived_table else []
        preview_cols: list[TableColumnMeta] = (
            outcome.derived_table.columns if outcome.derived_table else []
        )
        return AnalysisRunResponse(
            run=saved_run,
            output_dataset=output_dataset,
            preview_rows=preview_rows,
            preview_columns=preview_cols,
        )

    def send_to_plot(
        self,
        project_id: str,
        dataset_id: str,
        *,
        name: str | None = None,
    ) -> SendToPlotResponse:
        ds, parsed, _ = self.store.get_dataset_with_data(project_id, dataset_id)
        if ds.row_count > PLOT_MAX_ROWS:
            raise ServiceError(
                422,
                "table_plot_row_limit",
                f"当前表共有 {ds.row_count} 行，超过隔离绘图上限 {PLOT_MAX_ROWS} 行；"
                "请先用「筛选与坐标」算子过滤后再送去绘图。",
            )
        csv_bytes = table_to_csv_bytes(parsed)
        if len(csv_bytes) > PLOT_MAX_DATA:
            raise ServiceError(
                413,
                "plot_dataset_too_large",
                "规范化 CSV 超过隔离绘图 5 MiB 上限，请先筛选列或行数后再送去绘图。",
            )
        header = [c.name for c in parsed.columns]
        str_rows = [["" if cell is None else cell for cell in row] for row in parsed.rows]
        units = {c.name: c.unit for c in parsed.columns if c.unit}
        plot_id = str(uuid4())
        info, norm_data = build_plot_dataset(
            plot_id,
            project_id,
            (name or ds.name)[:128],
            csv_bytes,
            header,
            str_rows,
            source="upload",
            provenance={
                "origin": "project_table",
                "analysis_dataset_id": ds.id,
                "analysis_source": ds.source,
                "coordinate_frame": ds.coordinate_frame,
                "ref_epoch": ds.ref_epoch,
                "filename": f"{ds.name}.csv",
            },
            units=units,
        )
        with self.store.repo.connection() as db:
            is_ready = plot_ready(db)
        if not is_ready:
            self.plot_store.initialize()
        saved = self.plot_store.save_dataset(info, norm_data, csv_bytes)
        plot_url = f"/?tool=plot&project={project_id}&plot_dataset={saved['id']}"
        return SendToPlotResponse(
            plot_dataset=PlotDataset.model_validate(saved),
            project_id=project_id,
            source_dataset_id=ds.id,
            plot_url=plot_url,
        )

    def export_dataset(self, project_id: str, dataset_id: str, fmt: str) -> tuple[bytes, str, str]:
        if fmt not in ("csv", "ecsv", "fits"):
            raise ServiceError(422, "table_export_format", "仅支持导出 csv、ecsv 或 fits 格式。")
        ds, parsed, _ = self.store.get_dataset_with_data(project_id, dataset_id)
        data, media, ext = export_table_bytes(parsed, fmt)
        safe_stem = (
            "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in ds.name)[:48].strip(
                "_"
            )
            or "table"
        )
        return data, media, f"{safe_stem}.{ext}"

    def export_run_bundle(self, project_id: str, run_id: str) -> bytes:
        run = self.store.get_run(project_id, run_id)
        files: dict[str, bytes] = {}
        files["run.json"] = encode(run.model_dump(mode="json")).encode("utf-8")
        files["result.json"] = encode(
            {
                "run_id": run.id,
                "operator": run.operator,
                "summary": run.summary,
                "warnings": run.warnings,
                "software": run.software,
            }
        ).encode("utf-8")
        if run.output_dataset_id:
            try:
                _, parsed, _ = self.store.get_dataset_with_data(project_id, run.output_dataset_id)
                ecsv_bytes, _, _ = export_table_bytes(parsed, "ecsv")
                csv_bytes, _, _ = export_table_bytes(parsed, "csv")
                files["output_table.ecsv"] = ecsv_bytes
                files["output_table.csv"] = csv_bytes
            except ServiceError:
                pass
        readme = (
            f"# Siderfolio 天文表分析复现包\n\n"
            f"- Run ID: {run.id}\n"
            f"- Project ID: {run.project_id}\n"
            f"- Operator: {run.operator}\n"
            f"- Created At (UTC): {run.created_at}\n"
            f"- Input Dataset IDs: {', '.join(run.input_dataset_ids) or '—'}\n"
            f"- Output Dataset ID: {run.output_dataset_id or '—'}\n\n"
            f"## 科学警告与边界\n\n"
            + "\n".join(f"- {w}" for w in run.warnings)
            + "\n\n## 软件版本\n\n"
            + json.dumps(run.software, ensure_ascii=False, indent=2)
            + "\n"
        )
        files["README.md"] = readme.encode("utf-8")
        manifest = {
            "format": "siderfolio-table-analysis",
            "version": 1,
            "run_id": run.id,
            "project_id": run.project_id,
            "operator": run.operator,
            "request_sha256": run.request_sha256,
            "created_at": run.created_at,
            "software": run.software,
            "files": {
                fname: {"bytes": len(content), "sha256": sha256_hex(content)}
                for fname, content in files.items()
            },
        }
        files["manifest.json"] = encode(manifest).encode("utf-8")

        buf = io.BytesIO()
        with ZipFile(buf, "w", compression=ZIP_DEFLATED) as zf:
            for fname, content in files.items():
                zf.writestr(fname, content)
        return buf.getvalue()
