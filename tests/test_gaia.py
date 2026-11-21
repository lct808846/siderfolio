"""Gaia 参数、实际 HTTP 约束、TAP 状态、严格字段转换和截断。"""

import math
from io import BytesIO

import pytest
import requests
from astropy.io.votable import parse, writeto
from gaia_fixtures import SOURCE_ID, FakeResponse, FakeSession, execute, source_row, votable
from pydantic import ValidationError
from urllib3.exceptions import ReadTimeoutError

from astroagent.gaia import (
    GAIA_COLUMNS,
    GAIA_ENDPOINT,
    MAX_RESPONSE_BYTES,
    GaiaService,
    build_adql,
)
from astroagent.schemas import GaiaQuery


def cone(**kwargs):
    return GaiaQuery(mode="cone", ra_deg=56.75, dec_deg=24.12, radius_arcmin=5, **kwargs)


@pytest.mark.parametrize(
    "bad",
    [
        {"mode": "unknown"},
        {"mode": "source_id"},
        *[
            {"mode": "source_id", "source_id": value}
            for value in [
                0,
                5853498713190525696,
                1.2,
                True,
                "0",
                "01",
                "-1",
                "1e10",
                "１",
                "1 OR 1=1",
                "9223372036854775808",
                "99999999999999999999",
            ]
        ],
        *[
            {"mode": "source_id", "source_id": SOURCE_ID, key: value}
            for key, value in [
                ("limit", 20),
                ("ra_deg", None),
                ("ruwe_max", 1.4),
                ("dec_deg", 2),
                ("radius_arcmin", 1),
                ("parallax_snr_min", 10),
                ("sql", "SELECT *"),
            ]
        ],
        {"mode": "cone", "ra_deg": 1, "dec_deg": 2},
        {"mode": "cone", "ra_deg": 1, "dec_deg": 2, "radius_arcmin": 1, "source_id": None},
    ],
)
def test_query_rejects_invalid_modes_ids_and_cross_mode_fields(bad):
    with pytest.raises(ValidationError):
        GaiaQuery.model_validate(bad)


@pytest.mark.parametrize(
    "name,values",
    [
        ("ra_deg", [-1, 360, True, "5", math.nan, math.inf]),
        ("dec_deg", [-91, 91, False, "0", math.inf]),
        ("radius_arcmin", [0, -1, 30.01, True, "2", math.nan]),
        ("ruwe_max", [0, -1, 10.1, True, "1.4", math.inf]),
        ("parallax_snr_min", [0, 1001, True, "10", math.nan]),
        ("limit", [0, 501, 1.0, True, "20"]),
        ("estimate_distance", [1, 0, "true", None]),
    ],
)
def test_query_strict_types_and_finite_boundaries(name, values):
    for value in values:
        arguments = {"mode": "cone", "ra_deg": 1, "dec_deg": 2, "radius_arcmin": 1, name: value}
        with pytest.raises(ValidationError):
            GaiaQuery.model_validate(arguments)


def test_query_valid_boundaries_and_effective_defaults():
    query = GaiaQuery(mode="source_id", source_id=" 9223372036854775807 ")
    assert query.effective_parameters() == {
        "mode": "source_id",
        "source_id": "9223372036854775807",
        "estimate_distance": False,
    }
    for dec in (-90, 90):
        query = GaiaQuery(
            mode="cone",
            ra_deg=0,
            dec_deg=dec,
            radius_arcmin=30,
            limit=500,
            ruwe_max=10,
            parallax_snr_min=1000,
        )
        assert query.limit == 500


def test_cone_filters_constrain_adql_and_effective_parameters():
    filters = {
        "parallax_min": 0.5,
        "parallax_max": 2.0,
        "pmra_min": -3.0,
        "pmra_max": 3.0,
        "pmdec_min": -4.0,
        "pmdec_max": 4.0,
        "g_mag_max": 18.0,
    }
    query = cone(limit=500, **filters)
    adql, requested = build_adql(query)
    assert requested == 501
    assert adql.startswith("SELECT TOP 501 ")
    assert "AND parallax >= 0.5 AND parallax <= 2.0" in adql
    assert "AND pmra >= -3.0 AND pmra <= 3.0" in adql
    assert "AND pmdec >= -4.0 AND pmdec <= 4.0" in adql
    assert "AND phot_g_mean_mag <= 18.0" in adql
    assert {key: query.effective_parameters()[key] for key in filters} == filters


