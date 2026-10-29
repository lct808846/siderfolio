"""从实际 OpenAPI 生成前端类型；--check 不修改已提交类型。"""

import argparse
import json
import os
import subprocess
import tempfile
from pathlib import Path

from astroagent.main import app

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    frontend = ROOT / "frontend"
    schema = json.dumps(app.openapi(), ensure_ascii=False, indent=2) + "\n"
    with tempfile.TemporaryDirectory() as temporary:
        directory = Path(temporary)
        input_path = directory / "openapi.json"
        output_path = directory / "generated.ts"
        input_path.write_text(schema, encoding="utf-8")
        subprocess.run(
            [
                os.getenv("NODE_BINARY", "node"),
                str(frontend / "node_modules/openapi-typescript/bin/cli.js"),
                str(input_path),
                "-o",
                str(output_path),
            ],
            check=True,
        )
        generated = output_path.read_text(encoding="utf-8")
    if args.check:
        assert (frontend / "openapi.json").read_text(encoding="utf-8") == schema, (
            "OpenAPI snapshot is stale"
        )
        assert (frontend / "src/types/generated.ts").read_text(encoding="utf-8") == generated, (
            "Frontend types are stale"
        )
    else:
        (frontend / "openapi.json").write_text(schema, encoding="utf-8")
        (frontend / "src/types/generated.ts").write_text(generated, encoding="utf-8")
    print("OpenAPI / TypeScript contract matches")


if __name__ == "__main__":
    main()
