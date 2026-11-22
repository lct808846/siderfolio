"""V1.3 plotting contracts. Scripts are data until an isolated run is confirmed."""

from typing import Literal

from pydantic import Field, model_validator

from astroagent.project_schemas import Contract, Digest, Identifier

Engine = Literal["python", "gnuplot"]


class DatasetColumn(Contract):
    name: str = Field(min_length=1, max_length=128)
    kind: Literal["number", "text", "identifier", "empty"]
    missing: int = Field(ge=0, le=10000)
    unit: str | None = Field(default=None, max_length=128)


class PlotDataset(Contract):
    id: Identifier
    project_id: Identifier
    name: str = Field(min_length=1, max_length=128)
    created_at: str
    source: Literal["upload", "snapshot"]
    source_sha256: Digest
    data_sha256: Digest
    rows: int = Field(ge=1, le=10000)
    columns: list[DatasetColumn] = Field(min_length=1, max_length=64)
    provenance: dict
    warnings: list[str] = Field(max_length=16)


class PlotDataPreview(Contract):
    dataset_id: Identifier
    rows: int
    columns: list[DatasetColumn]
    sample: list[list[str]]
    sample_rows: int
    sample_cell_max_chars: int
    sample_cells_truncated: bool
    warnings: list[str]


class SnapshotDatasetRequest(Contract):
    snapshot_id: Identifier
    query_index: int = Field(default=0, ge=0, le=11)


class TurnDatasetRequest(Contract):
    conversation_id: Identifier
    turn_id: Identifier
    query_index: int = Field(default=0, ge=0, le=11)


class PlotProposal(Contract):
    engine: Engine
    chart: Literal["scatter", "line", "histogram", "errorbar"]
    title: str = Field(min_length=1, max_length=200)
    columns: list[str] = Field(min_length=1, max_length=12)
    axes: dict[str, str] = Field(max_length=4)
    filters: list[str] = Field(max_length=12)
    explanation: str = Field(min_length=1, max_length=2000)
    warnings: list[str] = Field(max_length=12)
    script: str = Field(min_length=1, max_length=24000)

    @model_validator(mode="after")
    def bounded_text(self):
        if any(
            len(v) > 500 for v in [*self.axes, *self.axes.values(), *self.filters, *self.warnings]
        ):
            raise ValueError("Plot annotations exceed bounds")
        if "\x00" in self.script:
            raise ValueError("NUL in script")
        return self


class PlotAppearance(Contract):
    width: int = Field(default=1600, ge=1200, le=2400)
    font_size: int = Field(default=12, ge=10, le=18)
    labels: Literal["none", "row_number"] = "none"
    x_label: str = Field(default="", max_length=80)
    y_label: str = Field(default="", max_length=80)


class PlotPlanRequest(Contract):
    dataset_id: Identifier
    model_id: str = Field(min_length=1, max_length=128)
    engine: Literal["auto", "python", "gnuplot"] = "auto"
    question: str = Field(min_length=1, max_length=4000)
    confirm_external_data: Literal[True]
    appearance: PlotAppearance = Field(default_factory=PlotAppearance)


class PlotCustomPlanRequest(Contract):
    dataset_id: Identifier
    model_id: str = Field(default="chat-proposal", min_length=1, max_length=128)
    question: str = Field(default="对话内绘图方案", min_length=1, max_length=4000)
    proposal: PlotProposal


class PlotRunRequest(Contract):
    plan_id: Identifier
    confirm_execute: Literal[True]


class PlotOperation(Contract):
    id: Identifier
    project_id: Identifier
    dataset_id: Identifier
    kind: Literal["plan", "run"]
    state: Literal["running", "completed", "failed", "interrupted"]
    created_at: str
    completed_at: str | None = None
    request_sha256: Digest
    request: dict
    proposal: PlotProposal | None = None
    script_sha256: Digest | None = None
    model_usage: dict = Field(default_factory=dict)
    runtime: dict = Field(default_factory=dict)
    files: list[str] = Field(default_factory=list)
    error: str | None = None
    imported: bool = False


class PlotStatus(Contract):
    storage_ready: bool
    execution_configured: bool
    message: str


class PlotInitialize(Contract):
    confirm_create_tables: Literal[True]


class PlotPage(Contract):
    datasets: list[PlotDataset]
    operations: list[PlotOperation]


class PlotSelection(Contract):
    files: list[str] = Field(min_length=1, max_length=9)
