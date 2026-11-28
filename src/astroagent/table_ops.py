"""确定性天文数据表算子（Astropy / NumPy / SciPy）：严禁 eval/exec 或模型口算。"""

from __future__ import annotations

import ast
import importlib.metadata
import math
import operator as py_op
from dataclasses import dataclass
from typing import Any

import numpy as np
from astropy import units as u
from astropy.coordinates import SkyCoord, match_coordinates_sky, search_around_sky
from scipy import optimize, stats

from astroagent import __version__
from astroagent.errors import ServiceError
from astroagent.table_io import SCIENTIFIC_BOUNDARY_WARNINGS, ParsedTable, _infer_column_meta
from astroagent.table_schemas import (
    MAX_CROSSMATCH_CANDIDATES_PER_ROW,
    MAX_TABLE_COLUMNS,
    MAX_TABLE_ROWS,
    CoordFrame,
    CoordinatesOperatorRequest,
    CoordUnit,
    CrossmatchOperatorRequest,
    FilterCondition,
    FilterDeriveOperatorRequest,
    FitOperatorRequest,
    StatsOperatorRequest,
    TableColumnMeta,
)

_ALLOWED_FUNCS: dict[str, Any] = {
    "abs": np.abs,
    "sqrt": np.sqrt,
    "log10": np.log10,
    "ln": np.log,
    "exp": np.exp,
    "sin": np.sin,
    "cos": np.cos,
    "tan": np.tan,
    "hypot": np.hypot,
    "pow": np.power,
}
_BIN_OPS = {
    ast.Add: py_op.add,
    ast.Sub: py_op.sub,
    ast.Mult: py_op.mul,
    ast.Div: py_op.truediv,
    ast.Pow: py_op.pow,
}
_UNARY_OPS = {
    ast.UAdd: py_op.pos,
    ast.USub: py_op.neg,
}


@dataclass(slots=True)
class OperatorOutcome:
    summary: dict[str, Any]
    warnings: list[str]
    derived_table: ParsedTable | None = None
    software: dict[str, str] | None = None


def scientific_software_versions() -> dict[str, str]:
    versions = {"astroagent": __version__}
    for pkg in ("astropy", "numpy", "scipy", "defusedxml"):
        try:
            versions[pkg] = importlib.metadata.version(pkg)
        except importlib.metadata.PackageNotFoundError:
            versions[pkg] = "unavailable"
    return versions


def _op_error(message: str, code: str = "table_operator_invalid") -> ServiceError:
    return ServiceError(422, code, message)


def _col_index_map(table: ParsedTable) -> dict[str, int]:
    return {col.name: idx for idx, col in enumerate(table.columns)}


def _to_float_array(table: ParsedTable, col_name: str) -> np.ndarray:
    idx_map = _col_index_map(table)
    if col_name not in idx_map:
        raise _op_error(f"数据表中不存在列「{col_name}」。")
    col_idx = idx_map[col_name]
    col_meta = table.columns[col_idx]
    if col_meta.kind == "identifier":
        raise _op_error(f"列「{col_name}」为标识符列，不能直接作为数值列运算。")
    out = np.full(len(table.rows), np.nan, dtype=np.float64)
    for r_idx, row in enumerate(table.rows):
        raw = row[col_idx]
        if raw is None or raw == "":
            continue
        try:
            val = float(raw)
        except (ValueError, OverflowError):
            continue
        if math.isfinite(val):
            out[r_idx] = val
    return out


def _col_values_raw(table: ParsedTable, col_name: str) -> list[str | None]:
    idx_map = _col_index_map(table)
    if col_name not in idx_map:
        raise _op_error(f"数据表中不存在列「{col_name}」。")
    col_idx = idx_map[col_name]
    return [row[col_idx] for row in table.rows]


def _format_float(val: float | None) -> str | None:
    if val is None or not math.isfinite(val):
        return None
    return repr(float(val))


