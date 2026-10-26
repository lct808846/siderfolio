"""运行离线测试与代码检查并按版本保存记录；--live 仅执行真实服务测试。"""

import argparse
import os
import subprocess
import sys
import time
from datetime import UTC, datetime

from record_utils import ROOT, create_record_directory, project_version, write_report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--live", action="store_true", help="访问真实 SIMBAD/模型，会产生模型用量")
    mode.add_argument(
        "--live-ads", action="store_true", help="访问真实 ADS/综合查询，会产生模型用量"
    )
    args = parser.parse_args()
    live = args.live or args.live_ads
    kind = "live-ads-tests" if args.live_ads else ("live-tests" if live else "offline-tests")
    output = create_record_directory(kind)
    environment = os.environ.copy()
    environment["ASTROAGENT_RUN_LIVE"] = "1" if args.live else "0"
    environment["ASTROAGENT_RUN_LIVE_ADS"] = "1" if args.live_ads else "0"
    commands = [
        [
            sys.executable,
            "-m",
            "pytest",
            *(
                ["tests/test_live_ads.py" if args.live_ads else "tests/test_live.py", "-v"]
                if live
                else ["-q"]
            ),
            f"--junitxml={output / 'pytest.xml'}",
            "-o",
            "faulthandler_timeout=30",
        ],
    ]
    if not live:
        commands.extend(
            [
                [sys.executable, "-m", "ruff", "check", "src", "tests", "scripts"],
                [sys.executable, "-m", "ruff", "format", "--check", "src", "tests", "scripts"],
                [sys.executable, "-m", "pip", "check"],
            ]
        )
    report = {
        "application_version": project_version(),
        "started_at": datetime.now(UTC).isoformat(),
        "kind": kind,
        "checks": [],
    }
    for index, command in enumerate(commands):
        started = time.perf_counter()
        completed = subprocess.run(
            command,
            cwd=ROOT,
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        transcript = f"check-{index + 1}.txt"
        (output / transcript).write_text(completed.stdout, encoding="utf-8")
        print(completed.stdout, end="", flush=True)
        report["checks"].append(
            {
                "command": command[1:],
                "exit_code": completed.returncode,
                "seconds": round(time.perf_counter() - started, 4),
                "transcript": transcript,
            }
        )
    report["outcome"] = (
        "passed" if all(check["exit_code"] == 0 for check in report["checks"]) else "failed"
    )
    report["finished_at"] = datetime.now(UTC).isoformat()
    print(f"Report: {write_report(output, report)}", flush=True)
    return 0 if report["outcome"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
