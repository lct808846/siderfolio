"""Run a single validated simulation in an offline, memory-limited child process."""

import math
import os
import platform
import resource
import sys
import time
from itertools import combinations
from pathlib import Path

import rebound

from astroagent import __version__, compute_petar
from astroagent.compute_io import read, write
from astroagent.compute_schemas import (
    ENERGY_WARNING,
    EPSILON,
    MAX_OUTPUT_BYTES,
    MIN_DISTANCE,
    PETAR_KEPLER_STEPS,
    PETAR_REVISION,
    REBOUND_VERSION,
    REBOUND_WHEEL_SHA256,
    ZERO_THRESHOLD,
    G,
    SimulationParameters,
)


def snapshot(time_yr, particles, energy, momentum, initial):
    initial_energy, initial_momentum = initial or (energy, momentum)
    energy_delta = energy - initial_energy
    angular_delta = math.dist(momentum, initial_momentum)
    angular_initial = math.hypot(*initial_momentum)
    if not all(math.isfinite(value) for value in (energy, *momentum, energy_delta, angular_delta)):
        raise ArithmeticError
    if any(
        not math.isfinite(value)
        for particle in particles
        for vector in particle.values()
        for value in vector
    ):
        raise ArithmeticError
    return {
        "time": time_yr,
        "particles": particles,
        "energy": energy,
        "angular_momentum": momentum,
        "energy_delta": energy_delta,
        "energy_relative": energy_delta / abs(initial_energy)
        if abs(initial_energy) > ZERO_THRESHOLD
        else None,
        "angular_delta": angular_delta,
        "angular_relative": angular_delta / angular_initial
        if angular_initial > ZERO_THRESHOLD
        else None,
    }


def run_rebound(params: SimulationParameters, directory: Path):
    if rebound.__version__ != REBOUND_VERSION:
        raise RuntimeError("Unexpected REBOUND version")
    sim = rebound.Simulation()
    sim.G = G
    sim.integrator = "ias15"
    sim.ri_ias15.epsilon = EPSILON
    sim.exit_min_distance = MIN_DISTANCE
    for particle in params.particles:
        x, y, z = particle.position
        vx, vy, vz = particle.velocity
        sim.add(m=particle.mass, x=x, y=y, z=z, vx=vx, vy=vy, vz=vz)

    samples = []
    initial = None
    for index in range(params.samples):
        if index:
            sim.integrate(params.duration * index / (params.samples - 1), exact_finish_time=1)
        particles = [
            {"position": [p.x, p.y, p.z], "velocity": [p.vx, p.vy, p.vz]} for p in sim.particles
        ]
        angular = sim.angular_momentum()
        sample = snapshot(
            sim.t, particles, sim.energy(), (angular.x, angular.y, angular.z), initial
        )
        if initial is None:
            initial = sample["energy"], sample["angular_momentum"]
        samples.append(sample)
        write(directory / "progress", index + 1)
    return samples, {
        "format_version": 1,
        "engine": "rebound",
        "rebound_version": rebound.__version__,
        "rebound_wheel_sha256": REBOUND_WHEEL_SHA256,
        "integrator": "IAS15",
        "epsilon": EPSILON,
        "min_distance": MIN_DISTANCE,
    }


def run_petar(params: SimulationParameters, directory: Path):
    numerics, states = compute_petar.simulate(params, Path.cwd())
    masses = [particle.mass for particle in params.particles]
    samples = []
    initial = None
    for index, particles in enumerate(states):
        positions = [p["position"] for p in particles]
        velocities = [p["velocity"] for p in particles]
        kinetic = 0.5 * math.fsum(
            mass * math.fsum(v * v for v in velocity)
            for mass, velocity in zip(masses, velocities, strict=True)
        )
        potential = -G * math.fsum(
            masses[i] * masses[j] / math.dist(positions[i], positions[j])
            for i, j in combinations(range(len(masses)), 2)
        )
        angular = tuple(
            math.fsum(
                mass * (position[a] * velocity[b] - position[b] * velocity[a])
                for mass, position, velocity in zip(masses, positions, velocities, strict=True)
            )
            for a, b in ((1, 2), (2, 0), (0, 1))
        )
        time_yr = params.duration * index / (params.samples - 1)
        sample = snapshot(time_yr, particles, kinetic + potential, angular, initial)
        if initial is None:
            initial = sample["energy"], sample["angular_momentum"]
        samples.append(sample)
        write(directory / "progress", index + 1)
    return samples, {
        **numerics,
        "format_version": 2,
        "engine": "petar",
        "petar_version": "1.0",
        "petar_revision": PETAR_REVISION,
        "integrator": "Tree + Hermite + SDAR",
        "kepler_steps": PETAR_KEPLER_STEPS,
    }


def run(directory: Path) -> None:
    start = time.monotonic()
    params = SimulationParameters.model_validate(read(directory / "input", 128 * 1024))
    integrator = run_petar if params.engine == "petar" else run_rebound
    samples, numerics = integrator(params, directory)

    warning = any(abs(sample["energy_relative"] or 0.0) > ENERGY_WARNING for sample in samples)
    write(
        directory / "result",
        {
            **numerics,
            "astroagent_version": __version__,
            "image_id": os.environ.get("ASTROAGENT_COMPUTE_IMAGE_ID") or None,
            "gravitational_constant": G,
            "zero_threshold": ZERO_THRESHOLD,
            "wall_seconds": time.monotonic() - start,
            "environment": (
                f"{platform.system()} {platform.machine()}, Python {platform.python_version()}"
            ),
            "warnings": ["最大相对能量偏差超过 10⁻⁶，请核对时间跨度与近接情况。"]
            if warning
            else [],
            "samples": samples,
        },
    )


def main() -> None:
    directory = Path(sys.argv[1])
    resource.setrlimit(resource.RLIMIT_AS, (448 * 1024**2, 448 * 1024**2))
    resource.setrlimit(resource.RLIMIT_FSIZE, (MAX_OUTPUT_BYTES, MAX_OUTPUT_BYTES))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    try:
        run(directory)
    except rebound.Encounter:
        write(directory / "failure", "粒子间距触及近接阈值（10⁻⁵ AU），积分已停止。")
    except compute_petar.PeTarError as exc:
        write(directory / "failure", str(exc))
    except ArithmeticError:
        write(directory / "failure", "积分产生了非有限数值，请核对初始条件与模拟时长。")
    except MemoryError:
        write(directory / "failure", "积分超过内存上限，请减少粒子数或采样数。")


if __name__ == "__main__":
    main()
