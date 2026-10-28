"""独立导出契约、读回核对、科学语义及资源失败回归。"""

import csv
import hashlib
import json
import threading
from copy import deepcopy
from io import BytesIO, StringIO
from zipfile import ZipFile

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from astroagent import exports, plots
from astroagent.api.exports import export_body, validate_json
from astroagent.errors import ServiceError
from astroagent.export_schemas import PlotSpec
from astroagent.main import app
from astroagent.schemas import GaiaSourceData
from scripts.export_samples import synthetic_request


def parse(body):
    return validate_json(json.dumps(body, ensure_ascii=False).encode())


def unpack(body):
    archive = ZipFile(BytesIO(body))
    manifest = json.loads(archive.read("manifest.json"))
    for item in manifest["files"]:
        content = archive.read(item["path"])
        assert item["bytes"] == len(content)
        assert item["sha256"] == hashlib.sha256(content).hexdigest()
    assert {f["path"] for f in manifest["files"]} == set(archive.namelist()) - {"manifest.json"}
    assert len(set(archive.namelist())) == len(archive.namelist())
    assert all(not p.startswith("/") and ".." not in p for p in archive.namelist())
    return archive, manifest


def test_complete_package_readback_and_pixels(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "")
    body = synthetic_request()
    with TestClient(app) as client:
        response = client.post("/api/v1/exports", json=body)
    assert response.status_code == 200, response.text[:200] if response.status_code != 200 else ""
    assert response.headers["content-type"] == "application/zip"
    assert (
        response.headers["content-disposition"] == 'attachment; filename="astroagent-results.zip"'
    )
    assert response.headers["cache-control"] == "no-store"
    archive, manifest = unpack(response.content)
    assert json.loads(archive.read("snapshot.json")) == body["snapshot"]
    assert manifest["source_authenticity_verified"] is False
    assert manifest["provenance"] == "client_supplied_snapshot"
    assert manifest["export_status"] == "success"
    assert manifest["queries"][2]["total_found"] is None
    for p in manifest["plots"]:
        assert p["valid_count"] == 99 and p["skipped_count"] == 1
        assert len(p["included_source_ids"]) == 99
        with Image.open(BytesIO(archive.read(p["output_path"]))) as image:
            assert image.size == (1200, 900)
            assert image.convert("RGB").getextrema()[0][0] < 100
            assert image.info["dpi"] == pytest.approx((150, 150), abs=0.1)
    histogram = manifest["plots"][1]
    assert sum(histogram["parameters"]["bin_counts"]) == 99
    assert histogram["parameters"]["bin_edges"][0] < 0
    for family in ("simbad", "ads", "gaia"):
        content = archive.read(f"tables/{family}-000.csv")
        assert content.startswith(b"\xef\xbb\xbf") and b"\r\n" in content
    rows = list(csv.DictReader(StringIO(archive.read("tables/gaia-000.csv").decode("utf-8-sig"))))
    assert len(rows) == 100
    assert (
        rows[-1]["source_id"] == "'" + body["snapshot"]["gaia_results"][0]["data"][-1]["source_id"]
    )
    assert rows[0]["pmra"] == "-20.0"
    assert rows[0]["parallax"] == "-2.5"
    assert rows[0]["skipped_reason"] == "non_positive_parallax"
    assert rows[2]["parallax"] == ""
    row = next(csv.DictReader(StringIO(archive.read("tables/simbad-000.csv").decode("utf-8-sig"))))
    assert row["main_id"] == "'" + body["snapshot"]["results"][0]["data"]["main_id"]
    assert row["dec_deg"] == "-20.0"
    row = next(csv.DictReader(StringIO(archive.read("tables/ads-000.csv").decode("utf-8-sig"))))
    assert json.loads(row["authors"]) == ["甲", "乙"]
    assert json.loads(row["doi"]) == ["10.synthetic/example"]
    assert row["abstract"] == "'@合成摘要"
    assert any(c["reason"] == "spreadsheet_formula" for c in manifest["csv_changes"])


