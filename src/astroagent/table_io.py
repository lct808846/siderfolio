"""Bounded, safe multi-format astronomical table I/O (FITS / VOTable / ECSV / CSV / TSV)."""

from __future__ import annotations

import csv
import gzip
import hashlib
import io
import math
import re
import threading
import warnings
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import PurePosixPath
from typing import Any, Literal

import numpy as np
from astropy import units as u
from astropy.io import ascii as astro_ascii
from astropy.io import fits
from astropy.io.votable import parse as parse_votable
from astropy.io.votable.exceptions import VOWarning
from astropy.table import MaskedColumn, Table
from defusedxml import ElementTree as SafeET
from defusedxml.common import DefusedXmlException

from astroagent.errors import ServiceError
from astroagent.table_schemas import (
    MAX_CELL_CHARS,
    MAX_TABLE_COLUMNS,
    MAX_TABLE_GZ_BYTES,
    MAX_TABLE_ROWS,
    MAX_TABLE_UPLOAD_BYTES,
    ColumnKind,
    TableColumnMeta,
    TableFormat,
    TableHduInfo,
    TableInspectResponse,
)

ANALYSIS_SLOTS = threading.BoundedSemaphore(2)

SCIENTIFIC_BOUNDARY_WARNINGS = (
    "未自动校正星际消光、视差零点或系统误差；负视差为合法测量值，不默认删除。",
    "所有运算仅基于当前交付数据行与列元数据，不代表完整总体或星团成员确认。",
)

_IDENTIFIER_NAMES = {
    "id",
    "source_id",
    "gaia_source_id",
    "gaiadr2",
    "gaiadr3",
    "designation",
    "bibcode",
    "identifier",
    "objid",
}
_VLA_FORMAT_RE = re.compile(r"^[01]?[PQ]", re.I)
_FITS_ARRAY_RE = re.compile(r"^(\d+)[A-Za-z]")
_UNSAFE_YAML_TAG_RE = re.compile(r"!!(?:python|map|seq|exec|object)", re.I)
_CANONICAL_META_KEY = "siderfolio_table_v1"
_HEADER_META_KEYS = (
    "OBJECT",
    "EQUINOX",
    "RADESYS",
    "RADECSYS",
    "MJD-OBS",
    "DATE-OBS",
    "EPOCH",
    "REF_EPOCH",
)


@dataclass(slots=True)
class ParsedTable:
    columns: list[TableColumnMeta]
    rows: list[list[str | None]]
    format: TableFormat
    coordinate_frame: str | None = None
    ref_epoch: str | None = None
    header_meta: dict[str, str] | None = None
    warnings: list[str] | None = None


