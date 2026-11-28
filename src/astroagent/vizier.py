"""有界只读 CDS VizieR TAP/VOTable 星表检索；外部 XML 先以 defusedxml 校验再解析。"""

from __future__ import annotations

import math
import struct
import warnings
from datetime import UTC, datetime
from io import BytesIO
from typing import Any
from urllib.parse import quote

import numpy as np
import requests
from astropy.io.votable import parse as parse_votable
from astropy.io.votable.exceptions import VOWarning
from defusedxml import ElementTree as SafeET
from defusedxml.common import DefusedXmlException

from astroagent.simbad import SimbadService
from astroagent.source_schemas import ErrorInfo, Source
from astroagent.table_io import (
    SCIENTIFIC_BOUNDARY_WARNINGS,
    ParsedTable,
    _infer_column_meta,
    _is_long_int,
)
from astroagent.table_schemas import (
    MAX_TABLE_COLUMNS,
    TableColumnMeta,
    VizierPreset,
    VizierQuery,
    VizierQueryResult,
)
from astroagent.usage import reserve_request

VIZIER_ENDPOINT = "https://tapvizier.cds.unistra.fr/TAPVizieR/tap/sync"
VIZIER_CATALOG_BASE = "https://vizier.cds.unistra.fr/viz-bin/VizieR?-source="
VIZIER_CFA_VOTABLE_ENDPOINT = "https://vizier.cfa.harvard.edu/viz-bin/votable"
VIZIER_CFA_CATALOG_BASE = "https://vizier.cfa.harvard.edu/viz-bin/VizieR?-source="
MAX_RESPONSE_BYTES = 4 * 1024 * 1024

VIZIER_POSITION_WARNING = (
    "圆锥结果仅为位置候选源，最近或唯一一行不代表确认匹配；未自动执行自行传播或星团成员判定。"
)
VIZIER_SAMPLE_WARNING = "统计与结果仅描述本次实际交付行；未校正星际消光、测光零点偏差或视场完整性。"

