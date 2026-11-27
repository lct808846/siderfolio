"""独立的严格导出契约；不改变聊天接口的兼容行为。"""

import math
import types
from copy import deepcopy
from datetime import timedelta
from typing import Annotated, Literal, Union, get_args, get_origin

from pydantic import BaseModel, ConfigDict, Field, StrictInt, create_model, model_validator

from astroagent.analysis import analyze_sources
from astroagent.gaia import GAIA_UNITS, build_adql
from astroagent.schemas import ChatResponse, GaiaQuery, LiteratureQuery, ObjectQuery

_models = {}


def _strict_type(annotation):
    """复制响应树以拒绝每层未知字段、非有限值和类型强制转换。"""
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        if annotation not in _models:
            fields = {}
            for name, original in annotation.model_fields.items():
                field = deepcopy(original)
                # Older snapshot manifests omit fields added in later versions.
                if annotation is not ChatResponse or name not in (
                    "nbody_proposals",
                    "plot_proposals",
                    "literature_receipts",
                    "skill_resolution",
                    "external_mcp_proposals",
                    "external_mcp_results",
                    "memory_receipts",
                ):
                    field.default = ...
                    field.default_factory = None
                fields[name] = (_strict_type(original.annotation), field)
            # A configured subclass also works on the minimum supported Pydantic;
            # older releases disallow create_model(__base__=..., __config__=...).
            base = type(
                f"_ExportBase{annotation.__name__}",
                (annotation,),
                {
                    "model_config": ConfigDict(extra="forbid", strict=True, allow_inf_nan=False),
                },
            )
            _models[annotation] = create_model(
                f"Export{annotation.__name__}",
                __base__=base,
                **fields,
            )
        return _models[annotation]
    origin, args = get_origin(annotation), get_args(annotation)
    if origin in (Union, types.UnionType):
        return Union[tuple(_strict_type(arg) for arg in args)]  # noqa: UP007
    if origin is list:
        return list[_strict_type(args[0])]
    if origin is dict:
        return dict[args[0], _strict_type(args[1])]
    if origin is Annotated:
        return Annotated[_strict_type(args[0]), *args[1:]]
    return annotation


ExportSnapshot = _strict_type(ChatResponse)


def _same(actual, expected):
    if isinstance(expected, dict):
        return (
            isinstance(actual, dict)
            and actual.keys() == expected.keys()
            and all(_same(actual[k], value) for k, value in expected.items())
        )
    if isinstance(expected, list):
        return (
            isinstance(actual, list)
            and len(actual) == len(expected)
            and all(_same(a, b) for a, b in zip(actual, expected, strict=True))
        )
    if type(expected) is float:
        return type(actual) in (float, int) and math.isclose(
            actual, expected, rel_tol=1e-12, abs_tol=1e-12
        )
    return type(actual) is type(expected) and actual == expected


