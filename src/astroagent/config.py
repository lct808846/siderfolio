"""从环境和本地 .env 读取配置；密钥不会出现在 repr 中。"""

import os
import re
from pathlib import Path
from typing import Literal

from pydantic import AnyHttpUrl, Field, SecretStr, ValidationInfo, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from astroagent.model_schemas import ChatModelOption


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    deepseek_api_key: SecretStr = SecretStr("")
    deepseek_model: str = Field(default="deepseek-flash", min_length=1)
    selected_model_id: str = Field(default="", exclude=True, repr=False)
    selected_model_label: str = Field(default="", exclude=True, repr=False)
    model_input_price_per_1m: float | None = Field(default=None, exclude=True, repr=False)
    model_output_price_per_1m: float | None = Field(default=None, exclude=True, repr=False)
    model_price_currency: Literal["USD", "CNY"] = Field(default="USD", exclude=True, repr=False)
    model_protocol: Literal["openai_chat", "openai_responses", "anthropic", "gemini"] = (
        "openai_chat"
    )
    deepseek_base_url: AnyHttpUrl = AnyHttpUrl("https://api.deepseek.com")
    chat_models: list[ChatModelOption] = Field(default_factory=list, max_length=16)
    llm_thinking_parameter: Literal["thinking", "enable_thinking", "none"] = "thinking"
    llm_timeout_seconds: float = Field(default=60, gt=0, le=300)
    simbad_timeout_seconds: float = Field(default=20, gt=0, le=120)
    ads_api_token: SecretStr = SecretStr("")
    ads_timeout_seconds: float = Field(default=20, gt=0, le=120)
    gaia_timeout_seconds: float = Field(default=45, gt=0, le=120)
    agent_max_rounds: int = Field(default=4, ge=1, le=8)
    agent_max_tool_calls: int = Field(default=6, ge=1, le=12)

    @model_validator(mode="after")
    def model_catalog(self):
        ids = [model.id for model in self.chat_models]
        if len(ids) != len(set(ids)) or (ids and self.deepseek_model not in ids):
            raise ValueError("Model IDs must be unique and include the default model")
        return self

    @property
    def available_models(self):
        return self.chat_models or [
            ChatModelOption(id=self.deepseek_model, label=self.deepseek_model)
        ]

    def for_model(self, model_id=None):
        from astroagent.errors import ServiceError
        from astroagent.model_providers import configured_registry

        registry = configured_registry(self)
        if registry is not None:
            return registry.resolve(model_id)

        selected = model_id if model_id is not None else self.deepseek_model
        if selected not in {model.id for model in self.available_models}:
            raise ServiceError(422, "model_not_enabled", "所选模型未启用，请刷新模型列表。")
        return self.model_copy(update={"deepseek_model": selected, "selected_model_id": selected})

    def non_thinking_body(self):
        if self.llm_thinking_parameter == "enable_thinking":
            return {"enable_thinking": False}
        if self.llm_thinking_parameter == "thinking":
            return {"thinking": {"type": "disabled"}}
        return {}


