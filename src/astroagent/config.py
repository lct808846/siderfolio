"""从环境和本地 .env 读取配置；密钥不会出现在 repr 中。"""

from pathlib import Path

from pydantic import AnyHttpUrl, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    deepseek_api_key: SecretStr = SecretStr("")
    deepseek_model: str = Field(default="deepseek-flash", min_length=1)
    deepseek_base_url: AnyHttpUrl = AnyHttpUrl("https://api.deepseek.com")
    llm_timeout_seconds: float = Field(default=60, gt=0, le=300)
    simbad_timeout_seconds: float = Field(default=20, gt=0, le=120)
    ads_api_token: SecretStr = SecretStr("")
    ads_timeout_seconds: float = Field(default=20, gt=0, le=120)
    gaia_timeout_seconds: float = Field(default=20, gt=0, le=120)
    agent_max_rounds: int = Field(default=4, ge=1, le=8)
    agent_max_tool_calls: int = Field(default=6, ge=1, le=12)


class LocalSettings(BaseSettings):
    """会话基础设施配置，与模型密钥/工具配置分开验证。"""

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore", env_prefix="ASTROAGENT_"
    )
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

    @field_validator("database_url")
    @classmethod
    def local_database(cls, value):
        from urllib.parse import urlsplit

        raw = value.get_secret_value()
        if not raw:
            return value
        parsed = urlsplit(raw)
        if (
            parsed.scheme not in ("postgresql", "postgres")
            or parsed.hostname not in ("localhost", "127.0.0.1", "::1")
            or not parsed.path.strip("/")
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("A local PostgreSQL URL without extra connection options is required")
        return value

    allowed_origins: list[str] = [
        "http://127.0.0.1:5173",
        "http://localhost:5173",
        "http://127.0.0.1:8000",
        "http://localhost:8000",
    ]
    allowed_hosts: list[str] = ["127.0.0.1", "localhost", "[::1]"]
    max_conversations: int = Field(default=20, ge=1, le=20)
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
