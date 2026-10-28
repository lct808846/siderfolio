"""Gaia 全交付样本的选行、分箱及无 GUI 绘图。"""

import math
import warnings
from io import BytesIO

import matplotlib as mpl
import numpy as np
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure
from matplotlib.ticker import MaxNLocator

STYLE_VERSION = "1"
FIELDS = {
    "proper_motion": ["pmra", "pmdec"],
    "parallax_histogram": ["parallax"],
    "observed_cmd": ["bp_rp", "phot_g_mean_mag"],
}
LABELS = {
    "proper_motion": ("Proper motion", "pmra (mas/yr; includes cos(dec))", "pmdec (mas/yr)"),
    "parallax_histogram": ("Parallax histogram", "parallax (mas)", "Returned row count"),
    "observed_cmd": ("Observed colour-magnitude diagram", "BP - RP (mag)", "G (mag; apparent)"),
}


def axis_limits(values):
    low, high = float(min(values)), float(max(values))
    span = high - low
    pad = span * 0.07 if span else max(abs(low) * 0.05, 0.5)
    limits = [low - pad, high + pad]
    width = limits[1] - limits[0]
    if (
        not all(math.isfinite(v) for v in (*limits, width))
        or width <= 0
        or not math.isfinite(1 / width)
    ):
        raise ValueError("Unrepresentable axis range")
    return limits


def prepare_plot(result, spec):
    record = {
        **spec.model_dump(),
        "status": "skipped",
        "reason": None,
        "fields": FIELDS[spec.kind],
        "delivered_count": len(result.data),
        "valid_count": 0,
        "skipped_count": 0,
        "included_source_ids": [],
        "excluded_rows": [],
        "coordinates": [],
        "parameters": {
            "pixels": [1200, 900],
            "dpi": 150,
            "style_version": STYLE_VERSION,
            "font": "DejaVu Sans",
            "returned_rows_only": True,
            "truncated": result.truncated,
            "archive_overflow": result.archive_overflow,
            "quality_filters": {
                k: v
                for k, v in result.query.items()
                if k in {"ruwe_max", "parallax_snr_min"} and v is not None
            },
        },
        "output_path": None,
    }
    if result.status != "success":
        record["reason"] = "query_not_successful"
        return record
    for row in result.data:
        values = [getattr(row, field) for field in record["fields"]]
        missing = [f for f, v in zip(record["fields"], values, strict=True) if v is None]
        nonfinite = [
            f
            for f, v in zip(record["fields"], values, strict=True)
            if v is not None and not math.isfinite(v)
        ]
        if missing or nonfinite:
            record["excluded_rows"].append(
                {
                    "source_id": row.source_id,
                    "reason": "missing_measurement" if missing else "non_finite_measurement",
                    "fields": missing or nonfinite,
                }
            )
        else:
            record["included_source_ids"].append(row.source_id)
            record["coordinates"].append(values)
    n = record["valid_count"] = len(record["coordinates"])
    record["skipped_count"] = len(record["excluded_rows"])
    if n < (2 if spec.kind == "parallax_histogram" else 1):
        record["reason"] = "insufficient_data"
        return record
    try:
        x = [v[0] for v in record["coordinates"]]
        params = record["parameters"]
        if spec.kind == "parallax_histogram":
            low, high = min(x), max(x)
            if low == high:
                edges = np.array([low - 0.5, high + 0.5])
            else:
                if not math.isfinite(high - low):
                    raise ValueError("Unrepresentable bins")
                edges = np.linspace(low, high, min(10, math.ceil(math.sqrt(n))) + 1)
            if not np.all(np.isfinite(edges)) or not np.all(np.diff(edges) > 0):
                raise ValueError("Unrepresentable bins")
            limits = axis_limits([*edges, 0.0])
            if not all(math.isfinite(1 / float(width)) for width in np.diff(edges)):
                raise ValueError("Unrepresentable bin width")
            counts, _ = np.histogram(x, bins=edges)
            if int(sum(counts)) != n:
                raise ValueError("Incomplete histogram")
            params.update(
                bin_edges=edges.tolist(),
                bin_counts=counts.tolist(),
                density=False,
                x_limits=limits,
                y_limits=[0, max(counts).item() * 1.15],
                zero_reference=True,
            )
        else:
            params.update(
                x_limits=axis_limits(x),
                y_limits=axis_limits([v[1] for v in record["coordinates"]]),
                aspect="equal" if spec.kind == "proper_motion" else "auto",
                y_inverted=spec.kind == "observed_cmd",
            )
    except (ValueError, OverflowError, FloatingPointError):
        record["reason"] = "unrepresentable_range"
        return record
    record["status"] = "ready"
    return record


def render_plot(record):
    """调用方持有进程导出锁；绘图样式不接受客户端覆盖。"""
    figure = None
    with (
        mpl.rc_context(
            {
                **mpl.rcParamsDefault,
                "font.family": "DejaVu Sans",
                "font.size": 11,
                "text.usetex": False,
                "axes.formatter.useoffset": False,
            }
        ),
        warnings.catch_warnings(),
        np.errstate(all="raise"),
    ):
        warnings.simplefilter("error", RuntimeWarning)
        try:
            figure = Figure(figsize=(8, 6), dpi=150, facecolor="white")
            canvas = FigureCanvasAgg(figure)
            ax = figure.subplots()
            figure.subplots_adjust(left=0.16, right=0.95, bottom=0.14, top=0.80)
            kind, params = record["kind"], record["parameters"]
            coords = record["coordinates"]
            if kind == "parallax_histogram":
                ax.stairs(params["bin_counts"], params["bin_edges"], fill=True, color="#28699c")
                ax.axvline(0, color="#bb4433", linestyle="--", linewidth=1)
                ax.yaxis.set_major_locator(MaxNLocator(integer=True))
            else:
                ax.scatter([v[0] for v in coords], [v[1] for v in coords], s=23, color="#28699c")
                ax.set_aspect(params["aspect"], adjustable="box")
            ax.set_xlim(params["x_limits"])
            ax.set_ylim(params["y_limits"])
            if params.get("y_inverted"):
                ax.invert_yaxis()
            title, xlabel, ylabel = LABELS[kind]
            ax.set_xlabel(xlabel)
            ax.set_ylabel(ylabel)
            ax.grid(alpha=0.2)
            figure.suptitle(title, y=0.96, fontsize=14)
            figure.text(
                0.5,
                0.88,
                (
                    f"Gaia result {record['gaia_result_index']} | "
                    f"{record['valid_count']}/{record['delivered_count']} | returned rows only"
                ),
                ha="center",
            )
            if params["truncated"] or params["archive_overflow"]:
                flags = [
                    label
                    for key, label in (
                        ("truncated", "TRUNCATED"),
                        ("archive_overflow", "ARCHIVE OVERFLOW"),
                    )
                    if params[key]
                ]
                figure.text(0.5, 0.83, " / ".join(flags), ha="center", color="#bb3322")
            with BytesIO() as buffer:
                canvas.print_png(buffer, metadata={"Software": "AstroAgent"})
                return buffer.getvalue()
        finally:
            if figure is not None:
                figure.clear()
