"""固定科研流程的输入、持久记录与输出；不允许用户提交执行代码。"""

from typing import Literal

from pydantic import Field, StrictBool, StrictInt, field_validator, model_validator

from astroagent.project_schemas import Contract, Digest, Identifier, Revision
from astroagent.schemas import ErrorInfo, FiniteNumber, LiteratureQuery, ObjectQuery

State = Literal["pending", "running", "succeeded", "failed", "skipped", "interrupted"]
PlotKind = Literal["proper_motion", "parallax_histogram", "observed_cmd"]


class GaiaFieldParameters(Contract):
    input_mode: Literal["name", "coordinates"]
    object_name: str | None = Field(default=None, max_length=200)
    ra_deg: FiniteNumber | None = Field(default=None, ge=0, lt=360)
    dec_deg: FiniteNumber | None = Field(default=None, ge=-90, le=90)
    radius_arcmin: FiniteNumber = Field(gt=0, le=30)
    limit: StrictInt = Field(ge=1, le=500)
    ruwe_max: FiniteNumber | None = Field(default=None, gt=0, le=10)
    parallax_snr_min: FiniteNumber | None = Field(default=None, gt=0, le=1000)
    parallax_min: FiniteNumber | None = Field(default=None, ge=-100, le=1000)
    parallax_max: FiniteNumber | None = Field(default=None, ge=-100, le=1000)
    pmra_min: FiniteNumber | None = Field(default=None, ge=-10000, le=10000)
    pmra_max: FiniteNumber | None = Field(default=None, ge=-10000, le=10000)
    pmdec_min: FiniteNumber | None = Field(default=None, ge=-10000, le=10000)
    pmdec_max: FiniteNumber | None = Field(default=None, ge=-10000, le=10000)
    g_mag_max: FiniteNumber | None = Field(default=None, ge=-5, le=25)
    estimate_distance: StrictBool = False
    plots: list[PlotKind] = Field(default_factory=list, max_length=3)

    @model_validator(mode="after")
    def input_coordinates(self):
        if self.input_mode == "name":
            if self.object_name is None or self.ra_deg is not None or self.dec_deg is not None:
                raise ValueError("名称模式不能同时提供坐标")
            self.object_name = ObjectQuery(object_name=self.object_name).object_name
        elif self.object_name is not None or self.ra_deg is None or self.dec_deg is None:
            raise ValueError("坐标模式要求完整ICRS坐标，且不能提供名称")
        if (
            self.parallax_min is not None
            and self.parallax_max is not None
            and self.parallax_min > self.parallax_max
        ):
            raise ValueError("视差下限不能大于上限")
        if (
            self.pmra_min is not None
            and self.pmra_max is not None
            and self.pmra_min > self.pmra_max
        ):
            raise ValueError("pmRA 下限不能大于上限")
        if (
            self.pmdec_min is not None
            and self.pmdec_max is not None
            and self.pmdec_min > self.pmdec_max
        ):
            raise ValueError("pmDec 下限不能大于上限")
        if len(set(self.plots)) != len(self.plots):
            raise ValueError("图种不能重复")
        self.plots = sorted(self.plots)
        return self


class AdsEvidenceParameters(LiteratureQuery):
    """年份等条件由用户写在实际检索式中，服务端不静默改写。"""


class WorkflowCreate(Revision):
    template_id: Literal["gaia_field", "ads_evidence"]
    name: str = Field(min_length=1, max_length=100)
    parameters: GaiaFieldParameters | AdsEvidenceParameters

    @field_validator("name")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("流程名称不能为空")
        return value.strip()

    @model_validator(mode="after")
    def template_parameters(self):
        expected = (
            GaiaFieldParameters if self.template_id == "gaia_field" else AdsEvidenceParameters
        )
        if not isinstance(self.parameters, expected):
            raise ValueError("模板与参数类型不符")
        return self


class WorkflowExecute(Revision):
    client_request_id: Identifier
    confirmed: StrictBool


class WorkflowDelete(Revision):
    confirmed: StrictBool


class StepDependency(Contract):
    step_id: str
    attempt_id: Identifier
    sha256: Digest


class StepAttempt(Contract):
    id: Identifier
    operation_id: Identifier
    client_request_id: Identifier
    sequence: StrictInt = Field(ge=1, le=5)
    state: State
    input: dict
    input_sha256: Digest
    dependencies: list[StepDependency]
    software: dict[str, str]
    started_at: str
    completed_at: str | None = None
    elapsed_seconds: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    output: dict | None = None
    output_sha256: Digest | None = None
    snapshot_id: Identifier | None = None
    output_ids: list[Identifier] = Field(default_factory=list, max_length=8)
    query_status: Literal["success", "not_found", "error"] | None = None
    export_status: Literal["success", "partial"] | None = None
    error: ErrorInfo | None = None
    warnings: list[str] = Field(default_factory=list)


class WorkflowStep(Contract):
    id: str
    version: str = "1"
    title: str
    state: State = "pending"
    skip_reason: str | None = None
    attempts: list[StepAttempt] = Field(default_factory=list, max_length=5)
    error: ErrorInfo | None = None


class WorkflowRun(Contract):
    id: Identifier
    project_id: Identifier
    name: str = Field(min_length=1, max_length=100)
    template_id: Literal["gaia_field", "ads_evidence"]
    template_version: str = Field(min_length=1, max_length=32)
    parameters: dict
    requested_parameters: dict
    revision: StrictInt = Field(ge=0)
    state: State = "pending"
    current_step_id: str | None = None
    created_at: str
    updated_at: str
    software: dict[str, str]
    provenance: Literal["local", "imported_unverified"] = "local"
    original_id: Identifier | None = None
    archive_sha256: Digest | None = None
    steps: list[WorkflowStep] = Field(min_length=1, max_length=4)
    error: ErrorInfo | None = None


class WorkflowSummary(Contract):
    id: Identifier
    project_id: Identifier
    name: str
    template_id: str
    template_version: str
    state: State
    revision: int
    updated_at: str
    provenance: str


class WorkflowOperation(Contract):
    id: Identifier
    run_id: Identifier
    client_request_id: Identifier
    state: State
    created_at: str
    completed_at: str | None = None
    error: ErrorInfo | None = None


class WorkflowOutput(Contract):
    id: Identifier
    run_id: Identifier
    project_id: Identifier
    attempt_id: Identifier
    filename: str = Field(pattern=r"^[a-zA-Z0-9_.-]{1,100}$")
    media_type: Literal["application/zip", "application/json", "image/png", "text/csv"]
    bytes: StrictInt = Field(ge=0, le=16 * 1024**2)
    sha256: Digest
    created_at: str
    provenance: Literal["local", "imported_unverified"] = "local"
    original_id: Identifier | None = None


class WorkflowDetail(WorkflowRun):
    outputs: list[WorkflowOutput]
    operations: list[WorkflowOperation]


class WorkflowExecution(Contract):
    operation: WorkflowOperation
    run: WorkflowDetail


class WorkflowTemplate(Contract):
    id: str
    version: str
    title: str
    description: str
    steps: list[dict[str, str]]
    input_schema: dict
    warnings: list[str]
