"""测试记录按项目版本、类型和 UTC 运行时间归档。"""

import json
import re
import tomllib
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RECORDS = ROOT / "docs" / "test-records"


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