@pytest.mark.parametrize(
    "path,value",
    [
        (("extra",), True),
        (("snapshot", "extra"), True),
        (("snapshot", "gaia_results", 0, "source", "extra"), True),
        (("snapshot", "gaia_results", 0, "data", 0, "extra"), True),
        (("snapshot", "gaia_results", 0, "analysis", "statistics", "parallax", "extra"), 1),
        (("snapshot", "literature_results", 0, "papers", 0, "extra"), 1),
        (("snapshot", "results", 0, "data", "extra"), 1),
        (("snapshot", "status"), "partial"),
        (("snapshot", "gaia_results", 0, "returned_count"), 1),
        (("snapshot", "gaia_results", 0, "data", 1, "source_id"), "5853498713190525696"),
        (("snapshot", "gaia_results", 0, "data", 0, "source_id"), 5853498713190525696),
        (("snapshot", "gaia_results", 0, "data", 0, "source_id"), "9223372036854775808"),
        (("snapshot", "gaia_results", 0, "data", 0, "parallax"), float("nan")),
        (("snapshot", "gaia_results", 0, "data", 0, "parallax_error"), -1),
        (("snapshot", "gaia_results", 0, "units", "pmra"), "deg"),
        (("snapshot", "gaia_results", 0, "query", "extra"), True),
        (("snapshot", "gaia_results", 0, "query", "limit"), 101),
        (("snapshot", "gaia_results", 0, "endpoint"), "https://example.invalid"),
        (("snapshot", "gaia_results", 0, "analysis", "sample_size"), 10),
        (("snapshot", "gaia_results", 0, "analysis", "estimate_distance"), False),
        (("snapshot", "gaia_results", 0, "analysis", "distance_estimates", 0, "distance_pc"), 1),
        (("snapshot", "gaia_results", 0, "source", "retrieved_at"), "2026-10-28T08:00:00+08:00"),
        (("snapshot", "literature_results", 0, "returned_count"), 0),
        (("snapshot", "literature_results", 0, "rows"), 11),
        (("snapshot", "results", 0, "status"), "not_found"),
        (("plots", 0, "gaia_result_index"), True),
        (("plots", 0, "gaia_result_index"), 1),
        (("plots", 0, "kind"), "code"),
    ],
)
def test_invalid_snapshots_are_rejected_without_echo(path, value):
    body = synthetic_request()
    target = body
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    with pytest.raises(ServiceError) as caught:
        export_body(json.dumps(body).encode())
    assert caught.value.status_code == 422
    assert "synthetic" not in caught.value.error.message


def test_limits_duplicate_plots_queries_and_required_metadata():
    for mutate in (
        lambda b: b["plots"].append(b["plots"][0]),
        lambda b: b["plots"].__setitem__(1, b["plots"][0]),
        lambda b: b["snapshot"]["gaia_results"].__imul__(11),
        lambda b: b["snapshot"]["gaia_results"][0].pop("units"),
        lambda b: b["snapshot"]["gaia_results"][0]["data"].append(
            b["snapshot"]["gaia_results"][0]["data"][0]
        ),
    ):
        body = synthetic_request()
        mutate(body)
        with pytest.raises(ValueError):
            parse(body)


def test_float_tolerance_and_distance_disabled():
    body = synthetic_request()
    median = body["snapshot"]["gaia_results"][0]["analysis"]["statistics"]["parallax"]
    median["median"] += 1e-13
    parse(body)
    median["median"] += 1e-5
    with pytest.raises(ValueError):
        parse(body)
    body = synthetic_request()
    r = body["snapshot"]["gaia_results"][0]
    r["query"]["estimate_distance"] = False
    r["analysis"] = None
    body["plots"] = []
    archive, manifest = unpack(exports.build_package(parse(body)))
    rows = list(csv.DictReader(StringIO(archive.read("tables/gaia-000.csv").decode("utf-8-sig"))))
    assert all(r["distance_pc"] == "" and r["method"] == "" for r in rows)
    assert manifest["queries"][2]["query"]["estimate_distance"] is False


def test_cross_query_duplicates_kept_and_failed_results_exported():
    body = synthetic_request()
    body["plots"] = []
    body["snapshot"]["gaia_results"].append(deepcopy(body["snapshot"]["gaia_results"][0]))
    archive, _ = unpack(exports.build_package(parse(body)))
    assert archive.read("tables/gaia-000.csv") == archive.read("tables/gaia-001.csv")
    for status in ("error", "not_found"):
        body = synthetic_request()
        snapshot = body["snapshot"]
        snapshot.update(results=[], literature_results=[], sources=[], status="error")
        r = snapshot["gaia_results"][0]
        r.update(
            data=[],
            returned_count=0,
            status=status,
            analysis=None,
            error={"code": "synthetic", "message": "合成失败", "retryable": False},
            has_more=False if status == "not_found" else None,
            truncated=False if status == "not_found" else None,
            archive_overflow=False if status == "not_found" else None,
        )
        archive, manifest = unpack(exports.build_package(parse(body)))
        assert len(archive.namelist()) == 3
        assert manifest["snapshot_status"] == "error" and manifest["export_status"] == "partial"
        assert all(p["reason"] == "query_not_successful" for p in manifest["plots"])