def validate_snapshot(snapshot):
    results = [*snapshot.results, *snapshot.literature_results, *snapshot.gaia_results]
    if len(results) > 12:
        raise ValueError("At most 12 queries are supported")
    successes = [r for r in results if r.status == "success"]
    status = (
        "error"
        if results and not successes
        else "partial"
        if len(successes) < len(results)
        else "success"
    )
    if snapshot.warnings and status == "success":
        status = "partial"
    if snapshot.status != status:
        raise ValueError("Inconsistent snapshot status")
    for result in results:
        if (result.status == "success" and result.error is not None) or (
            result.status == "error" and result.error is None
        ):
            raise ValueError("Inconsistent query error")
    # Across tools the chronological order is unavailable; verify unique source identities,
    # accepting the first successful retrieval for each URL in that original order.
    candidates = [
        source
        for r in successes
        for source in ([p.source for p in r.papers] if hasattr(r, "papers") else [r.source])
    ]
    if len({s.url for s in snapshot.sources}) != len(snapshot.sources) or {
        s.url for s in snapshot.sources
    } != {s.url for s in candidates}:
        raise ValueError("Inconsistent successful sources")
    for source in snapshot.sources:
        if not any(source.model_dump() == c.model_dump() for c in candidates):
            raise ValueError("Source identity differs from result")
    for source in [*snapshot.sources, *(r.source for r in results), *candidates]:
        if source.retrieved_at.utcoffset() != timedelta(0):
            raise ValueError("UTC source timestamps are required")
    for result in snapshot.results:
        ObjectQuery(object_name=result.object_name)
        if (
            (result.status == "not_found" and result.error is None)
            or (result.source.name != "SIMBAD")
            or (result.data is not None) != (result.status == "success")
        ):
            raise ValueError("Inconsistent SIMBAD result")
    for result in snapshot.literature_results:
        LiteratureQuery(**{k: getattr(result, k) for k in LiteratureQuery.model_fields})
        n = len(result.papers)
        if (
            result.source.name != "ADS"
            or result.filters != ["database:astronomy"]
            or n > result.rows
            or result.returned_count != n
            or len({p.bibcode for p in result.papers}) != n
            or any(p.source.name != "ADS" for p in result.papers)
            or (result.status == "not_found" and result.error is not None)
            or (result.status == "success") != bool(n)
        ):
            raise ValueError("Inconsistent ADS result")
        if result.status == "error":
            if result.total_found is not None or result.has_more is not None:
                raise ValueError("Unknown ADS pagination required on failure")
        elif (
            result.total_found is None
            or result.total_found < 0
            or result.has_more != (result.start + result.rows < result.total_found)
            or (n and result.start + n > result.total_found)
            or (not n and result.start < result.total_found)
        ):
            raise ValueError("Inconsistent ADS pagination")
    for result in snapshot.gaia_results:
        query = GaiaQuery.model_validate(result.query)
        n = len(result.data)
        if (
            result.query != query.effective_parameters()
            or result.source.name != "Gaia"
            or (result.status == "not_found" and result.error is None)
            or result.units != GAIA_UNITS
            or result.maxrec != build_adql(query)[1]
            or not result.adql.strip()
            or n > (query.limit if query.mode == "cone" else 1)
            or result.returned_count != n
            or len({s.source_id for s in result.data}) != n
            or (result.status == "success") != bool(n)
        ):
            raise ValueError("Inconsistent Gaia result")
        if result.status == "success":
            if (
                type(result.truncated) is not bool
                or result.has_more != result.truncated
                or type(result.archive_overflow) is not bool
                or (result.archive_overflow and not result.truncated)
                or (query.mode == "source_id" and result.truncated)
            ):
                raise ValueError("Inconsistent Gaia truncation")
            for row in result.data:
                if query.mode == "source_id" and row.source_id != query.source_id:
                    raise ValueError("Wrong exact source")
                if query.mode == "cone" and (
                    row.separation_arcsec is None
                    or row.separation_arcsec > query.radius_arcmin * 60 + 1e-6
                ):
                    raise ValueError("Invalid cone separation")
                if query.ruwe_max is not None and (row.ruwe is None or row.ruwe > query.ruwe_max):
                    raise ValueError("RUWE filter violated")
                if query.parallax_snr_min is not None and (
                    row.parallax is None
                    or row.parallax <= 0
                    or row.parallax_error is None
                    or row.parallax_error <= 0
                    or row.parallax / row.parallax_error < query.parallax_snr_min
                ):
                    raise ValueError("Parallax filter violated")
            if result.analysis is not None and not _same(
                result.analysis.model_dump(),
                analyze_sources(result.data, query, truncated=result.truncated).model_dump(),
            ):
                raise ValueError("Analysis differs from submitted rows")
        elif result.analysis is not None or any(
            value is not (False if result.status == "not_found" else None)
            for value in (result.has_more, result.truncated, result.archive_overflow)
        ):
            raise ValueError("Inconsistent failed Gaia result")


class PlotSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    gaia_result_index: StrictInt = Field(ge=0)
    kind: Literal["proper_motion", "parallax_histogram", "observed_cmd"]


class ExportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    schema_version: Literal["1"]
    snapshot: ExportSnapshot
    plots: list[PlotSpec] = Field(default_factory=list, max_length=3)

    @model_validator(mode="after")
    def check_snapshot(self):
        if any(p.gaia_result_index >= len(self.snapshot.gaia_results) for p in self.plots):
            raise ValueError("Gaia result index out of range")
        if len({(p.gaia_result_index, p.kind) for p in self.plots}) != len(self.plots):
            raise ValueError("Duplicate plot")
        validate_snapshot(self.snapshot)
        return self


class FileRecord(BaseModel):
    path: str
    bytes: int
    sha256: str


class ExportManifest(BaseModel):
    schema_version: Literal["1"] = "1"
    exporter_version: str
    git_commit: str | None
    git_dirty: bool | None
    exported_at: str
    runtime: dict[str, str]
    plot_style_version: str
    provenance: Literal["client_supplied_snapshot"] = "client_supplied_snapshot"
    source_authenticity_verified: Literal[False] = False
    snapshot_status: str
    export_status: Literal["success", "partial"]
    queries: list[dict]
    plots: list[dict]
    csv_policy: dict
    csv_changes: list[dict]
    files: list[FileRecord]
