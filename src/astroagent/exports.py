"""完整客户端快照的内存导出，不访问模型、URL 或外部数据库。"""

import csv
import hashlib
import json
import platform
import subprocess
import threading
from datetime import UTC, datetime
from io import BytesIO, StringIO
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import matplotlib
import numpy

from astroagent import __version__
from astroagent.errors import ServiceError
from astroagent.export_schemas import ExportManifest
from astroagent.plots import STYLE_VERSION, prepare_plot, render_plot
from astroagent.schemas import GaiaDistanceEstimate, GaiaSourceData, ObjectData, PaperData

MAX_PACKAGE_BYTES = 16 * 1024 * 1024
EXPORT_LOCK = threading.Lock()
CSV_POLICY = {
    "encoding": "utf-8-sig",
    "delimiter": ",",
    "line_ending": "CRLF",
    "null": "empty_cell",
    "text_formula_protection": "leading_apostrophe",
    "gaia_source_id": "leading_apostrophe_exact_string_in_snapshot_json",
    "change_row_numbering": "1-based data rows, excluding header",
    "array_columns": "JSON strings",
    "numeric_rounding": False,
}
README = """# AstroAgent 查询导出包

本包来自客户端提交的快照（client_supplied_snapshot）。来源真实性未经认证；
SHA-256 只检验文件字节变化，不是来源签名或科研结论认证。
snapshot.json 保留完整语义，字段顺序、空白不保证与原 HTTP 字节相同。
answer 为模型回答；data / papers 为提交的数据库测量或书目；analysis 为程序派生量。

## 表格与完整数据

CSV 含 UTF-8 BOM，逗号分隔，CRLF 换行。null 为空；数组列为 JSON 数组字符串。
危险文本加前导单引号，Gaia source_id 统一加前导单引号以提示文本；各软件行为可能不同。
精确编号、空字符串、null 与未经处理文本以 JSON 为准。变更位置见清单。
成功查询各生成一份表；失败和无匹配不生成伪数据，其状态、错误和来源保留在快照和清单。
多次查询独立导出，不合并、去重或自动翻页。所有图使用该次全部交付行。

## 图表与科学边界

图只描述本次实际交付样本；最多 500 行且可能截断，不代表整个视场、星表或总体分布。
圆锥源仅为位置候选，不能称为确认匹配或星团成员；自行聚集不能完成成员判定。
pmra 已含 cos(dec)，未做自行传播。自行图为等比例坐标，保留负值。
观测颜色—星等图使用已有 BP-RP 和 G 视星等，亮源在上，未校正消光；
不是绝对星等 HR 图，不据此拟合年龄。缺失 BP-RP 不从别的字段补算。
视差直方图保留负/零视差，纵轴为实际行数，不是距离分布或概率密度。
不自动绘制距离、拟合或误差条；测量误差随表格导出。
距离仅在原查询启用时导出原派生值：高信噪比视差倒数和一阶随机误差，
未校正视差零点、系统误差或选择偏差，未做贝叶斯估计。
原查询条件、质量筛选、ADQL、ADS 检索式、单位、来源 UTC、截断与警告见下方元数据及 manifest.json。
图表逐行选取、排除原因、坐标、分箱边界和计数见 manifest.json。
缺少数据、失败或数值范围不可表示时跳图，包的 export_status 可为 partial。
固定输入与参数复现选行与统计；依赖、字体、时间戳和图片元数据可能变化，
不承诺跨平台 ZIP 或 PNG 逐字节相同。

## 本包查询元数据（JSON 文本）

"""


def json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")


def csv_bytes(path, columns, rows, changes):
    with StringIO(newline="") as text:
        writer = csv.DictWriter(text, fieldnames=columns, lineterminator="\r\n")
        writer.writeheader()
        for number, row in enumerate(rows, 1):
            output = {}
            for column in columns:
                value = row.get(column)
                reason = None
                if isinstance(value, (dict, list)):
                    value = json.dumps(value, ensure_ascii=False, allow_nan=False)
                if isinstance(value, str):
                    if column == "source_id":
                        reason = "source_id_precision"
                    elif value.startswith(("\t", "\r")) or value.lstrip().startswith(
                        ("=", "+", "-", "@")
                    ):
                        reason = "spreadsheet_formula"
                    if reason:
                        value = "'" + value
                        changes.append(
                            {
                                "file": path,
                                "data_row": number,
                                "column": column,
                                "reason": reason,
                            }
                        )
                output[column] = value
            writer.writerow(output)
        return text.getvalue().encode("utf-8-sig")


def git_state():
    root = Path(__file__).resolve().parents[2]
    try:

        def git(*args):
            return subprocess.run(
                ["git", "-C", str(root), *args],
                capture_output=True,
                text=True,
                timeout=2,
                check=True,
                encoding="utf-8",
                errors="replace",
            ).stdout.strip()

        if Path(git("rev-parse", "--show-toplevel")).resolve() != root:
            return None, None
        return git("rev-parse", "HEAD"), bool(git("status", "--porcelain"))
    except (OSError, subprocess.SubprocessError):
        return None, None


def _too_large():
    return ServiceError(413, "export_too_large", "导出超过资源上限。")


