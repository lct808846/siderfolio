"""合成数据的统计、距离条件和极端值；不把视场统计当总体推断。"""

import pytest

from astroagent.analysis import analyze_sources
from astroagent.schemas import GaiaQuery, GaiaSourceData


def source(index=1, **values):
    return GaiaSourceData(source_id=str(index), ra=0.0, dec=0.0, ref_epoch=2016.0, **values)


def query(enabled=True):
    return GaiaQuery(
        mode="cone", ra_deg=0, dec_deg=0, radius_arcmin=1, ruwe_max=1.4, estimate_distance=enabled
    )


def test_statistics_full_sample_missing_negative_zero_and_scope():
    rows = [
        source(1, parallax=-2, pmra=2),
        source(2, parallax=0),
        source(3, parallax=10, pmra=4),
        source(4),
    ]
    found = analyze_sources(rows, query(False), truncated=True)
    stat = found.statistics["parallax"]
    assert (stat.valid_count, stat.missing_count) == (3, 1)
    assert (stat.median, stat.minimum, stat.maximum, stat.unit) == (0, -2, 10, "mas")
    assert found.statistics["pmra"].median == 3
    empty = found.statistics["radial_velocity"]
    assert empty.valid_count == 0 and empty.missing_count == 4
    assert empty.median is empty.minimum is empty.maximum is None
    assert (
        found.negative_parallax_count
        == found.zero_parallax_count
        == found.missing_parallax_count
        == 1
    )
    assert found.sample_size == 4 and found.scope == "returned_rows" and found.truncated
    assert found.quality_filters == {"ruwe_max": 1.4}
    assert found.distance_estimates == [] and found.distance_computed_count == 0
    assert found.distance_skipped_count == 0 and found.estimate_distance is False


@pytest.mark.parametrize(
    "p,e,reason",
    [
        (None, None, "missing_parallax"),
        (None, 1, "missing_parallax"),
        (-1, None, "non_positive_parallax"),
        (0, 0, "non_positive_parallax"),
        (1, None, "invalid_or_missing_error"),
        (1, 0, "invalid_or_missing_error"),
        (1, 0.10001, "low_parallax_snr"),
        (10, 1, None),
        (10, 0.5, None),
    ],
)
def test_distance_first_failure_reason_and_snr_boundary(p, e, reason):
    found = analyze_sources([source(parallax=p, parallax_error=e)], query(), truncated=False)
    distance = found.distance_estimates[0]
    assert distance.source_id == "1" and distance.skipped_reason == reason
    assert distance.method == "inverse_parallax_high_snr" and not distance.zero_point_corrected
    if reason:
        assert distance.distance_pc is distance.distance_error_pc is None
        assert found.distance_skipped_count == 1 and found.distance_computed_count == 0
    else:
        assert distance.distance_pc == 100
        assert distance.distance_error_pc == pytest.approx(10 if e == 1 else 5)
        assert found.distance_computed_count == 1 and found.distance_skipped_count == 0


def test_empty_and_single_samples():
    empty = analyze_sources([], query(), truncated=False)
    assert empty.sample_size == 0 and empty.distance_estimates == []
    single = analyze_sources([source(parallax=2)], query(False), truncated=False)
    assert single.statistics["parallax"].median == 2


def test_extreme_finite_values_remain_json_serializable():
    rows = [
        source(1, parallax=1e308),
        source(2, parallax=1e308),
        source(3, parallax=1e-310, parallax_error=1e-312),
    ]
    found = analyze_sources(rows, query(), truncated=False)
    assert found.statistics["parallax"].median == 1e308
    assert found.distance_estimates[-1].skipped_reason == "numerical_overflow"
    assert "Infinity" not in found.model_dump_json() and "NaN" not in found.model_dump_json()


def test_median_keeps_tiny_values_in_wide_dynamic_range():
    rows = [source(1, parallax=1e-310), source(2, parallax=1e-310), source(3, parallax=1e308)]
    assert (
        analyze_sources(rows, query(False), truncated=False).statistics["parallax"].median == 1e-310
    )
