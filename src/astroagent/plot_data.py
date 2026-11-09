"""Bounded CSV/TSV ingestion; retain identifiers and original bytes."""

import csv
import hashlib
import io
import math
from decimal import Decimal, InvalidOperation

from astroagent.conversations import encode, utc_now
from astroagent.errors import ServiceError
from astroagent.plot_schemas import PlotDataset

MAX_DATA = 5 * 1024**2
MAX_ROWS = 10000
MAX_COLUMNS = 64
WARNINGS = [
    "图形只描述当前交付数据，不能据此认定星团成员或完整总体。",
    "未自动校正消光、视差零点或系统误差；负视差是测量值，不应默认删除。",
]


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def invalid(message):
    return ServiceError(422, "plot_dataset_invalid", message)


def table(raw, filename):
    if len(raw) > MAX_DATA:
        raise ServiceError(413, "plot_dataset_too_large", "数据文件超过5 MiB，未截断导入。")
    suffix = filename.rsplit(".", 1)[-1].lower()
    if suffix not in ("csv", "tsv"):
        raise invalid("仅支持UTF-8编码的CSV或TSV数据表。")
    try:
        text = raw.decode("utf-8-sig")
        if "\x00" in text:
            raise ValueError("NUL")
        reader = csv.reader(
            io.StringIO(text, newline=""), delimiter="\t" if suffix == "tsv" else ",", strict=True
        )
        header = next(reader)
        if not 1 <= len(header) <= MAX_COLUMNS or len(set(header)) != len(header):
            raise invalid("列名须唯一，列数应为1至64。")
        if any(not h.strip() or len(h) > 128 or any(ord(c) < 32 for c in h) for h in header):
            raise invalid("列名不能为空、包含控制字符或超过128字符。")
        rows = []
        for row in reader:
            if len(row) != len(header) or any(len(c) > 8192 for c in row):
                raise invalid("数据行列数不一致，或单元格超过8192字符。")
            rows.append(row)
            if len(rows) > MAX_ROWS:
                raise invalid("最多10000行，未截断导入。")
        if not rows:
            raise invalid("数据表至少需要一行数据。")
        return header, rows
    except (UnicodeError, csv.Error, StopIteration, ValueError) as exc:
        raise invalid("无法完整解析UTF-8数据表，请检查编码、引号和分隔符。") from exc


def canonical(header, rows):
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, lineterminator="\n")
    writer.writerow(header)
    writer.writerows(rows)
    return stream.getvalue().encode("utf-8")


def numeric(value):
    try:
        return Decimal(value).is_finite() and math.isfinite(float(value))
    except (InvalidOperation, ValueError, OverflowError):
        return False


def dataset(
    identifier, project_id, name, raw, header, rows, *, source="upload", provenance=None, units=None
):
    normalized = canonical(header, rows)
    if len(normalized) > MAX_DATA:
        raise ServiceError(413, "plot_dataset_too_large", "规范化数据超过5 MiB。")
    columns = []
    for i, label in enumerate(header):
        values = [row[i] for row in rows if row[i].strip()]
        identifier_column = label.lower() in {
            "id",
            "source_id",
            "bibcode",
            "identifier",
        } or label.lower().endswith("_id")
        long_integer = any(v.lstrip("+-").isdigit() and len(v.lstrip("+-")) > 15 for v in values)
        kind = (
            "empty"
            if not values
            else "identifier"
            if identifier_column or long_integer
            else "number"
            if all(numeric(v) for v in values)
            else "text"
        )
        columns.append(
            {
                "name": label,
                "kind": kind,
                "missing": len(rows) - len(values),
                "unit": (units or {}).get(label),
            }
        )
    info = PlotDataset(
        id=identifier,
        project_id=project_id,
        name=name[:128],
        created_at=utc_now(),
        source=source,
        source_sha256=digest(raw),
        data_sha256=digest(normalized),
        rows=len(rows),
        columns=columns,
        provenance=provenance or {"filename": name},
        warnings=[*WARNINGS, "所有列以原字符串保存；未知单位不会自动推断。"],
    )
    return info.model_dump(), normalized


def from_snapshot(identifier, project_id, snapshot, index):
    from astroagent.gaia import GAIA_UNITS

    results = snapshot["response"]["gaia_results"]
    if (
        type(index) is not int
        or not 0 <= index < len(results)
        or results[index]["status"] != "success"
    ):
        raise invalid("请选择一份成功的Gaia查询快照。")
    result = results[index]
    rows = result["data"]
    if not rows:
        raise invalid("该快照没有数据行。")
    # Use the complete API snapshot, never the model-visible ten-row sample.
    header = [k for k, v in rows[0].items() if not isinstance(v, (dict, list))]
    values = [["" if row.get(k) is None else str(row[k]) for k in header] for row in rows]
    raw = encode(snapshot).encode()
    info, data = dataset(
        identifier,
        project_id,
        snapshot["name"],
        raw,
        header,
        values,
        source="snapshot",
        units=GAIA_UNITS,
        provenance={
            "snapshot_id": snapshot["id"],
            "query_index": index,
            "query": result.get("query"),
            "source": result.get("source"),
            "returned_rows": len(rows),
            "has_more": result.get("has_more"),
            "truncated": result.get("truncated"),
            "pmra": "includes cos(dec)",
        },
    )
    return info, data, raw
