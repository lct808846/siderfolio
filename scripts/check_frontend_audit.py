"""Limit the approved v1.6.0 audit exception to one development advisory."""

import json
import os
import sys
from pathlib import Path

ADVISORY = "https://github.com/advisories/GHSA-fc5q-39xc-vjpf"
RELEASE_REFS = {"refs/heads/main", "refs/tags/v1.6.0"}
RELEASE_VERSION = "1.6.0"


def exception_applies(vulnerabilities, blocking, lockfile, ref):
    if ref not in RELEASE_REFS or lockfile["version"] != RELEASE_VERSION:
        return False

    packages = lockfile["packages"]

    def attributable_to_advisory(name, chain=frozenset()):
        if name not in vulnerabilities or name in chain:
            return False
        finding = vulnerabilities[name]
        nodes = finding["nodes"]
        if not nodes or any(packages.get(node, {}).get("dev") is not True for node in nodes):
            return False
        if finding["severity"] == "critical" or not finding["via"]:
            return False
        return all(
            attributable_to_advisory(cause, chain | {name})
            if isinstance(cause, str)
            else name == "picomatch"
            and cause["url"] == ADVISORY
            and cause["dependency"] == "picomatch"
            and cause["severity"] == "high"
            for cause in finding["via"]
        )

    return bool(blocking) and all(attributable_to_advisory(name) for name in blocking)


def main():
    report_path, status = sys.argv[1:]
    report = json.loads(Path(report_path).read_text(encoding="utf-8-sig"))
    if report.get("error") or report.get("auditReportVersion") != 2:
        return 1
    vulnerabilities = report["vulnerabilities"]
    blocking = [
        name
        for name, finding in vulnerabilities.items()
        if finding["severity"] in {"high", "critical"}
    ]
    if status == "0" and not blocking:
        return 0
    lockfile = json.loads(Path("package-lock.json").read_text(encoding="utf-8"))
    if status == "1" and exception_applies(
        vulnerabilities, blocking, lockfile, os.environ.get("GITHUB_REF")
    ):
        print(f"::warning::Approved v{RELEASE_VERSION} development-only exception: {ADVISORY}")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
