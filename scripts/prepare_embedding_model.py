"""Explicit model metadata/download or offline fingerprint; never invoked by application startup."""

import argparse
import fnmatch
import json
import re
from pathlib import Path

from astroagent.embeddings import model_identity

REPOSITORY = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
PATTERNS = ["*.json", "*.txt", "*.safetensors", "*.model"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("describe", "download", "fingerprint"))
    parser.add_argument("--revision")
    parser.add_argument("--directory", type=Path)
    parser.add_argument("--maximum-bytes", type=int, default=2 * 1024**3)
    parser.add_argument("--confirm-download", action="store_true")
    args = parser.parse_args()
    if not 1024 <= args.maximum_bytes <= 4 * 1024**3:
        parser.error("模型预算范围为1 KiB至4 GiB。")
    if args.action == "fingerprint":
        if args.directory is None:
            parser.error("提供本地目录；此操作不联网。")
        sha, size = model_identity(args.directory, args.maximum_bytes)
        print(json.dumps({"sha256": sha, "bytes": size, "model": REPOSITORY}))
        return
    if not args.revision or not re.fullmatch(r"[0-9a-f]{40}", args.revision):
        parser.error("必须事先选定40位固定模型提交；不接受浮动main。")
    from huggingface_hub import HfApi, hf_hub_download

    info = HfApi(token=False).model_info(REPOSITORY, revision=args.revision, files_metadata=True)
    files = [
        file
        for file in info.siblings
        if any(fnmatch.fnmatch(file.rfilename, pattern) for pattern in PATTERNS)
        and not file.rfilename.startswith(("onnx/", "openvino/"))
    ]
    if info.sha != args.revision or any(file.size is None for file in files):
        raise ValueError("模型版本或文件体积信息不可核对。")
    size = sum(file.size for file in files)
    print(
        json.dumps(
            {
                "source": "https://huggingface.co/" + REPOSITORY,
                "revision": info.sha,
                "download_bytes": size,
                "budget_bytes": args.maximum_bytes,
                "license": "Review the pinned model card before download",
            },
            ensure_ascii=False,
        )
    )
    if args.action == "describe":
        return
    if not args.confirm_download or args.directory is None or size > args.maximum_bytes:
        parser.error("下载须明确确认、提供全新目录并满足已知磁盘预算。")
    root = args.directory.resolve()
    root.mkdir(parents=True, exist_ok=False)
    for file in files:
        # Fixed allow-list extensions only; no repository Python, pickle or arbitrary URLs.
        hf_hub_download(
            REPOSITORY, file.rfilename, revision=args.revision, local_dir=root, token=False
        )
    # Hub creates local metadata; it is not part of the inference model identity.
    sha, actual = model_identity(root, args.maximum_bytes)
    (root / "astroagent-model.json").write_text(
        json.dumps(
            {"repository": REPOSITORY, "revision": info.sha, "sha256": sha, "bytes": actual},
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print("ASTROAGENT_RAG_MODEL_SHA256=" + sha)


if __name__ == "__main__":
    main()
