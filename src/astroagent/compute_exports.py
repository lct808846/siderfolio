"""Derive fixed, inert SVG plots and a self-contained experiment archive."""

import csv
import hashlib
import io
import json
import math
import zipfile
from html import escape

from astroagent.compute_schemas import MAX_OUTPUT_BYTES
from astroagent.errors import ServiceError

COLORS = ("#287567", "#a7633a", "#4c68ab", "#a44363", "#577139", "#755ba3")
UNITS = {
    "position": "AU",
    "time": "yr",
    "mass": "M_sun",
    "velocity": "AU/yr",
    "energy": "M_sun AU²/yr²",
    "angular_momentum": "M_sun AU²/yr",
}


def plot_svg(row, kind, sample_index=None):
    samples = row["result"]["samples"]
    particles = row["parameters"]["particles"]
    selected = max(
        0, min(len(samples) - 1, sample_index if sample_index is not None else len(samples) - 1)
    )
    if kind == "energy":
        relative = samples[0]["energy_relative"] is not None
        key = "energy_relative" if relative else "energy_delta"
        series = [[(sample["time"], sample[key]) for sample in samples]]
        title = "能量偏差"
        ylabel = "ΔE / |E₀|" if relative else "ΔE (M_sun AU²/yr²)"
        xlabel = "t (yr)"
    else:
        series = [
            [tuple(sample["particles"][index]["position"][:2]) for sample in samples]
            for index in range(len(particles))
        ]
        title = (
            "XY 轨迹"
            if kind == "trajectory"
            else f"XY 位置快照 · {samples[selected]['time']:.5g} yr"
        )
        xlabel, ylabel = "X (AU)", "Y (AU)"

    xmin = min(point[0] for line in series for point in line)
    xmax = max(point[0] for line in series for point in line)
    ymin = min(point[1] for line in series for point in line)
    ymax = max(point[1] for line in series for point in line)
    left, top, width, height = 92, 45, 626, 295
    xspan, yspan = max(xmax - xmin, 1e-20) * 1.05, max(ymax - ymin, 1e-20) * 1.05
    if kind != "energy":
        scale = max(xspan / width, yspan / height, 1e-12)
        xspan, yspan = width * scale, height * scale
    x0, y0 = (xmax + xmin - xspan) / 2, (ymax + ymin - yspan) / 2

    def coordinates(point):
        return left + (point[0] - x0) / xspan * width, top + height - (
            point[1] - y0
        ) / yspan * height

    pieces = [
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 750 402" role="img">',
        f"<title>{escape(title)}</title>",
        '<rect width="750" height="402" fill="#fafcf9" rx="14"/>',
        '<g font-family="system-ui,sans-serif" font-size="13" fill="#344d44">',
        f'<text x="{left}" y="28" font-size="16">{escape(title)}</text>',
    ]
    for step in range(5):
        fraction = step / 4
        x, y = left + width * fraction, top + height * (1 - fraction)
        pieces.extend(
            [
                f'<path d="M{x:g} {top}v{height} M{left} {y:g}h{width}" stroke="#dce5df"/>',
                f'<text x="{x:g}" y="360" text-anchor="middle">{x0 + xspan * fraction:.3g}</text>',
                f'<text x="83" y="{y + 4:g}" text-anchor="end">{y0 + yspan * fraction:.3g}</text>',
            ]
        )
    pieces.extend(
        [
            f'<text x="{left + width / 2:g}" y="386" text-anchor="middle">{escape(xlabel)}</text>',
            '<text x="20" y="196" text-anchor="middle" transform="rotate(-90 20 196)">'
            f"{escape(ylabel)}</text>",
        ]
    )
    for index, line in enumerate(series):
        color = COLORS[index % len(COLORS)]
        label = particles[index]["id"] if kind != "energy" else "能量偏差"
        if kind == "snapshot":
            x, y = coordinates(line[selected])
            pieces.append(
                f'<circle cx="{x:.2f}" cy="{y:.2f}" r="4.5" fill="{color}">'
                f"<title>{escape(label)}</title></circle>"
            )
        else:
            points = " ".join(f"{x:.2f},{y:.2f}" for x, y in map(coordinates, line))
            pieces.append(
                f'<polyline fill="none" stroke="{color}" stroke-width="1.5" points="{points}">'
                f"<title>{escape(label)}</title></polyline>"
            )
    pieces.append("</g></svg>")
    return "".join(pieces).encode("utf-8")