VIZIER_PRESETS: tuple[VizierPreset, ...] = (
    VizierPreset(
        catalog_id="II/246/out",
        title="2MASS Point Source Catalog (PSC)",
        description="全天近红外 J / H / K_s 点源星表（参考历元 J2000.0）",
        default_columns=[
            "RAJ2000",
            "DEJ2000",
            "Jmag",
            "e_Jmag",
            "Hmag",
            "e_Hmag",
            "Kmag",
            "e_Kmag",
            "Qflg",
        ],
        ra_col="RAJ2000",
        dec_col="DEJ2000",
        ref_epoch="J2000.0",
        coordinate_frame="ICRS",
        units={
            "RAJ2000": "deg",
            "DEJ2000": "deg",
            "Jmag": "mag",
            "e_Jmag": "mag",
            "Hmag": "mag",
            "e_Hmag": "mag",
            "Kmag": "mag",
            "e_Kmag": "mag",
            "Qflg": "1",
            "separation_arcsec": "arcsec",
        },
        cds_url=f"{VIZIER_CATALOG_BASE}{quote('II/246/out', safe='/')}",
    ),
    VizierPreset(
        catalog_id="II/328/allwise",
        title="AllWISE Source Catalog",
        description="WISE 全天中红外 W1–W4 测光星表（参考历元 J2010.0）",
        default_columns=[
            "RAJ2000",
            "DEJ2000",
            "W1mag",
            "e_W1mag",
            "W2mag",
            "e_W2mag",
            "W3mag",
            "e_W3mag",
            "W4mag",
            "e_W4mag",
            "qph",
        ],
        ra_col="RAJ2000",
        dec_col="DEJ2000",
        ref_epoch="J2010.0",
        coordinate_frame="ICRS",
        units={
            "RAJ2000": "deg",
            "DEJ2000": "deg",
            "W1mag": "mag",
            "e_W1mag": "mag",
            "W2mag": "mag",
            "e_W2mag": "mag",
            "W3mag": "mag",
            "e_W3mag": "mag",
            "W4mag": "mag",
            "e_W4mag": "mag",
            "qph": "1",
            "separation_arcsec": "arcsec",
        },
        cds_url=f"{VIZIER_CATALOG_BASE}{quote('II/328/allwise', safe='/')}",
    ),
    VizierPreset(
        catalog_id="II/349/ps1",
        title="Pan-STARRS DR1 (PS1)",
        description="Pan-STARRS1 g/r/i/z/y 五波段光学测光星表（参考历元 J2012.0）",
        default_columns=[
            "RAJ2000",
            "DEJ2000",
            "gmag",
            "e_gmag",
            "rmag",
            "e_rmag",
            "imag",
            "e_imag",
            "zmag",
            "e_zmag",
            "ymag",
            "e_ymag",
        ],
        ra_col="RAJ2000",
        dec_col="DEJ2000",
        ref_epoch="J2012.0",
        coordinate_frame="ICRS",
        units={
            "RAJ2000": "deg",
            "DEJ2000": "deg",
            "gmag": "mag",
            "e_gmag": "mag",
            "rmag": "mag",
            "e_rmag": "mag",
            "imag": "mag",
            "e_imag": "mag",
            "zmag": "mag",
            "e_zmag": "mag",
            "ymag": "mag",
            "e_ymag": "mag",
            "separation_arcsec": "arcsec",
        },
        cds_url=f"{VIZIER_CATALOG_BASE}{quote('II/349/ps1', safe='/')}",
    ),
    VizierPreset(
        catalog_id="V/156/dr7lrs",
        title="LAMOST DR7 Low-Resolution Spectra",
        description="LAMOST DR7 低分辨率光谱恒星参数与视向速度星表（参考历元 J2000.0）",
        default_columns=[
            "RAJ2000",
            "DEJ2000",
            "Class",
            "SubClass",
            "Teff",
            "e_Teff",
            "logg",
            "e_logg",
            "FeH",
            "e_FeH",
            "RV",
            "e_RV",
        ],
        ra_col="RAJ2000",
        dec_col="DEJ2000",
        ref_epoch="J2000.0",
        coordinate_frame="ICRS",
        units={
            "RAJ2000": "deg",
            "DEJ2000": "deg",
            "Class": "1",
            "SubClass": "1",
            "Teff": "K",
            "e_Teff": "K",
            "logg": "log(cm/s2)",
            "e_logg": "log(cm/s2)",
            "FeH": "dex",
            "e_FeH": "dex",
            "RV": "km/s",
            "e_RV": "km/s",
            "separation_arcsec": "arcsec",
        },
        cds_url=f"{VIZIER_CATALOG_BASE}{quote('V/156/dr7lrs', safe='/')}",
    ),
    VizierPreset(
        catalog_id="J/A+A/640/A1/nodup",
        title="Cantat-Gaudin+2020 疏散星团成员表",
        description="基于 Gaia DR2 的银河系疏散星团成员星与成员概率表（参考历元 J2015.5）",
        default_columns=["GaiaDR2", "RA_ICRS", "DE_ICRS", "Gmag", "BP-RP", "proba", "Cluster"],
        ra_col="RA_ICRS",
        dec_col="DE_ICRS",
        ref_epoch="J2015.5",
        coordinate_frame="ICRS",
        units={
            "GaiaDR2": "1",
            "RA_ICRS": "deg",
            "DE_ICRS": "deg",
            "Gmag": "mag",
            "BP-RP": "mag",
            "proba": "1",
            "Cluster": "1",
            "separation_arcsec": "arcsec",
        },
        cds_url=f"{VIZIER_CATALOG_BASE}{quote('J/A+A/640/A1/nodup', safe='/')}",
    ),
)

_PRESETS_BY_ID: dict[str, VizierPreset] = {p.catalog_id: p for p in VIZIER_PRESETS}


