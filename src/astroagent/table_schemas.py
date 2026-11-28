"""V2.3 天文数据表、VizieR 检索、确定性算子与血缘追踪数据契约。"""

from __future__ import annotations

from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    field_validator,
    model_validator,
)

from astroagent.source_schemas import ErrorInfo, Source

Identifier = Annotated[
    str, Field(pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
]
Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]

TABLE_SCHEMA_VERSION = 1
MAX_TABLE_UPLOAD_BYTES = 10 * 1024**2
MAX_TABLE_ROWS = 20_000
MAX_TABLE_COLUMNS = 64
MAX_TABLE_GZ_BYTES = 8 * 1024**2
MAX_PROJECT_TABLES = 40
MAX_PROJECT_RUNS = 120
MAX_CELL_CHARS = 8192
MAX_CROSSMATCH_CANDIDATES_PER_ROW = 10

FiniteNumber = Annotated[float, Field(allow_inf_nan=False)]
TableFormat = Literal["fits", "votable", "ecsv", "csv", "tsv"]
TableSourceKind = Literal["upload", "gaia_turn", "gaia_snapshot", "vizier", "derived"]
ColumnKind = Literal["number", "integer", "identifier", "text", "boolean", "empty"]
OperatorName = Literal["stats", "filter_derive", "coordinates", "crossmatch", "fit"]
CoordFrame = Literal["icrs", "fk5", "galactic"]
CoordUnit = Literal["deg", "hourangle_deg"]

VIZIER_CATALOG_ID_RE = r"^[A-Za-z0-9_+./-]{3,64}$"
VIZIER_COLUMN_NAME_RE = r"^[A-Za-z0-9_+-]{1,64}$"
DERIVED_COL_NAME_RE = r"^[A-Za-z_][A-Za-z0-9_-]{0,63}$"


class StrictRequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, allow_inf_nan=False)


def _empty_to_none(value: Any) -> Any:
    if isinstance(value, str) and not value.strip():
        return None
    return value


def _lower_token(value: Any) -> Any:
    if isinstance(value, str):
        cleaned = value.strip()
        return cleaned.lower() if cleaned else None
    return value


class TableColumnMeta(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    name: str = Field(min_length=1, max_length=128)
    kind: ColumnKind
    dtype: str = Field(default="string", min_length=1, max_length=64)
    unit: str | None = Field(default=None, max_length=128)
    ucd: str | None = Field(default=None, max_length=128)
    description: str | None = Field(default=None, max_length=500)
    missing: int = Field(default=0, ge=0, le=MAX_TABLE_ROWS)


class TableHduInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    index: int = Field(ge=0)
    name: str
    kind: str
    rows: int = Field(ge=0)
    columns: list[TableColumnMeta] = Field(default_factory=list)
    selectable: bool
    reason: str | None = None


class TableInspectResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    filename: str
    format: TableFormat
    size_bytes: int = Field(ge=1, le=MAX_TABLE_UPLOAD_BYTES)
    sha256: Digest
    hdus: list[TableHduInfo]
    default_hdu_index: int | None = None
    coordinate_frame: str | None = None
    ref_epoch: str | None = None
    header_meta: dict[str, str] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)


class TableLineage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: TableSourceKind
    parent_dataset_ids: list[str] = Field(default_factory=list)
    operator: OperatorName | None = None
    run_id: str | None = None
    origin: dict[str, Any] = Field(default_factory=dict)


