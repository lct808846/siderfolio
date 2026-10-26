"""接口与工具共用的可追溯数据结构。"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


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
    name: Literal["SIMBAD"] = "SIMBAD"
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


class ChatResponse(BaseModel):
    status: Literal["success", "partial", "error"]
    answer: str
    results: list[QueryResult] = Field(default_factory=list)
    sources: list[Source] = Field(default_factory=list)
    warnings: list[ErrorInfo] = Field(default_factory=list)
