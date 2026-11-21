"""接口与工具共用的可追溯数据结构。"""

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

    object_name: str = Field(min_length=1, max_length=200, description="SIMBAD 天体名称或标识符")


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

    query: str = Field(min_length=1, max_length=1000, description="ADS 检索式")
    rows: int = Field(default=5, strict=True, ge=1, le=10)
    start: int = Field(default=0, strict=True, ge=0, le=90)
    sort: Literal["relevance", "date_desc", "citation_count_desc"] = "relevance"

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

    mode: Literal["source_id", "cone"]
    source_id: GaiaSourceId | None = None
    ra_deg: Annotated[FiniteNumber, Field(ge=0, lt=360)] | None = None
    dec_deg: Annotated[FiniteNumber, Field(ge=-90, le=90)] | None = None
    radius_arcmin: Annotated[FiniteNumber, Field(gt=0, le=30)] | None = None
    limit: StrictInt = Field(default=20, ge=1, le=500)
    ruwe_max: Annotated[FiniteNumber, Field(gt=0, le=10)] | None = None
    parallax_snr_min: Annotated[FiniteNumber, Field(gt=0, le=1000)] | None = None
    parallax_min: Annotated[FiniteNumber, Field(ge=-100, le=1000)] | None = None
    parallax_max: Annotated[FiniteNumber, Field(ge=-100, le=1000)] | None = None
    pmra_min: Annotated[FiniteNumber, Field(ge=-10000, le=10000)] | None = None
    pmra_max: Annotated[FiniteNumber, Field(ge=-10000, le=10000)] | None = None
    pmdec_min: Annotated[FiniteNumber, Field(ge=-10000, le=10000)] | None = None
    pmdec_max: Annotated[FiniteNumber, Field(ge=-10000, le=10000)] | None = None
    g_mag_max: Annotated[FiniteNumber, Field(ge=-5, le=25)] | None = None
    estimate_distance: StrictBool = False

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


class ChatResponse(BaseModel):
    status: Literal["success", "partial", "error"]
    answer: str
    results: list[QueryResult] = Field(default_factory=list)
    literature_results: list[LiteratureSearchResult] = Field(default_factory=list)
    gaia_results: list[GaiaQueryResult] = Field(default_factory=list)
    sources: list[Source] = Field(default_factory=list)
    warnings: list[ErrorInfo] = Field(default_factory=list)