class AnalysisDataset(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    id: Identifier
    project_id: Identifier
    name: str = Field(min_length=1, max_length=128)
    source: TableSourceKind
    format: TableFormat
    source_sha256: Digest
    data_sha256: Digest
    row_count: int = Field(ge=1, le=MAX_TABLE_ROWS)
    column_count: int = Field(ge=1, le=MAX_TABLE_COLUMNS)
    columns: list[TableColumnMeta] = Field(min_length=1, max_length=MAX_TABLE_COLUMNS)
    coordinate_frame: str | None = None
    ref_epoch: str | None = None
    header_meta: dict[str, str] = Field(default_factory=dict)
    lineage: TableLineage
    warnings: list[str] = Field(default_factory=list)
    created_at: str
    updated_at: str


class TablePreviewResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dataset_id: Identifier
    offset: int = Field(ge=0)
    limit: int = Field(ge=1, le=200)
    total_rows: int = Field(ge=1, le=MAX_TABLE_ROWS)
    columns: list[TableColumnMeta]
    rows: list[list[str | None]]


class TableImportGaiaRequest(StrictRequestModel):
    source_kind: Literal["turn", "snapshot"]
    conversation_id: Identifier | None = None
    turn_id: Identifier | None = None
    snapshot_id: Identifier | None = None
    query_index: StrictInt = Field(default=0, ge=0, le=11)
    name: str | None = Field(default=None, min_length=1, max_length=128)

    @model_validator(mode="after")
    def check_source(self):
        if self.source_kind == "turn":
            if self.conversation_id is None or self.turn_id is None:
                raise ValueError("导入会话轮次 Gaia 数据需要提供 conversation_id 与 turn_id。")
        elif self.snapshot_id is None:
            raise ValueError("导入项目快照 Gaia 数据需要提供 snapshot_id。")
        return self


class TableImportVizierTurnRequest(StrictRequestModel):
    conversation_id: Identifier
    turn_id: Identifier
    query_index: StrictInt = Field(default=0, ge=0, le=11)
    name: str | None = Field(default=None, min_length=1, max_length=128)


class VizierPreset(BaseModel):
    model_config = ConfigDict(extra="forbid")

    catalog_id: str
    title: str
    description: str
    default_columns: list[str]
    ra_col: str
    dec_col: str
    ref_epoch: str
    coordinate_frame: str = "ICRS"
    units: dict[str, str]
    cds_url: str


class VizierQuery(StrictRequestModel):
    catalog_id: str = Field(
        pattern=VIZIER_CATALOG_ID_RE,
        description=(
            "VizieR 星表编号，如 II/246/out、II/328/allwise、II/349/ps1、"
            "V/156/dr7lrs、J/A+A/640/A1/nodup"
        ),
    )
    ra_deg: Annotated[FiniteNumber, Field(ge=0, lt=360)] | None = Field(
        default=None,
        description="ICRS 中心赤经，单位 deg，范围 [0, 360)；与 object_name 互斥",
    )
    dec_deg: Annotated[FiniteNumber, Field(ge=-90, le=90)] | None = Field(
        default=None,
        description="ICRS 中心赤纬，单位 deg，范围 [-90, 90]；与 object_name 互斥",
    )
    object_name: str | None = Field(
        default=None,
        min_length=1,
        max_length=200,
        description="待解析天体名称（通过 SIMBAD 获取 ICRS 坐标），与 ra_deg/dec_deg 互斥",
    )
    radius_arcmin: Annotated[FiniteNumber, Field(ge=0.05, le=60.0)] = Field(
        default=5.0,
        description="圆锥检索半径，单位 arcmin，范围 [0.05, 60]",
    )
    limit: StrictInt = Field(
        default=50,
        ge=1,
        le=500,
        description="最多返回源行数，范围 1–500，默认 50",
    )
    columns: list[Annotated[str, Field(pattern=VIZIER_COLUMN_NAME_RE)]] | None = Field(
        default=None,
        max_length=32,
        description="可选返回列名列表（1–32 列）；留空则使用预设默认列或表默认坐标与核心列",
    )

    @model_validator(mode="after")
    def check_target(self):
        has_coords = self.ra_deg is not None or self.dec_deg is not None
        if self.object_name is not None and has_coords:
            raise ValueError("object_name 与 ra_deg/dec_deg 互斥，请只提供其中一种定位方式。")
        if self.object_name is None:
            if self.ra_deg is None or self.dec_deg is None:
                raise ValueError("请提供完整的 ICRS 坐标 (ra_deg, dec_deg) 或 object_name。")
        if self.columns is not None and len(self.columns) == 0:
            raise ValueError("columns 若指定则不能为空列表。")
        return self

    def effective_parameters(self) -> dict[str, Any]:
        data = {
            "catalog_id": self.catalog_id,
            "radius_arcmin": self.radius_arcmin,
            "limit": self.limit,
        }
        if self.object_name is not None:
            data["object_name"] = self.object_name
        else:
            data["ra_deg"] = self.ra_deg
            data["dec_deg"] = self.dec_deg
        if self.columns is not None:
            data["columns"] = list(self.columns)
        return data


class VizierQueryHttpRequest(VizierQuery):
    project_id: Identifier | None = None
    save_to_project: StrictBool = False
    dataset_name: str | None = Field(default=None, min_length=1, max_length=128)

    @model_validator(mode="after")
    def check_save_target(self):
        if self.save_to_project and self.project_id is None:
            raise ValueError("同步保存到项目数据时必须指定 project_id。")
        return self


class VizierQueryResult(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    catalog_id: str
    catalog_title: str
    query: dict[str, Any]
    adql: str
    endpoint: str = "https://tapvizier.cds.unistra.fr/TAPVizieR/tap/sync"
    cds_url: str
    status: Literal["success", "not_found", "error"]
    returned_count: int = 0
    has_more: bool | None = None
    truncated: bool | None = None
    archive_overflow: bool | None = None
    columns: list[str] = Field(default_factory=list)
    units: dict[str, str] = Field(default_factory=dict)
    ref_epoch: str | None = None
    coordinate_frame: str = "ICRS"
    ra_column: str | None = None
    dec_column: str | None = None
    resolved_object: dict[str, Any] | None = None
    rows: list[dict[str, str | int | float | bool | None]] = Field(default_factory=list)
    source: Source
    warnings: list[str] = Field(default_factory=list)
    error: ErrorInfo | None = None


class VizierQueryHttpResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    result: VizierQueryResult
    saved_dataset: AnalysisDataset | None = None


class StatsOperatorRequest(StrictRequestModel):
    dataset_id: Identifier
    columns: list[str] = Field(default_factory=list, max_length=16)
    corr_x: str | None = Field(default=None, min_length=1, max_length=128)
    corr_y: str | None = Field(default=None, min_length=1, max_length=128)
    ks_column: str | None = Field(default=None, min_length=1, max_length=128)
    ks_other_dataset_id: Identifier | None = None
    ks_group_column: str | None = Field(default=None, min_length=1, max_length=128)
    ks_group_a: str | None = Field(default=None, max_length=128)
    ks_group_b: str | None = Field(default=None, max_length=128)

    @field_validator(
        "corr_x",
        "corr_y",
        "ks_column",
        "ks_other_dataset_id",
        "ks_group_column",
        "ks_group_a",
        "ks_group_b",
        mode="before",
    )
    @classmethod
    def normalize_optional_str(cls, value: Any) -> Any:
        return _empty_to_none(value)

    @model_validator(mode="after")
    def check_target(self):
        has_corr = self.corr_x is not None or self.corr_y is not None
        if has_corr and (not self.corr_x or not self.corr_y):
            raise ValueError("双列相关性检验需要同时指定 corr_x 与 corr_y。")
        if self.ks_group_column and (self.ks_group_a is None or self.ks_group_b is None):
            raise ValueError("按同表分组进行 KS 检验需同时指定 ks_group_a 与 ks_group_b。")
        if self.ks_other_dataset_id and self.ks_group_column:
            raise ValueError("KS 检验不能同时指定跨表对比和同表分组。")
        if not self.columns and not has_corr and not self.ks_column:
            raise ValueError("请至少选择统计列、相关性列或 KS 检验目标。")
        return self


class FilterCondition(StrictRequestModel):
    column: str = Field(min_length=1, max_length=128)
    op: Literal[
        "eq",
        "ne",
        "lt",
        "le",
        "gt",
        "ge",
        "between",
        "is_null",
        "not_null",
        "in",
        "contains",
        "ratio_ge",
        "ratio_le",
        "ratio_gt",
        "ratio_lt",
        "diff_ge",
        "diff_le",
        "diff_gt",
        "diff_lt",
    ]
    value: str | float | int | bool | None = None
    value_max: float | int | None = None
    values: list[str | float | int] | None = Field(default=None, max_length=64)
    rhs_column: str | None = Field(default=None, min_length=1, max_length=128)

    @field_validator("op", mode="before")
    @classmethod
    def normalize_op(cls, value: Any) -> Any:
        return _lower_token(value)

    @field_validator("rhs_column", mode="before")
    @classmethod
    def normalize_rhs(cls, value: Any) -> Any:
        return _empty_to_none(value)

    @model_validator(mode="after")
    def check_operands(self):
        if self.op == "between" and (self.value is None or self.value_max is None):
            raise ValueError("between 条件需要同时提供 value 与 value_max。")
        if self.op == "in" and not self.values:
            raise ValueError("in 条件需要提供非空 values 列表。")
        if self.op.startswith(("ratio_", "diff_")) and (not self.rhs_column or self.value is None):
            raise ValueError("比值或差值条件需要提供 rhs_column 与阈值 value。")
        if self.op in {"eq", "ne", "lt", "le", "gt", "ge", "contains"} and self.value is None:
            raise ValueError(f"{self.op} 条件需要提供 value。")
        return self


class DerivedColumnSpec(StrictRequestModel):
    name: str = Field(pattern=DERIVED_COL_NAME_RE)
    expression: str = Field(min_length=1, max_length=300)
    unit: str | None = Field(default=None, max_length=128)
    description: str | None = Field(default=None, max_length=240)


class FilterDeriveOperatorRequest(StrictRequestModel):
    dataset_id: Identifier
    combine: Literal["and", "or"] = "and"
    conditions: list[FilterCondition] = Field(default_factory=list, max_length=24)
    derived_columns: list[DerivedColumnSpec] = Field(default_factory=list, max_length=12)
    save_derived: StrictBool = False
    derived_name: str | None = Field(default=None, min_length=1, max_length=128)

    @field_validator("combine", mode="before")
    @classmethod
    def normalize_combine(cls, value: Any) -> Any:
        return _lower_token(value)

    @field_validator("derived_name", mode="before")
    @classmethod
    def normalize_derived_name(cls, value: Any) -> Any:
        return _empty_to_none(value)

    @model_validator(mode="after")
    def check_work(self):
        if not self.conditions and not self.derived_columns:
            raise ValueError("请至少配置一条筛选条件或派生列公式。")
        return self


class CoordinatesOperatorRequest(StrictRequestModel):
    dataset_id: Identifier
    lon_col: str = Field(min_length=1, max_length=128)
    lat_col: str = Field(min_length=1, max_length=128)
    input_frame: CoordFrame = "icrs"
    input_unit: CoordUnit = "deg"
    output_frame: CoordFrame | None = "galactic"
    ref_ra_deg: Annotated[FiniteNumber, Field(ge=0, lt=360)] | None = None
    ref_dec_deg: Annotated[FiniteNumber, Field(ge=-90, le=90)] | None = None
    save_derived: StrictBool = False
    derived_name: str | None = Field(default=None, min_length=1, max_length=128)

    @field_validator("input_frame", "input_unit", "output_frame", mode="before")
    @classmethod
    def normalize_coord_tokens(cls, value: Any) -> Any:
        return _lower_token(value)

    @field_validator("derived_name", mode="before")
    @classmethod
    def normalize_coord_derived_name(cls, value: Any) -> Any:
        return _empty_to_none(value)

    @model_validator(mode="after")
    def check_ref(self):
        if (self.ref_ra_deg is None) != (self.ref_dec_deg is None):
            raise ValueError("参考中心点需同时提供 ref_ra_deg 与 ref_dec_deg。")
        if self.output_frame is None and self.ref_ra_deg is None:
            raise ValueError("请至少选择目标坐标系或指定参考中心点计算角距。")
        return self


class CrossmatchOperatorRequest(StrictRequestModel):
    left_dataset_id: Identifier
    right_dataset_id: Identifier
    left_ra_col: str = Field(min_length=1, max_length=128)
    left_dec_col: str = Field(min_length=1, max_length=128)
    right_ra_col: str = Field(min_length=1, max_length=128)
    right_dec_col: str = Field(min_length=1, max_length=128)
    left_frame: CoordFrame = "icrs"
    right_frame: CoordFrame = "icrs"
    left_unit: CoordUnit = "deg"
    right_unit: CoordUnit = "deg"
    radius_arcsec: Annotated[FiniteNumber, Field(ge=0.05, le=300.0)] = 2.0
    mode: Literal["nearest", "all_within_radius"] = "nearest"
    join_type: Literal["inner", "left"] = "inner"
    right_prefix: str = Field(default="r_", min_length=1, max_length=24, pattern=r"^[A-Za-z0-9_]+$")
    save_derived: StrictBool = False
    derived_name: str | None = Field(default=None, min_length=1, max_length=128)

    @field_validator(
        "left_frame", "right_frame", "left_unit", "right_unit", "mode", "join_type", mode="before"
    )
    @classmethod
    def normalize_crossmatch_tokens(cls, value: Any) -> Any:
        return _lower_token(value)

    @field_validator("derived_name", mode="before")
    @classmethod
    def normalize_crossmatch_derived_name(cls, value: Any) -> Any:
        return _empty_to_none(value)


class FitInitialGuess(StrictRequestModel):
    amplitude: FiniteNumber | None = None
    center: FiniteNumber | None = None
    sigma: Annotated[FiniteNumber, Field(gt=0)] | None = None
    baseline: FiniteNumber | None = None
    scale: FiniteNumber | None = None
    exponent: FiniteNumber | None = None


class FitOperatorRequest(StrictRequestModel):
    dataset_id: Identifier
    x_col: str = Field(min_length=1, max_length=128)
    y_col: str = Field(min_length=1, max_length=128)
    y_err_col: str | None = Field(default=None, min_length=1, max_length=128)
    model: Literal["linear", "polynomial", "power_law", "gaussian"] = "linear"
    degree: StrictInt = Field(default=2, ge=2, le=4)
    initial_guess: FitInitialGuess | None = None
    save_derived: StrictBool = False
    derived_name: str | None = Field(default=None, min_length=1, max_length=128)

    @field_validator("model", mode="before")
    @classmethod
    def normalize_model(cls, value: Any) -> Any:
        return _lower_token(value)

    @field_validator("y_err_col", "derived_name", mode="before")
    @classmethod
    def normalize_fit_optional(cls, value: Any) -> Any:
        return _empty_to_none(value)


class AnalysisRunRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    id: Identifier
    project_id: Identifier
    operator: OperatorName
    state: Literal["completed", "failed"]
    request_sha256: Digest
    input_dataset_ids: list[str] = Field(default_factory=list)
    output_dataset_id: Identifier | None = None
    parameters: dict[str, Any] = Field(default_factory=dict)
    summary: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    software: dict[str, str] = Field(default_factory=dict)
    created_at: str


class AnalysisRunResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    run: AnalysisRunRecord
    output_dataset: AnalysisDataset | None = None
    preview_rows: list[list[str | None]] = Field(default_factory=list)
    preview_columns: list[TableColumnMeta] = Field(default_factory=list)


class ProjectTablesPage(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    datasets: list[AnalysisDataset] = Field(default_factory=list)
    runs: list[AnalysisRunRecord] = Field(default_factory=list)


class SendToPlotRequest(StrictRequestModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)


class ProjectTablesListQuery(StrictRequestModel):
    project_id: Identifier | None = Field(
        default=None,
        description="可选项目 UUID；省略时使用当前会话所属项目（或默认个人空间）。",
    )


class TableAnalysisProposalQuery(StrictRequestModel):
    operator: OperatorName = Field(
        description="算子类型：stats、filter_derive、coordinates、crossmatch 或 fit"
    )
    title: str = Field(min_length=1, max_length=160, description="分析任务标题")
    dataset_id: Identifier = Field(description="主数据表 UUID（必须来自 list_project_tables 返回）")
    dataset_name: str | None = Field(default=None, max_length=128, description="主数据表显示名")
    secondary_dataset_id: Identifier | None = Field(
        default=None,
        description="可选第二张表 UUID（仅 crossmatch 或跨表 stats KS 检验使用）",
    )
    secondary_dataset_name: str | None = Field(default=None, max_length=128)
    parameters: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "按 operator 填写严格匹配的参数字典（严禁附带未定义字段）："
            "1) stats: {columns?: string[], corr_x?: string, corr_y?: string, "
            "ks_column?: string, ks_other_dataset_id?: uuid, ks_group_column?: string, "
            "ks_group_a?: string, ks_group_b?: string}；"
            "2) filter_derive: {combine?: 'and'|'or', conditions?: [{column, op, "
            "value?, value_max?, values?, rhs_column?}], "
            "derived_columns?: [{name, expression, unit?, description?}]}；"
            "3) coordinates: {lon_col, lat_col, input_frame?: 'icrs'|'fk5'|'galactic', "
            "input_unit?: 'deg'|'hourangle_deg', output_frame?: 'galactic'|'icrs'|'fk5'|null, "
            "ref_ra_deg?: number, ref_dec_deg?: number}；"
            "4) crossmatch: {left_ra_col, left_dec_col, right_ra_col, right_dec_col, "
            "left_frame?: 'icrs'|'fk5'|'galactic', right_frame?: 'icrs'|'fk5'|'galactic', "
            "left_unit?: 'deg'|'hourangle_deg', right_unit?: 'deg'|'hourangle_deg', "
            "radius_arcsec?: number(0.05-300), mode?: 'nearest'|'all_within_radius', "
            "join_type?: 'inner'|'left', right_prefix?: string}"
            "（left/right_dataset_id 由顶层 dataset_id 与 secondary_dataset_id 自动补全）；"
            "5) fit: {x_col, y_col, y_err_col?: string, model?: 'linear'|'polynomial'|"
            "'power_law'|'gaussian', degree?: int(2-4), "
            "initial_guess?: {amplitude?, center?, sigma?, baseline?, scale?, exponent?}}。"
        ),
    )
    save_derived: StrictBool = Field(default=False, description="是否保存为派生表")
    derived_name: str | None = Field(default=None, min_length=1, max_length=128)
    explanation: str = Field(
        min_length=1,
        max_length=2000,
        description="分析目标、物理单位/坐标系与统计或拟合假设说明",
    )
    warnings: list[str] = Field(default_factory=list, max_length=12)

    @field_validator("operator", mode="before")
    @classmethod
    def normalize_operator(cls, value: Any) -> Any:
        return _lower_token(value)

    @field_validator(
        "dataset_name",
        "secondary_dataset_id",
        "secondary_dataset_name",
        "derived_name",
        mode="before",
    )
    @classmethod
    def normalize_proposal_optionals(cls, value: Any) -> Any:
        return _empty_to_none(value)

    @field_validator("warnings")
    @classmethod
    def check_warnings(cls, values):
        if any(len(v) > 400 for v in values):
            raise ValueError("warnings 单条不能超过 400 字符。")
        return values

    @field_validator("dataset_id", "secondary_dataset_id")
    @classmethod
    def check_uuid_or_none(cls, value):
        if value is None:
            return None
        return str(UUID(value))


class TableAnalysisProposalResult(TableAnalysisProposalQuery):
    status: Literal["proposed"] = "proposed"
    project_id: Identifier | None = None