def run_stats(
    table: ParsedTable,
    req: StatsOperatorRequest,
    *,
    other_table: ParsedTable | None = None,
) -> OperatorOutcome:
    idx_map = _col_index_map(table)
    warnings_list = list(SCIENTIFIC_BOUNDARY_WARNINGS)
    column_stats: dict[str, Any] = {}
    for col_name in req.columns:
        if col_name not in idx_map:
            raise _op_error(f"统计列「{col_name}」不存在。")
        arr = _to_float_array(table, col_name)
        valid = arr[np.isfinite(arr)]
        total = len(arr)
        valid_n = int(len(valid))
        missing_n = total - valid_n
        unit = table.columns[idx_map[col_name]].unit
        if valid_n == 0:
            column_stats[col_name] = {
                "total": total,
                "valid": 0,
                "missing": missing_n,
                "unit": unit,
                "mean": None,
                "std": None,
                "min": None,
                "p05": None,
                "p25": None,
                "median": None,
                "p75": None,
                "p95": None,
                "iqr": None,
                "max": None,
            }
            continue
        p05, p25, p50, p75, p95 = np.percentile(valid, [5, 25, 50, 75, 95])
        column_stats[col_name] = {
            "total": total,
            "valid": valid_n,
            "missing": missing_n,
            "unit": unit,
            "mean": float(np.mean(valid)),
            "std": float(np.std(valid, ddof=1)) if valid_n > 1 else 0.0,
            "min": float(np.min(valid)),
            "p05": float(p05),
            "p25": float(p25),
            "median": float(p50),
            "p75": float(p75),
            "p95": float(p95),
            "iqr": float(p75 - p25),
            "max": float(np.max(valid)),
        }

    correlation: dict[str, Any] | None = None
    if req.corr_x and req.corr_y:
        x_arr = _to_float_array(table, req.corr_x)
        y_arr = _to_float_array(table, req.corr_y)
        mask = np.isfinite(x_arr) & np.isfinite(y_arr)
        n_valid = int(np.sum(mask))
        if n_valid < 3:
            raise _op_error("双列相关性检验至少需要 3 对同时有限的观测值。")
        xv = x_arr[mask]
        yv = y_arr[mask]
        if np.std(xv) == 0 or np.std(yv) == 0:
            raise _op_error("所选相关性列存在零方差常数列，无法计算相关系数。")
        pr, pp = stats.pearsonr(xv, yv)
        sr, sp = stats.spearmanr(xv, yv)
        correlation = {
            "x_col": req.corr_x,
            "y_col": req.corr_y,
            "valid_pairs": n_valid,
            "skipped_rows": len(table.rows) - n_valid,
            "pearson_r": float(pr),
            "pearson_p": float(pp),
            "spearman_rho": float(sr),
            "spearman_p": float(sp),
        }

    ks_test: dict[str, Any] | None = None
    if req.ks_column:
        sample_a: np.ndarray
        sample_b: np.ndarray
        mode_desc: str
        if other_table is not None:
            a_all = _to_float_array(table, req.ks_column)
            b_all = _to_float_array(other_table, req.ks_column)
            sample_a = a_all[np.isfinite(a_all)]
            sample_b = b_all[np.isfinite(b_all)]
            mode_desc = "cross_table"
        elif req.ks_group_column:
            vals_target = _to_float_array(table, req.ks_column)
            group_vals = _col_values_raw(table, req.ks_group_column)
            mask_a = np.array([g == req.ks_group_a for g in group_vals], dtype=bool) & np.isfinite(
                vals_target
            )
            mask_b = np.array([g == req.ks_group_b for g in group_vals], dtype=bool) & np.isfinite(
                vals_target
            )
            sample_a = vals_target[mask_a]
            sample_b = vals_target[mask_b]
            mode_desc = "within_table_groups"
        else:
            raise _op_error("KS 检验需要指定对比数据表或同表分组列。")
        if len(sample_a) < 2 or len(sample_b) < 2:
            raise _op_error("双样本 KS 检验每侧至少需要 2 个有限数值。")
        res = stats.ks_2samp(sample_a, sample_b)
        ks_test = {
            "mode": mode_desc,
            "column": req.ks_column,
            "n_a": int(len(sample_a)),
            "n_b": int(len(sample_b)),
            "statistic_d": float(res.statistic),
            "p_value": float(res.pvalue),
        }

    return OperatorOutcome(
        summary={
            "row_count": len(table.rows),
            "column_stats": column_stats,
            "correlation": correlation,
            "ks_test": ks_test,
        },
        warnings=warnings_list,
        software=scientific_software_versions(),
    )


def _eval_ast_expression(
    expr: str,
    env: dict[str, np.ndarray],
) -> tuple[np.ndarray, set[str]]:
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError as exc:
        raise _op_error(f"派生列表达式语法无效：{expr}") from exc

    referenced: set[str] = set()
    node_count = 0

    def visit(node: ast.AST, depth: int) -> Any:
        nonlocal node_count
        node_count += 1
        if node_count > 64 or depth > 16:
            raise _op_error("派生列表达式复杂度超过安全限制。")
        if isinstance(node, ast.Expression):
            return visit(node.body, depth + 1)
        if isinstance(node, ast.Constant):
            if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
                raise _op_error("派生列表达式仅允许实数常量。")
            val = float(node.value)
            if not math.isfinite(val):
                raise _op_error("派生列表达式不能包含 NaN 或 Inf。")
            return np.float64(val)
        if isinstance(node, ast.Name):
            if node.id not in env:
                raise _op_error(f"派生列表达式引用了不存在或非数值列：{node.id}")
            referenced.add(node.id)
            return env[node.id]
        if isinstance(node, ast.UnaryOp):
            op_fn = _UNARY_OPS.get(type(node.op))
            if op_fn is None:
                raise _op_error("派生列表达式仅支持正负号一元运算。")
            return op_fn(visit(node.operand, depth + 1))
        if isinstance(node, ast.BinOp):
            op_fn = _BIN_OPS.get(type(node.op))
            if op_fn is None:
                raise _op_error("派生列表达式仅支持 + - * / ** 四则与幂运算。")
            left = visit(node.left, depth + 1)
            right = visit(node.right, depth + 1)
            with np.errstate(divide="ignore", invalid="ignore", over="ignore"):
                return op_fn(left, right)
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name) or node.func.id not in _ALLOWED_FUNCS:
                raise _op_error("派生列表达式包含未授权的函数调用。")
            if node.keywords:
                raise _op_error("派生列表达式函数不支持关键字参数。")
            args = [visit(arg, depth + 1) for arg in node.args]
            fn = _ALLOWED_FUNCS[node.func.id]
            expected_n = 2 if node.func.id in ("hypot", "pow") else 1
            if len(args) != expected_n:
                raise _op_error(f"函数 {node.func.id} 需要 {expected_n} 个参数。")
            with np.errstate(divide="ignore", invalid="ignore", over="ignore"):
                return fn(*args)
        raise _op_error("派生列表达式包含不允许的语法结构。")

    result = visit(tree, 0)
    arr = np.broadcast_to(
        np.asarray(result, dtype=np.float64), (len(next(iter(env.values()))) if env else 0,)
    )
    return np.array(arr, dtype=np.float64), referenced