@pytest.mark.parametrize("kind", list(plots.FIELDS))
def test_prepared_coordinates_missing_values_and_rendered_axes(kind, monkeypatch):
    result = parse(synthetic_request()).snapshot.gaia_results[0]
    record = plots.prepare_plot(result, PlotSpec(gaia_result_index=0, kind=kind))
    assert record["valid_count"] == 99 and record["skipped_count"] == 1
    excluded = record["excluded_rows"][0]["source_id"]
    assert excluded not in record["included_source_ids"]
    captured = {}
    original = plots.FigureCanvasAgg.print_png

    def capture(canvas, *args, **kwargs):
        ax = canvas.figure.axes[0]
        captured.update(
            aspect=ax.get_aspect(),
            inverted=ax.yaxis_inverted(),
            offsets=ax.collections[0].get_offsets().tolist() if ax.collections else [],
        )
        return original(canvas, *args, **kwargs)

    monkeypatch.setattr(plots.FigureCanvasAgg, "print_png", capture)
    plots.render_plot(record)
    if kind == "proper_motion":
        assert captured["aspect"] == 1
        assert captured["offsets"] == record["coordinates"]
    if kind == "observed_cmd":
        assert captured["inverted"]


def test_histogram_constant_single_missing_and_extreme():
    result = parse(synthetic_request()).snapshot.gaia_results[0]
    spec = PlotSpec(gaia_result_index=0, kind="parallax_histogram")
    result.data = [
        GaiaSourceData(source_id=str(i), ra=0, dec=0, ref_epoch=2016, parallax=2) for i in (1, 2)
    ]
    record = plots.prepare_plot(result, spec)
    assert record["parameters"]["bin_edges"] == [1.5, 2.5]
    assert record["parameters"]["bin_counts"] == [2]
    result.data.pop()
    assert plots.prepare_plot(result, spec)["reason"] == "insufficient_data"
    result.data[0].parallax = None
    assert plots.prepare_plot(result, spec)["valid_count"] == 0
    result.data = [
        GaiaSourceData(source_id=str(i), ra=0, dec=0, ref_epoch=2016, parallax=v)
        for i, v in ((1, -1.7e308), (2, 1.7e308))
    ]
    record = plots.prepare_plot(result, spec)
    assert record["reason"] == "unrepresentable_range"
    assert record["valid_count"] == 2 and record["skipped_count"] == 0
    result.data[0].parallax, result.data[1].parallax = 1e-320, 2e-320
    assert plots.prepare_plot(result, spec)["reason"] == "unrepresentable_range"


@pytest.mark.parametrize(
    "raw",
    [b'{"schema_version":"1","schema_version":"1"}', b"[" * 65 + b"]" * 65, b"{", b"NaN", b"\xff"],
)
def test_malformed_json_controlled(raw):
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/exports", content=raw, headers={"Content-Type": "application/json"}
        )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_export_snapshot"


