"""从环境和本地 .env 读取配置；密钥不会出现在 repr 中。"""

from pydantic import AnyHttpUrl, Field, SecretStr
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
