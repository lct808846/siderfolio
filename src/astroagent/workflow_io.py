"""流程产物的固定格式与完整性边界；不会执行导入文本或访问其URL。"""

import csv
import hashlib
import math
import re
import stat
import threading
from io import BytesIO, StringIO
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile

from astroagent.conversations import encode
from astroagent.export_schemas import (
    ExportManifest,
    ExportSnapshot,
    _strict_type,
    validate_snapshot,
)

MAX_FILE_BYTES = 16 * 1024**2
CSV_READER_LOCK = threading.RLock()
PACKAGE_PATH = re.compile(
    r"(?:snapshot\.json|manifest\.json|README\.md|"
    r"tables/(?:simbad|ads|gaia)-[0-9]{3}\.csv|"
    r"figures/gaia-[0-9]{3}-(?:proper-motion|parallax-histogram|observed-cmd)\.png)"
)


def safe_csv(content):
    if not content.startswith(b"\xef\xbb\xbf"):
        raise ValueError("CSV requires UTF-8 BOM")
    with CSV_READER_LOCK:
        previous = csv.field_size_limit(MAX_FILE_BYTES)
        try:
            for line in csv.reader(StringIO(content.decode("utf-8-sig"), newline=""), strict=True):
                for cell in line:
                    candidate = cell.lstrip()
                    if candidate.startswith(("=", "+", "@")) or cell.startswith(("\t", "\r")):
                        raise ValueError("Unprotected spreadsheet expression")
                    if candidate.startswith("-"):
                        try:
                            if len(candidate) > 400 or not math.isfinite(float(candidate)):
                                raise ValueError("Non-finite CSV number")
                        except ValueError as exc:
                            raise ValueError("Unprotected negative text") from exc
        except csv.Error as exc:
            raise ValueError("Invalid CSV") from exc
        finally:
            csv.field_size_limit(previous)


def package_members(content):
    from astroagent.project_archives import strict_json

    if len(content) > MAX_FILE_BYTES:
        raise ValueError("ZIP output exceeds boundary")
    files, total = {}, 0
    with ZipFile(BytesIO(content)) as archive:
        infos = archive.infolist()
        if len(infos) > 32 or len({i.filename for i in infos}) != len(infos):
            raise ValueError("Unexpected package members")
        for info in infos:
            if (
                not PACKAGE_PATH.fullmatch(info.filename)
                or info.flag_bits & 1
                or stat.S_IFMT(info.external_attr >> 16) not in (0, stat.S_IFREG)
                or info.compress_type not in (ZIP_STORED, ZIP_DEFLATED)
            ):
                raise ValueError("Unsupported package entry")
            raw = bytearray()
            with archive.open(info) as source:
                while chunk := source.read(65536):
                    raw.extend(chunk)
                    total += len(chunk)
                    if total > MAX_FILE_BYTES:
                        raise ValueError("Actual package expansion exceeds boundary")
            files[info.filename] = bytes(raw)
    manifest = _strict_type(ExportManifest).model_validate_json(
        encode(strict_json(files["manifest.json"]))
    )
    names = [entry.path for entry in manifest.files]
    if len(set(names)) != len(names) or set(names) | {"manifest.json"} != set(files):
        raise ValueError("Incomplete package manifest")
    for entry in manifest.files:
        raw = files[entry.path]
        if len(raw) != entry.bytes or hashlib.sha256(raw).hexdigest() != entry.sha256:
            raise ValueError("Package file digest mismatch")
    snapshot = ExportSnapshot.model_validate_json(encode(strict_json(files["snapshot.json"])))
    validate_snapshot(snapshot)
    if manifest.snapshot_status != snapshot.status:
        raise ValueError("Package snapshot state mismatch")
    for path, raw in files.items():
        if path.endswith(".csv"):
            safe_csv(raw)
        elif path.endswith(".png") and not raw.startswith(b"\x89PNG\r\n\x1a\n"):
            raise ValueError("Invalid PNG")
    return files, manifest.model_dump(mode="json")


def validate_output(info, content):
    from astroagent.project_archives import strict_json

    if (
        len(content) != info.bytes
        or len(content) > MAX_FILE_BYTES
        or hashlib.sha256(content).hexdigest() != info.sha256
    ):
        raise ValueError("Workflow file digest mismatch")
    if info.media_type == "application/zip":
        package_members(content)
    elif info.media_type == "application/json":
        strict_json(content)
    elif info.media_type == "text/csv":
        safe_csv(content)
    elif not content.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("Invalid PNG output")
