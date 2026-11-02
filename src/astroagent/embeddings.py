"""Pinned local-only embeddings in a bounded subprocess; never download at runtime."""

import hashlib
import json
import math
import os
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

from astroagent.errors import ServiceError

EMBED_SLOT = threading.BoundedSemaphore(1)


def model_identity(path, budget):
    root = path.resolve(strict=True)
    if not root.is_dir():
        raise ValueError("Model directory is missing")
    values, size = [], 0
    for item in sorted(root.rglob("*")):
        if ".cache" in item.relative_to(root).parts:
            continue
        if item.is_symlink():
            raise ValueError("Model symlinks are not accepted")
        if not item.is_file() or item.name == "astroagent-model.json":
            continue
        size += item.stat().st_size
        if size > budget or len(values) >= 2000:
            raise ValueError("Model exceeds the configured budget")
        sha = hashlib.sha256()
        with item.open("rb") as source:
            while chunk := source.read(1024**2):
                sha.update(chunk)
        values.append([item.relative_to(root).as_posix(), item.stat().st_size, sha.hexdigest()])
    if not values or not (root / "modules.json").is_file():
        raise ValueError("Sentence Transformer files are incomplete")
    return hashlib.sha256(json.dumps(values, separators=(",", ":")).encode()).hexdigest(), size


class LocalEmbedder:
    def __init__(self, settings):
        self.settings = settings

    def identity(self):
        value = self.settings
        if value.rag_model_path is None or len(value.rag_model_sha256) != 64:
            raise ServiceError(
                503,
                "rag_model_not_configured",
                "请先准备并固定本地嵌入模型及文件SHA-256；不会自动下载。",
            )
        try:
            sha, _ = model_identity(value.rag_model_path, value.rag_model_bytes)
            if sha != value.rag_model_sha256:
                raise ValueError("Model fingerprint mismatch")
        except (OSError, ValueError) as exc:
            raise ServiceError(
                503, "rag_model_identity_invalid", "本地模型缺失、超限或固定文件哈希不符。"
            ) from exc
        return sha

    def encode(self, texts):
        if not EMBED_SLOT.acquire(blocking=False):
            raise ServiceError(
                409, "rag_embedding_busy", "已有本地嵌入任务；本次可使用词法结果，或稍后重新预览。"
            )
        try:
            return self._encode(texts)
        finally:
            EMBED_SLOT.release()

    def _encode(self, texts):
        self.identity()
        if not texts or len(texts) > 25000 or sum(len(t.encode()) for t in texts) > 20 * 1024**2:
            raise ServiceError(422, "rag_embedding_limit", "嵌入批次超出25000段或20 MiB限制。")
        from astroagent.knowledge_parser import windows_job

        process, release = None, None
        try:
            with tempfile.TemporaryDirectory(prefix="astroagent-embedding-") as temporary:
                root = Path(temporary)
                source, target = root / "input.json", root / "vectors.bin"
                source.write_text(json.dumps(texts, ensure_ascii=False), encoding="utf-8")
                environment = {
                    key: os.environ[key]
                    for key in (
                        "SystemRoot",
                        "WINDIR",
                        "TEMP",
                        "TMP",
                        "LANG",
                        "LC_ALL",
                        "HF_HOME",
                        "HF_HUB_CACHE",
                        "TORCH_HOME",
                        "XDG_CACHE_HOME",
                    )
                    if key in os.environ
                }
                environment.update(
                    HF_HUB_OFFLINE="1",
                    TRANSFORMERS_OFFLINE="1",
                    OMP_NUM_THREADS="1",
                    TOKENIZERS_PARALLELISM="false",
                )
                process = subprocess.Popen(
                    [
                        sys.executable,
                        "-I",
                        str(Path(__file__).with_name("embedding_worker.py")),
                        str(source),
                        str(self.settings.rag_model_path.resolve()),
                        str(target),
                        str(self.settings.rag_dimension),
                    ],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    env=environment,
                    cwd=root,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                )
                if os.name == "nt":
                    release = windows_job(process, memory_bytes=3 * 1024**3)
                process.communicate(input=b"1", timeout=120)
                expected = len(texts) * self.settings.rag_dimension * 4
                if (
                    process.returncode
                    or not target.is_file()
                    or target.stat().st_size != expected
                    or expected > self.settings.rag_vector_bytes
                ):
                    raise ValueError("Local embedding did not complete")
                import numpy as np

                matrix = np.fromfile(target, dtype="<f4").reshape(
                    len(texts), self.settings.rag_dimension
                )
                if not all(math.isfinite(float(v)) for v in matrix.flat):
                    raise ValueError("Invalid vector")
                norms = np.linalg.norm(matrix, axis=1)
                if not np.allclose(norms, 1, atol=0.001):
                    raise ValueError("Unnormalized or empty vector")
                self.identity()
                return matrix.tolist()
        except ServiceError:
            raise
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            raise ServiceError(
                503,
                "rag_embedding_unavailable",
                "本地嵌入未完成：请核对模型依赖、文件、120秒时限与3 GiB进程内存边界。",
            ) from exc
        finally:
            if process is not None:
                if process.poll() is None:
                    process.kill()
                process.wait()
            if release:
                release()


def vector_literal(vector):
    if not vector or not all(math.isfinite(v) for v in vector):
        raise ValueError("Invalid vector")
    return "[" + ",".join(format(v, ".9g") for v in vector) + "]"
