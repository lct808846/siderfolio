"""Isolated local CPU embedding worker; starts only after the parent's limits handshake."""

import json
import os
import socket
import sys
from pathlib import Path


def main():
    if sys.stdin.buffer.read(1) != b"1":
        return 3
    if sys.platform.startswith("linux"):
        import resource

        resource.setrlimit(resource.RLIMIT_AS, (3 * 1024**3, 3 * 1024**3))
        resource.setrlimit(resource.RLIMIT_CPU, (115, 120))
        resource.setrlimit(resource.RLIMIT_FSIZE, (128 * 1024**2, 128 * 1024**2))
    elif os.name != "nt":
        return 3

    def blocked(*args, **kwargs):
        raise OSError("Embedding worker is offline")

    socket.socket.connect = blocked
    socket.create_connection = blocked
    source, model_path, target, dimension = sys.argv[1:]
    if Path(source).stat().st_size > 32 * 1024**2:
        return 2
    texts = json.loads(Path(source).read_text(encoding="utf-8"))
    if (
        not isinstance(texts, list)
        or not 1 <= len(texts) <= 25000
        or any(not isinstance(t, str) or len(t) > 1200 for t in texts)
    ):
        return 2
    # Restrict module types as well as disabling transformer remote code / pickle weights.
    modules = json.loads((Path(model_path) / "modules.json").read_text(encoding="utf-8"))
    allowed = {
        "sentence_transformers.models.Transformer",
        "sentence_transformers.models.Pooling",
        "sentence_transformers.models.Normalize",
    }
    if any(module.get("type") not in allowed for module in modules):
        return 2
    root = Path(model_path).resolve()
    for module in modules:
        relative = Path(module.get("path", ""))
        if (
            relative.is_absolute()
            or ".." in relative.parts
            or ".cache" in relative.parts
            or not (root / relative).resolve().is_relative_to(root)
        ):
            return 2
    import torch
    from sentence_transformers import SentenceTransformer

    torch.set_num_threads(1)
    model = SentenceTransformer(
        model_path,
        device="cpu",
        local_files_only=True,
        trust_remote_code=False,
        model_kwargs={"use_safetensors": True},
    )
    if model.get_sentence_embedding_dimension() != int(dimension):
        return 2
    vectors = model.encode(
        texts,
        batch_size=16,
        show_progress_bar=False,
        normalize_embeddings=True,
        convert_to_numpy=True,
    )
    vectors.astype("<f4").tofile(target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