class LimitedBuffer(BytesIO):
    def write(self, data):
        if self.tell() + len(data) > MAX_PACKAGE_BYTES:
            raise _too_large()
        return super().write(data)


def _build_package(request):
    files, queries, changes, plots = {}, [], [], []
    total_bytes = 0

    def add(path, content):
        nonlocal total_bytes
        total_bytes += len(content)
        if total_bytes > MAX_PACKAGE_BYTES:
            raise _too_large()
        files[path] = content

    snapshot = request.snapshot.model_dump(mode="json")
    add("snapshot.json", json_bytes(snapshot))
    for family, results in (
        ("simbad", request.snapshot.results),
        ("ads", request.snapshot.literature_results),
        ("gaia", request.snapshot.gaia_results),
    ):
        for index, result in enumerate(results):
            metadata = result.model_dump(mode="json")
            for key in ("data", "papers", "analysis"):
                metadata.pop(key, None)
            path = f"tables/{family}-{index:03d}.csv" if result.status == "success" else None
            queries.append(
                {
                    "family": family,
                    "result_index": index,
                    **metadata,
                    "table_path": path,
                    "table_skipped_reason": None if path else "query_not_successful",
                }
            )
            if path is None:
                continue
            if family == "gaia":
                distance_columns = [
                    k for k in GaiaDistanceEstimate.model_fields if k != "source_id"
                ]
                columns = [*GaiaSourceData.model_fields, *distance_columns]
                distances = {
                    d.source_id: d.model_dump(exclude={"source_id"})
                    for d in (result.analysis.distance_estimates if result.analysis else [])
                }
                rows = [{**s.model_dump(), **distances.get(s.source_id, {})} for s in result.data]
            else:
                fields = ObjectData.model_fields if family == "simbad" else PaperData.model_fields
                columns = [
                    "query_index",
                    *(["object_name"] if family == "simbad" else []),
                    *(k for k in fields if k != "source"),
                    "source_url",
                    "retrieved_at",
                ]
                entries = [result.data] if family == "simbad" else result.papers
                rows = []
                for entry in entries:
                    source = result.source if family == "simbad" else entry.source
                    rows.append(
                        {
                            "query_index": index,
                            **({"object_name": result.object_name} if family == "simbad" else {}),
                            **entry.model_dump(exclude={"source"}),
                            "source_url": source.url,
                            "retrieved_at": source.model_dump(mode="json")["retrieved_at"],
                        }
                    )
            add(path, csv_bytes(path, columns, rows, changes))
    for spec in request.plots:
        record = prepare_plot(request.snapshot.gaia_results[spec.gaia_result_index], spec)
        if record["status"] == "ready":
            try:
                content = render_plot(record)
            except (ValueError, OverflowError, FloatingPointError, RuntimeWarning):
                record.update(status="skipped", reason="unrepresentable_range")
            except Exception:
                record.update(status="skipped", reason="render_failed")
            else:
                path = (
                    f"figures/gaia-{spec.gaia_result_index:03d}-{spec.kind.replace('_', '-')}.png"
                )
                add(path, content)
                record.update(status="success", output_path=path)
        plots.append(record)
    # Serialize as indented JSON without treating any submitted strings as Markdown commands.
    metadata_text = "\n".join("    " + line for line in json_bytes(queries).decode().splitlines())
    add("README.md", (README + metadata_text + "\n").encode("utf-8"))
    commit, dirty = git_state()
    manifest = ExportManifest(
        exporter_version=__version__,
        git_commit=commit,
        git_dirty=dirty,
        exported_at=datetime.now(UTC).isoformat(),
        runtime={
            "python": platform.python_version(),
            "matplotlib": matplotlib.__version__,
            "numpy": numpy.__version__,
        },
        plot_style_version=STYLE_VERSION,
        snapshot_status=request.snapshot.status,
        export_status="partial" if any(p["status"] != "success" for p in plots) else "success",
        queries=queries,
        plots=plots,
        csv_policy=CSV_POLICY,
        csv_changes=changes,
        files=[
            {"path": path, "bytes": len(content), "sha256": hashlib.sha256(content).hexdigest()}
            for path, content in files.items()
        ],
    )
    add("manifest.json", json_bytes(manifest.model_dump()))
    with LimitedBuffer() as buffer:
        with ZipFile(buffer, "w", compression=ZIP_DEFLATED) as archive:
            for path, content in files.items():
                archive.writestr(path, content)
        package = buffer.getvalue()
    # Check actual ZIP members and their bytes before returning any HTTP body.
    with ZipFile(BytesIO(package)) as archive:
        if len(archive.namelist()) != len(files):
            raise ValueError("Duplicate package member")
        for item in manifest.files:
            body = archive.read(item.path)
            if len(body) != item.bytes or hashlib.sha256(body).hexdigest() != item.sha256:
                raise ValueError("Package verification failed")
    return package


def build_package(request):
    if not EXPORT_LOCK.acquire(blocking=False):
        raise ServiceError(503, "export_busy", "导出正忙，请稍后重试。", retryable=True)
    try:
        return _build_package(request)
    except ServiceError:
        raise
    except Exception as exc:
        raise ServiceError(500, "export_failed", "导出失败，请稍后重试。") from exc
    finally:
        EXPORT_LOCK.release()