def csv_bytes(header, rows):
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(header)
    writer.writerows(rows)
    return output.getvalue().encode("utf-8")


def snapshot_csv(row):
    samples = row["result"]["samples"]
    particles = row["parameters"]["particles"]
    return csv_bytes(
        [
            "time_yr",
            "particle_id",
            "mass_M_sun",
            "x_AU",
            "y_AU",
            "z_AU",
            "vx_AU_per_yr",
            "vy_AU_per_yr",
            "vz_AU_per_yr",
        ],
        (
            (
                sample["time"],
                particle["id"],
                particle["mass"],
                *state["position"],
                *state["velocity"],
            )
            for sample in samples
            for particle, state in zip(particles, sample["particles"], strict=True)
        ),
    )


def experiment_zip(row, plots, snapshot_index=None):
    result = row["result"]
    samples = result["samples"]
    engine = result.get("engine", "rebound")
    files = {
        "input.json": json.dumps(
            {
                "parameters": row["parameters"],
                "units": UNITS,
                "reference_frame": "input inertial Cartesian frame",
                "random_seed": None,
                "softening": 0,
                "close_encounter": "regularization" if engine == "petar" else "stop",
            },
            ensure_ascii=False,
            indent=2,
        ).encode(),
        "snapshots.csv": snapshot_csv(row),
        "diagnostics.csv": csv_bytes(
            [
                "time_yr",
                "energy",
                "Lx",
                "Ly",
                "Lz",
                "energy_delta",
                "energy_relative",
                "angular_delta",
                "angular_relative",
            ],
            (
                (
                    s["time"],
                    s["energy"],
                    *s["angular_momentum"],
                    s["energy_delta"],
                    s["energy_relative"],
                    s["angular_delta"],
                    s["angular_relative"],
                )
                for s in samples
            ),
        ),
    }
    for kind in sorted(set(plots)):
        files[kind + ".svg"] = plot_svg(row, kind, snapshot_index if kind == "snapshot" else None)
    manifest = {
        "format_version": 1,
        "astroagent_version": result["astroagent_version"],
        "engine": engine,
        "task_id": str(row["id"]),
        "attempt_id": str(row["attempt_id"]),
        "source_task_id": str(row["origin_id"]) if row["origin_id"] else None,
        "parameter_sha256": row["parameter_sha256"],
        "created_at": row["created_at"].isoformat(),
        "started_at": row["started_at"].isoformat(),
        "finished_at": row["finished_at"].isoformat(),
        "events": row["events"],
        "units": UNITS,
        "numerics": {key: value for key, value in result.items() if key != "samples"},
        "max_energy_absolute_delta": max(abs(s["energy_delta"]) for s in samples),
        "max_angular_absolute_delta": max(s["angular_delta"] for s in samples),
        "initial_angular_momentum_norm": math.hypot(*samples[0]["angular_momentum"]),
        "files": [
            {
                "name": name,
                "bytes": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
                "media_type": {
                    "json": "application/json",
                    "csv": "text/csv",
                    "svg": "image/svg+xml",
                }[name.rsplit(".", 1)[1]],
            }
            for name, data in files.items()
        ],
    }
    files["manifest.json"] = json.dumps(manifest, ensure_ascii=False, indent=2).encode()
    if sum(map(len, files.values())) > MAX_OUTPUT_BYTES:
        raise ServiceError(413, "compute_archive_limit", "实验包超过 32 MiB，请减少所选图表。")
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    return output.getvalue()
