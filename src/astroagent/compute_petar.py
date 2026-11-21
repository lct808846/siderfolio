"""Translate the fixed AstroAgent experiment contract to the pinned PeTar executable."""

import math
import subprocess
from itertools import combinations
from pathlib import Path

from astroagent.compute_schemas import PETAR_KEPLER_STEPS, G, SimulationParameters

PETAR_EXECUTABLE = Path("/opt/petar/bin/petar")
SNAPSHOT_COLUMNS = 20


class PeTarError(RuntimeError):
    pass


def power_of_two(value: float) -> float:
    return math.ldexp(1.0, math.frexp(value)[1] - 1)


def write_initial_conditions(path: Path, params: SimulationParameters, time_scale: float) -> None:
    with path.open("w", encoding="ascii") as stream:
        stream.write(f"0 {len(params.particles)} 0\n")
        for index, particle in enumerate(params.particles, start=1):
            values = (
                particle.mass,
                *particle.position,
                *(v * time_scale for v in particle.velocity),
            )
            # The FPSoft format appends acceleration, potentials and the neighbor
            # count to the particle's binary state, search radius, ID and group data.
            particle_columns = (0, 0, index, 0, 0, 0, 0)
            force_columns = (0, 0, 0, 0, 0, 0)
            stream.write(" ".join(map(repr, (*values, *particle_columns, *force_columns))) + "\n")


def read_snapshot(
    path: Path, params: SimulationParameters, native_time: float, time_scale: float
) -> list[dict]:
    count = len(params.particles)
    try:
        if path.stat().st_size > 1024 * (count + 1):
            raise ValueError("Oversized snapshot")
        header, *rows = path.read_text(encoding="ascii").splitlines()
        _, particle_count, time = header.split()
        if int(particle_count) != count or len(rows) != count or float(time) != native_time:
            raise ValueError("Invalid snapshot grid")
        states = {}
        for row in rows:
            columns = row.split()
            if len(columns) != SNAPSHOT_COLUMNS:
                raise ValueError("Unexpected particle format")
            index = int(columns[9]) - 1
            if index in states or not 0 <= index < count:
                raise ValueError("Invalid particle ID")
            mass, x, y, z, vx, vy, vz = map(float, columns[:7])
            if mass != params.particles[index].mass:
                raise ValueError("Mass changed")
            states[index] = {
                "position": [x, y, z],
                "velocity": [vx / time_scale, vy / time_scale, vz / time_scale],
            }
    except (OSError, ValueError) as exc:
        raise PeTarError("PeTar 快照的时间或粒子数据不完整。") from exc
    return [states[index] for index in range(count)]


def simulate(params: SimulationParameters, workspace: Path):
    # A dyadic native grid avoids PeTar rounding the requested output interval down.
    # One native time unit equals time_scale years, so v and G scale by s and s².
    interval = params.duration / (params.samples - 1)
    output_step = power_of_two(interval)
    time_scale = interval / output_step
    dynamical_time = min(
        math.sqrt(math.dist(a.position, b.position) ** 3 / (G * (a.mass + b.mass)))
        for a, b in combinations(params.particles, 2)
    )
    # Cap the tree step independently of output cadence to resolve the fastest initial pair.
    tree_step = power_of_two(min(interval / 8, dynamical_time / 1024) / time_scale)
    write_initial_conditions(workspace / "initial.dat", params, time_scale)
    try:
        subprocess.run(
            [
                str(PETAR_EXECUTABLE),
                "-u",
                "0",
                "-G",
                str(G * time_scale**2),
                "-t",
                str(output_step * (params.samples - 1)),
                "-o",
                str(output_step),
                "-s",
                str(tree_step),
                "--nstep-dt-soft-kepler",
                str(PETAR_KEPLER_STEPS),
                "--soft-eps",
                "0",
                "--detect-interrupt",
                "0",
                "--write-group-info",
                "0",
                "-w",
                "1",
                "-i",
                "1",
                "-a",
                "0",
                "initial.dat",
            ],
            check=True,
            cwd=workspace,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise PeTarError("PeTar 未能完成积分，请核对初始条件或缩短模拟时长。") from exc
    return (
        {"tree_step_yr": tree_step * time_scale, "time_scale_yr": time_scale},
        (
            read_snapshot(workspace / f"data.{index}", params, index * output_step, time_scale)
            for index in range(params.samples)
        ),
    )
