"""前端检查/浏览器验收按版本归档；不会使用个人会话库。"""

import argparse
import os
import shutil
import socket
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

from record_utils import ROOT, create_record_directory, runtime_metadata, write_report


def npm_command(node):
    executable = Path(shutil.which("npm.cmd" if os.name == "nt" else "npm") or "npm")
    candidate = (
        executable.parent / "node_modules/npm/bin/npm-cli.js"
        if os.name == "nt"
        else executable.resolve()
    )
    return [node, str(candidate)] if candidate.is_file() else [str(executable)]


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--browser", action="store_true")
    args = parser.parse_args()
    out = create_record_directory("browser-tests" if args.browser else "frontend-tests")
    node = os.getenv("NODE_BINARY", "node")
    npm = npm_command(node)
    environment = os.environ.copy()
    environment["ASTROAGENT_PYTHON"] = sys.executable
    environment["ASTROAGENT_RECORD_DIR"] = str(out)
    environment["ASTROAGENT_BROWSER_REPORT"] = str(out / "playwright.json")
    environment["PATH"] = (
        str(Path(shutil.which(node) or node).resolve().parent)
        + os.pathsep
        + environment.get("PATH", "")
    )
    environment["PYTHONIOENCODING"] = "utf-8"
    commands = [
        [*npm, "ci", "--no-audit", "--no-fund"],
        [*npm, "run", "typecheck"],
        [*npm, "run", "lint"],
        [*npm, "run", "test"],
        [*npm, "run", "build"],
        [sys.executable, str(ROOT / "scripts/generate_frontend_types.py"), "--check"],
    ]
    if args.browser:
        commands = [
            [*npm, "run", "build"],
            [
                node,
                str(ROOT / "frontend/node_modules/playwright/cli.js"),
                "test",
                "--output",
                str(out / "artifacts"),
            ],
        ]
    report = {
        "started_at": datetime.now(UTC).isoformat(),
        **runtime_metadata(),
        "checks": [],
        "node": subprocess.check_output([node, "--version"], text=True).strip(),
        "data_kind": "synthetic_not_observations",
        "visual_review": "pending_manual_inspection" if args.browser else None,
    }
    for i, command in enumerate(commands):
        completed = subprocess.run(
            command,
            cwd=ROOT / "frontend",
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        path = out / f"check-{i + 1}.txt"
        path.write_text(completed.stdout, encoding="utf-8")
        print(completed.stdout, end="", flush=True)
        report["checks"].append(
            {"command": command, "exit_code": completed.returncode, "transcript": path.name}
        )
        if completed.returncode:
            break
    if args.browser:
        ports = {}
        for port in (8000, 5173):
            with socket.socket() as sock:
                sock.settimeout(1)
                ports[str(port)] = sock.connect_ex(("127.0.0.1", port)) != 0
        report["server_ports_closed"] = ports
    report["outcome"] = (
        "passed"
        if all(c["exit_code"] == 0 for c in report["checks"])
        and all(report.get("server_ports_closed", {}).values())
        else "failed"
    )
    report["finished_at"] = datetime.now(UTC).isoformat()
    print("Report:", write_report(out, report))
    return 0 if report["outcome"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
