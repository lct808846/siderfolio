"""Explicit future network diagnosis of fixed Gaia endpoints. Never runs during development."""

import argparse
import json
import os
import platform
import socket
import ssl
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path


def stage(name):
    started = time.monotonic()
    result = {"stage": name, "started_at": datetime.now(UTC).isoformat()}
    try:
        host = "gea.esac.esa.int"
        if name == "dns":
            result["addresses"] = sorted(
                {item[4][0] for item in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)}
            )
        elif name == "direct_tls":
            with socket.create_connection((host, 443), timeout=10) as connection:
                with ssl.create_default_context().wrap_socket(
                    connection, server_hostname=host
                ) as tls:
                    result["tls_version"] = tls.version()
            result["path"] = "direct socket; not the requests proxy path"
        elif name == "capabilities":
            import requests

            with requests.get(
                "https://gea.esac.esa.int/tap-server/tap/capabilities", timeout=(5, 15), stream=True
            ) as response:
                result["http_status"] = response.status_code
            result["note"] = "Capabilities status is not a successful scientific query"
        else:
            from astroagent.gaia import GAIA_ENDPOINT, GaiaService
            from astroagent.schemas import GaiaQuery

            query = GaiaQuery(mode="source_id", source_id="5853498713190525696")
            value = GaiaService(timeout=15).query(query)
            result.update(
                endpoint=GAIA_ENDPOINT,
                query=query.model_dump(mode="json"),
                query_status=value.status,
                error_code=value.error.code if value.error else None,
                actual_source=value.source.model_dump(mode="json"),
            )
        result["completed"] = True
    except Exception as exc:
        result.update(completed=False, exception_type=type(exc).__name__)
    result["seconds"] = time.monotonic() - started
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true")
    parser.add_argument(
        "--stage",
        choices=("dns", "direct_tls", "capabilities", "source_query"),
        help=argparse.SUPPRESS,
    )
    args = parser.parse_args()
    if not args.run:
        parser.error("仅在发布前明确授权联网后使用--run。")
    if args.stage:
        print(json.dumps(stage(args.stage), ensure_ascii=False))
        return
    from astroagent import __version__

    report = {
        "version": __version__,
        "kind": "gaia_layered_diagnosis",
        "platform": platform.platform(),
        "started_at": datetime.now(UTC).isoformat(),
        "proxy_configured": any(
            os.getenv(key) for key in ("HTTPS_PROXY", "https_proxy", "ALL_PROXY", "all_proxy")
        ),
        "root_cause": "undetermined",
        "stages": [],
    }
    for name in ("dns", "direct_tls", "capabilities", "source_query"):
        try:
            result = subprocess.run(
                [sys.executable, str(Path(__file__).resolve()), "--run", "--stage", name],
                capture_output=True,
                timeout=25,
                encoding="utf-8",
                check=False,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            if result.returncode or len(result.stdout) > 65536:
                raise ValueError("No bounded result")
            report["stages"].append(json.loads(result.stdout))
        except Exception as exc:
            report["stages"].append(
                {"stage": name, "completed": False, "exception_type": type(exc).__name__}
            )
    root = (
        Path(__file__).resolve().parents[1]
        / f"docs/test-records/v{__version__}/gaia-diagnosis"
        / datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    )
    root.mkdir(parents=True)
    (root / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(root)
    return (
        0
        if all(item.get("completed") for item in report["stages"])
        and report["stages"][-1].get("query_status") == "success"
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())