def sha256_hex(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _invalid(message: str, *, code: str = "table_invalid") -> ServiceError:
    return ServiceError(422, code, message)


def detect_table_format(filename: str) -> TableFormat:
    suffix = PurePosixPath((filename or "").replace("\\", "/").rsplit("/", 1)[-1]).suffix.lower()
    if suffix in (".fits", ".fit"):
        return "fits"
    if suffix in (".vot", ".xml"):
        return "votable"
    if suffix == ".ecsv":
        return "ecsv"
    if suffix == ".csv":
        return "csv"
    if suffix == ".tsv":
        return "tsv"
    raise ServiceError(
        415,
        "table_format_unsupported",
        "仅支持 FITS (.fits/.fit)、VOTable (.vot/.xml)、ECSV (.ecsv)、"
        "CSV (.csv) 与 TSV (.tsv) 数据表。",
    )


def _is_finite_number(text: str) -> bool:
    try:
        dec = Decimal(text)
        if not dec.is_finite():
            return False
        return math.isfinite(float(text))
    except (InvalidOperation, ValueError, OverflowError):
        return False


def _is_long_int(text: str) -> bool:
    stripped = text.strip()
    digits = stripped.lstrip("+-")
    return digits.isdigit() and len(digits) > 15


def _is_int_literal(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return False
    digits = stripped.lstrip("+-")
    return digits.isdigit()


def _is_identifier_name(name: str) -> bool:
    lower = name.strip().lower()
    return lower in _IDENTIFIER_NAMES or lower.endswith("_id")


def _infer_column_meta(
    name: str,
    values: list[str | None],
    *,
    dtype_hint: str | None = None,
    unit: str | None = None,
    ucd: str | None = None,
    description: str | None = None,
) -> TableColumnMeta:
    non_null = [v for v in values if v is not None and v != ""]
    missing = len(values) - len(non_null)
    if not non_null:
        kind: ColumnKind = "empty"
        dtype = dtype_hint or "string"
    elif _is_identifier_name(name) or any(_is_long_int(v) for v in non_null):
        kind = "identifier"
        dtype = "string"
    elif all(v.lower() in ("true", "false") for v in non_null) and (
        dtype_hint in (None, "bool", "boolean")
    ):
        kind = "boolean"
        dtype = "bool"
    elif all(_is_int_literal(v) for v in non_null) and (
        dtype_hint is None or "int" in dtype_hint.lower()
    ):
        kind = "integer"
        dtype = dtype_hint or "int64"
    elif all(_is_finite_number(v) for v in non_null):
        kind = "number"
        dtype = dtype_hint or "float64"
    else:
        kind = "text"
        dtype = dtype_hint or "string"
    return TableColumnMeta(
        name=name[:128],
        kind=kind,
        dtype=str(dtype)[:64],
        unit=(unit.strip()[:128] if unit and unit.strip() and unit.strip() != "---" else None),
        ucd=(ucd.strip()[:128] if ucd and ucd.strip() else None),
        description=(description.strip()[:500] if description and description.strip() else None),
        missing=missing,
    )


def _format_cell(val: Any) -> str | None:
    if val is None or np.ma.is_masked(val):
        return None
    if isinstance(val, (bytes, np.bytes_)):
        text = bytes(val).decode("utf-8", errors="replace").rstrip("\x00").strip()
        if "\x00" in text:
            raise _invalid("数据包含非法空字节。")
        return text or None
    if isinstance(val, (bool, np.bool_)):
        return "true" if bool(val) else "false"
    if isinstance(val, (int, np.integer)):
        return str(int(val))
    if isinstance(val, (float, np.floating)):
        fval = float(val)
        if not math.isfinite(fval):
            return None
        return repr(fval)
    if isinstance(val, np.ndarray):
        raise _invalid("暂不支持数组型或变长向量单元格。")
    text = str(val).strip()
    if "\x00" in text:
        raise _invalid("数据包含非法空字节。")
    if len(text) > MAX_CELL_CHARS:
        raise _invalid(f"单元格内容超过 {MAX_CELL_CHARS} 字符上限。")
    return text if text != "" else None


def _validate_col_names(names: list[str]) -> list[str]:
    cleaned: list[str] = []
    seen: set[str] = set()
    for raw_name in names:
        name = str(raw_name).strip()
        if not name or len(name) > 128 or any(ord(ch) < 32 for ch in name):
            raise _invalid("列名不能为空、包含控制字符或超过 128 字符。")
        if name in seen:
            raise _invalid(f"存在重复列名：{name}。")
        seen.add(name)
        cleaned.append(name)
    return cleaned


def _subset_columns(
    columns: list[TableColumnMeta],
    rows: list[list[str | None]],
    selected_columns: list[str] | None,
) -> tuple[list[TableColumnMeta], list[list[str | None]]]:
    if selected_columns is None:
        if len(columns) > MAX_TABLE_COLUMNS:
            raise _invalid(
                f"当前表包含 {len(columns)} 列，超过单表 {MAX_TABLE_COLUMNS} 列上限；"
                f"请在导入预览中勾选不超过 {MAX_TABLE_COLUMNS} 个目标列。",
                code="table_too_many_columns",
            )
        return columns, rows
    requested = [c.strip() for c in selected_columns if c and c.strip()]
    if not 1 <= len(requested) <= MAX_TABLE_COLUMNS:
        raise _invalid(f"请选择 1 至 {MAX_TABLE_COLUMNS} 个不重复的目标列。")
    if len(set(requested)) != len(requested):
        raise _invalid("所选列名存在重复。")
    index_by_name = {col.name: idx for idx, col in enumerate(columns)}
    missing = [c for c in requested if c not in index_by_name]
    if missing:
        raise _invalid(f"指定的列名在数据表中不存在：{', '.join(missing[:8])}。")
    indices = [index_by_name[c] for c in requested]
    return (
        [columns[i] for i in indices],
        [[row[i] for i in indices] for row in rows],
    )


def _tag_name(elem) -> str:
    return elem.tag.rsplit("}", 1)[-1]


def _extract_fits_header_meta(header) -> tuple[str | None, str | None, dict[str, str]]:
    meta: dict[str, str] = {}
    for key in _HEADER_META_KEYS:
        if key in header and header[key] is not None:
            val = str(header[key]).strip()
            if val:
                meta[key] = val[:160]
    frame = meta.get("RADESYS") or meta.get("RADECSYS")
    epoch = meta.get("REF_EPOCH") or meta.get("EPOCH") or meta.get("EQUINOX")
    if not epoch and "MJD-OBS" in meta:
        epoch = f"MJD {meta['MJD-OBS']}"
    return frame, epoch, meta


def _fits_column_selectable(col) -> tuple[bool, str | None]:
    fmt = str(getattr(col, "format", "") or "")
    if _VLA_FORMAT_RE.match(fmt):
        return False, f"列 {col.name} 为变长数组 (VLA {fmt})，暂不支持。"
    match = _FITS_ARRAY_RE.match(fmt)
    if match and int(match.group(1)) > 1 and not fmt.upper().endswith("A"):
        return False, f"列 {col.name} 为多维数组 ({fmt})，暂不支持。"
    return True, None


def _inspect_fits(
    raw: bytes,
) -> tuple[list[TableHduInfo], str | None, str | None, dict[str, str], list[str]]:
    if not raw.startswith(b"SIMPLE  ="):
        raise _invalid("无效 FITS 文件：缺少标准 SIMPLE 头签名。")
    hdus_info: list[TableHduInfo] = []
    warnings_list: list[str] = []
    coord_frame: str | None = None
    ref_epoch: str | None = None
    merged_meta: dict[str, str] = {}
    try:
        with fits.open(io.BytesIO(raw), memmap=False, lazy_load_hdus=False) as hdul:
            primary_frame, primary_epoch, primary_meta = _extract_fits_header_meta(hdul[0].header)
            coord_frame = primary_frame
            ref_epoch = primary_epoch
            merged_meta.update(primary_meta)
            for idx, hdu in enumerate(hdul):
                is_table = isinstance(hdu, (fits.BinTableHDU, fits.TableHDU))
                hdu_name = str(hdu.name or f"HDU_{idx}")
                if not is_table:
                    hdus_info.append(
                        TableHduInfo(
                            index=idx,
                            name=hdu_name,
                            kind=type(hdu).__name__,
                            rows=0,
                            columns=[],
                            selectable=False,
                            reason="非表格 HDU（图像或主头仅保留观测元信息）",
                        )
                    )
                    continue
                nrows = int(hdu.header.get("NAXIS2", 0) or 0)
                t_frame, t_epoch, t_meta = _extract_fits_header_meta(hdu.header)
                coord_frame = coord_frame or t_frame
                ref_epoch = ref_epoch or t_epoch
                merged_meta.update(t_meta)
                cols_meta: list[TableColumnMeta] = []
                bad_reason: str | None = None
                for col_idx, col in enumerate(hdu.columns, start=1):
                    ok_col, reason = _fits_column_selectable(col)
                    if not ok_col and bad_reason is None:
                        bad_reason = reason
                    unit = col.unit or hdu.header.get(f"TUNIT{col_idx}")
                    comm = hdu.header.get(f"TCOMM{col_idx}")
                    fmt = str(col.format or "")
                    dtype_hint = (
                        "string"
                        if "A" in fmt.upper()
                        else "int64"
                        if any(t in fmt.upper() for t in ("I", "J", "K"))
                        else "float64"
                    )
                    cols_meta.append(
                        TableColumnMeta(
                            name=str(col.name).strip() or f"col_{col_idx}",
                            kind="identifier"
                            if _is_identifier_name(str(col.name))
                            else "number"
                            if dtype_hint == "float64"
                            else "integer"
                            if dtype_hint == "int64"
                            else "text",
                            dtype=dtype_hint,
                            unit=(
                                str(unit).strip()[:128]
                                if unit and str(unit).strip() != "---"
                                else None
                            ),
                            description=(str(comm).strip()[:500] if comm else None),
                        )
                    )
                selectable = (
                    bad_reason is None and 1 <= nrows <= MAX_TABLE_ROWS and len(cols_meta) >= 1
                )
                if nrows == 0:
                    bad_reason = bad_reason or "表格为空（0 行）"
                elif nrows > MAX_TABLE_ROWS:
                    bad_reason = bad_reason or f"行数 {nrows} 超过上限 {MAX_TABLE_ROWS}"
                hdus_info.append(
                    TableHduInfo(
                        index=idx,
                        name=hdu_name,
                        kind=type(hdu).__name__,
                        rows=nrows,
                        columns=cols_meta,
                        selectable=selectable,
                        reason=bad_reason,
                    )
                )
    except ServiceError:
        raise
    except Exception as exc:
        raise _invalid("无法解析 FITS 文件，请确认文件未损坏且为标准 FITS 格式。") from exc
    if not any(item.kind in ("BinTableHDU", "TableHDU") for item in hdus_info):
        raise _invalid(
            "该 FITS 文件不包含 BinTableHDU 或 TableHDU 表格扩展（不支持纯图像 HDU 测光）。"
        )
    return hdus_info, coord_frame, ref_epoch, merged_meta, warnings_list


def _validate_votable_xml(raw: bytes) -> tuple[list[Any], str | None, str | None]:
    try:
        root = SafeET.fromstring(raw, forbid_dtd=True, forbid_entities=True, forbid_external=True)
    except (SafeET.ParseError, DefusedXmlException) as exc:
        raise _invalid("VOTable XML 安全校验失败（禁止 DTD、实体扩展或外部引用）。") from exc
    if _tag_name(root) != "VOTABLE":
        raise _invalid("无效 VOTable：根元素必须为 VOTABLE。")
    coord_frame: str | None = None
    ref_epoch: str | None = None
    for elem in root.iter():
        tag = _tag_name(elem)
        if tag == "FITS" or any(key.rsplit("}", 1)[-1] == "href" for key in elem.attrib):
            raise _invalid("出于安全边界限制，禁止 VOTable 包含外部 href 或外链 FITS 引用。")
        if tag == "COOSYS":
            coord_frame = coord_frame or elem.get("system")
            ref_epoch = ref_epoch or elem.get("epoch") or elem.get("equinox")
    tables = [e for e in root.iter() if _tag_name(e) == "TABLE"]
    if not tables:
        raise _invalid("VOTable 中未找到 TABLE 定义。")
    for table_xml in tables:
        nrows = table_xml.get("nrows")
        if nrows is not None and (
            not nrows.isascii() or not nrows.isdigit() or int(nrows) > MAX_TABLE_ROWS
        ):
            raise _invalid(f"VOTable 声明行数无效或超过上限 {MAX_TABLE_ROWS}。")
        for tdata in table_xml.iter():
            if _tag_name(tdata) == "TABLEDATA" and len(tdata) > MAX_TABLE_ROWS:
                raise _invalid(f"VOTable 数据行数超过上限 {MAX_TABLE_ROWS}。")
        for field in table_xml:
            if _tag_name(field) != "FIELD":
                continue
            size = field.get("arraysize", "1")
            dtype = field.get("datatype", "")
            if dtype in ("char", "unicodeChar"):
                if size != "*" and (
                    not size.isascii() or not size.isdigit() or not 1 <= int(size) <= MAX_CELL_CHARS
                ):
                    raise _invalid("VOTable 字符串列 arraysize 超限。")
            elif size != "1":
                raise _invalid("暂不支持 VOTable 非标量数值数组列。")
    return tables, coord_frame, ref_epoch


def inspect_table_bytes(raw: bytes, filename: str) -> TableInspectResponse:
    if not raw or len(raw) > MAX_TABLE_UPLOAD_BYTES:
        raise ServiceError(413, "table_too_large", "文件不能为空，且不能超过 10 MiB。")
    fmt = detect_table_format(filename)
    digest = sha256_hex(raw)
    base_name = (filename or "table").replace("\\", "/").rsplit("/", 1)[-1].strip() or "table"
    if fmt in ("fits", "votable"):
        if not ANALYSIS_SLOTS.acquire(timeout=2.0):
            raise ServiceError(
                503,
                "table_analysis_busy",
                "服务器正在解析其他天文数据表，请稍后重试。",
                retryable=True,
            )
        try:
            if fmt == "fits":
                hdus, frame, epoch, meta, warn = _inspect_fits(raw)
                default_idx = next((h.index for h in hdus if h.selectable), None)
                return TableInspectResponse(
                    filename=base_name,
                    format=fmt,
                    size_bytes=len(raw),
                    sha256=digest,
                    hdus=hdus,
                    default_hdu_index=default_idx,
                    coordinate_frame=frame,
                    ref_epoch=epoch,
                    header_meta=meta,
                    warnings=[*warn, *SCIENTIFIC_BOUNDARY_WARNINGS],
                )
            tables_xml, frame, epoch = _validate_votable_xml(raw)
            try:
                with warnings.catch_warnings(record=True) as caught:
                    warnings.simplefilter("always", VOWarning)
                    vot = parse_votable(io.BytesIO(raw), verify="ignore")
            except Exception as exc:
                raise _invalid("无法解析 VOTable 数据内容。") from exc
            hdus: list[TableHduInfo] = []
            for idx, resource in enumerate(vot.resources):
                for t_idx, table in enumerate(resource.tables):
                    hdu_idx = len(hdus)
                    cols = [
                        TableColumnMeta(
                            name=str(f.name or f.ID or f"col_{i + 1}").strip()[:128],
                            kind="identifier"
                            if _is_identifier_name(str(f.name or f.ID or ""))
                            else "text"
                            if f.datatype in ("char", "unicodeChar")
                            else "number",
                            dtype=str(f.datatype or "string"),
                            unit=(str(f.unit) if f.unit else None),
                            ucd=(str(f.ucd) if f.ucd else None),
                            description=(str(f.description)[:500] if f.description else None),
                        )
                        for i, f in enumerate(table.fields)
                    ]
                    nrows = int(len(table.array))
                    selectable = 1 <= nrows <= MAX_TABLE_ROWS and len(cols) >= 1
                    reason = (
                        None
                        if selectable
                        else ("表格为空" if nrows == 0 else f"行数超过 {MAX_TABLE_ROWS}")
                    )
                    hdus.append(
                        TableHduInfo(
                            index=hdu_idx,
                            name=str(table.name or table.ID or f"TABLE_{idx}_{t_idx}"),
                            kind="VOTable",
                            rows=nrows,
                            columns=cols,
                            selectable=selectable,
                            reason=reason,
                        )
                    )
            default_idx = next((h.index for h in hdus if h.selectable), None)
            warn = [str(w.message)[:200] for w in caught[:3]]
            return TableInspectResponse(
                filename=base_name,
                format=fmt,
                size_bytes=len(raw),
                sha256=digest,
                hdus=hdus,
                default_hdu_index=default_idx,
                coordinate_frame=frame,
                ref_epoch=epoch,
                header_meta={},
                warnings=[*warn, *SCIENTIFIC_BOUNDARY_WARNINGS],
            )
        finally:
            ANALYSIS_SLOTS.release()

    parsed = parse_table_bytes(raw, base_name, allow_wide=True)
    return TableInspectResponse(
        filename=base_name,
        format=fmt,
        size_bytes=len(raw),
        sha256=digest,
        hdus=[
            TableHduInfo(
                index=0,
                name=base_name,
                kind=fmt.upper(),
                rows=len(parsed.rows),
                columns=parsed.columns,
                selectable=True,
            )
        ],
        default_hdu_index=0,
        coordinate_frame=parsed.coordinate_frame,
        ref_epoch=parsed.ref_epoch,
        header_meta=parsed.header_meta or {},
        warnings=[*(parsed.warnings or []), *SCIENTIFIC_BOUNDARY_WARNINGS],
    )


def parse_table_bytes(
    raw: bytes,
    filename: str,
    *,
    hdu_index: int | None = None,
    selected_columns: list[str] | None = None,
    allow_wide: bool = False,
) -> ParsedTable:
    if not raw or len(raw) > MAX_TABLE_UPLOAD_BYTES:
        raise ServiceError(413, "table_too_large", "文件不能为空，且不能超过 10 MiB。")
    fmt = detect_table_format(filename)
    if not ANALYSIS_SLOTS.acquire(timeout=2.0):
        raise ServiceError(
            503, "table_analysis_busy", "服务器正在解析其他天文数据表，请稍后重试。", retryable=True
        )
    try:
        if fmt == "fits":
            return _parse_fits_bytes(
                raw, hdu_index=hdu_index, selected_columns=selected_columns, allow_wide=allow_wide
            )
        if fmt == "votable":
            return _parse_votable_bytes(
                raw, hdu_index=hdu_index, selected_columns=selected_columns, allow_wide=allow_wide
            )
        if fmt == "ecsv":
            return _parse_ecsv_bytes(raw, selected_columns=selected_columns, allow_wide=allow_wide)
        return _parse_delimited_bytes(
            raw, fmt, selected_columns=selected_columns, allow_wide=allow_wide
        )
    finally:
        ANALYSIS_SLOTS.release()


def _parse_fits_bytes(
    raw: bytes,
    *,
    hdu_index: int | None,
    selected_columns: list[str] | None,
    allow_wide: bool,
) -> ParsedTable:
    if not raw.startswith(b"SIMPLE  ="):
        raise _invalid("无效 FITS 文件：缺少标准 SIMPLE 头签名。")
    try:
        with fits.open(io.BytesIO(raw), memmap=False, lazy_load_hdus=False) as hdul:
            primary_frame, primary_epoch, meta = _extract_fits_header_meta(hdul[0].header)
            table_indices = [
                i for i, h in enumerate(hdul) if isinstance(h, (fits.BinTableHDU, fits.TableHDU))
            ]
            if not table_indices:
                raise _invalid("该 FITS 文件不包含表格 HDU（不支持纯图像 HDU）。")
            target_idx = table_indices[0] if hdu_index is None else hdu_index
            if target_idx not in table_indices:
                raise _invalid(f"指定的 HDU #{target_idx} 不是有效的 FITS 表格扩展。")
            hdu = hdul[target_idx]
            nrows = len(hdu.data) if hdu.data is not None else 0
            if nrows < 1 or nrows > MAX_TABLE_ROWS:
                raise _invalid(f"FITS 表格行数须在 1 至 {MAX_TABLE_ROWS} 之间（当前 {nrows} 行）。")
            raw_names = _validate_col_names([str(c.name) for c in hdu.columns])
            for col in hdu.columns:
                ok_col, reason = _fits_column_selectable(col)
                if not ok_col:
                    raise _invalid(reason or "FITS 列格式不支持。")
            t_frame, t_epoch, t_meta = _extract_fits_header_meta(hdu.header)
            meta.update(t_meta)
            frame = t_frame or primary_frame
            epoch = t_epoch or primary_epoch

            col_values: list[list[str | None]] = []
            col_metas: list[TableColumnMeta] = []
            for c_idx, col_name in enumerate(raw_names):
                fits_col = hdu.columns[c_idx]
                arr = hdu.data[fits_col.name]
                null_val = getattr(fits_col, "null", None)
                vals: list[str | None] = []
                for item in arr:
                    if null_val is not None and item == null_val:
                        vals.append(None)
                    else:
                        vals.append(_format_cell(item))
                col_values.append(vals)
                t_idx = c_idx + 1
                unit = fits_col.unit or hdu.header.get(f"TUNIT{t_idx}")
                comm = hdu.header.get(f"TCOMM{t_idx}")
                col_metas.append(
                    _infer_column_meta(
                        col_name,
                        vals,
                        dtype_hint=str(arr.dtype),
                        unit=str(unit) if unit else None,
                        description=str(comm) if comm else None,
                    )
                )
            rows = [[col_values[c][r] for c in range(len(col_metas))] for r in range(nrows)]
            if not allow_wide:
                col_metas, rows = _subset_columns(col_metas, rows, selected_columns)
            return ParsedTable(
                columns=col_metas,
                rows=rows,
                format="fits",
                coordinate_frame=frame,
                ref_epoch=epoch,
                header_meta=meta,
                warnings=list(SCIENTIFIC_BOUNDARY_WARNINGS),
            )
    except ServiceError:
        raise
    except Exception as exc:
        raise _invalid("无法解析 FITS 表格数据，请检查文件完整性。") from exc


def _parse_votable_bytes(
    raw: bytes,
    *,
    hdu_index: int | None,
    selected_columns: list[str] | None,
    allow_wide: bool,
) -> ParsedTable:
    _, frame, epoch = _validate_votable_xml(raw)
    try:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always", VOWarning)
            vot = parse_votable(io.BytesIO(raw), verify="ignore")
    except Exception as exc:
        raise _invalid("无法解析 VOTable 数据内容。") from exc
    all_tables = [t for res in vot.resources for t in res.tables]
    if not all_tables:
        raise _invalid("VOTable 不包含可用数据表。")
    target_idx = 0 if hdu_index is None else hdu_index
    if not 0 <= target_idx < len(all_tables):
        raise _invalid(f"指定的表索引 #{target_idx} 不存在。")
    vtable = all_tables[target_idx]
    arr = vtable.array
    nrows = len(arr)
    if nrows < 1 or nrows > MAX_TABLE_ROWS:
        raise _invalid(f"VOTable 行数须在 1 至 {MAX_TABLE_ROWS} 之间（当前 {nrows} 行）。")
    field_names = _validate_col_names(
        [str(f.name or f.ID or f"col_{i + 1}") for i, f in enumerate(vtable.fields)]
    )
    col_values: list[list[str | None]] = []
    col_metas: list[TableColumnMeta] = []
    for idx, field in enumerate(vtable.fields):
        key = field.ID or field.name
        raw_col = arr[key]
        vals = [_format_cell(item) for item in raw_col]
        col_values.append(vals)
        col_metas.append(
            _infer_column_meta(
                field_names[idx],
                vals,
                dtype_hint=str(field.datatype or "string"),
                unit=str(field.unit) if field.unit else None,
                ucd=str(field.ucd) if field.ucd else None,
                description=str(field.description) if field.description else None,
            )
        )
    rows = [[col_values[c][r] for c in range(len(col_metas))] for r in range(nrows)]
    if not allow_wide:
        col_metas, rows = _subset_columns(col_metas, rows, selected_columns)
    extra_warns = [str(w.message)[:200] for w in caught[:2]]
    return ParsedTable(
        columns=col_metas,
        rows=rows,
        format="votable",
        coordinate_frame=frame,
        ref_epoch=epoch,
        header_meta={},
        warnings=[*extra_warns, *SCIENTIFIC_BOUNDARY_WARNINGS],
    )


def _parse_ecsv_bytes(
    raw: bytes,
    *,
    selected_columns: list[str] | None,
    allow_wide: bool,
) -> ParsedTable:
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise _invalid("ECSV 文件必须为 UTF-8 编码。") from exc
    if "\x00" in text or _UNSAFE_YAML_TAG_RE.search(text):
        raise _invalid("ECSV 文件包含非法控制字符或不安全 YAML 标签。")
    try:
        table = astro_ascii.read(text.splitlines(), format="ecsv", guess=False)
    except Exception as exc:
        raise _invalid("无法解析 ECSV 文件，请核对 ECSV 表头与数据格式。") from exc
    nrows = len(table)
    if nrows < 1 or nrows > MAX_TABLE_ROWS:
        raise _invalid(f"ECSV 行数须在 1 至 {MAX_TABLE_ROWS} 之间（当前 {nrows} 行）。")
    names = _validate_col_names(list(table.colnames))
    col_values: list[list[str | None]] = []
    col_metas: list[TableColumnMeta] = []
    for col_name in names:
        col = table[col_name]
        vals = [_format_cell(v) for v in col]
        col_values.append(vals)
        unit = str(col.unit) if getattr(col, "unit", None) else None
        desc = getattr(col, "description", None)
        col_metas.append(
            _infer_column_meta(
                col_name,
                vals,
                dtype_hint=str(col.dtype),
                unit=unit,
                description=str(desc) if desc else None,
            )
        )
    rows = [[col_values[c][r] for c in range(len(col_metas))] for r in range(nrows)]
    if not allow_wide:
        col_metas, rows = _subset_columns(col_metas, rows, selected_columns)
    meta_dict = {
        str(k): str(v)[:160]
        for k, v in (table.meta or {}).items()
        if isinstance(k, str) and isinstance(v, (str, int, float)) and k != _CANONICAL_META_KEY
    }
    return ParsedTable(
        columns=col_metas,
        rows=rows,
        format="ecsv",
        coordinate_frame=meta_dict.get("RADESYS") or meta_dict.get("coordinate_frame"),
        ref_epoch=meta_dict.get("REF_EPOCH") or meta_dict.get("ref_epoch"),
        header_meta=meta_dict,
        warnings=list(SCIENTIFIC_BOUNDARY_WARNINGS),
    )


def _parse_delimited_bytes(
    raw: bytes,
    fmt: Literal["csv", "tsv"],
    *,
    selected_columns: list[str] | None,
    allow_wide: bool,
) -> ParsedTable:
    try:
        text = raw.decode("utf-8-sig")
        if "\x00" in text:
            raise ValueError("NUL")
        reader = csv.reader(
            io.StringIO(text, newline=""),
            delimiter="\t" if fmt == "tsv" else ",",
            strict=True,
        )
        header = _validate_col_names(next(reader))
        if not header:
            raise ValueError("Empty header")
        rows: list[list[str | None]] = []
        for row in reader:
            if len(row) != len(header):
                raise _invalid("数据行列数与表头不一致。")
            cleaned_row: list[str | None] = []
            for cell in row:
                if len(cell) > MAX_CELL_CHARS:
                    raise _invalid(f"单元格内容超过 {MAX_CELL_CHARS} 字符上限。")
                trimmed = cell.strip()
                cleaned_row.append(trimmed if trimmed != "" else None)
            rows.append(cleaned_row)
            if len(rows) > MAX_TABLE_ROWS:
                raise _invalid(f"数据表最多支持 {MAX_TABLE_ROWS} 行，未截断导入。")
        if not rows:
            raise _invalid("数据表至少需要一行数据。")
    except ServiceError:
        raise
    except (UnicodeError, csv.Error, StopIteration, ValueError) as exc:
        raise _invalid("无法完整解析 UTF-8 CSV/TSV 数据表，请检查编码、引号和分隔符。") from exc
    col_metas = [
        _infer_column_meta(header[idx], [row[idx] for row in rows]) for idx in range(len(header))
    ]
    if not allow_wide:
        col_metas, rows = _subset_columns(col_metas, rows, selected_columns)
    return ParsedTable(
        columns=col_metas,
        rows=rows,
        format=fmt,
        warnings=list(SCIENTIFIC_BOUNDARY_WARNINGS),
    )


def encode_canonical_ecsv_gz(table: ParsedTable) -> tuple[bytes, bytes, str]:
    """将 ParsedTable 编码为 gzip 压缩的规范化 ECSV 字节流，确保 64 位标识符与单位 100% 保真。"""
    if not 1 <= len(table.rows) <= MAX_TABLE_ROWS:
        raise _invalid(f"数据表行数须在 1 至 {MAX_TABLE_ROWS} 之间。")
    if not 1 <= len(table.columns) <= MAX_TABLE_COLUMNS:
        raise _invalid(f"数据表列数须在 1 至 {MAX_TABLE_COLUMNS} 之间。")

    astropy_table = Table()
    for col_idx, col_meta in enumerate(table.columns):
        raw_vals = [row[col_idx] for row in table.rows]
        mask = [v is None or v == "" for v in raw_vals]
        str_vals = ["" if m else str(v) for m, v in zip(mask, raw_vals, strict=True)]
        mcol = MaskedColumn(str_vals, name=col_meta.name, mask=mask, dtype=str)
        if col_meta.unit:
            try:
                mcol.unit = u.Unit(col_meta.unit)
            except Exception:
                pass
        if col_meta.description:
            mcol.description = col_meta.description
        astropy_table[col_meta.name] = mcol

    astropy_table.meta[_CANONICAL_META_KEY] = {
        "format": table.format,
        "coordinate_frame": table.coordinate_frame,
        "ref_epoch": table.ref_epoch,
        "header_meta": table.header_meta or {},
        "columns": [c.model_dump(mode="json") for c in table.columns],
    }

    stream = io.StringIO(newline="")
    astro_ascii.write(astropy_table, stream, format="ecsv")
    ecsv_bytes = stream.getvalue().encode("utf-8")
    gz_bytes = gzip.compress(ecsv_bytes, compresslevel=6, mtime=0)
    if len(gz_bytes) > MAX_TABLE_GZ_BYTES:
        raise ServiceError(
            413,
            "table_storage_size_limit",
            "规范化数据表压缩后超过 8 MiB 存储上限，请先筛选列或行数。",
        )
    return ecsv_bytes, gz_bytes, sha256_hex(ecsv_bytes)


def decode_canonical_ecsv_gz(data_gz: bytes) -> ParsedTable:
    raw = gzip.decompress(data_gz).decode("utf-8")
    astropy_table = astro_ascii.read(raw.splitlines(), format="ecsv", guess=False)
    meta_block = (astropy_table.meta or {}).get(_CANONICAL_META_KEY) or {}
    saved_cols = meta_block.get("columns") or []
    col_metas: list[TableColumnMeta] = []
    if len(saved_cols) == len(astropy_table.colnames):
        for item in saved_cols:
            col_metas.append(TableColumnMeta.model_validate(item))
    else:
        for name in astropy_table.colnames:
            col = astropy_table[name]
            vals = [None if np.ma.is_masked(v) or str(v) == "" else str(v) for v in col]
            col_metas.append(
                _infer_column_meta(
                    name,
                    vals,
                    unit=str(col.unit) if getattr(col, "unit", None) else None,
                    description=getattr(col, "description", None),
                )
            )
    nrows = len(astropy_table)
    cols_data: list[list[str | None]] = []
    for name in astropy_table.colnames:
        col = astropy_table[name]
        cols_data.append([None if np.ma.is_masked(v) or str(v) == "" else str(v) for v in col])
    rows = [[cols_data[c][r] for c in range(len(col_metas))] for r in range(nrows)]
    return ParsedTable(
        columns=col_metas,
        rows=rows,
        format=meta_block.get("format", "ecsv"),
        coordinate_frame=meta_block.get("coordinate_frame"),
        ref_epoch=meta_block.get("ref_epoch"),
        header_meta=meta_block.get("header_meta") or {},
        warnings=list(SCIENTIFIC_BOUNDARY_WARNINGS),
    )


def table_to_csv_bytes(table: ParsedTable) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, lineterminator="\n")
    writer.writerow([col.name for col in table.columns])
    for row in table.rows:
        writer.writerow(["" if cell is None else cell for cell in row])
    return stream.getvalue().encode("utf-8")


def _fits_ascii(text: str | None) -> str:
    return "".join(ch for ch in (text or "") if 32 <= ord(ch) <= 126).strip()[:68]


def export_table_bytes(
    table: ParsedTable,
    fmt: Literal["csv", "ecsv", "fits"],
) -> tuple[bytes, str, str]:
    if fmt == "csv":
        return table_to_csv_bytes(table), "text/csv; charset=utf-8", "csv"
    if fmt == "ecsv":
        ecsv_bytes, _, _ = encode_canonical_ecsv_gz(table)
        return ecsv_bytes, "text/plain; charset=utf-8", "ecsv"
    if fmt == "fits":
        fits_cols: list[fits.Column] = []
        for idx, col_meta in enumerate(table.columns):
            raw_vals = [row[idx] for row in table.rows]
            col_unit = col_meta.unit if col_meta.unit and col_meta.unit.isascii() else None
            if col_meta.kind == "number":
                arr = np.array(
                    [np.nan if v is None else float(v) for v in raw_vals], dtype=np.float64
                )
                fits_cols.append(
                    fits.Column(name=col_meta.name, format="D", array=arr, unit=col_unit)
                )
            elif col_meta.kind == "integer":
                has_null = any(v is None for v in raw_vals)
                if has_null:
                    arr = np.array(
                        [-9223372036854775808 if v is None else int(v) for v in raw_vals],
                        dtype=np.int64,
                    )
                    fits_cols.append(
                        fits.Column(
                            name=col_meta.name,
                            format="K",
                            null=-9223372036854775808,
                            array=arr,
                            unit=col_unit,
                        )
                    )
                else:
                    arr = np.array([int(v) for v in raw_vals], dtype=np.int64)
                    fits_cols.append(
                        fits.Column(name=col_meta.name, format="K", array=arr, unit=col_unit)
                    )
            elif col_meta.kind == "boolean":
                arr = np.array([v == "true" for v in raw_vals], dtype=bool)
                fits_cols.append(fits.Column(name=col_meta.name, format="L", array=arr))
            else:
                str_vals = ["" if v is None else v for v in raw_vals]
                encoded = [s.encode("utf-8")[:MAX_CELL_CHARS] for s in str_vals]
                max_len = max(1, max((len(b) for b in encoded), default=1))
                fits_cols.append(
                    fits.Column(
                        name=col_meta.name,
                        format=f"A{max_len}",
                        array=np.array(encoded, dtype=f"S{max_len}"),
                        unit=col_unit,
                    )
                )
        hdu = fits.BinTableHDU.from_columns(fits_cols)
        radesys = _fits_ascii(table.coordinate_frame)
        if radesys:
            hdu.header["RADESYS"] = radesys
        ref_epoch = _fits_ascii(table.ref_epoch)
        if ref_epoch:
            hdu.header["REF_EPOCH"] = ref_epoch
        for idx, col_meta in enumerate(table.columns, start=1):
            tcomm = _fits_ascii(col_meta.description)
            if tcomm:
                hdu.header[f"TCOMM{idx}"] = tcomm
        buf = io.BytesIO()
        fits.HDUList([fits.PrimaryHDU(), hdu]).writeto(buf)
        return buf.getvalue(), "application/fits", "fits"
    raise _invalid("不支持的数据表导出格式。")


def summarize_astro_table_attachment(raw: bytes, filename: str) -> tuple[str, list[str]]:
    """Parse FITS/VOTable/ECSV offline and produce a bounded text summary (never raw binary)."""
    info = inspect_table_bytes(raw, filename)
    lines = [
        f"[天文数据表结构摘要：{info.filename}]",
        f"格式：{info.format.upper()} · 文件大小：{info.size_bytes} 字节 · SHA-256：{info.sha256}",
    ]
    if info.coordinate_frame or info.ref_epoch:
        lines.append(
            f"坐标系/参考历元：{info.coordinate_frame or '未知'} / {info.ref_epoch or '未知'}"
        )
    if info.header_meta:
        meta_items = [f"{k}={v}" for k, v in list(info.header_meta.items())[:8]]
        lines.append("观测头信息：" + "，".join(meta_items))
    lines.append(f"HDU / 表数量：{len(info.hdus)}")
    for hdu in info.hdus[:6]:
        status_note = "可选" if hdu.selectable else f"不可选（{hdu.reason or '非表格'}）"
        lines.append(
            f"- #{hdu.index} {hdu.name} [{hdu.kind}]："
            f"{hdu.rows} 行 × {len(hdu.columns)} 列（{status_note}）"
        )
    if info.default_hdu_index is not None:
        target = next(h for h in info.hdus if h.index == info.default_hdu_index)
        lines.append("默认数据表列结构（前 24 列）：")
        for col in target.columns[:24]:
            unit_str = f" [{col.unit}]" if col.unit else ""
            desc_str = f" — {col.description}" if col.description else ""
            lines.append(f"  * {col.name} ({col.kind}/{col.dtype}){unit_str}{desc_str}")
        if len(target.columns) > 24:
            lines.append(f"  … 其余 {len(target.columns) - 24} 列已省略")
        try:
            parsed = parse_table_bytes(
                raw,
                filename,
                hdu_index=info.default_hdu_index,
                selected_columns=[c.name for c in target.columns[:12]]
                if len(target.columns) > MAX_TABLE_COLUMNS
                else None,
            )
            sample_cols = [c.name for c in parsed.columns[:10]]
            lines.append("前 8 行预览（部分列）：" + " | ".join(sample_cols))
            for row in parsed.rows[:8]:
                lines.append(
                    "  " + " | ".join(cell if cell is not None else "—" for cell in row[:10])
                )
        except ServiceError:
            pass
    lines.append(
        "提示：已上传的数据表附件发送后会自动同步至当前项目数据表，可直接在对话中要求筛选、坐标变换、交叉匹配、拟合或绘图。"
    )
    return "\n".join(lines), list(info.warnings[:4])
