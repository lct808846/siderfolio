"""Public model choices; credentials and provider configuration stay on the server."""

from pydantic import BaseModel, ConfigDict, Field


class ChatModelOption(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/-]*$")
    label: str = Field(min_length=1, max_length=80)
    provider: str | None = Field(default=None, max_length=60)


class ChatModelCatalog(BaseModel):
    configured: bool
    default_model: str
    models: list[ChatModelOption]
