"""Provenance shared by astronomical query results and the literature library."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class Source(BaseModel):
    name: Literal["SIMBAD", "ADS", "Gaia"] = "SIMBAD"
    url: str
    retrieved_at: datetime