class TapQueryError(ValueError):
    pass


class ResponseTooLarge(ValueError):
    pass


def list_presets() -> list[VizierPreset]:
    return list(VIZIER_PRESETS)


def _tag(element) -> str:
    return element.tag.rsplit("}", 1)[-1]


def _quote_ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _escape_adql_string(value: str) -> str:
    return value.replace("'", "''")


def _validate_votable_xml(body: bytes, maxrec: int):
    root = SafeET.fromstring(body, forbid_dtd=True, forbid_entities=True, forbid_external=True)
    if _tag(root) != "VOTABLE":
        raise ValueError("Not a VOTable")
    for element in root.iter():
        if _tag(element) == "FITS" or any(
            key.rsplit("}", 1)[-1] == "href" for key in element.attrib
        ):
            raise ValueError("External VOTable references are forbidden")
    resources = [e for e in root.iter() if _tag(e) == "RESOURCE" and e.get("type") == "results"]
    if not resources:
        resources = [e for e in root.iter() if _tag(e) == "RESOURCE"]
    if not resources:
        raise ValueError("Missing results resource")
    resource = resources[0]
    statuses = [
        e.get("value")
        for e in resource.iter()
        if _tag(e) == "INFO" and e.get("name") == "QUERY_STATUS"
    ]
    if "ERROR" in statuses:
        raise TapQueryError("VizieR TAP query failed")
    if statuses and any(s not in {"OK", "OVERFLOW"} for s in statuses):
        raise ValueError("Invalid TAP status")
    tables = [e for e in resource.iter() if _tag(e) == "TABLE"]
    if not tables:
        return "OVERFLOW" in statuses, False
    if len(tables) != 1:
        raise ValueError("Ambiguous result table")
    table_xml = tables[0]
    nrows = table_xml.get("nrows")
    if nrows is not None and (not nrows.isascii() or not nrows.isdigit() or int(nrows) > maxrec):
        raise ValueError("Invalid declared row count")
    fields = [e for e in table_xml if _tag(e) == "FIELD"]
    if len(fields) > MAX_TABLE_COLUMNS:
        raise ValueError("Too many fields")
    tabledata = [e for e in table_xml.iter() if _tag(e) == "TABLEDATA"]
    if tabledata and len(tabledata[0]) > maxrec:
        raise ValueError("Too many table rows")
    for field in fields:
        size = field.get("arraysize", "1")
        if field.get("datatype") in {"char", "unicodeChar"}:
            if size == "*" and tabledata:
                continue
            if not size.isascii() or not size.isdigit() or not 1 <= int(size) <= 8192:
                raise ValueError("Unbounded string array")
        elif size != "1":
            raise ValueError("Non-scalar field")
    return "OVERFLOW" in statuses, True


def _cell_value(raw_val: Any, col_name: str) -> str | int | float | bool | None:
    if raw_val is None or np.ma.is_masked(raw_val):
        return None
    if isinstance(raw_val, (bytes, np.bytes_)):
        text = bytes(raw_val).decode("utf-8", errors="replace").rstrip("\x00").strip()
        return text or None
    if isinstance(raw_val, np.generic):
        raw_val = raw_val.item()
    if isinstance(raw_val, bool):
        return raw_val
    if isinstance(raw_val, int):
        # Preserve >15-digit integers and identifier columns as exact strings.
        lower = col_name.lower()
        if (
            abs(raw_val) >= 10**15
            or lower in {"source_id", "gaiadr2", "gaiadr3", "objid"}
            or lower.endswith("_id")
        ):
            return str(raw_val)
        return raw_val
    if isinstance(raw_val, float):
        if not math.isfinite(raw_val):
            return None
        return raw_val
    text = str(raw_val).strip()
    if not text:
        return None
    if _is_long_int(text):
        return text
    return text


