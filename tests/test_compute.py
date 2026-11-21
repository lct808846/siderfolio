"""The confirmed compute contract and fail-closed inputs."""

import hashlib
import json
from uuid import uuid4

import pytest
from pydantic import ValidationError

from astroagent.compute_io import read
from astroagent.compute_petar import read_snapshot, write_initial_conditions
from astroagent.compute_schemas import ComputeConfirm, SimulationParameters, binary_template


@pytest.mark.parametrize("value", [False, 1, "true", None])
def test_compute_confirm_requires_a_json_true(value):
    with pytest.raises(ValidationError, match="confirmed"):
        ComputeConfirm.model_validate(
            {
                "request_id": str(uuid4()),
                "expected_revision": 0,
                "parameter_sha256": "a" * 64,
                "confirmed": value,
            }
        )


@pytest.mark.parametrize(
    ("field", "value", "error"),
    [
        ("id", "A", "ID"),
        ("mass", -1, "mass"),
        ("velocity", [0, float("inf"), 0], "velocity"),
        ("position", [-0.5, 0, 0], "近接阈值"),
    ],
)
def test_compute_rejects_invalid_initial_conditions(field, value, error):
    parameters = binary_template().model_dump()
    parameters["particles"][1][field] = value
    with pytest.raises(ValidationError, match=error):
        SimulationParameters.model_validate(parameters)


def test_compute_rejects_an_oversized_worker_message_before_parsing(tmp_path):
    payload = tmp_path / "progress"
    payload.write_bytes(b" " * 129)
    with pytest.raises(ValueError, match="Output limit exceeded"):
        read(payload, limit=128)


def test_engine_selection_preserves_legacy_rebound_confirmation():
    legacy = binary_template().model_dump(exclude={"engine"})
    digest = hashlib.sha256(
        json.dumps(legacy, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    assert SimulationParameters.model_validate(legacy).digest() == digest
    assert SimulationParameters.model_validate({**legacy, "engine": "petar"}).digest() != digest


def test_petar_snapshot_uses_native_columns_and_restores_input_order(tmp_path):
    params = binary_template()
    snapshot = tmp_path / "data.1"
    write_initial_conditions(snapshot, params, time_scale=1.5)
    _, first, second = snapshot.read_text(encoding="ascii").splitlines()
    assert len(first.split()) == len(second.split()) == 20
    snapshot.write_text(f"1 2 0.25\n{second}\n{first}\n", encoding="ascii")
    states = read_snapshot(snapshot, params, native_time=0.25, time_scale=1.5)
    for state, particle in zip(states, params.particles, strict=True):
        assert state["position"] == particle.position
        assert state["velocity"] == pytest.approx(particle.velocity)