def test_http_stream_limits_and_media():
    with TestClient(app) as client:
        for headers in (
            {"Content-Type": "text/plain"},
            {"Content-Type": "application/json", "Content-Encoding": "gzip"},
        ):
            assert client.post("/api/v1/exports", content=b"{}", headers=headers).status_code == 415
        response = client.post(
            "/api/v1/exports",
            content=iter([b" " * 65536] * 33),
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 413
        assert client.get("/health").status_code == 200


def test_real_concurrency_busy_and_release(monkeypatch):
    started, release = threading.Event(), threading.Event()
    original = exports._build_package

    def delayed(request):
        started.set()
        assert release.wait(5)
        return original(request)

    body = synthetic_request()
    body["plots"] = []
    request = parse(body)
    monkeypatch.setattr(exports, "_build_package", delayed)
    outcome = []
    thread = threading.Thread(target=lambda: outcome.append(exports.build_package(request)))
    thread.start()
    assert started.wait(5)
    try:
        with pytest.raises(ServiceError, match="导出正忙") as caught:
            exports.build_package(request)
        assert caught.value.status_code == 503
    finally:
        release.set()
        thread.join(10)
    assert not thread.is_alive() and outcome
    unpack(outcome[0])
    assert not exports.EXPORT_LOCK.locked()


def test_render_failure_package_failure_and_locks(monkeypatch):
    def fail(*args, **kwargs):
        raise RuntimeError("sensitive internal details")

    request = parse(synthetic_request())
    monkeypatch.setattr(exports, "render_plot", fail)
    archive, manifest = unpack(exports.build_package(request))
    assert manifest["export_status"] == "partial"
    assert all(p["reason"] == "render_failed" for p in manifest["plots"])
    assert "sensitive" not in archive.read("manifest.json").decode()
    with monkeypatch.context() as m:
        m.setattr(exports, "ZipFile", fail)
        with pytest.raises(ServiceError) as caught:
            exports.build_package(request)
        assert caught.value.status_code == 500 and "sensitive" not in str(caught.value)
    assert not exports.EXPORT_LOCK.locked()
    unpack(exports.build_package(request))


def test_package_size_both_limits(monkeypatch):
    body = synthetic_request()
    body["plots"] = []
    request = parse(body)
    with monkeypatch.context() as m:
        m.setattr(exports, "MAX_PACKAGE_BYTES", 100)
        with pytest.raises(ServiceError) as caught:
            exports.build_package(request)
        assert caught.value.status_code == 413
    with monkeypatch.context() as m:
        m.setattr(exports, "MAX_PACKAGE_BYTES", 3)
        with pytest.raises(ServiceError):
            exports.LimitedBuffer().write(b"1234")
    assert not exports.EXPORT_LOCK.locked()


def test_openapi_binary_contract():
    with TestClient(app) as client:
        schema = client.get("/openapi.json").json()
    operation = schema["paths"]["/api/v1/exports"]["post"]
    assert (
        operation["responses"]["200"]["content"]["application/zip"]["schema"]["format"] == "binary"
    )
    assert operation["requestBody"]["required"]

    # All JSON schema references must resolve at the document root, including export-only models.
    def walk(node):
        if isinstance(node, dict):
            if "$ref" in node:
                target = schema
                for key in node["$ref"].removeprefix("#/").split("/"):
                    target = target[key]
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(schema)


def test_ads_empty_page_contract_and_concept_only():
    body = synthetic_request()
    body["plots"] = []
    snapshot = body["snapshot"]
    snapshot.update(status="error", results=[], gaia_results=[], sources=[])
    result = snapshot["literature_results"][0]
    result.update(status="not_found", papers=[], returned_count=0, total_found=0, has_more=False)
    archive, manifest = unpack(exports.build_package(parse(body)))
    assert set(archive.namelist()) == {"snapshot.json", "manifest.json", "README.md"}
    assert manifest["snapshot_status"] == "error" and manifest["export_status"] == "success"
    snapshot.update(status="success", literature_results=[])
    unpack(exports.build_package(parse(body)))


@pytest.mark.parametrize(
    "text",
    [
        "=1+1",
        "+cmd",
        "-text",
        "@SUM(A1)",
        "\tplain",
        "\rplain",
        "   =1",
        "\n@value",
        "\u2003+value",
    ],
)
def test_csv_formula_prefix_and_exact_json(text):
    changes = []
    content = exports.csv_bytes(
        "tables/simbad-000.csv", ["value", "number"], [{"value": text, "number": -12.5}], changes
    )
    row = next(csv.DictReader(StringIO(content.decode("utf-8-sig"))))
    assert row == {"value": "'" + text, "number": "-12.5"}
    assert changes == [
        {
            "file": "tables/simbad-000.csv",
            "data_row": 1,
            "column": "value",
            "reason": "spreadsheet_formula",
        }
    ]


def test_historical_v03_snapshots_remain_exportable():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / "docs/test-records/v0.3.0"
    for name in ("model-source.json", "model-name.json", "model-three-tools.json"):
        recorded = json.loads(
            (root / "live-gaia-tests/20261028T035108550097Z" / name).read_text(encoding="utf-8")
        )
        request = {"schema_version": "1", "snapshot": recorded["body"], "plots": []}
        archive, _ = unpack(exports.build_package(parse(request)))
        assert json.loads(archive.read("snapshot.json")) == recorded["body"]
