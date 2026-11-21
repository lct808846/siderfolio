"""仅描述实际交付行的统计与高信噪比视差倒数近似，不访问外部服务。"""

import math

from astroagent.schemas import (
    GaiaAnalysis,
    GaiaDistanceEstimate,
    GaiaQuery,
    GaiaSourceData,
    GaiaStatistic,
)

STATISTIC_UNITS = {
    "parallax": "mas",
    "pmra": "mas/yr",
    "pmdec": "mas/yr",
    "phot_g_mean_mag": "mag",
    "bp_rp": "mag",
    "radial_velocity": "km/s",
}


def estimate_distance(source: GaiaSourceData) -> GaiaDistanceEstimate:
    p, e = source.parallax, source.parallax_error
    reason = None
    if p is None or not math.isfinite(p):
        reason = "missing_parallax"
    elif p <= 0:
        reason = "non_positive_parallax"
    elif e is None or not math.isfinite(e) or e <= 0:
        reason = "invalid_or_missing_error"
    elif p / e < 10:
        reason = "low_parallax_snr"
    if reason:
        return GaiaDistanceEstimate(source_id=source.source_id, skipped_reason=reason)
    # This equivalent order avoids p**2 underflow/overflow for extreme finite inputs.
    distance = 1000 / p
    error = distance * (e / p)
    if not math.isfinite(distance) or not math.isfinite(error):
        return GaiaDistanceEstimate(source_id=source.source_id, skipped_reason="numerical_overflow")
    return GaiaDistanceEstimate(
        source_id=source.source_id, distance_pc=distance, distance_error_pc=error
    )


def analyze_sources(
    sources: list[GaiaSourceData], query: GaiaQuery, *, truncated: bool
) -> GaiaAnalysis:
    statistics = {}
    for name, unit in STATISTIC_UNITS.items():
        values = [getattr(source, name) for source in sources]
        valid = [value for value in values if value is not None and math.isfinite(value)]
        # Preserve tiny values and avoid overflow when averaging a finite even pair.
        middle = None
        if valid:
            ordered = sorted(valid)
            n = len(ordered)
            middle = ordered[n // 2]
            if n % 2 == 0:
                a, b = ordered[n // 2 - 1 : n // 2 + 1]
                middle = a + (b - a) / 2 if (a >= 0) == (b >= 0) else (a + b) / 2
        statistics[name] = GaiaStatistic(
            valid_count=len(valid),
            missing_count=len(values) - len(valid),
            median=middle,
            minimum=min(valid) if valid else None,
            maximum=max(valid) if valid else None,
            unit=unit,
        )
    distances = [estimate_distance(source) for source in sources] if query.estimate_distance else []
    return GaiaAnalysis(
        sample_size=len(sources),
        truncated=truncated,
        quality_filters={
            name: value
            for name in (
                "ruwe_max",
                "parallax_snr_min",
                "parallax_min",
                "parallax_max",
                "pmra_min",
                "pmra_max",
                "pmdec_min",
                "pmdec_max",
                "g_mag_max",
            )
            if (value := getattr(query, name)) is not None
        },
        statistics=statistics,
        negative_parallax_count=sum(s.parallax is not None and s.parallax < 0 for s in sources),
        zero_parallax_count=sum(s.parallax == 0 for s in sources),
        missing_parallax_count=sum(s.parallax is None for s in sources),
        estimate_distance=query.estimate_distance,
        distance_estimates=distances,
        distance_computed_count=sum(d.skipped_reason is None for d in distances),
        distance_skipped_count=sum(d.skipped_reason is not None for d in distances),
    )