@pytest.mark.parametrize("field", ["parallax", "pmra", "pmdec"])
def test_inverted_cone_filter_ranges_are_rejected(field):
    with pytest.raises(ValidationError, match=f"{field}_min"):
        cone(**{f"{field}_min": 2, f"{field}_max": 1})


def test_fixed_adql_and_http_contract(monkeypatch):
    session = FakeSession(FakeResponse(votable(cone=True)))
    monkeypatch.setattr(requests, "Session", lambda: session)
    query = cone(limit=2, ruwe_max=1.4, parallax_snr_min=10)
    result = GaiaService(timeout=7).query(query)
    assert result.status == "success", result.model_dump_json()
    args, options = session.calls[0]
    assert args == (GAIA_ENDPOINT,)
    assert options["timeout"] == (7, 7)
    assert options["allow_redirects"] is False and options["stream"] is True
    assert "verify" not in options  # requests defaults to TLS verification
    assert options["data"] == {
        "REQUEST": "doQuery",
        "LANG": "ADQL",
        "FORMAT": "votable",
        "MAXREC": 3,
        "QUERY": result.adql,
    }
    assert session.closed and session.response.closed
    assert "SELECT TOP 3 " in result.adql and "SELECT *" not in result.adql
    assert "gaiadr3.gaia_source" in result.adql
    assert "0.08333333333333333" in result.adql
    assert "AND ruwe <= 1.4" in result.adql
    assert "parallax > 0 AND parallax_error > 0" in result.adql
    assert "parallax / parallax_error >= 10.0" in result.adql
    assert result.adql.endswith("ORDER BY separation_deg ASC, source_id ASC")
    assert all(column in result.adql for column in GAIA_COLUMNS)
    adql, maximum = build_adql(GaiaQuery(mode="source_id", source_id=SOURCE_ID))
    assert maximum == 2 and f"WHERE source_id = {SOURCE_ID}" in adql
    assert "separation" not in adql and "ruwe <=" not in adql
    adql, _ = build_adql(cone())
    assert "AND ruwe <=" not in adql and "AND parallax >" not in adql


def test_fresh_production_session_has_no_retries():
    with requests.Session() as session:
        assert session.get_adapter(GAIA_ENDPOINT).max_retries.total == 0


def test_all_fields_precision_missing_nonfinite_and_units():
    row = source_row(
        parallax=-2,
        ra_error=0.2,
        dec_error=0.3,
        pmra_error=0.1,
        pmdec_error=0.2,
        phot_g_mean_mag=12.1,
        phot_bp_mean_mag=13,
        phot_rp_mean_mag=11,
        bp_rp=2,
        radial_velocity=math.inf,
        radial_velocity_error=math.nan,
        duplicated_source=True,
    )
    result, _, response = execute(votable([row]))
    assert result.status == "success", result.model_dump_json()
    data = result.data[0]
    assert data.source_id == SOURCE_ID and f'"{SOURCE_ID}"' in result.model_dump_json()
    assert data.parallax == -2 and data.pmra == 2
    assert data.ref_epoch == 2016 and data.separation_arcsec is None
    assert data.duplicated_source is True and data.astrometric_params_solved == 31
    assert data.radial_velocity is None and data.radial_velocity_error is None
    assert data.phot_g_mean_mag == 12.1 and data.bp_rp == 2
    assert result.units["parallax"] == "mas" and result.units["pmra"] == "mas/yr"
    assert result.analysis.negative_parallax_count == 1
    assert (
        result.source.name == "Gaia" and result.source.retrieved_at.utcoffset().total_seconds() == 0
    )
    assert response.closed and "Infinity" not in result.model_dump_json()


def test_decimal_string_source_id_and_empty_optional_cells():
    result, _, _ = execute(
        votable(
            [source_row(duplicated_source=None, astrometric_params_solved=None)],
            types={"source_id": "char"},
        )
    )
    assert result.status == "success", result.model_dump_json()
    assert result.data[0].source_id == SOURCE_ID
    assert result.data[0].duplicated_source is None
    assert result.data[0].astrometric_params_solved is None


def test_esa_computed_distance_alias_without_unit_uses_fixed_adql_degrees():
    result, _, _ = execute(votable(cone=True, units={"separation_deg": ""}), query=cone())
    assert result.status == "success", result.model_dump_json()
    assert result.data[0].separation_arcsec == pytest.approx(3.6)
    assert result.units["separation_arcsec"] == "arcsec"
    result, _, _ = execute(votable(cone=True, units={"separation_deg": "rad"}), query=cone())
    assert result.error.code == "gaia_unexpected_response"