def _read_tap_response(session, adql: str, maxrec: int, timeout: float) -> bytes:
    response = session.post(
        VIZIER_ENDPOINT,
        data={
            "REQUEST": "doQuery",
            "LANG": "ADQL",
            "FORMAT": "votable",
            "QUERY": adql,
            "MAXREC": maxrec,
        },
        timeout=(min(10.0, timeout), timeout),
        allow_redirects=False,
        stream=True,
    )
    try:
        status = response.status_code
        if status in (401, 403):
            raise PermissionError(f"HTTP {status}")
        if status == 429:
            raise TimeoutError("rate_limited")
        if status == 400:
            raise TapQueryError("VizieR rejected ADQL query")
        if 500 <= status <= 599:
            raise ConnectionError(f"HTTP {status}")
        if status != 200:
            raise ValueError(f"Unexpected HTTP {status}")
        body = bytearray()
        for chunk in response.iter_content(chunk_size=64 * 1024):
            body.extend(chunk)
            if len(body) > MAX_RESPONSE_BYTES:
                raise ResponseTooLarge("Response exceeds 4 MiB limit")
        return bytes(body)
    finally:
        response.close()


def _read_cfa_asu_response(
    session,
    *,
    catalog_id: str,
    ra_deg: float,
    dec_deg: float,
    radius_arcmin: float,
    maxrec: int,
    selected_cols: list[str] | None,
    timeout: float,
) -> bytes:
    params: dict[str, str] = {
        "-source": catalog_id,
        "-c": f"{ra_deg:.7f} {dec_deg:+.7f}",
        "-c.rm": f"{radius_arcmin:.6f}",
        "-out.max": str(maxrec),
        "-sort": "_r",
    }
    if selected_cols:
        params["-out"] = ",".join(["_r", *selected_cols])
    else:
        params["-out"] = "_r,*"
    response = session.get(
        VIZIER_CFA_VOTABLE_ENDPOINT,
        params=params,
        timeout=(min(10.0, timeout), timeout),
        allow_redirects=False,
        stream=True,
    )
    try:
        status = response.status_code
        if status in (401, 403):
            raise PermissionError(f"HTTP {status}")
        if status == 429:
            raise TimeoutError("rate_limited")
        if status == 400:
            raise TapQueryError("VizieR mirror rejected query")
        if 500 <= status <= 599:
            raise ConnectionError(f"HTTP {status}")
        if status != 200:
            raise ValueError(f"Unexpected HTTP {status}")
        body = bytearray()
        for chunk in response.iter_content(chunk_size=64 * 1024):
            body.extend(chunk)
            if len(body) > MAX_RESPONSE_BYTES:
                raise ResponseTooLarge("Response exceeds 4 MiB limit")
        return bytes(body)
    finally:
        response.close()


def _parse_votable_rows(
    body: bytes,
    maxrec: int,
    *,
    preset_units: dict[str, str] | None = None,
) -> tuple[list[str], dict[str, str], list[dict[str, str | int | float | bool | None]], bool]:
    overflow, has_table = _validate_votable_xml(body, maxrec)
    if not has_table:
        return [], {}, [], overflow
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", VOWarning)
        parsed = parse_votable(BytesIO(body), verify="ignore").get_first_table()
    arr = parsed.array
    if len(arr) > maxrec:
        raise ValueError("Unexpected row count")

    fields = list(parsed.fields)
    col_names: list[str] = []
    units: dict[str, str] = {}
    for field in fields:
        name = str(field.name or field.ID)
        if name in ("separation_deg", "_r"):
            col_names.append("separation_arcsec")
            units["separation_arcsec"] = "arcsec"
            continue
        col_names.append(name)
        raw_unit = str(field.unit) if field.unit else (preset_units or {}).get(name, "")
        units[name] = "" if raw_unit in ("", "---") else raw_unit

    rows: list[dict[str, str | int | float | bool | None]] = []
    for raw_row in arr:
        item: dict[str, str | int | float | bool | None] = {}
        for field in fields:
            fname = str(field.name or field.ID)
            key = field.ID or field.name
            val = _cell_value(raw_row[key], fname)
            if fname == "separation_deg":
                if isinstance(val, (int, float)) and math.isfinite(float(val)):
                    item["separation_arcsec"] = round(float(val) * 3600.0, 6)
                else:
                    item["separation_arcsec"] = None
            elif fname == "_r":
                # VizieR ASU cone search (-c.rm) reports _r in arcmin.
                if isinstance(val, (int, float)) and math.isfinite(float(val)):
                    item["separation_arcsec"] = round(float(val) * 60.0, 6)
                else:
                    item["separation_arcsec"] = None
            else:
                item[fname] = val
        rows.append(item)
    return col_names, units, rows, overflow


