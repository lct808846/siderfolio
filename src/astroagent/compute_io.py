"""The fixed, bounded file protocol between the dispatcher and simulator."""

import json
import os
import re
import time
from pathlib import Path

from astroagent.compute_schemas import MAX_OUTPUT_BYTES, SPOOL


def spool() -> Path:
    return Path(SPOOL)


def fresh(path: Path, seconds: int = 8) -> bool:
    try:
        return 0 <= time.time() - path.stat().st_mtime <= seconds
    except FileNotFoundError:
        return False


def write(path: Path, value) -> None:
    data = json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()
    if len(data) > MAX_OUTPUT_BYTES:
        raise ValueError("Output limit exceeded")
    temporary = path.with_suffix(".part")
    temporary.write_bytes(data)
    os.replace(temporary, path)


def read(path: Path, limit: int = MAX_OUTPUT_BYTES):
    with path.open("rb") as stream:
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise ValueError("Output limit exceeded")
    return json.loads(data)


def attempts(root: Path):
    return sorted(
        path for path in root.iterdir() if re.fullmatch("[0-9a-f]{32}", path.name) and path.is_dir()
    )