@pytest.mark.parametrize("count,has_more", [(0, False), (1, False), (2, False), (3, True)])
def test_truncation_and_sentinel_excluded_from_statistics(count, has_more):
    rows = [
        source_row(
            source_id=str(int(SOURCE_ID) + i), parallax=float(i + 1), separation_deg=i / 1000
        )
        for i in range(count)
    ]
    result, _, _ = execute(votable(rows, cone=True), query=cone(limit=2, estimate_distance=True))
    assert result.status == ("success" if count else "not_found"), result.model_dump_json()
    assert result.returned_count == min(count, 2)
    assert result.has_more is has_more and result.truncated is has_more
    assert result.total_found is None and result.archive_overflow is False
    if count:
        assert result.analysis.sample_size == min(count, 2)
        assert result.analysis.statistics["parallax"].maximum == min(count, 2)
        assert len(result.analysis.distance_estimates) == min(count, 2)
        assert result.data[-1].separation_arcsec == pytest.approx((min(count, 2) - 1) * 3.6)
    else:
        assert result.error.code == "gaia_not_found" and result.analysis is None


@pytest.mark.parametrize("where", ["before", "after"])
def test_tap_error_checked_before_and_after_table(where):
    result, _, response = execute(votable(**{where: "ERROR"}))
    assert result.status == "error" and result.error.code == "gaia_query_failed"
    assert result.data == [] and response.closed


def test_archive_overflow_and_zero_row_overflow():
    result, _, _ = execute(votable(cone=True, after="OVERFLOW"), query=cone(limit=2))
    assert result.status == "success", result.model_dump_json()
    assert result.has_more and result.truncated and result.archive_overflow
    assert any("OVERFLOW" in warning for warning in result.warnings)
    result, _, _ = execute(votable([], after="OVERFLOW"))
    assert result.error.code == "gaia_unexpected_response"


@pytest.mark.parametrize(
    "name,value",
    [
        ("source_id", "0"),
        ("source_id", "9223372036854775808"),
        ("ra", 360),
        ("ra", math.inf),
        ("ra", None),
        ("dec", -91),
        ("ref_epoch", math.nan),
        ("ref_epoch", None),
        ("ra_error", -0.1),
        ("dec_error", -1),
        ("parallax_error", -1),
        ("pmra_error", -1),
        ("pmdec_error", -1),
        ("radial_velocity_error", -1),
    ],
)
def test_bad_required_values_and_negative_errors_fail_whole_query(name, value):
    result, _, response = execute(votable([source_row(**{name: value})]))
    assert result.status == "error" and result.error.code == "gaia_unexpected_response"
    assert result.returned_count == 0 and result.data == [] and response.closed


@pytest.mark.parametrize(
    "body",
    [
        b"not xml",
        b"<html/>",
        votable(before=None),
        votable(after="UNKNOWN"),
        votable(missing=("ra",)),
        votable(missing=("parallax_error",)),
        votable(types={"source_id": "double"}),
        votable(types={"ra": "char"}),
        votable(types={"duplicated_source": "int"}),
        votable(types={"astrometric_params_solved": "double"}),
        votable(units={"parallax": "arcsec"}),
        votable(units={"ra": "rad"}),
        votable([source_row(source_id=str(int(SOURCE_ID) + 1))]),
        votable([source_row(), source_row()]),
        votable([source_row(), source_row(), source_row()]),
        votable().replace(
            b"<DATA>", b"<DATA><BINARY><STREAM href='https://example.test/x'/></BINARY>"
        ),
        b'<!DOCTYPE VOTABLE [<!ENTITY x SYSTEM "file:///secret">]><VOTABLE>&x;</VOTABLE>',
        b"<!DOCTYPE VOTABLE><VOTABLE/>",
    ],
)
def test_malformed_response_has_safe_error_and_no_partial_data(body):
    result, _, response = execute(body)
    assert result.status == "error", result.model_dump_json()
    assert result.error.code == "gaia_unexpected_response"
    assert result.data == [] and result.has_more is None and response.closed
    assert "secret" not in result.model_dump_json()


@pytest.mark.parametrize(
    "rows",
    [
        [source_row(), source_row()],
        [source_row(separation_deg=0.002), source_row(source_id="2", separation_deg=0.001)],
        [source_row(separation_deg=1)],
        [source_row(separation_deg=-1)],
        [source_row(separation_deg=math.nan)],
        [source_row(source_id=str(i + 1)) for i in range(4)],
    ],
)
def test_bad_cone_rows_are_not_silently_repaired(rows):
    result, _, _ = execute(votable(rows, cone=True), query=cone(limit=2))
    assert result.error.code == "gaia_unexpected_response"


