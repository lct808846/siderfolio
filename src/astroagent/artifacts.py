"""轮次产物缓存：预览与下载读取同一份 ZIP 字节。"""

import hashlib
import json
import re
import threading
import time
from collections import OrderedDict
from datetime import UTC, datetime, timedelta
from io import BytesIO
from uuid import uuid4
from zipfile import BadZipFile, ZipFile

from astroagent import __version__
from astroagent.api.exports import MAX_REQUEST_BYTES, validate_json
from astroagent.conversation_schemas import ArtifactInfo
from astroagent.conversations import encode
from astroagent.errors import ServiceError
from astroagent.exports import build_package


class ArtifactCache:
    def __init__(self, service, settings, clock=time.monotonic):
        self.service, self.settings, self.clock = service, settings, clock
        self.items = {}
        self.expired = OrderedDict()
        self.lock = threading.RLock()
        service.artifacts = self

    def purge(self):
        now = self.clock()
        for identifier, item in list(self.items.items()):
            if item["deadline"] <= now:
                del self.items[identifier]
                self.expired[identifier] = True
                while len(self.expired) > 128:
                    self.expired.popitem(last=False)

    def remove_conversation(self, identifier):
        with self.lock:
            for key in [
                k
                for k, v in self.items.items()
                if not v.get("owner") and v["info"].conversation_id == identifier
            ]:
                del self.items[key]

    def remove_project(self, project_id, snapshot_id=None):
        with self.lock:
            for key, value in list(self.items.items()):
                owner = value.get("owner")
                if (
                    owner
                    and owner[0] == project_id
                    and (snapshot_id is None or owner[1] == snapshot_id)
                ):
                    del self.items[key]

    def generate(self, conversation_id, turn_id, request, *, snapshot_loader=None, owner=None):
        with self.service.gate:
            response = (
                snapshot_loader()
                if snapshot_loader
                else self.service.repository.turn(conversation_id, turn_id).response
            )
            if response is None:
                raise ServiceError(422, "invalid_export_snapshot", "此记录没有可导出的完整结果。")
            snapshot = response.model_dump(mode="json")
        plots = sorted(
            [p.model_dump() for p in request.plots],
            key=lambda p: (p["gaia_result_index"], p["kind"]),
        )
        raw = encode({"schema_version": "1", "snapshot": snapshot, "plots": plots}).encode()
        if len(raw) > MAX_REQUEST_BYTES:
            raise ServiceError(413, "export_too_large", "完整快照超过导出上限，未裁剪数据。")
        try:
            validated = validate_json(raw)
        except (ValueError, TypeError) as exc:
            raise ServiceError(
                422, "invalid_export_snapshot", "此记录与当前导出格式不兼容。"
            ) from exc
        digest = hashlib.sha256(encode(snapshot).encode()).hexdigest()
        cache_key = (owner or (conversation_id, turn_id), digest, encode(plots), __version__)
        with self.lock:
            self.purge()
            for item in self.items.values():
                if item["key"] == cache_key:
                    return item["info"]
            if len(self.items) >= self.settings.artifact_count:
                raise ServiceError(
                    503, "artifact_cache_full", "产物缓存已满，请等待过期后再生成。", retryable=True
                )
        package = build_package(validated)
        identifier = str(uuid4())
        figures, members = [], {}
        with ZipFile(BytesIO(package)) as archive:
            manifest = json.loads(archive.read("manifest.json"))
            for p in manifest["plots"]:
                if p["status"] != "success":
                    continue
                path = p["output_path"]
                if not re.fullmatch(
                    r"figures/gaia-[0-9]{3}-(proper-motion|parallax-histogram|observed-cmd)\.png",
                    path,
                ):
                    raise ServiceError(500, "export_failed", "产物清单无效。")
                entry = next(f for f in manifest["files"] if f["path"] == path)
                content = archive.read(path)
                if (
                    len(content) != entry["bytes"]
                    or hashlib.sha256(content).hexdigest() != entry["sha256"]
                ):
                    raise ServiceError(500, "export_failed", "产物图片校验失败。")
                figure_id = str(uuid4())
                members[figure_id] = entry
                figures.append(
                    {
                        "figure_id": figure_id,
                        "kind": p["kind"],
                        "url": f"/api/v1/artifacts/{identifier}/figures/{figure_id}",
                        "sha256": entry["sha256"],
                    }
                )
        created = datetime.now(UTC)
        info = ArtifactInfo(
            artifact_id=identifier,
            conversation_id=conversation_id,
            turn_id=turn_id,
            snapshot_sha256=digest,
            exporter_version=__version__,
            export_status=manifest["export_status"],
            created_at=created.isoformat(),
            expires_at=(
                created + timedelta(seconds=self.settings.artifact_ttl_seconds)
            ).isoformat(),
            manifest_url=f"/api/v1/artifacts/{identifier}/manifest",
            download_url=f"/api/v1/artifacts/{identifier}/download",
            figures=figures,
        )
        with self.service.gate, self.lock:
            if snapshot_loader:
                snapshot_loader()
            else:
                self.service.repository.turn(conversation_id, turn_id)
            self.purge()
            for item in self.items.values():
                if item["key"] == cache_key:
                    return item["info"]
            if (
                len(self.items) >= self.settings.artifact_count
                or sum(len(i["package"]) for i in self.items.values()) + len(package)
                > self.settings.artifact_bytes
            ):
                raise ServiceError(
                    503, "artifact_cache_full", "产物缓存已满，请等待过期后再生成。", retryable=True
                )
            self.items[identifier] = dict(
                info=info,
                key=cache_key,
                package=package,
                manifest=manifest,
                members=members,
                deadline=self.clock() + self.settings.artifact_ttl_seconds,
                owner=owner,
            )
        return info

    def get(self, identifier):
        with self.lock:
            self.purge()
            if identifier in self.expired:
                raise ServiceError(410, "artifact_expired", "产物已过期，请回到原始结果重新生成。")
            if identifier not in self.items:
                raise ServiceError(
                    404, "artifact_not_found", "产物不存在或服务已重启，请重新生成。"
                )
            return self.items[identifier]

    def figure(self, identifier, figure_id):
        item = self.get(identifier)
        if figure_id not in item["members"]:
            raise ServiceError(404, "figure_not_found", "该产物没有此图片。")
        entry = item["members"][figure_id]
        try:
            with ZipFile(BytesIO(item["package"])) as archive:
                content = archive.read(entry["path"])
        except (BadZipFile, KeyError, OSError, ValueError) as exc:
            raise ServiceError(500, "export_failed", "产物图片校验失败。") from exc
        if len(content) != entry["bytes"] or hashlib.sha256(content).hexdigest() != entry["sha256"]:
            raise ServiceError(500, "export_failed", "产物图片校验失败。")
        return content
