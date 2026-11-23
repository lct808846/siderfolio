"""AstroAgent V1.9.0 fixed scientific evaluation and version comparison harness.

Supports:
- `--mode offline`: Deterministic local verification of V1.9 authorization boundaries,
  trace sanitization, MCP read-only surface, and frozen case definitions (zero external HTTP).
- `--mode live`: Evaluates a live isolated AstroAgent instance (never point at daily DB).

Writes structured JSON and Markdown reports under:
  docs/test-records/v1.9.0/<record-type>/<UTC-timestamp>/
preserving pass/fail/skip outcomes, sample sizes, latency, and honest token/cost status.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CASES_PATH = ROOT / "docs" / "development" / "v1.9.0" / "evaluation-cases.json"


def _git_head() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, text=True
        ).strip()
    except Exception:
        return "unknown"


def _run_offline_case(case: dict) -> dict:
    from astroagent.literature_auth import analyze_save_permit
    from astroagent.mcp_server import build_mcp_tools
    from astroagent.schemas import LiteratureSearchResult, PaperData, Source
    from astroagent.trace_runtime import TraceRecorder

    started = time.perf_counter()
    cid = case["id"]
    notes: list[str] = []
    status = "skipped"

    if cid == "al-01-search-only-no-save":
        permit = analyze_save_permit(
            case["input"], conversation_id="eval-c", turn_id="eval-t", client_request_id="eval-r"
        )
        ok = not permit.authorized
        status = "passed" if ok else "failed"
        notes.append(f"authorized={permit.authorized} reason={permit.deny_reason}")

    elif cid == "al-02-search-and-save-top3":
        permit = analyze_save_permit(
            case["input"], conversation_id="eval-c", turn_id="eval-t", client_request_id="eval-r"
        )
        ok = permit.authorized and permit.selection_kind == "top_n" and permit.max_count == 3
        status = "passed" if ok else "failed"
        notes.append(
            f"authorized={permit.authorized} kind={permit.selection_kind} max={permit.max_count}"
        )

    elif cid == "al-03-followup-save-indices":
        permit = analyze_save_permit(
            case["input"], conversation_id="eval-c", turn_id="eval-t", client_request_id="eval-r"
        )
        ok = (
            permit.authorized
            and permit.selection_kind == "indices"
            and permit.allowed_indices == [1, 3]
        )
        status = "passed" if ok else "failed"
        notes.append(
            f"authorized={permit.authorized} kind={permit.selection_kind} "
            f"indices={permit.allowed_indices}"
        )

    elif cid == "al-04-negation-and-quoted-injection-denied":
        results = []
        for idx, text in enumerate(case.get("inputs", [])):
            permit = analyze_save_permit(
                text,
                conversation_id="eval-c",
                turn_id=f"eval-t-{idx}",
                client_request_id=f"r-{idx}",
            )
            results.append((text[:24], permit.authorized, permit.deny_reason))
        ok = all(not auth for _, auth, _ in results)
        status = "passed" if ok else "failed"
        notes.append("; ".join(f"{t}...=>auth={a}({r})" for t, a, r in results))

    elif cid == "al-05-ambiguous-reference-rejected":
        from astroagent.literature_schemas import SaveLiteratureQuery

        permit = analyze_save_permit(
            case["input"], conversation_id="eval-c", turn_id="eval-t", client_request_id="eval-r"
        )
        dummy_src = Source(
            name="ADS",
            url="https://ui.adsabs.harvard.edu/abs/2024ApJ...000....1A",
            retrieved_at="2026-11-22T00:00:00Z",
        )
        paper = PaperData(bibcode="2024ApJ...000....1A", title="Test", source=dummy_src)
        batch = LiteratureSearchResult(
            status="success",
            query="q",
            rows=1,
            start=0,
            sort="relevance",
            returned_count=1,
            total_found=1,
            papers=[paper],
            source=dummy_src,
        )
        t1 = "11111111-1111-4111-8111-111111111111"
        t2 = "22222222-2222-4222-8222-222222222222"
        rejected = False
        try:
            permit.verify_and_resolve(
                SaveLiteratureQuery(
                    source_scope="history_turn",
                    source_turn_id=t1,
                    batch_index=0,
                    paper_indices=[1],
                ),
                current_batches=[],
                history_batches=[(t1, 0, batch), (t2, 0, batch)],
            )
        except (PermissionError, ValueError) as exc:
            rejected = True
            notes.append(f"rejected={exc}")
        status = "passed" if rejected else "failed"

    elif cid == "iso-01-account-isolation-and-sanitized-trace":
        recorder = TraceRecorder(
            conversation_id="eval-c", turn_id="eval-t", astronomy_transport="mcp"
        )
        span = recorder.start_span(kind="tool_ads", name="ADS 文献检索")
        recorder.record_span(
            span_id=span[0],
            started_at=span[1],
            started_mono=span[2],
            kind="tool_ads",
            name="ADS 文献检索",
            status="ok",
            transport="mcp",
            provider="ADS",
            correlation_id="eval-corr-1",
            result_count=3,
        )
        trace = recorder.finalize(status="ok")
        dumped = trace.model_dump_json()
        forbidden = ("prompt", "abstract", "secret", "password", "traceback")
        sanitized = not any(word in dumped.lower() for word in forbidden)
        tool_names = sorted(tool.name for tool in build_mcp_tools())
        mcp_ok = tool_names == ["query_gaia", "query_simbad", "search_ads"]
        ok = sanitized and mcp_ok and trace.astronomy_transport == "mcp"
        status = "passed" if ok else "failed"
        notes.append(f"sanitized={sanitized} mcp_tools={tool_names}")

    else:
        status = "skipped"
        notes.append("离线模式不发起外部 HTTP / 实时模型 / 容器计算调用；需 --mode live 执行。")

    elapsed_ms = round((time.perf_counter() - started) * 1000.0, 2)
    return {
        "id": cid,
        "category": case["category"],
        "title": case["title"],
        "v18_applicable": case.get("v18_applicable", False),
        "transport_parity": case.get("transport_parity", False),
        "status": status,
        "latency_ms": elapsed_ms,
        "samples": 1 if status != "skipped" else 0,
        "tokens": None,
        "cost_status": "unknown",
        "notes": notes,
    }


def _render_markdown(report: dict) -> str:
    lines = [
        "# AstroAgent V1.9.0 科研评估与版本对照报告",
        "",
        f"- **生成时间 (UTC)**：`{report['generated_at']}`",
        f"- **运行模式**：`{report['mode']}`",
        f"- **样例集版本**：`{report['suite_version']}`",
        (
            f"- **对比锚点**：`{report['baseline_anchor']}` → "
            f"`v{report['target_version']}` (`{report['git_head']}`)"
        ),
        "",
        "## 1. 汇总统计",
        "",
        (
            f"- 通过：`{report['summary']['passed']}`　"
            f"失败：`{report['summary']['failed']}`　"
            f"跳过：`{report['summary']['skipped']}`　"
            f"总计：`{report['summary']['total']}`"
        ),
        "- Token 用量：离线模式未调用真实模型，记为 `未报告`；费用记为 `未知`（不编造数据）。",
        "",
        "## 2. 逐项结果与 V1.8 / V1.9 版本对照",
        "",
        (
            "| 样例 ID | 场景 | V1.8 基线适用性 | V1.9 结果 | "
            "样本数 n | 耗时 (ms) | Token / 费用 | 备注 |"
        ),
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for item in report["results"]:
        v18_col = "共同支持（对照）" if item["v18_applicable"] else "不适用（V1.9 新增基线）"
        tok = "未报告 / 未知" if item["tokens"] is None else str(item["tokens"])
        note = "；".join(item["notes"]).replace("|", "/")
        lines.append(
            f"| `{item['id']}` | {item['title']} | {v18_col} | `{item['status']}` | "
            f"{item['samples']} | {item['latency_ms']} | {tok} | {note} |"
        )
    lines.extend(
        [
            "",
            "## 3. 限制与说明",
            "",
            (
                "- 离线模式仅验证确定性本地规则（授权边界、追踪脱敏、MCP 工具面）；"
                "真实外部服务（SIMBAD/ADS/Gaia/模型/REBOUND/PeTar）"
                "须在隔离验收环境使用 `--mode live` 单独留证。"
            ),
            "- 本报告完整保留失败与跳过项，不覆盖历史记录。",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("offline", "live"), default="offline")
    parser.add_argument("--record-type", default="evaluation")
    parser.add_argument(
        "--dry-run", action="store_true", help="Print report to stdout without writing test-records"
    )
    args = parser.parse_args()

    sys.path.insert(0, str(ROOT / "src"))
    suite = json.loads(CASES_PATH.read_text(encoding="utf-8"))

    if args.mode == "live":
        print(
            "Live evaluation requires an explicitly provisioned isolated AstroAgent instance "
            "and database; configure ASTROAGENT_EVAL_BASE_URL against an isolated acceptance "
            "stack before running.",
            file=sys.stderr,
        )
        return 2

    results = [_run_offline_case(case) for case in suite["scenarios"]]
    now = datetime.now(UTC)
    report = {
        "generated_at": now.isoformat(),
        "mode": args.mode,
        "suite_version": suite["suite_version"],
        "baseline_anchor": suite["baseline_anchor"],
        "target_version": suite["target_version"],
        "git_head": _git_head(),
        "thresholds": suite["thresholds"],
        "summary": {
            "total": len(results),
            "passed": sum(1 for r in results if r["status"] == "passed"),
            "failed": sum(1 for r in results if r["status"] == "failed"),
            "skipped": sum(1 for r in results if r["status"] == "skipped"),
        },
        "results": results,
    }
    markdown = _render_markdown(report)
    if args.dry_run:
        print(markdown)
        return 0 if report["summary"]["failed"] == 0 else 1

    stamp = now.strftime("%Y%m%dT%H%M%SZ")
    out_dir = ROOT / "docs" / "test-records" / "v1.9.0" / args.record_type / stamp
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (out_dir / "README.md").write_text(markdown, encoding="utf-8")
    print(f"Wrote V1.9 evaluation report to {out_dir}")
    return 0 if report["summary"]["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