@pytest.mark.parametrize(
    "row,options",
    [
        (source_row(ruwe=None), {"ruwe_max": 1.4}),
        (source_row(ruwe=2), {"ruwe_max": 1.4}),
        (source_row(parallax=-1), {"parallax_snr_min": 10}),
        (source_row(parallax_error=0), {"parallax_snr_min": 10}),
        (source_row(parallax=1, parallax_error=1), {"parallax_snr_min": 10}),
    ],
)
def test_upstream_filter_contradiction_is_error(row, options):
    result, _, _ = execute(votable([row], cone=True), query=cone(**options))
    assert result.error.code == "gaia_unexpected_response"


@pytest.mark.parametrize(
    "status,code,retryable",
    [
        (400, "gaia_query_failed", False),
        (401, "gaia_access_denied", False),
        (403, "gaia_access_denied", False),
        (429, "gaia_rate_limited", True),
        (500, "gaia_unavailable", True),
        (503, "gaia_unavailable", True),
        (302, "gaia_unexpected_response", False),
        (404, "gaia_unexpected_response", False),
    ],
)
def test_http_error_mapping(status, code, retryable):
    result, _, response = execute(b"raw upstream secret", status=status)
    assert result.error.code == code and result.error.retryable is retryable
    assert "secret" not in result.model_dump_json() and response.closed


@pytest.mark.parametrize(
    "error,code",
    [
        (requests.Timeout("secret"), "gaia_timeout"),
        (requests.ConnectionError("secret"), "gaia_unavailable"),
        (requests.ConnectionError(ReadTimeoutError(None, None, "secret")), "gaia_timeout"),
    ],
)
def test_network_errors_and_session_cleanup(monkeypatch, error, code):
    session = FakeSession(error=error)
    monkeypatch.setattr(requests, "Session", lambda: session)
    result = GaiaService().query(GaiaQuery(mode="source_id", source_id=SOURCE_ID))
    assert result.error.code == code and result.error.retryable
    assert "secret" not in result.model_dump_json() and session.closed


def test_response_limit_aborts_stream_and_closes_connection(monkeypatch):
    def chunks():
        yield b"x" * MAX_RESPONSE_BYTES
        yield b"x"
        raise AssertionError("Oversized stream should not be consumed further")

    response = FakeResponse(chunks=chunks())
    session = FakeSession(response)
    monkeypatch.setattr(requests, "Session", lambda: session)
    result = GaiaService().query(GaiaQuery(mode="source_id", source_id=SOURCE_ID))
    assert result.error.code == "gaia_response_too_large"
    assert response.closed and session.closed


def test_stream_read_timeout_closes_response():
    def chunks():
        yield b"partial"
        raise requests.ConnectionError(ReadTimeoutError(None, None, "private"))

    result, _, response = execute(chunks=chunks())
    assert result.error.code == "gaia_timeout" and response.closed


@pytest.mark.parametrize(
    "body",
    [
        votable().replace(b"<TABLE>", b'<TABLE nrows="999999999">'),
        votable().replace(b"<TABLE>", b'<TABLE nrows="-1">'),
        votable().replace(b'<FIELD name="ra"', b'<FIELD arraysize="999999999" name="ra"'),
    ],
)
def test_votable_allocation_hints_cannot_exceed_query_budget(body):
    result, _, _ = execute(body)
    assert result.error.code == "gaia_unexpected_response"


def test_binary2_masks_and_different_field_id_match_esa_layout():
    xml = votable([source_row(parallax=None, duplicated_source=None)])
    xml = xml.replace(b'ID="source_id"', b'ID="SOURCE_ID"')
    parsed = parse(BytesIO(xml), verify="exception")
    stream = BytesIO()
    writeto(parsed, stream, tabledata_format="binary2")
    result, _, _ = execute(stream.getvalue())
    assert result.status == "success", result.model_dump_json()
    assert result.data[0].source_id == SOURCE_ID
    assert result.data[0].parallax is result.data[0].duplicated_source is None


def test_unknown_scalar_column_does_not_enter_api_or_model_data():
    xml = votable().replace(b"<DATA>", b'<FIELD name="extra" datatype="double"/><DATA>')
    xml = xml.replace(b"</TR>", b"<TD>42</TD></TR>")
    result, _, _ = execute(xml)
    assert result.status == "success", result.model_dump_json()
    assert "extra" not in result.data[0].model_dump()
