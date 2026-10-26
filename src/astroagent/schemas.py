"""接口与工具共用的可追溯数据结构。"""

from datetime import datetime
from typing import Literal
from urllib.parse import quote_plus

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    message: str = Field(min_length=1, max_length=4000, examples=["请查询 Betelgeuse 的坐标和类型"])


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
    name: Literal["SIMBAD", "ADS"] = "SIMBAD"
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


class ChatResponse(BaseModel):
    status: Literal["success", "partial", "error"]
    answer: str
    results: list[QueryResult] = Field(default_factory=list)
    literature_results: list[LiteratureSearchResult] = Field(default_factory=list)
    sources: list[Source] = Field(default_factory=list)
    warnings: list[ErrorInfo] = Field(default_factory=list)