def _eval_condition(
    table: ParsedTable,
    cond: FilterCondition,
    float_cache: dict[str, np.ndarray],
) -> np.ndarray:
    nrows = len(table.rows)
    raw_vals = _col_values_raw(table, cond.column)

    def get_float(col_name: str) -> np.ndarray:
        if col_name not in float_cache:
            float_cache[col_name] = _to_float_array(table, col_name)
        return float_cache[col_name]

    op = cond.op
    if op == "is_null":
        return np.array([v is None or v == "" for v in raw_vals], dtype=bool)
    if op == "not_null":
        return np.array([v is not None and v != "" for v in raw_vals], dtype=bool)
    if op == "contains":
        needle = str(cond.value or "").lower()
        return np.array([v is not None and needle in v.lower() for v in raw_vals], dtype=bool)
    if op == "in":
        allowed = {str(item) for item in (cond.values or [])}
        return np.array([v is not None and v in allowed for v in raw_vals], dtype=bool)
    if op in ("eq", "ne") and isinstance(cond.value, (str, bool)):
        target = (
            "true" if cond.value is True else "false" if cond.value is False else str(cond.value)
        )
        mask = np.array([v is not None and v == target for v in raw_vals], dtype=bool)
        return mask if op == "eq" else ~mask

    lhs = get_float(cond.column)
    if op.startswith(("ratio_", "diff_")):
        assert cond.rhs_column is not None
        rhs = get_float(cond.rhs_column)
        thresh = float(cond.value)  # type: ignore[arg-type]
        if op.startswith("ratio_"):
            valid = np.isfinite(lhs) & np.isfinite(rhs) & (rhs != 0)
            metric = np.full(nrows, np.nan, dtype=np.float64)
            metric[valid] = lhs[valid] / rhs[valid]
        else:
            valid = np.isfinite(lhs) & np.isfinite(rhs)
            metric = np.full(nrows, np.nan, dtype=np.float64)
            metric[valid] = lhs[valid] - rhs[valid]
        cmp_op = op.split("_", 1)[1]
        return _compare_numeric(metric, cmp_op, thresh)

    if op == "between":
        lo = float(cond.value)  # type: ignore[arg-type]
        hi = float(cond.value_max)  # type: ignore[arg-type]
        if lo > hi:
            lo, hi = hi, lo
        return np.isfinite(lhs) & (lhs >= lo) & (lhs <= hi)

    try:
        thresh = float(cond.value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise _op_error(f"条件 {cond.column} {op} 需要有效数值阈值。") from exc
    return _compare_numeric(lhs, op, thresh)


def _compare_numeric(arr: np.ndarray, op: str, thresh: float) -> np.ndarray:
    finite = np.isfinite(arr)
    if op == "eq":
        return finite & (arr == thresh)
    if op == "ne":
        return finite & (arr != thresh)
    if op == "lt":
        return finite & (arr < thresh)
    if op == "le":
        return finite & (arr <= thresh)
    if op == "gt":
        return finite & (arr > thresh)
    if op == "ge":
        return finite & (arr >= thresh)
    raise _op_error(f"不支持的数值比较算子：{op}")


def run_filter_derive(table: ParsedTable, req: FilterDeriveOperatorRequest) -> OperatorOutcome:
    nrows = len(table.rows)
    warnings_list = list(SCIENTIFIC_BOUNDARY_WARNINGS)
    float_cache: dict[str, np.ndarray] = {}
    condition_reports: list[dict[str, Any]] = []

    if req.conditions:
        combined = (
            np.ones(nrows, dtype=bool) if req.combine == "and" else np.zeros(nrows, dtype=bool)
        )
        for cond in req.conditions:
            mask = _eval_condition(table, cond, float_cache)
            matched = int(np.sum(mask))
            condition_reports.append(
                {
                    "column": cond.column,
                    "op": cond.op,
                    "matched_rows": matched,
                    "excluded_rows": nrows - matched,
                }
            )
            combined = (combined & mask) if req.combine == "and" else (combined | mask)
    else:
        combined = np.ones(nrows, dtype=bool)

    kept_indices = np.flatnonzero(combined)
    if len(kept_indices) == 0:
        raise _op_error("筛选后剩余 0 行数据，无法生成有效结果表；请放宽筛选条件。")

    out_cols = list(table.columns)
    out_rows: list[list[str | None]] = [list(table.rows[i]) for i in kept_indices]

    if req.derived_columns:
        filtered_table = ParsedTable(columns=out_cols, rows=out_rows, format=table.format)
        env: dict[str, np.ndarray] = {}
        for col in out_cols:
            if col.kind in ("number", "integer", "empty"):
                env[col.name] = _to_float_array(filtered_table, col.name)
        existing_names = {c.name for c in out_cols}
        derived_summaries: list[dict[str, Any]] = []
        for spec in req.derived_columns:
            if spec.name in existing_names:
                raise _op_error(f"派生列名「{spec.name}」与现有列重名。")
            if len(out_cols) >= MAX_TABLE_COLUMNS:
                raise _op_error(f"列数已达 {MAX_TABLE_COLUMNS} 上限，无法继续添加派生列。")
            arr, used_cols = _eval_ast_expression(spec.expression, env)
            finite_mask = np.isfinite(arr)
            str_vals = [
                _format_float(float(v)) if ok else None
                for v, ok in zip(arr, finite_mask, strict=True)
            ]
            new_meta = TableColumnMeta(
                name=spec.name,
                kind="number" if int(np.sum(finite_mask)) > 0 else "empty",
                dtype="float64",
                unit=spec.unit,
                description=spec.description or f"派生列: {spec.expression}",
                missing=len(str_vals) - int(np.sum(finite_mask)),
            )
            out_cols.append(new_meta)
            existing_names.add(spec.name)
            env[spec.name] = np.where(finite_mask, arr, np.nan)
            for row_idx, cell in enumerate(str_vals):
                out_rows[row_idx].append(cell)
            if any("parallax" in col.lower() for col in used_cols):
                warnings_list.append(
                    "涉及视差的派生计算仅作近似，未校正视差零点、星际消光或系统误差。"
                )
            derived_summaries.append(
                {
                    "name": spec.name,
                    "expression": spec.expression,
                    "unit": spec.unit,
                    "valid_rows": int(np.sum(finite_mask)),
                    "null_rows": len(str_vals) - int(np.sum(finite_mask)),
                }
            )
    else:
        derived_summaries = []

    derived_table = ParsedTable(
        columns=out_cols,
        rows=out_rows,
        format=table.format,
        coordinate_frame=table.coordinate_frame,
        ref_epoch=table.ref_epoch,
        header_meta=table.header_meta,
        warnings=list(dict.fromkeys(warnings_list)),
    )
    return OperatorOutcome(
        summary={
            "input_rows": nrows,
            "output_rows": len(out_rows),
            "excluded_rows": nrows - len(out_rows),
            "combine": req.combine,
            "condition_reports": condition_reports,
            "derived_columns": derived_summaries,
        },
        warnings=list(dict.fromkeys(warnings_list)),
        derived_table=derived_table,
        software=scientific_software_versions(),
    )


def _build_skycoord(
    table: ParsedTable,
    lon_col: str,
    lat_col: str,
    frame: CoordFrame,
    unit_mode: CoordUnit,
) -> tuple[SkyCoord | None, np.ndarray]:
    lon_raw = _col_values_raw(table, lon_col)
    lat_raw = _col_values_raw(table, lat_col)
    nrows = len(table.rows)
    valid_indices: list[int] = []
    lons: list[Any] = []
    lats: list[Any] = []
    valid_mask = np.zeros(nrows, dtype=bool)

    for idx, (x_str, y_str) in enumerate(zip(lon_raw, lat_raw, strict=True)):
        if not x_str or not y_str:
            continue
        if unit_mode == "deg":
            try:
                xv = float(x_str)
                yv = float(y_str)
            except (ValueError, OverflowError):
                continue
            if not (math.isfinite(xv) and math.isfinite(yv)) or not (-90.0 <= yv <= 90.0):
                continue
            lons.append(xv)
            lats.append(yv)
            valid_indices.append(idx)
            valid_mask[idx] = True
        else:
            lons.append(x_str)
            lats.append(y_str)
            valid_indices.append(idx)
            valid_mask[idx] = True

    if not valid_indices:
        return None, valid_mask

    coord_unit = u.deg if unit_mode == "deg" else (u.hourangle, u.deg)
    try:
        coords = SkyCoord(lons, lats, frame=frame, unit=coord_unit)
    except Exception as exc:
        if unit_mode != "hourangle_deg":
            raise _op_error(
                f"坐标列 ({lon_col}, {lat_col}) 无法按 {frame}/{unit_mode} 解析为天球坐标。"
            ) from exc
        valid_mask[:] = False
        good_lons: list[Any] = []
        good_lats: list[Any] = []
        for orig_idx, x_str, y_str in zip(valid_indices, lons, lats, strict=True):
            try:
                SkyCoord(x_str, y_str, frame=frame, unit=coord_unit)
            except Exception:
                continue
            good_lons.append(x_str)
            good_lats.append(y_str)
            valid_mask[orig_idx] = True
        if not good_lons:
            return None, valid_mask
        try:
            coords = SkyCoord(good_lons, good_lats, frame=frame, unit=coord_unit)
        except Exception as inner_exc:
            raise _op_error(
                f"坐标列 ({lon_col}, {lat_col}) 无法按 {frame}/{unit_mode} 解析为天球坐标。"
            ) from inner_exc
    return coords, valid_mask


def run_coordinates(table: ParsedTable, req: CoordinatesOperatorRequest) -> OperatorOutcome:
    coords, valid_mask = _build_skycoord(
        table, req.lon_col, req.lat_col, req.input_frame, req.input_unit
    )
    if coords is None:
        raise _op_error("所选坐标列没有任何有效的有限天球坐标。")

    nrows = len(table.rows)
    valid_count = int(np.sum(valid_mask))
    out_cols = list(table.columns)
    existing_names = {c.name for c in out_cols}
    new_columns_data: list[tuple[TableColumnMeta, list[str | None]]] = []

    def add_numeric_col(name: str, values: np.ndarray, unit_str: str, desc: str) -> None:
        target_name = name if name not in existing_names else f"{name}_out"
        existing_names.add(target_name)
        col_vals: list[str | None] = [None] * nrows
        cursor = 0
        for r_idx in range(nrows):
            if valid_mask[r_idx]:
                val = float(values[cursor])
                col_vals[r_idx] = _format_float(val)
                cursor += 1
        meta = TableColumnMeta(
            name=target_name,
            kind="number",
            dtype="float64",
            unit=unit_str,
            description=desc,
            missing=nrows - valid_count,
        )
        new_columns_data.append((meta, col_vals))

    if req.output_frame is not None:
        if req.output_frame == "galactic":
            transformed = coords.galactic
            add_numeric_col("gal_l_deg", transformed.l.deg, "deg", "银经 Galactic l")
            add_numeric_col("gal_b_deg", transformed.b.deg, "deg", "银纬 Galactic b")
        elif req.output_frame == "icrs":
            transformed = coords.icrs
            add_numeric_col("ra_icrs_deg", transformed.ra.deg, "deg", "ICRS 赤经 RA")
            add_numeric_col("dec_icrs_deg", transformed.dec.deg, "deg", "ICRS 赤纬 Dec")
        elif req.output_frame == "fk5":
            transformed = coords.fk5
            add_numeric_col("ra_fk5_deg", transformed.ra.deg, "deg", "FK5 J2000 赤经")
            add_numeric_col("dec_fk5_deg", transformed.dec.deg, "deg", "FK5 J2000 赤纬")

    if req.ref_ra_deg is not None and req.ref_dec_deg is not None:
        ref_coord = SkyCoord(ra=req.ref_ra_deg * u.deg, dec=req.ref_dec_deg * u.deg, frame="icrs")
        icrs_coords = coords.icrs
        seps = icrs_coords.separation(ref_coord).arcsec
        pas = ref_coord.position_angle(icrs_coords).deg
        add_numeric_col("sep_ref_arcsec", seps, "arcsec", "到参考中心的球面角距")
        add_numeric_col("pa_ref_deg", pas, "deg", "相对参考中心的方位角 (East of North)")

    if len(out_cols) + len(new_columns_data) > MAX_TABLE_COLUMNS:
        raise _op_error(f"新增坐标列后总列数超过 {MAX_TABLE_COLUMNS} 上限。")

    out_rows = [list(r) for r in table.rows]
    added_names: list[str] = []
    for meta, vals in new_columns_data:
        out_cols.append(meta)
        added_names.append(meta.name)
        for r_idx, cell in enumerate(vals):
            out_rows[r_idx].append(cell)

    warnings_list = list(SCIENTIFIC_BOUNDARY_WARNINGS)
    if nrows - valid_count > 0:
        warnings_list.append(f"有 {nrows - valid_count} 行坐标缺失或无效，已原样保留行并置为空值。")

    derived_table = ParsedTable(
        columns=out_cols,
        rows=out_rows,
        format=table.format,
        coordinate_frame=req.output_frame.upper() if req.output_frame else table.coordinate_frame,
        ref_epoch=table.ref_epoch,
        header_meta=table.header_meta,
        warnings=list(dict.fromkeys(warnings_list)),
    )
    return OperatorOutcome(
        summary={
            "total_rows": nrows,
            "valid_coord_rows": valid_count,
            "invalid_coord_rows": nrows - valid_count,
            "input_frame": req.input_frame,
            "output_frame": req.output_frame,
            "added_columns": added_names,
        },
        warnings=list(dict.fromkeys(warnings_list)),
        derived_table=derived_table,
        software=scientific_software_versions(),
    )


def run_crossmatch(
    left_table: ParsedTable,
    right_table: ParsedTable,
    req: CrossmatchOperatorRequest,
) -> OperatorOutcome:
    left_coords, left_mask = _build_skycoord(
        left_table, req.left_ra_col, req.left_dec_col, req.left_frame, req.left_unit
    )
    right_coords, right_mask = _build_skycoord(
        right_table, req.right_ra_col, req.right_dec_col, req.right_frame, req.right_unit
    )
    if left_coords is None or right_coords is None:
        raise _op_error("左表或右表缺少有效的有限天球坐标，无法执行交叉匹配。")

    left_icrs = left_coords.icrs
    right_icrs = right_coords.icrs
    left_orig_idx = np.flatnonzero(left_mask)
    right_orig_idx = np.flatnonzero(right_mask)

    idx_l, idx_r, sep2d, _ = search_around_sky(left_icrs, right_icrs, req.radius_arcsec * u.arcsec)
    sep_arcsec_all = sep2d.arcsec

    candidates_by_left: dict[int, list[tuple[int, float]]] = {}
    for l_pos, r_pos, sep_val in zip(
        idx_l.tolist(), idx_r.tolist(), sep_arcsec_all.tolist(), strict=True
    ):
        candidates_by_left.setdefault(l_pos, []).append((r_pos, float(sep_val)))
    for cands in candidates_by_left.values():
        cands.sort(key=lambda pair: pair[1])

    next_sep_lookup: dict[int, float] = {}
    if len(right_icrs) >= 2:
        _, sep_2nd, _ = match_coordinates_sky(left_icrs, right_icrs, nthneighbor=2)
        for l_pos, sep_val in enumerate(sep_2nd.arcsec.tolist()):
            next_sep_lookup[l_pos] = float(sep_val)

    left_names = {c.name for c in left_table.columns}
    right_out_names: list[str] = []
    for col in right_table.columns:
        candidate_name = f"{req.right_prefix}{col.name}" if col.name in left_names else col.name
        while candidate_name in left_names or candidate_name in right_out_names:
            candidate_name = f"{req.right_prefix}{candidate_name}"
        right_out_names.append(candidate_name[:128])

    diag_names = ["match_sep_arcsec", "match_candidate_count", "match_next_sep_arcsec"]
    total_cols = len(left_table.columns) + len(right_out_names) + len(diag_names)
    if total_cols > MAX_TABLE_COLUMNS:
        raise _op_error(
            f"交叉匹配合并后共 {total_cols} 列，超过单表 {MAX_TABLE_COLUMNS} 列上限；"
            "请先筛选左右表列数。"
        )

    left_pos_by_row = {orig: pos for pos, orig in enumerate(left_orig_idx.tolist())}
    right_null_row: list[str | None] = [None] * len(right_table.columns)

    merged_rows: list[list[str | None]] = []
    matched_left_count = 0
    multi_candidate_rows = 0
    truncated_candidate_rows = 0
    matched_seps: list[float] = []

    for orig_l in range(len(left_table.rows)):
        l_row = list(left_table.rows[orig_l])
        l_pos = left_pos_by_row.get(orig_l)
        cands = candidates_by_left.get(l_pos, []) if l_pos is not None else []
        cand_total = len(cands)
        if cand_total > 0:
            matched_left_count += 1
        if cand_total > 1:
            multi_candidate_rows += 1

        if not cands:
            if req.join_type == "left":
                merged_rows.append([*l_row, *right_null_row, None, "0", None])
            continue

        selected = cands[:1] if req.mode == "nearest" else cands[:MAX_CROSSMATCH_CANDIDATES_PER_ROW]
        if req.mode == "all_within_radius" and cand_total > MAX_CROSSMATCH_CANDIDATES_PER_ROW:
            truncated_candidate_rows += 1

        next_sep_val = (
            cands[1][1]
            if len(cands) >= 2
            else next_sep_lookup.get(l_pos)
            if l_pos is not None
            else None
        )
        for r_pos, sep_val in selected:
            orig_r = int(right_orig_idx[r_pos])
            r_row = list(right_table.rows[orig_r])
            matched_seps.append(sep_val)
            merged_rows.append(
                [
                    *l_row,
                    *r_row,
                    _format_float(sep_val),
                    str(cand_total),
                    _format_float(next_sep_val),
                ]
            )
            if len(merged_rows) > MAX_TABLE_ROWS:
                raise _op_error(
                    f"交叉匹配输出超过 {MAX_TABLE_ROWS} 行上限，请缩小搜索半径或改用 nearest 模式。"
                )

    if not merged_rows:
        raise _op_error("在给定搜索半径内未找到任何匹配源（inner 连接结果为空）。")

    out_cols: list[TableColumnMeta] = [
        *left_table.columns,
        *[
            _infer_column_meta(
                right_out_names[idx],
                [row[len(left_table.columns) + idx] for row in merged_rows],
                dtype_hint=col.dtype,
                unit=col.unit,
                ucd=col.ucd,
                description=col.description,
            )
            for idx, col in enumerate(right_table.columns)
        ],
        TableColumnMeta(
            name="match_sep_arcsec",
            kind="number",
            dtype="float64",
            unit="arcsec",
            description="左右表匹配大圆角距",
            missing=sum(1 for row in merged_rows if row[-3] is None),
        ),
        TableColumnMeta(
            name="match_candidate_count",
            kind="integer",
            dtype="int64",
            unit="1",
            description="搜索半径内右表候选源总数",
            missing=0,
        ),
        TableColumnMeta(
            name="match_next_sep_arcsec",
            kind="number",
            dtype="float64",
            unit="arcsec",
            description="次近邻角距（评估拥挤视场错配风险）",
            missing=sum(1 for row in merged_rows if row[-1] is None),
        ),
    ]

    warnings_list = list(SCIENTIFIC_BOUNDARY_WARNINGS)
    left_epoch = (left_table.ref_epoch or "").strip()
    right_epoch = (right_table.ref_epoch or "").strip()
    if not left_epoch or not right_epoch or left_epoch != right_epoch:
        warnings_list.append(
            f"两表参考历元不同或未知（左：{left_epoch or '未知'}，右：{right_epoch or '未知'}），"
            "未执行自行传播，高自行源或拥挤星场可能漏配或错配。"
        )
    if truncated_candidate_rows > 0:
        warnings_list.append(
            f"有 {truncated_candidate_rows} 个左表源在半径内候选超过 "
            f"{MAX_CROSSMATCH_CANDIDATES_PER_ROW} 个，"
            f"已截断保留最近 {MAX_CROSSMATCH_CANDIDATES_PER_ROW} 个候选。"
        )

    valid_left_n = len(left_orig_idx)
    sep_median = float(np.median(matched_seps)) if matched_seps else None
    sep_p90 = float(np.percentile(matched_seps, 90)) if matched_seps else None

    derived_table = ParsedTable(
        columns=out_cols,
        rows=merged_rows,
        format="ecsv",
        coordinate_frame="ICRS",
        ref_epoch=left_epoch or right_epoch or None,
        header_meta={},
        warnings=list(dict.fromkeys(warnings_list)),
    )
    return OperatorOutcome(
        summary={
            "left_total_rows": len(left_table.rows),
            "left_valid_coord_rows": valid_left_n,
            "right_total_rows": len(right_table.rows),
            "right_valid_coord_rows": len(right_orig_idx),
            "matched_left_rows": matched_left_count,
            "output_rows": len(merged_rows),
            "match_rate": round(matched_left_count / valid_left_n, 6) if valid_left_n else 0.0,
            "multi_candidate_rows": multi_candidate_rows,
            "truncated_candidate_rows": truncated_candidate_rows,
            "sep_median_arcsec": sep_median,
            "sep_p90_arcsec": sep_p90,
            "radius_arcsec": req.radius_arcsec,
            "mode": req.mode,
            "join_type": req.join_type,
        },
        warnings=list(dict.fromkeys(warnings_list)),
        derived_table=derived_table,
        software=scientific_software_versions(),
    )


def run_fit(table: ParsedTable, req: FitOperatorRequest) -> OperatorOutcome:
    x_all = _to_float_array(table, req.x_col)
    y_all = _to_float_array(table, req.y_col)
    valid_mask = np.isfinite(x_all) & np.isfinite(y_all)
    weighted = req.y_err_col is not None
    yerr_all: np.ndarray | None = None
    if weighted:
        assert req.y_err_col is not None
        yerr_all = _to_float_array(table, req.y_err_col)
        if np.any(np.isfinite(yerr_all) & (yerr_all <= 0)):
            raise _op_error("误差列 y_err 必须严格大于 0；发现非正误差值。")
        valid_mask = valid_mask & np.isfinite(yerr_all) & (yerr_all > 0)

    if req.model == "power_law":
        if np.any(valid_mask & (x_all <= 0)):
            raise _op_error("幂律模型 y = A * x^alpha 要求全部有效自变量 x > 0。")
        valid_mask = valid_mask & (x_all > 0)

    valid_idx = np.flatnonzero(valid_mask)
    p_count = (
        2
        if req.model in ("linear", "power_law")
        else (req.degree + 1)
        if req.model == "polynomial"
        else 4
    )
    min_pts = p_count + 1
    if len(valid_idx) < min_pts:
        raise _op_error(
            f"{req.model} 拟合至少需要 {min_pts} 个有效数据点（当前仅 {len(valid_idx)} 个）。"
        )

    xv = x_all[valid_idx]
    yv = y_all[valid_idx]
    sigmav = yerr_all[valid_idx] if yerr_all is not None else None
    n_pts = len(xv)
    dof = n_pts - p_count

    params: list[dict[str, Any]] = []
    extra_metrics: dict[str, Any] = {}
    converged = True

    if req.model == "linear":
        # Exact WLS/OLS closed form for y = a*x + b
        w = 1.0 / (sigmav**2) if sigmav is not None else np.ones(n_pts, dtype=np.float64)
        s0 = float(np.sum(w))
        sx = float(np.sum(w * xv))
        sy = float(np.sum(w * yv))
        sxx = float(np.sum(w * xv * xv))
        sxy = float(np.sum(w * xv * yv))
        det = s0 * sxx - sx * sx
        if det <= 0:
            raise _op_error("自变量 x 全部相同或矩阵奇异，无法执行线性拟合。")
        slope = (s0 * sxy - sx * sy) / det
        intercept = (sxx * sy - sx * sxy) / det
        y_hat = slope * xv + intercept
        chi2 = float(np.sum(w * (yv - y_hat) ** 2))
        scale = 1.0 if weighted else (chi2 / dof)
        var_slope = (s0 / det) * scale
        var_intercept = (sxx / det) * scale
        params = [
            {"name": "slope (a)", "value": slope, "err": math.sqrt(max(0.0, var_slope))},
            {
                "name": "intercept (b)",
                "value": intercept,
                "err": math.sqrt(max(0.0, var_intercept)),
            },
        ]
    elif req.model == "polynomial":
        deg = req.degree
        w = 1.0 / (sigmav**2) if sigmav is not None else np.ones(n_pts, dtype=np.float64)
        # Design matrix [1, x, x^2, ..., x^deg]
        design = np.column_stack([xv**k for k in range(deg + 1)])
        sw = np.sqrt(w)[:, None]
        weighted_design = design * sw
        weighted_y = yv * np.sqrt(w)
        coeffs, _, _, _ = np.linalg.lstsq(weighted_design, weighted_y, rcond=None)
        y_hat = design @ coeffs
        chi2 = float(np.sum(w * (yv - y_hat) ** 2))
        try:
            cov = np.linalg.inv(weighted_design.T @ weighted_design)
        except np.linalg.LinAlgError as exc:
            raise _op_error("多项式设计矩阵奇异，请降低阶数或检查 x 分布。") from exc
        if not weighted:
            cov = cov * (chi2 / dof)
        params = [
            {
                "name": f"c_{k}",
                "value": float(coeffs[k]),
                "err": math.sqrt(max(0.0, float(cov[k, k]))),
            }
            for k in range(deg + 1)
        ]
    elif req.model == "power_law":
        if np.any(yv <= 0) and (req.initial_guess is None or req.initial_guess.scale is None):
            # 允许 y 含非正值时通过均值初值，但优先使用对数初值
            p0 = [float(np.median(yv)) or 1.0, 1.0]
        else:
            pos = yv > 0
            if np.sum(pos) >= 2:
                lx = np.log(xv[pos])
                ly = np.log(yv[pos])
                alpha0, log_a0 = np.polyfit(lx, ly, 1)
                p0 = [float(np.exp(log_a0)), float(alpha0)]
            else:
                p0 = [1.0, 1.0]
        if req.initial_guess is not None:
            if req.initial_guess.scale is not None:
                p0[0] = float(req.initial_guess.scale)
            if req.initial_guess.exponent is not None:
                p0[1] = float(req.initial_guess.exponent)

        def power_fn(x, amp, alpha):
            return amp * np.power(x, alpha)

        try:
            popt, pcov = optimize.curve_fit(
                power_fn,
                xv,
                yv,
                p0=p0,
                sigma=sigmav,
                absolute_sigma=weighted,
                maxfev=10000,
            )
        except Exception as exc:
            raise _op_error("幂律模型拟合未收敛，请检查数据范围或提供初值。") from exc
        if not np.all(np.isfinite(popt)) or not np.all(np.isfinite(pcov)):
            raise _op_error("拟合协方差矩阵非有限或奇异，无法估计参数误差，请调整数据或初值。")
        y_hat = power_fn(xv, *popt)
        perr = np.sqrt(np.maximum(0.0, np.diag(pcov)))
        params = [
            {"name": "amplitude (A)", "value": float(popt[0]), "err": float(perr[0])},
            {"name": "exponent (alpha)", "value": float(popt[1]), "err": float(perr[1])},
        ]
    else:  # gaussian
        med_y = float(np.median(yv))
        idx_max = int(np.argmax(yv))
        idx_min = int(np.argmin(yv))
        if abs(float(yv[idx_max]) - med_y) >= abs(float(yv[idx_min]) - med_y):
            amp0 = float(yv[idx_max]) - med_y
            mu0 = float(xv[idx_max])
        else:
            amp0 = float(yv[idx_min]) - med_y
            mu0 = float(xv[idx_min])
        span_x = float(np.max(xv) - np.min(xv))
        half_mask = (
            np.abs(yv - med_y) >= 0.5 * abs(amp0) if amp0 != 0 else np.ones(n_pts, dtype=bool)
        )
        if np.sum(half_mask) >= 2:
            fwhm_est = float(np.max(xv[half_mask]) - np.min(xv[half_mask]))
            sigma0 = max(fwhm_est / 2.354820045, span_x / max(n_pts, 4), 1e-6)
        else:
            sigma0 = max(span_x / 6.0, 1e-6)
        p0 = [med_y, amp0 or 1.0, mu0, sigma0]
        if req.initial_guess is not None:
            if req.initial_guess.baseline is not None:
                p0[0] = float(req.initial_guess.baseline)
            if req.initial_guess.amplitude is not None:
                p0[1] = float(req.initial_guess.amplitude)
            if req.initial_guess.center is not None:
                p0[2] = float(req.initial_guess.center)
            if req.initial_guess.sigma is not None:
                p0[3] = float(req.initial_guess.sigma)

        def gauss_fn(x, baseline, amp, mu, sigma):
            return baseline + amp * np.exp(-0.5 * ((x - mu) / sigma) ** 2)

        try:
            popt, pcov = optimize.curve_fit(
                gauss_fn,
                xv,
                yv,
                p0=p0,
                sigma=sigmav,
                absolute_sigma=weighted,
                bounds=([-np.inf, -np.inf, -np.inf, 1e-12], [np.inf, np.inf, np.inf, np.inf]),
                maxfev=15000,
            )
        except Exception as exc:
            raise _op_error("单高斯模型拟合未收敛，请核对初值或数据区间。") from exc
        if not np.all(np.isfinite(popt)) or not np.all(np.isfinite(pcov)):
            raise _op_error("拟合协方差矩阵非有限或奇异，无法估计参数误差，请调整数据或初值。")
        y_hat = gauss_fn(xv, *popt)
        perr = np.sqrt(np.maximum(0.0, np.diag(pcov)))
        fwhm_factor = 2.0 * math.sqrt(2.0 * math.log(2.0))
        extra_metrics["fwhm"] = float(fwhm_factor * popt[3])
        extra_metrics["fwhm_err"] = float(fwhm_factor * perr[3])
        params = [
            {"name": "baseline (b)", "value": float(popt[0]), "err": float(perr[0])},
            {"name": "amplitude (A)", "value": float(popt[1]), "err": float(perr[1])},
            {"name": "center (mu)", "value": float(popt[2]), "err": float(perr[2])},
            {"name": "sigma", "value": float(popt[3]), "err": float(perr[3])},
        ]

    residuals = yv - y_hat
    ss_res = float(np.sum(residuals**2))
    ss_tot = float(np.sum((yv - np.mean(yv)) ** 2))
    r2 = 1.0 - (ss_res / ss_tot) if ss_tot > 0 else 1.0
    rmse = math.sqrt(ss_res / n_pts)
    reduced_chi2 = (
        float(np.sum((residuals / sigmav) ** 2)) / dof if sigmav is not None and dof > 0 else None
    )

    out_cols = list(table.columns)
    existing = {c.name for c in out_cols}
    y_unit = table.columns[_col_index_map(table)[req.y_col]].unit
    fit_col_name = "y_fit" if "y_fit" not in existing else "fit_y_model"
    res_col_name = "residual" if "residual" not in existing else "fit_residual"
    extra_cols = [
        (
            fit_col_name,
            y_unit,
            f"{req.model} 拟合预测值",
        ),
        (
            res_col_name,
            y_unit,
            "观测值减拟合预测值 (y - y_fit)",
        ),
    ]
    if sigmav is not None:
        norm_name = (
            "normalized_residual" if "normalized_residual" not in existing else "fit_norm_residual"
        )
        extra_cols.append((norm_name, "1", "归一化残差 (y - y_fit) / y_err"))

    if len(out_cols) + len(extra_cols) > MAX_TABLE_COLUMNS:
        raise _op_error(f"附加拟合残差列后超过 {MAX_TABLE_COLUMNS} 列上限。")

    fit_map = {int(orig_i): float(y_hat[pos]) for pos, orig_i in enumerate(valid_idx.tolist())}
    res_map = {int(orig_i): float(residuals[pos]) for pos, orig_i in enumerate(valid_idx.tolist())}
    norm_map = (
        {
            int(orig_i): float(residuals[pos] / sigmav[pos])
            for pos, orig_i in enumerate(valid_idx.tolist())
        }
        if sigmav is not None
        else {}
    )

    out_rows = [list(r) for r in table.rows]
    for r_idx in range(len(out_rows)):
        out_rows[r_idx].append(_format_float(fit_map.get(r_idx)))
        out_rows[r_idx].append(_format_float(res_map.get(r_idx)))
        if sigmav is not None:
            out_rows[r_idx].append(_format_float(norm_map.get(r_idx)))

    for cname, cunit, cdesc in extra_cols:
        out_cols.append(
            TableColumnMeta(
                name=cname,
                kind="number",
                dtype="float64",
                unit=cunit,
                description=cdesc,
                missing=len(out_rows) - n_pts,
            )
        )

    warnings_list = list(SCIENTIFIC_BOUNDARY_WARNINGS)
    if not weighted:
        warnings_list.append(
            "未提供误差列 y_err，已执行无权重拟合（unweighted），参数误差按残差方差缩放。"
        )
    if len(table.rows) - n_pts > 0:
        warnings_list.append(
            f"已排除 {len(table.rows) - n_pts} 行无效或非正输入，残差列对应位置保留空值。"
        )

    derived_table = ParsedTable(
        columns=out_cols,
        rows=out_rows,
        format=table.format,
        coordinate_frame=table.coordinate_frame,
        ref_epoch=table.ref_epoch,
        header_meta=table.header_meta,
        warnings=list(dict.fromkeys(warnings_list)),
    )
    return OperatorOutcome(
        summary={
            "model": req.model,
            "degree": req.degree if req.model == "polynomial" else None,
            "weighted": weighted,
            "weight_mode": "wls" if weighted else "unweighted",
            "converged": converged,
            "valid_points": n_pts,
            "skipped_rows": len(table.rows) - n_pts,
            "dof": dof,
            "r2": r2,
            "rmse": rmse,
            "reduced_chi2": reduced_chi2,
            "parameters": params,
            **extra_metrics,
        },
        warnings=list(dict.fromkeys(warnings_list)),
        derived_table=derived_table,
        software=scientific_software_versions(),
    )
