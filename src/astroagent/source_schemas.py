"""Provenance and shared error contracts for astronomical queries and libraries."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class ErrorInfo(BaseModel):
    code: str
    message: str
    retryable: bool = False


class Source(BaseModel):
    name: Literal["SIMBAD", "ADS", "Gaia", "VizieR"] = "SIMBAD"
    url: str
    retrieved_at: datetime