def vizier_result_to_parsed_table(result: VizierQueryResult) -> ParsedTable:
    if result.status != "success" or not result.rows:
        raise ValueError("VizieR 查询结果为空或未成功，无法导入为数据表。")
    col_names = list(result.columns or result.rows[0].keys())
    col_metas: list[TableColumnMeta] = []
    str_cols: list[list[str | None]] = []
    for name in col_names:
        vals: list[str | None] = []
        for row in result.rows:
            cell = row.get(name)
            if cell is None:
                vals.append(None)
            elif isinstance(cell, bool):
                vals.append("true" if cell else "false")
            else:
                vals.append(str(cell))
        str_cols.append(vals)
        col_metas.append(
            _infer_column_meta(
                name,
                vals,
                unit=result.units.get(name) or None,
            )
        )
    rows = [[str_cols[c][r] for c in range(len(col_metas))] for r in range(len(result.rows))]
    return ParsedTable(
        columns=col_metas,
        rows=rows,
        format="votable",
        coordinate_frame=result.coordinate_frame,
        ref_epoch=result.ref_epoch,
        header_meta={"CATALOG_ID": result.catalog_id, "CDS_URL": result.cds_url},
        warnings=[*result.warnings, *SCIENTIFIC_BOUNDARY_WARNINGS],
    )


