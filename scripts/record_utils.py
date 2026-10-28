"""测试记录按项目版本、类型和 UTC 运行时间归档。"""

import importlib.metadata
import json
import re
import subprocess
import sys
import tomllib
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RECORDS = ROOT / "docs" / "test-records"


def runtime_metadata() -> dict:
    """只记录版本、Git 状态；不保存环境变量、密钥或请求头。"""

    def git(*args):
        result = subprocess.run(
            ["git", *args],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
            encoding="utf-8",
            errors="replace",
        )
        return result.stdout.strip() if result.returncode == 0 else None

    versions = {}
    for name in (
        "astroagent",
        "fastapi",
        "langchain-core",
        "langchain-openai",
        "astroquery",
        "astropy",
        "defusedxml",
        "numpy",
        "matplotlib",
        "requests",
        "pydantic",
        "pytest",
    ):
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = None
    state = git("status", "--porcelain")
    return {
        "python": sys.version.split()[0],
        "versions": versions,
        "git_head": git("rev-parse", "HEAD"),
        "git_dirty": bool(state) if state is not None else None,
        "git_status": state,
    }


def project_version() -> str:
    with (ROOT / "pyproject.toml").open("rb") as source:
        return tomllib.load(source)["project"]["version"]


def create_record_directory(
    kind: str, *, version: str | None = None, recorded_at: datetime | None = None
) -> Path:
    version = version or project_version()
    for component in (version, kind):
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._+-]*", component):
            raise ValueError("Invalid record version or kind")
    timestamp = (recorded_at or datetime.now(UTC)).astimezone(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    directory = RECORDS / f"v{version}" / kind / timestamp
    directory.mkdir(parents=True, exist_ok=False)
    return directory


def write_report(directory: Path, report: dict) -> Path:
    path = directory / "report.json"
    # 即使调用方重复写入，也不能覆盖已有记录。
    with path.open("x", encoding="utf-8") as target:
        json.dump(report, target, ensure_ascii=False, indent=2)
        target.write("\n")
    return path
