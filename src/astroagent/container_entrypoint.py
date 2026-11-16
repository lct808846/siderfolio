"""Read mounted secrets at runtime, never at image build time. No implicit DB/model setup."""

import json
import os
import re
import sys
from pathlib import Path
from urllib.parse import quote


def secret(name):
    path = Path("/run/secrets") / name
    if not path.is_file() or path.stat().st_size > 32768:
        raise ValueError("Missing runtime secret")
    return path.read_text(encoding="utf-8").strip()


def main():
    try:
        password, proxy = secret("database_password"), secret("proxy_token")
        if not re.fullmatch(r"[0-9a-f]{64}", password) or not re.fullmatch(r"[0-9a-f]{64}", proxy):
            raise ValueError("Invalid runtime credential")
        database = os.getenv("ASTROAGENT_CONTAINER_DATABASE", "astroagent")
        if not re.fullmatch("[a-z][a-z0-9_]{0,62}", database):
            raise ValueError("Invalid database name")
        remote = json.loads(secret("backend_settings"))
        allowed = {
            "DEEPSEEK_API_KEY",
            "DEEPSEEK_BASE_URL",
            "DEEPSEEK_MODEL",
            "CHAT_MODELS",
            "LLM_THINKING_PARAMETER",
            "LLM_TIMEOUT_SECONDS",
            "ADS_API_TOKEN",
            "SIMBAD_TIMEOUT_SECONDS",
            "ADS_TIMEOUT_SECONDS",
            "GAIA_TIMEOUT_SECONDS",
        }
        if not isinstance(remote, dict) or set(remote) - allowed:
            raise ValueError("Unexpected backend settings")
        for key, value in remote.items():
            if key == "CHAT_MODELS":
                if not isinstance(value, list):
                    raise ValueError("Invalid model list")
                value = json.dumps(value, ensure_ascii=False)
            if not isinstance(value, str) or "\x00" in value:
                raise ValueError("Invalid backend setting")
            os.environ[key] = value
        os.environ.update(
            ASTROAGENT_DEPLOYMENT_MODE="container",
            ASTROAGENT_DATABASE_URL=(
                f"postgresql://astroagent:{quote(password, safe='')}@postgres:5432/{database}"
            ),
            ASTROAGENT_PROXY_TOKEN=proxy,
        )
        identity = json.loads(secret("auth_settings"))
        from astroagent.auth_config import AuthSettings

        names = {"ASTROAGENT_AUTH_" + name.upper() for name in AuthSettings.model_fields}
        if not isinstance(identity, dict) or set(identity) - names:
            raise ValueError("Unexpected identity settings")
        for key, value in identity.items():
            if not isinstance(value, str) or "\x00" in value:
                raise ValueError("Invalid identity setting")
            os.environ[key] = value
        auth = AuthSettings()
        os.environ["ASTROAGENT_ALLOWED_ORIGINS"] = json.dumps([auth.origin])
        if Path("/run/secrets/executor_token").is_file():
            token = secret("executor_token")
            if not re.fullmatch(r"[0-9a-f]{64}", token):
                raise ValueError("Invalid executor credential")
            os.environ["ASTROAGENT_PLOT_EXECUTOR_TOKEN"] = token
        # Validate before binding a listener; pydantic errors must not print input values.
        from astroagent.config import LocalSettings, Settings

        LocalSettings()
        Settings()
    except Exception:
        raise SystemExit(
            "Container configuration is invalid; check mounted settings without printing secrets."
        ) from None
    if sys.argv[1:2] == ["identity"]:
        os.execvp("python", ["python", "-m", "astroagent.identity_cli", *sys.argv[2:]])
    if sys.argv[1:] not in ([], ["serve"]):
        raise SystemExit("Unsupported container command")
    os.execvp(
        "python",
        [
            "python",
            "-m",
            "uvicorn",
            "astroagent.main:app",
            "--host",
            "0.0.0.0",
            "--port",
            "8000",
            "--workers",
            "1",
            "--no-proxy-headers",
            "--no-access-log",
        ],
    )


if __name__ == "__main__":
    main()
