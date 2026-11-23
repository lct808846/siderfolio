"""Public contract shared by the API, dispatcher and isolated integrator."""

import hashlib
import json
import math
from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

G = 4 * math.pi**2
EPSILON = 1e-9
MIN_DISTANCE = 1e-5
ZERO_THRESHOLD = 1e-12
ENERGY_WARNING = 1e-6
REBOUND_VERSION = "4.4.11"
REBOUND_WHEEL_SHA256 = "9b75b76483e70988901c5d19045a7e2d5a1de1537af2bf7d2d90023d327cd6a3"
PETAR_REVISION = "fcca98d425cbb8bc9ce409532e31aa72dfd39e28"
PETAR_KEPLER_STEPS = 32
WALL_SECONDS = 120
MAX_OUTPUT_BYTES = 32 * 1024 * 1024
SPOOL = "/var/lib/astroagent-compute"

Vector = tuple[float, float, float]
Coordinate = Annotated[float, Field(ge=-1e6, le=1e6, allow_inf_nan=False)]
ParticleID = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,31}$")]
TaskState = Literal[
    "draft", "queued", "running", "cancelling", "succeeded", "failed", "cancelled", "interrupted"
]
PlotKind = Literal["snapshot", "trajectory", "energy"]
DraftSource = Literal["manual", "template", "conversation"]
SimulationEngine = Literal["rebound", "petar"]


class ComputeInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Particle(ComputeInput):
    id: ParticleID
    mass: float = Field(ge=1e-9, le=1e6, allow_inf_nan=False)
    position: Annotated[list[Coordinate], Field(min_length=3, max_length=3)]
    velocity: Annotated[list[Coordinate], Field(min_length=3, max_length=3)]


class SimulationParameters(ComputeInput):
    particles: list[Particle] = Field(min_length=2, max_length=128)
    duration: float = Field(ge=1e-6, le=1e4, allow_inf_nan=False)
    samples: int = Field(ge=2, le=512)
    engine: SimulationEngine = "rebound"

    @model_validator(mode="after")
    def validate_particles(self):
        if len({particle.id for particle in self.particles}) != len(self.particles):
            raise ValueError("粒子 ID 必须唯一。")
        for index, particle in enumerate(self.particles):
            for other in self.particles[:index]:
                if math.dist(particle.position, other.position) <= MIN_DISTANCE:
                    raise ValueError(f"粒子 {particle.id} 与 {other.id} 的初始距离不超过近接阈值。")
        return self

    def digest(self) -> str:
        # Older REBOUND drafts did not store an engine field.
        data = json.dumps(
            self.model_dump(exclude_defaults=True),
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        return hashlib.sha256(data.encode()).hexdigest()


class ComputeDraft(ComputeInput):
    name: Annotated[
        str,
        StringConstraints(
            strip_whitespace=True, min_length=1, max_length=120, pattern=r"^[^\x00]+$"
        ),
    ]
    source: DraftSource = "manual"
    parameters: SimulationParameters


class ComputeEdit(ComputeDraft):
    expected_revision: int = Field(ge=0)


class ComputeConfirm(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID
    expected_revision: int = Field(ge=0, strict=True)
    parameter_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    confirmed: Literal[True]

    @field_validator("confirmed", mode="before")
    @classmethod
    def explicit_confirmation(cls, value):
        if value is not True:
            raise ValueError("必须明确确认运行。")
        return value


class ComputeDescribe(ComputeInput):
    description: str = Field(min_length=1, max_length=6000)
    model_id: str | None = Field(default=None, max_length=260)


class ComputeProposal(ComputeInput):
    clarification: str | None = Field(default=None, max_length=1200)
    parameters: SimulationParameters | None = None


class ComputeSummary(BaseModel):
    id: UUID
    name: str
    state: TaskState
    created_at: datetime
    updated_at: datetime
    samples_completed: int
    sample_count: int


class ComputeEvent(BaseModel):
    state: TaskState
    at: datetime


class ComputeTiming(BaseModel):
    queue_wait_seconds: float | None = Field(default=None, ge=0.0)
    execution_seconds: float | None = Field(default=None, ge=0.0)
    total_seconds: float | None = Field(default=None, ge=0.0)


class ComputeTask(ComputeSummary):
    source: DraftSource
    parameters: SimulationParameters
    parameter_sha256: str
    revision: int
    origin_id: UUID | None
    attempt_id: UUID | None
    started_at: datetime | None
    finished_at: datetime | None
    error: str | None
    events: list[ComputeEvent]
    timing: ComputeTiming | None = None


class SimulationOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class ParticleState(SimulationOutput):
    position: Vector
    velocity: Vector


class SimulationSample(SimulationOutput):
    time: float
    particles: list[ParticleState]
    energy: float
    angular_momentum: Vector
    energy_delta: float
    energy_relative: float | None
    angular_delta: float
    angular_relative: float | None


class SimulationResultBase(SimulationOutput):
    astroagent_version: str
    image_id: str | None = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    gravitational_constant: float
    zero_threshold: float
    wall_seconds: float
    environment: str
    warnings: list[str]
    samples: list[SimulationSample]


class ReboundResult(SimulationResultBase):
    format_version: Literal[1]
    engine: Literal["rebound"] = "rebound"
    rebound_version: Literal["4.4.11"]
    rebound_wheel_sha256: str
    integrator: Literal["IAS15"]
    epsilon: float
    min_distance: float


class PeTarResult(SimulationResultBase):
    format_version: Literal[2]
    engine: Literal["petar"]
    petar_version: Literal["1.0"]
    petar_revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    integrator: Literal["Tree + Hermite + SDAR"]
    tree_step_yr: float = Field(gt=0)
    time_scale_yr: float = Field(ge=1, lt=2)
    kepler_steps: Literal[32]


SimulationResult = ReboundResult | PeTarResult


class ComputeStatus(BaseModel):
    enabled: bool
    worker_ready: bool
    engines: list[SimulationEngine]


class ComputeList(BaseModel):
    worker_ready: bool
    engines: list[SimulationEngine]
    tasks: list[ComputeSummary]


def binary_template() -> SimulationParameters:
    return SimulationParameters(
        duration=1.0,
        samples=129,
        particles=[
            Particle(id="A", mass=0.5, position=[-0.5, 0.0, 0.0], velocity=[0.0, -math.pi, 0.0]),
            Particle(id="B", mass=0.5, position=[0.5, 0.0, 0.0], velocity=[0.0, math.pi, 0.0]),
        ],
    )