class LocalSettings(BaseSettings):
    """会话基础设施配置，与模型密钥/工具配置分开验证。"""

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore", env_prefix="ASTROAGENT_"
    )
    deployment_mode: Literal["native", "container"] = "native"
    proxy_token: SecretStr = SecretStr("")
    data_dir: Path = Path(".astroagent")
    database_url: SecretStr = SecretStr("")
    rag_model_path: Path | None = None
    rag_model_sha256: str = ""
    rag_model_name: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    rag_dimension: int = Field(default=384, ge=32, le=2048)
    rag_model_bytes: int = Field(default=2 * 1024**3, ge=1024, le=4 * 1024**3)
    rag_vector_bytes: int = Field(default=128 * 1024**2, ge=1024, le=512 * 1024**2)
    rag_semantic_enabled: bool = True
    rag_max_cosine_distance: float = Field(default=0.65, ge=0, le=2)
    rag_query_cache_size: int = Field(default=32, ge=0, le=128)
    rag_query_cache_seconds: float = Field(default=300, gt=0, le=900)
    local_model_enabled: bool = False
    local_model_url: str = "http://127.0.0.1:11434"
    local_model_name: str = Field(
        default="astroagent-qwen3-4b-instruct-2507:q4km",
        min_length=1,
        max_length=120,
        pattern=r"^[a-zA-Z0-9_.:/-]+$",
    )
    local_model_digest: str = Field(default="", pattern=r"^(?:sha256:)?[0-9a-f]{64}$|^$")
    local_model_timeout_seconds: int = Field(default=120, ge=5, le=120)
    local_model_threads: int = Field(default=4, ge=1, le=8)
    local_model_queue_size: int = Field(default=2, ge=0, le=4)
    astronomy_tool_transport: Literal["direct", "mcp"] = "direct"
    mcp_startup_timeout_seconds: float = Field(default=15.0, ge=1.0, le=60.0)
    mcp_call_timeout_seconds: float = Field(default=60.0, ge=1.0, le=180.0)
    mcp_max_message_bytes: int = Field(default=8 * 1024 * 1024, ge=64 * 1024, le=16 * 1024 * 1024)
    mcp_max_request_bytes: int = Field(default=256 * 1024, ge=4 * 1024, le=1024 * 1024)
    mcp_pool_size: int = Field(default=2, ge=1, le=4)
    mcp_acquire_timeout_seconds: float = Field(default=5.0, ge=0.1, le=60.0)

    @field_validator("local_model_url")
    @classmethod
    def loopback_model(cls, value, info: ValidationInfo):
        from urllib.parse import urlsplit

        parsed = urlsplit(value)
        if (
            parsed.scheme != "http"
            or parsed.hostname
            not in (
                ("ollama",)
                if info.data.get("deployment_mode") == "container"
                else ("127.0.0.1", "::1")
            )
            or parsed.username
            or parsed.password
            or parsed.path not in ("", "/")
            or parsed.query
            or parsed.fragment
            or not 1 <= (parsed.port or 11434) <= 65535
            or info.data.get("deployment_mode") == "container"
            and parsed.port != 11434
        ):
            raise ValueError("Use the fixed model origin for the selected deployment mode")
        return value.rstrip("/")

    plot_execution_enabled: bool = False
    plot_executor_url: str = "http://plot-executor:8090"
    plot_executor_token: SecretStr = SecretStr("")

    @field_validator("plot_executor_url")
    @classmethod
    def fixed_executor(cls, value):
        if value != "http://plot-executor:8090":
            raise ValueError("Only the fixed internal plot executor is allowed")
        return value

    plot_python_image: str = ""
    plot_gnuplot_image: str = ""
    plot_docker_host: str = (
        "npipe:////./pipe/docker_engine" if os.name == "nt" else "unix:///var/run/docker.sock"
    )
    plot_timeout_seconds: int = Field(default=30, ge=5, le=30)

    @field_validator("plot_docker_host")
    @classmethod
    def local_plot_daemon(cls, value):
        if value not in {"npipe:////./pipe/docker_engine", "unix:///var/run/docker.sock"}:
            raise ValueError("Only the local Docker daemon is permitted")
        return value

    @field_validator("database_url")
    @classmethod
    def local_database(cls, value, info: ValidationInfo):
        from urllib.parse import urlsplit

        raw = value.get_secret_value()
        if not raw:
            return value
        parsed = urlsplit(raw)
        if (
            parsed.scheme not in ("postgresql", "postgres")
            or parsed.hostname
            not in (
                ("postgres",)
                if info.data.get("deployment_mode") == "container"
                else ("localhost", "127.0.0.1", "::1")
            )
            or info.data.get("deployment_mode") == "container"
            and parsed.port != 5432
            or not parsed.path.strip("/")
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("A local PostgreSQL URL without extra connection options is required")
        return value

    @model_validator(mode="after")
    def container_proxy(self):
        if self.deployment_mode == "container":
            if not re.fullmatch("[0-9a-f]{64}", self.proxy_token.get_secret_value()):
                raise ValueError("Container mode requires an independent proxy credential")
            loopback_origins = {
                "http://127.0.0.1:5173",
                "http://localhost:5173",
            }

            from astroagent.auth_config import AuthSettings

            try:
                site = AuthSettings()
                # AuthSettings already validates HTTPS or explicitly enabled local
                # HTTP. Honor its exact port so isolated deployments can coexist.
                trusted = {site.origin}
            except Exception:
                trusted = loopback_origins
            if not set(self.allowed_origins) <= trusted or not set(self.allowed_hosts) <= {
                "127.0.0.1",
                "localhost",
                "[::1]",
            }:
                raise ValueError("Container mode only permits the fixed local browser entry")
        return self

    allowed_origins: list[str] = [
        "http://127.0.0.1:5173",
        "http://localhost:5173",
        "http://127.0.0.1:8000",
        "http://localhost:8000",
    ]
    allowed_hosts: list[str] = ["127.0.0.1", "localhost", "[::1]"]
    max_turns: int = Field(default=40, ge=1, le=40)
    storage_bytes: int = Field(default=256 * 1024**2, ge=1024, le=256 * 1024**2)
    turn_bytes: int = Field(default=16 * 1024**2, ge=512, le=16 * 1024**2)
    artifact_bytes: int = Field(default=64 * 1024**2, ge=1024, le=64 * 1024**2)
    artifact_count: int = Field(default=8, ge=1, le=8)
    artifact_ttl_seconds: float = Field(default=900, gt=0, le=900)

    @field_validator("data_dir")
    @classmethod
    def local_disk(cls, value):
        if str(value).replace("\\", "/").startswith("//"):
            raise ValueError("The data directory must be on a local disk")
        return value

    @field_validator("allowed_origins")
    @classmethod
    def explicit_origins(cls, values):
        from urllib.parse import urlsplit

        for value in values:
            parsed = urlsplit(value)
            if (
                parsed.scheme not in {"http", "https"}
                or not parsed.netloc
                or parsed.username
                or parsed.password
                or parsed.path
                or parsed.query
                or parsed.fragment
            ):
                raise ValueError("Explicit HTTP(S) origins are required")
        return values