class VizierService:
    def __init__(
        self,
        timeout: float = 30.0,
        *,
        simbad: SimbadService | None = None,
        session=None,
    ):
        self.timeout = timeout
        self._simbad = simbad
        self._session = session

    def _discover_catalog_schema(
        self, session, catalog_id: str
    ) -> tuple[str, str, list[str], dict[str, str]]:
        escaped = _escape_adql_string(catalog_id)
        adql = (
            "SELECT TOP 64 column_name, unit, ucd "
            "FROM TAP_SCHEMA.columns "
            f"WHERE table_name = '{escaped}'"
        )
        body = _read_tap_response(session, adql, 64, self.timeout)
        _, _, schema_rows, _ = _parse_votable_rows(body, 64)
        if not schema_rows:
            raise TapQueryError("Catalog not found in TAP_SCHEMA.columns")

        ra_col: str | None = None
        dec_col: str | None = None
        all_cols: list[str] = []
        units: dict[str, str] = {}

        for row in schema_rows:
            cname = str(row.get("column_name") or "").strip()
            if not cname:
                continue
            all_cols.append(cname)
            unit = str(row.get("unit") or "").strip()
            if unit and unit != "---":
                units[cname] = unit
            ucd = str(row.get("ucd") or "").lower()
            if ra_col is None and ("pos.eq.ra;meta.main" in ucd or "pos.eq.ra" in ucd):
                ra_col = cname
            if dec_col is None and ("pos.eq.dec;meta.main" in ucd or "pos.eq.dec" in ucd):
                dec_col = cname

        if ra_col is None:
            for candidate in ("RAJ2000", "RA_ICRS", "_RAJ2000", "RA", "ra"):
                if candidate in all_cols:
                    ra_col = candidate
                    break
        if dec_col is None:
            for candidate in ("DEJ2000", "DE_ICRS", "_DEJ2000", "DEC", "Dec", "dec"):
                if candidate in all_cols:
                    dec_col = candidate
                    break
        if not ra_col or not dec_col:
            raise ValueError("Missing coordinate columns")
        return ra_col, dec_col, all_cols, units

    def query(self, arguments: VizierQuery) -> VizierQueryResult:
        preset = _PRESETS_BY_ID.get(arguments.catalog_id)
        cds_url = (
            preset.cds_url
            if preset is not None
            else f"{VIZIER_CATALOG_BASE}{quote(arguments.catalog_id, safe='/')}"
        )
        catalog_title = preset.title if preset is not None else arguments.catalog_id
        ref_epoch = preset.ref_epoch if preset is not None else None
        coord_frame = preset.coordinate_frame if preset is not None else "ICRS"
        warnings_list = [VIZIER_SAMPLE_WARNING, VIZIER_POSITION_WARNING]
        if ref_epoch:
            warnings_list.append(
                f"星表 {arguments.catalog_id} 默认参考历元为 {ref_epoch}，"
                "与 Gaia DR3 (J2016.0) 交叉匹配时应留意自行差异。"
            )
        else:
            warnings_list.append("自定义星表参考历元未在预设中锁定，跨星表匹配前请核对历元元数据。")

        resolved_object: dict[str, Any] | None = None
        ra_deg = arguments.ra_deg
        dec_deg = arguments.dec_deg
        if arguments.object_name is not None:
            simbad_service = self._simbad or SimbadService(timeout=min(20.0, self.timeout))
            simbad_res = simbad_service.query(arguments.object_name)
            if (
                simbad_res.status != "success"
                or simbad_res.data is None
                or simbad_res.data.ra_deg is None
                or simbad_res.data.dec_deg is None
            ):
                return VizierQueryResult(
                    catalog_id=arguments.catalog_id,
                    catalog_title=catalog_title,
                    query=arguments.effective_parameters(),
                    adql="",
                    cds_url=cds_url,
                    status="error" if simbad_res.status == "error" else "not_found",
                    ref_epoch=ref_epoch,
                    coordinate_frame=coord_frame,
                    source=Source(name="VizieR", url=cds_url, retrieved_at=datetime.now(UTC)),
                    warnings=warnings_list,
                    error=simbad_res.error
                    or ErrorInfo(
                        code="vizier_object_unresolved",
                        message=(
                            f"无法通过 SIMBAD 解析天体「{arguments.object_name}」的 ICRS 坐标。"
                        ),
                    ),
                )
            ra_deg = simbad_res.data.ra_deg
            dec_deg = simbad_res.data.dec_deg
            resolved_object = {
                "query_name": arguments.object_name,
                "main_id": simbad_res.data.main_id,
                "ra_deg": ra_deg,
                "dec_deg": dec_deg,
                "source_url": simbad_res.source.url,
            }

        assert ra_deg is not None and dec_deg is not None
        reserve_request("astronomy_queries")

        def failure(
            code: str,
            message: str,
            retryable: bool = False,
            *,
            status: str = "error",
            adql: str = "",
            ra_col: str | None = None,
            dec_col: str | None = None,
        ):
            return VizierQueryResult(
                catalog_id=arguments.catalog_id,
                catalog_title=catalog_title,
                query=arguments.effective_parameters(),
                adql=adql,
                cds_url=cds_url,
                status=status,
                ref_epoch=ref_epoch,
                coordinate_frame=coord_frame,
                ra_column=ra_col,
                dec_column=dec_col,
                resolved_object=resolved_object,
                source=Source(name="VizieR", url=cds_url, retrieved_at=datetime.now(UTC)),
                warnings=warnings_list,
                error=ErrorInfo(code=code, message=message, retryable=retryable),
            )

        owned = self._session is None
        session = self._session if self._session is not None else requests.Session()
        adql = ""
        ra_col: str | None = preset.ra_col if preset else None
        dec_col: str | None = preset.dec_col if preset else None
        effective_source_url = cds_url
        try:
            maxrec = arguments.limit + 1
            used_cfa_mirror = False
            preset_units: dict[str, str] = dict(preset.units) if preset is not None else {}

            def _run_tap():
                nonlocal adql, ra_col, dec_col, preset_units
                if preset is not None:
                    selected_cols = list(arguments.columns or preset.default_columns)
                    for coord_col in (preset.ra_col, preset.dec_col):
                        if coord_col not in selected_cols:
                            selected_cols.insert(0, coord_col)
                    preset_units = preset.units
                else:
                    ra_col, dec_col, all_cols, preset_units = self._discover_catalog_schema(
                        session, arguments.catalog_id
                    )
                    if arguments.columns:
                        missing = [c for c in arguments.columns if c not in all_cols]
                        if missing:
                            raise TapQueryError(f"Missing columns: {', '.join(missing[:6])}")
                        selected_cols = list(arguments.columns)
                    else:
                        selected_cols = list(all_cols[:16])
                    for coord_col in (ra_col, dec_col):
                        if coord_col not in selected_cols:
                            selected_cols.insert(0, coord_col)

                selected_cols = selected_cols[: MAX_TABLE_COLUMNS - 1]
                col_expr = ", ".join(_quote_ident(c) for c in selected_cols)
                ra_ident = _quote_ident(ra_col)
                dec_ident = _quote_ident(dec_col)
                table_ident = _quote_ident(arguments.catalog_id)
                radius_deg = arguments.radius_arcmin / 60.0
                point = f"POINT('ICRS', {ra_deg!r}, {dec_deg!r})"
                adql = (
                    f"SELECT TOP {maxrec} {col_expr}, "
                    f"DISTANCE(POINT('ICRS', {ra_ident}, {dec_ident}), {point}) AS separation_deg "
                    f"FROM {table_ident} "
                    f"WHERE 1 = CONTAINS(POINT('ICRS', {ra_ident}, {dec_ident}), "
                    f"CIRCLE('ICRS', {ra_deg!r}, {dec_deg!r}, {radius_deg!r})) "
                    "ORDER BY separation_deg ASC"
                )
                tap_timeout = min(8.0, self.timeout) if owned else self.timeout
                body = _read_tap_response(session, adql, maxrec, tap_timeout)
                return _parse_votable_rows(body, maxrec, preset_units=preset_units)

            try:
                col_names, units, rows, overflow = _run_tap()
            except (requests.Timeout, requests.RequestException, ConnectionError):
                if not owned:
                    raise
                cfa_cols: list[str] | None = None
                if preset is not None:
                    cfa_cols = list(arguments.columns or preset.default_columns)
                    for coord_col in (preset.ra_col, preset.dec_col):
                        if coord_col not in cfa_cols:
                            cfa_cols.insert(0, coord_col)
                    cfa_cols = cfa_cols[: MAX_TABLE_COLUMNS - 1]
                elif arguments.columns:
                    cfa_cols = list(arguments.columns)[: MAX_TABLE_COLUMNS - 1]
                body = _read_cfa_asu_response(
                    session,
                    catalog_id=arguments.catalog_id,
                    ra_deg=ra_deg,
                    dec_deg=dec_deg,
                    radius_arcmin=arguments.radius_arcmin,
                    maxrec=maxrec,
                    selected_cols=cfa_cols,
                    timeout=self.timeout,
                )
                col_names, units, rows, overflow = _parse_votable_rows(
                    body, maxrec, preset_units=preset_units
                )
                used_cfa_mirror = True
                effective_source_url = (
                    f"{VIZIER_CFA_CATALOG_BASE}{quote(arguments.catalog_id, safe='/')}"
                )
                adql = (
                    f"-- VizieR CfA Mirror VOTable cone search\n"
                    f"source={arguments.catalog_id} ra={ra_deg:.6f} dec={dec_deg:+.6f} "
                    f"radius_arcmin={arguments.radius_arcmin} maxrec={maxrec}"
                )
                if ra_col is None:
                    for cand in ("RAJ2000", "RA_ICRS", "_RAJ2000", "RA", "ra"):
                        if cand in col_names:
                            ra_col = cand
                            break
                if dec_col is None:
                    for cand in ("DEJ2000", "DE_ICRS", "_DEJ2000", "DEC", "Dec", "dec"):
                        if cand in col_names:
                            dec_col = cand
                            break
            if not rows:
                return failure(
                    "vizier_not_found",
                    f"在星表 {arguments.catalog_id} 的检索半径内未找到匹配源。",
                    status="not_found",
                    adql=adql,
                    ra_col=ra_col,
                    dec_col=dec_col,
                )
            has_more = overflow or len(rows) > arguments.limit
            delivered = rows[: arguments.limit]
            if used_cfa_mirror:
                warnings_list.append(
                    "CDS VizieR 法国主站连接超时，"
                    "本次已自动切换至哈佛 CfA 官方 VizieR 镜像（vizier.cfa.harvard.edu）。"
                )
            if has_more:
                warnings_list.append("结果已按返回上限截断，统计仅限交付行；未执行自动翻页。")
            if overflow:
                warnings_list.append("VizieR TAP 服务报告 OVERFLOW：服务端已截断结果。")

            return VizierQueryResult(
                catalog_id=arguments.catalog_id,
                catalog_title=catalog_title,
                query=arguments.effective_parameters(),
                adql=adql,
                cds_url=effective_source_url,
                status="success",
                returned_count=len(delivered),
                has_more=has_more,
                truncated=has_more,
                archive_overflow=overflow,
                columns=col_names,
                units=units,
                ref_epoch=ref_epoch,
                coordinate_frame=coord_frame,
                ra_column=ra_col,
                dec_column=dec_col,
                resolved_object=resolved_object,
                rows=delivered,
                source=Source(
                    name="VizieR", url=effective_source_url, retrieved_at=datetime.now(UTC)
                ),
                warnings=warnings_list,
            )
        except ResponseTooLarge:
            return failure(
                "vizier_response_too_large",
                "VizieR 响应超过 4 MiB 上限，已终止读取。",
                adql=adql,
                ra_col=ra_col,
                dec_col=dec_col,
            )
        except PermissionError:
            return failure(
                "vizier_access_denied",
                "VizieR 服务拒绝访问此查询。",
                adql=adql,
                ra_col=ra_col,
                dec_col=dec_col,
            )
        except TapQueryError:
            return failure(
                "vizier_query_failed",
                "VizieR TAP 报告查询失败，请检查星表编号或字段兼容性。",
                adql=adql,
                ra_col=ra_col,
                dec_col=dec_col,
            )
        except requests.Timeout:
            return failure(
                "vizier_timeout",
                "VizieR 查询超时，请稍后重试。",
                True,
                adql=adql,
                ra_col=ra_col,
                dec_col=dec_col,
            )
        except TimeoutError:
            return failure(
                "vizier_rate_limited",
                "VizieR 请求受限，请稍后重试。",
                True,
                adql=adql,
                ra_col=ra_col,
                dec_col=dec_col,
            )
        except (requests.RequestException, ConnectionError):
            return failure(
                "vizier_unavailable",
                "无法连接 VizieR 服务，请稍后重试。",
                True,
                adql=adql,
                ra_col=ra_col,
                dec_col=dec_col,
            )
        except (
            ValueError,
            TypeError,
            KeyError,
            OverflowError,
            OSError,
            SafeET.ParseError,
            DefusedXmlException,
            VOWarning,
            IndexError,
            EOFError,
            struct.error,
        ):
            return failure(
                "vizier_unexpected_response",
                "VizieR 返回的数据无效、缺少坐标列或未通过安全校验。",
                adql=adql,
                ra_col=ra_col,
                dec_col=dec_col,
            )
        finally:
            if owned:
                session.close()
