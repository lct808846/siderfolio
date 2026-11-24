"""Identity settings are server-only; authentication has no anonymous fallback."""

from email.utils import parseaddr
from pathlib import Path
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class AuthSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="ASTROAGENT_AUTH_", env_file=".env", extra="ignore"
    )
    origin: str = "http://127.0.0.1:5173"
    local_http: bool = False
    secret: SecretStr = SecretStr("")
    idle_seconds: int = Field(default=315360000, ge=300, le=315360000)
    absolute_seconds: int = Field(default=315360000, ge=1800, le=315360000)
    cookie_max_age: int = Field(default=34560000, ge=3600, le=34560000)
    token_seconds: int = Field(default=1800, ge=300, le=3600)
    smtp_host: str = ""
    smtp_port: int = Field(default=465, ge=1, le=65535)
    smtp_user: str = ""
    smtp_password: SecretStr = SecretStr("")
    smtp_from: str = ""
    smtp_mode: str = "tls"
    mail_hour_limit: int = Field(default=100, ge=1, le=10000)
    mail_day_limit: int = Field(default=90, ge=1, le=10000)
    mail_month_limit: int = Field(default=2700, ge=1, le=300000)
    mail_request_address_day_limit: int = Field(default=8, ge=1, le=1000)
    mail_request_ip_day_limit: int = Field(default=20, ge=1, le=1000)
    registration_ip_day_limit: int = Field(default=5, ge=1, le=1000)
    registration_enabled: bool = True
    registration_limit: int = Field(default=1000, ge=1, le=100000)
    tenant_limit: int = Field(default=32, ge=1, le=128)
    audit_days: int = Field(default=90, ge=7, le=365)
    password_blocklist: Path | None = Path(__file__).parent / "auth_data" / "common-passwords.txt"
    password_blocklist_sha256: str = (
        "1472aafa2561df5e3293aee252aee3ca660c12b399a283cf808bb01b39be388b"
    )

    @property
    def secure(self):
        return not self.local_http

    @property
    def mail_ready(self):
        return all(
            (self.smtp_host, self.smtp_user, self.smtp_password.get_secret_value(), self.smtp_from)
        )

    @property
    def feedback_mail_ready(self):
        return (
            self.mail_ready
            and not self.local_http
            and parseaddr(self.smtp_from)[1].lower() == "noreply@siderfolio.com"
        )

    @model_validator(mode="after")
    def boundary(self):
        parsed = urlsplit(self.origin)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("A fixed trusted site origin is required")
        if parsed.scheme == "http" and not (
            self.local_http and parsed.hostname in {"127.0.0.1", "localhost", "::1"}
        ):
            raise ValueError("HTTP is restricted to explicitly enabled loopback development")
        if self.local_http and parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError("Local development mode cannot be used on a remote site")
        if self.smtp_mode not in {"tls", "starttls"}:
            raise ValueError("Encrypted authenticated SMTP is required")
        hostname = parsed.hostname.encode("idna").decode("ascii").lower()
        host = f"[{hostname}]" if ":" in hostname else hostname
        port = parsed.port
        suffix = (
            f":{port}"
            if port and (parsed.scheme, port) not in {("http", 80), ("https", 443)}
            else ""
        )
        self.origin = f"{parsed.scheme}://{host}{suffix}"
        return self
