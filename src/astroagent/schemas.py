"""接口与工具共用的可追溯数据结构。"""

import math
from datetime import datetime
from typing import Annotated, Literal
from urllib.parse import quote_plus

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, model_validator


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    message: str = Field(min_length=1, max_length=4000, examples=["请查询 Betelgeuse 的坐标和类型"])
    model: str | None = Field(default=None, min_length=1, max_length=128)


class ObjectQuery(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    object_name: str = Field(
        min_length=1,
        max_length=200,
        description="SIMBAD 天体名称或标识符（1–200 字符，不使用通配符）",
    )


class ErrorInfo(BaseModel):
    code: str
    message: str
    retryable: bool = False


class ErrorResponse(BaseModel):
    error: ErrorInfo


class Source(BaseModel):
    name: Literal["SIMBAD", "ADS", "Gaia"] = "SIMBAD"
    url: str
    retrieved_at: datetime


class ObjectData(BaseModel):
    main_id: str
    ra_deg: float | None = Field(default=None, ge=0, lt=360)
    dec_deg: float | None = Field(default=None, ge=-90, le=90)
    coordinate_frame: Literal["ICRS"] = "ICRS"
    object_type: str | None = None
    spectral_type: str | None = None
    coordinate_bibcode: str | None = None


class QueryResult(BaseModel):
    object_name: str
    status: Literal["success", "not_found", "error"]
    source: Source
    data: ObjectData | None = None
    error: ErrorInfo | None = None


class LiteratureQuery(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    query: str = Field(
        min_length=1,
        max_length=1000,
        description="ADS 检索式（URL 编码后至多 1000 字符，固定限定 database:astronomy）",
    )
    rows: int = Field(
        default=5,
        strict=True,
        ge=1,
        le=10,
        description="单页返回文献数量，范围 1–10，默认 5；须满足 start + rows <= 100",
    )
    start: int = Field(
        default=0,
        strict=True,
        ge=0,
        le=90,
        description="分页起始偏移（0 起），范围 0–90，默认 0；须满足 start + rows <= 100",
    )
    sort: Literal["relevance", "date_desc", "citation_count_desc"] = Field(
        default="relevance",
        description=(
            "排序方式：relevance（相关性，默认）、date_desc（发表日期降序）、"
            "citation_count_desc（被引次数降序）"
        ),
    )

    @model_validator(mode="after")
    def check_limits(self):
        if len(quote_plus(self.query, safe="")) > 1000:
            raise ValueError("URL-encoded query exceeds 1000 characters")
        if self.start + self.rows > 100:
            raise ValueError("start + rows must not exceed 100")
        return self


class PaperData(BaseModel):
    bibcode: str = Field(min_length=1)
    title: str | None = None
    authors: list[str] = Field(default_factory=list)
    year: int | None = Field(default=None, ge=1, le=9999)
    publication: str | None = None
    doi: list[str] = Field(default_factory=list)
    abstract: str | None = None
    citation_count: int | None = Field(default=None, ge=0)
    source: Source


class LiteratureSearchResult(BaseModel):
    query: str
    filters: list[str] = Field(default_factory=lambda: ["database:astronomy"])
    rows: int
    start: int
    sort: Literal["relevance", "date_desc", "citation_count_desc"]
    status: Literal["success", "not_found", "error"]
    total_found: int | None = None
    returned_count: int = 0
    has_more: bool | None = None
    papers: list[PaperData] = Field(default_factory=list)
    source: Source
    error: ErrorInfo | None = None


FiniteNumber = Annotated[float, Field(strict=True, allow_inf_nan=False)]
GaiaSourceId = Annotated[str, Field(strict=True, pattern=r"^[1-9][0-9]{0,18}$")]


class GaiaQuery(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    mode: Literal["source_id", "cone"] = Field(
        description=(
            "查询模式：source_id 按 Gaia DR3 64 位有符号正整数编号精确查询"
            "（不可传坐标、半径、limit 或筛选条件）；cone 按 ICRS 坐标与半径圆锥查询"
            "（不可传 source_id）"
        )
    )
    source_id: GaiaSourceId | None = Field(
        default=None,
        description=(
            "Gaia DR3 source_id 十进制字符串（正 64 位有符号整数）；"
            "仅 mode=source_id 必填，与圆锥参数互斥"
        ),
    )
    ra_deg: Annotated[FiniteNumber, Field(ge=0, lt=360)] | None = Field(
        default=None,
        description=(
            "圆锥中心赤经，ICRS 坐标系，单位 deg，范围 [0, 360)；"
            "仅 mode=cone 必填，与 mode=source_id 互斥"
        ),
    )
    dec_deg: Annotated[FiniteNumber, Field(ge=-90, le=90)] | None = Field(
        default=None,
        description=(
            "圆锥中心赤纬，ICRS 坐标系，单位 deg，范围 [-90, 90]；"
            "仅 mode=cone 必填，与 mode=source_id 互斥"
        ),
    )
    radius_arcmin: Annotated[FiniteNumber, Field(gt=0, le=30)] | None = Field(
        default=None,
        description=(
            "圆锥检索半径，单位 arcmin，范围 (0, 30]；仅 mode=cone 必填，与 mode=source_id 互斥"
        ),
    )
    limit: StrictInt = Field(
        default=20,
        ge=1,
        le=500,
        description=(
            "圆锥查询最多返回源行数，范围 1–500，默认 20；仅 mode=cone 使用，与 mode=source_id 互斥"
        ),
    )
    ruwe_max: Annotated[FiniteNumber, Field(gt=0, le=10)] | None = Field(
        default=None,
        description="可选 RUWE 上限（无量纲），范围 (0, 10]，默认不限；仅 mode=cone 使用",
    )
    parallax_snr_min: Annotated[FiniteNumber, Field(gt=0, le=1000)] | None = Field(
        default=None,
        description=(
            "可选视差信噪比下限（parallax / parallax_error，无量纲），"
            "范围 (0, 1000]，默认不限；仅 mode=cone 使用"
        ),
    )
    parallax_min: Annotated[FiniteNumber, Field(ge=-100, le=1000)] | None = Field(
        default=None,
        description=(
            "可选视差下限，单位 mas，范围 [-100, 1000]，"
            "须 <= parallax_max，默认不限；仅 mode=cone 使用"
        ),
    )
    parallax_max: Annotated[FiniteNumber, Field(ge=-100, le=1000)] | None = Field(
        default=None,
        description=(
            "可选视差上限，单位 mas，范围 [-100, 1000]，"
            "须 >= parallax_min，默认不限；仅 mode=cone 使用"
        ),
    )
    pmra_min: Annotated[FiniteNumber, Field(ge=-10000, le=10000)] | None = Field(
        default=None,
        description=(
            "可选赤经自行下限（pmra，含 cos(dec)），单位 mas/yr，"
            "范围 [-10000, 10000]，须 <= pmra_max，默认不限；仅 mode=cone 使用"
        ),
    )
    pmra_max: Annotated[FiniteNumber, Field(ge=-10000, le=10000)] | None = Field(
        default=None,
        description=(
            "可选赤经自行上限（pmra，含 cos(dec)），单位 mas/yr，"
            "范围 [-10000, 10000]，须 >= pmra_min，默认不限；仅 mode=cone 使用"
        ),
    )
    pmdec_min: Annotated[FiniteNumber, Field(ge=-10000, le=10000)] | None = Field(
        default=None,
        description=(
            "可选赤纬自行下限（pmdec），单位 mas/yr，"
            "范围 [-10000, 10000]，须 <= pmdec_max，默认不限；仅 mode=cone 使用"
        ),
    )
    pmdec_max: Annotated[FiniteNumber, Field(ge=-10000, le=10000)] | None = Field(
        default=None,
        description=(
            "可选赤纬自行上限（pmdec），单位 mas/yr，"
            "范围 [-10000, 10000]，须 >= pmdec_min，默认不限；仅 mode=cone 使用"
        ),
    )
    g_mag_max: Annotated[FiniteNumber, Field(ge=-5, le=25)] | None = Field(
        default=None,
        description=(
            "可选 G 波段平均星等上限（phot_g_mean_mag），单位 mag，"
            "范围 [-5, 25]，默认不限；仅 mode=cone 使用"
        ),
    )
    estimate_distance: StrictBool = Field(
        default=False,
        description=(
            "是否对高信噪比视差源（parallax > 0、parallax_error > 0、SNR >= 10）"
            "计算 1000/parallax 近似距离（pc），默认 false"
        ),
    )

    @model_validator(mode="after")
    def check_mode(self):
        if self.mode == "source_id":
            if self.source_id is None or int(self.source_id) > 2**63 - 1:
                raise ValueError("A positive signed 64-bit DR3 source_id is required")
            cone_fields = {
                "ra_deg",
                "dec_deg",
                "radius_arcmin",
                "limit",
                "ruwe_max",
                "parallax_snr_min",
                "parallax_min",
                "parallax_max",
                "pmra_min",
                "pmra_max",
                "pmdec_min",
                "pmdec_max",
                "g_mag_max",
            }
            if self.model_fields_set & cone_fields:
                raise ValueError("Cone fields are not allowed in source_id mode")
        elif (
            "source_id" in self.model_fields_set
            or self.ra_deg is None
            or self.dec_deg is None
            or self.radius_arcmin is None
        ):
            raise ValueError("Cone mode requires coordinates and radius, without source_id")
        if (
            self.parallax_min is not None
            and self.parallax_max is not None
            and self.parallax_min > self.parallax_max
        ):
            raise ValueError("parallax_min must be <= parallax_max")
        if (
            self.pmra_min is not None
            and self.pmra_max is not None
            and self.pmra_min > self.pmra_max
        ):
            raise ValueError("pmra_min must be <= pmra_max")
        if (
            self.pmdec_min is not None
            and self.pmdec_max is not None
            and self.pmdec_min > self.pmdec_max
        ):
            raise ValueError("pmdec_min must be <= pmdec_max")
        return self

    def effective_parameters(self) -> dict:
        if self.mode == "source_id":
            return self.model_dump(include={"mode", "source_id", "estimate_distance"})
        base = {
            "mode",
            "ra_deg",
            "dec_deg",
            "radius_arcmin",
            "limit",
            "ruwe_max",
            "parallax_snr_min",
            "estimate_distance",
        }
        optional = (
            "parallax_min",
            "parallax_max",
            "pmra_min",
            "pmra_max",
            "pmdec_min",
            "pmdec_max",
            "g_mag_max",
        )
        for key in optional:
            if getattr(self, key) is not None:
                base.add(key)
        return self.model_dump(include=base)


class GaiaSourceData(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False, strict=True)

    source_id: GaiaSourceId
    ra: float = Field(ge=0, lt=360, description="ICRS degrees")
    dec: float = Field(ge=-90, le=90, description="ICRS degrees")
    ref_epoch: float = Field(description="Julian year")
    ra_error: float | None = Field(default=None, ge=0, description="mas")
    dec_error: float | None = Field(default=None, ge=0, description="mas")
    parallax: float | None = Field(default=None, description="mas; negative values retained")
    parallax_error: float | None = Field(default=None, ge=0, description="mas")
    pmra: float | None = Field(default=None, description="mas/yr, includes cos(dec)")
    pmra_error: float | None = Field(default=None, ge=0, description="mas/yr")
    pmdec: float | None = Field(default=None, description="mas/yr")
    pmdec_error: float | None = Field(default=None, ge=0, description="mas/yr")
    phot_g_mean_mag: float | None = Field(default=None, description="mag")
    phot_bp_mean_mag: float | None = Field(default=None, description="mag")
    phot_rp_mean_mag: float | None = Field(default=None, description="mag")
    bp_rp: float | None = Field(default=None, description="mag")
    radial_velocity: float | None = Field(default=None, description="km/s")
    radial_velocity_error: float | None = Field(default=None, ge=0, description="km/s")
    ruwe: float | None = Field(default=None, ge=0)
    astrometric_params_solved: int | None = None
    duplicated_source: bool | None = None
    separation_arcsec: float | None = Field(default=None, ge=0, description="arcsec")

    @model_validator(mode="after")
    def check_source_id(self):
        if int(self.source_id) > 2**63 - 1:
            raise ValueError("Invalid source_id")
        return self


class GaiaStatistic(BaseModel):
    valid_count: int
    missing_count: int
    median: float | None
    minimum: float | None
    maximum: float | None
    unit: str


class GaiaDistanceEstimate(BaseModel):
    source_id: str
    distance_pc: float | None = None
    distance_error_pc: float | None = None
    method: Literal["inverse_parallax_high_snr"] = "inverse_parallax_high_snr"
    zero_point_corrected: Literal[False] = False
    skipped_reason: (
        Literal[
            "missing_parallax",
            "non_positive_parallax",
            "invalid_or_missing_error",
            "low_parallax_snr",
            "numerical_overflow",
        ]
        | None
    ) = None


class GaiaAnalysis(BaseModel):
    sample_size: int
    scope: Literal["returned_rows"] = "returned_rows"
    truncated: bool
    quality_filters: dict[str, float] = Field(default_factory=dict)
    statistics: dict[str, GaiaStatistic]
    negative_parallax_count: int
    zero_parallax_count: int
    missing_parallax_count: int
    estimate_distance: bool
    distance_estimates: list[GaiaDistanceEstimate] = Field(default_factory=list)
    distance_computed_count: int = 0
    distance_skipped_count: int = 0


class GaiaQueryResult(BaseModel):
    query: dict
    release: Literal["Gaia DR3"] = "Gaia DR3"
    table: Literal["gaiadr3.gaia_source"] = "gaiadr3.gaia_source"
    endpoint: Literal["https://gea.esac.esa.int/tap-server/tap/sync"] = (
        "https://gea.esac.esa.int/tap-server/tap/sync"
    )
    adql: str
    maxrec: int
    status: Literal["success", "not_found", "error"]
    returned_count: int = 0
    total_found: None = None
    has_more: bool | None = None
    truncated: bool | None = None
    archive_overflow: bool | None = None
    data: list[GaiaSourceData] = Field(default_factory=list)
    analysis: GaiaAnalysis | None = None
    units: dict[str, str] = Field(default_factory=dict)
    source: Source
    warnings: list[str] = Field(default_factory=list)
    error: ErrorInfo | None = None


class NBodyParticleInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    id: str = Field(
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,31}$",
        description=(
            "粒子唯一编号，仅含英文字母、数字、下划线或连字符，如 Sun、Earth、Jupiter、A、B"
        ),
    )
    mass: float = Field(
        ge=1e-9,
        le=1e6,
        allow_inf_nan=False,
        description="粒子质量，单位太阳质量 M_sun，范围 [1e-9, 1e6]",
    )
    position: list[Annotated[float, Field(ge=-1e6, le=1e6, allow_inf_nan=False)]] = Field(
        min_length=3,
        max_length=3,
        description="三维初始位置 [x, y, z]，单位 AU",
    )
    velocity: list[Annotated[float, Field(ge=-1e6, le=1e6, allow_inf_nan=False)]] = Field(
        min_length=3,
        max_length=3,
        description="三维初始速度 [vx, vy, vz]，单位 AU/yr（引力常数 G = 4*pi^2）",
    )


class NBodyProposalQuery(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(
        min_length=1, max_length=120, description="实验名称，如「太阳-地球-木星三体演化」"
    )
    engine: Literal["rebound", "petar"] = Field(
        default="rebound",
        description=(
            "模拟程序：rebound（高精度 IAS15，适合双星/三星/行星系统）或 petar"
            "（树算法+SDAR，适合多体星团与近接）"
        ),
    )
    duration: float = Field(
        ge=1e-6,
        le=1e4,
        allow_inf_nan=False,
        description="模拟总时长，单位年 yr，范围 [1e-6, 1e4]",
    )
    samples: int = Field(
        default=129,
        ge=2,
        le=512,
        description="采样帧数，范围 2–512，默认 129",
    )
    particles: list[NBodyParticleInput] = Field(
        min_length=2,
        max_length=128,
        description="2–128 个点质量粒子的初始条件",
    )
    explanation: str = Field(
        min_length=1,
        max_length=2000,
        description="物理参数设定、初始轨道速度计算依据与关键假设说明",
    )
    warnings: list[str] = Field(
        default_factory=list, max_length=12, description="物理近似与注意事项"
    )

    @model_validator(mode="after")
    def check_particles(self):
        if len({p.id for p in self.particles}) != len(self.particles):
            raise ValueError("粒子 ID 必须唯一。")
        for idx, particle in enumerate(self.particles):
            for other in self.particles[:idx]:
                if math.dist(particle.position, other.position) <= 1e-5:
                    raise ValueError(
                        f"粒子 {particle.id} 与 {other.id} 的初始距离必须大于 1e-5 AU。"
                    )
        if any(len(item) > 500 for item in self.warnings):
            raise ValueError("warnings 单条不能超过 500 字符。")
        return self


class NBodyProposalResult(BaseModel):
    status: Literal["proposed"] = "proposed"
    name: str
    engine: Literal["rebound", "petar"] = "rebound"
    duration: float
    samples: int
    particles: list[NBodyParticleInput]
    explanation: str
    warnings: list[str] = Field(default_factory=list)


class PlotProposalQuery(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    data_source_kind: Literal[
        "current_turn_gaia", "history_turn_gaia", "attachment_csv", "project_dataset"
    ] = Field(
        description=(
            "数据来源类型：current_turn_gaia=本轮刚查到的 Gaia 数据；"
            "history_turn_gaia=历史轮次的 Gaia 数据；"
            "attachment_csv=用户附件中的 CSV/TSV 文件；"
            "project_dataset=项目已有数据集"
        )
    )
    source_turn_id: str | None = Field(
        default=None,
        max_length=128,
        description="data_source_kind=history_turn_gaia 时填写对应的历史 turn_id",
    )
    gaia_query_index: int = Field(
        default=0,
        ge=0,
        le=11,
        description="Gaia 查询索引（0 起，通常为 0）",
    )
    attachment_filename: str | None = Field(
        default=None,
        max_length=180,
        description="data_source_kind=attachment_csv 时填写对应附件文件名",
    )
    dataset_id: str | None = Field(
        default=None,
        max_length=128,
        description="data_source_kind=project_dataset 时填写数据集 UUID",
    )
    engine: Literal["python", "gnuplot"] = Field(
        default="python",
        description="绘图引擎：python（Matplotlib，默认推荐）或 gnuplot",
    )
    chart: Literal["scatter", "line", "histogram", "errorbar"] = Field(
        description="图种：scatter、line、histogram 或 errorbar"
    )
    title: str = Field(min_length=1, max_length=200, description="图标题")
    columns: list[str] = Field(
        min_length=1,
        max_length=12,
        description="使用的真实数据列名列表（必须与数据表表头完全一致）",
    )
    axes: dict[str, str] = Field(
        default_factory=dict,
        max_length=4,
        description="坐标轴标签与说明，如 {'x': 'BP - RP (mag)', 'y': 'G (mag, 反向)'}",
    )
    filters: list[str] = Field(
        default_factory=list,
        max_length=12,
        description="用户明确要求的数据筛选条件，未要求则为空列表",
    )
    explanation: str = Field(
        min_length=1,
        max_length=2000,
        description="绘图方案说明（所用列、单位、轴反转、缺失值处理与图注）",
    )
    warnings: list[str] = Field(default_factory=list, max_length=12, description="科学边界提醒")
    script: str = Field(
        min_length=1,
        max_length=24000,
        description=(
            "完整独立可执行脚本（读取 /input/data.csv，输出 "
            "/output/figure.png 和 /output/figure.pdf，"
            "不要包含 markdown 代码围栏）"
        ),
    )

    @model_validator(mode="after")
    def sanitize_and_validate(self):
        text = self.script.strip()
        if text.startswith("```"):
            lines = text.splitlines()
            if lines and lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            self.script = "\n".join(lines).strip()
        if not self.script or "\x00" in self.script:
            raise ValueError("脚本不能为空且不能包含 NUL 字符。")
        if any(
            len(v) > 500 for v in [*self.axes, *self.axes.values(), *self.filters, *self.warnings]
        ):
            raise ValueError("绘图说明字段超出长度限制。")
        return self


class PlotProposalResult(BaseModel):
    status: Literal["proposed"] = "proposed"
    data_source_kind: Literal[
        "current_turn_gaia", "history_turn_gaia", "attachment_csv", "project_dataset"
    ]
    source_turn_id: str | None = None
    gaia_query_index: int = 0
    attachment_filename: str | None = None
    dataset_id: str | None = None
    engine: Literal["python", "gnuplot"] = "python"
    chart: Literal["scatter", "line", "histogram", "errorbar"]
    title: str
    columns: list[str]
    axes: dict[str, str] = Field(default_factory=dict)
    filters: list[str] = Field(default_factory=list)
    explanation: str
    warnings: list[str] = Field(default_factory=list)
    script: str


class ChatResponse(BaseModel):
    status: Literal["success", "partial", "error"]
    answer: str
    results: list[QueryResult] = Field(default_factory=list)
    literature_results: list[LiteratureSearchResult] = Field(default_factory=list)
    gaia_results: list[GaiaQueryResult] = Field(default_factory=list)
    nbody_proposals: list[NBodyProposalResult] = Field(default_factory=list)
    plot_proposals: list[PlotProposalResult] = Field(default_factory=list)
    sources: list[Source] = Field(default_factory=list)
    warnings: list[ErrorInfo] = Field(default_factory=list)
