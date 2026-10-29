"""构建 wheel 并安装到独立目录，核对 API 不依赖源码树/前端打包。"""

import hashlib
import os
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from zipfile import ZipFile

from record_utils import (
    ROOT,
    create_record_directory,
    project_version,
    runtime_metadata,
    write_report,
)


def main():
    out = create_record_directory("release-audit")
    report = {
        "started_at": datetime.now(UTC).isoformat(),
        **runtime_metadata(),
        "checks": [],
        "scope": "Dedicated wheel installation; dependencies reused from the verified Python "
        "environment. No installer is published.",
    }
    with tempfile.TemporaryDirectory(prefix="astroagent-wheel-") as temporary:
        work = Path(temporary)
        wheels = work / "wheels"
        target = work / "installed"
        cwd = work / "runtime"
        cwd.mkdir()
        commands = [
            [
                sys.executable,
                "-m",
                "pip",
                "wheel",
                str(ROOT),
                "--no-deps",
                "--no-build-isolation",
                "--wheel-dir",
                str(wheels),
            ],
        ]
        for command in commands:
            result = subprocess.run(
                command,
                cwd=ROOT,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            (out / "wheel-build.txt").write_text(result.stdout + result.stderr, encoding="utf-8")
            report["checks"].append({"command": command, "exit_code": result.returncode})
            if result.returncode:
                break
        if all(c["exit_code"] == 0 for c in report["checks"]):
            wheel = next(wheels.glob("*.whl"))
            report["wheel"] = {
                "name": wheel.name,
                "sha256": hashlib.sha256(wheel.read_bytes()).hexdigest(),
            }
            with ZipFile(wheel) as package:
                assert not any(name.startswith("frontend/") for name in package.namelist())
                report["wheel"]["frontend_embedded"] = False
            command = [
                sys.executable,
                "-m",
                "pip",
                "install",
                "--no-deps",
                "--no-compile",
                "--target",
                str(target),
                str(wheel),
            ]
            result = subprocess.run(
                command, capture_output=True, text=True, encoding="utf-8", errors="replace"
            )
            (out / "wheel-install.txt").write_text(result.stdout + result.stderr, encoding="utf-8")
            report["checks"].append({"command": command, "exit_code": result.returncode})
            if result.returncode == 0:
                environment = os.environ.copy()
                environment["PYTHONPATH"] = str(target)
                environment["ASTROAGENT_DATA_DIR"] = str(work / "data")
                environment["DEEPSEEK_API_KEY"] = ""
                environment["ADS_API_TOKEN"] = ""
                environment["PYTHONIOENCODING"] = "utf-8"
                environment["EXPECTED_VERSION"] = project_version()
                code = """
import json,os
from pathlib import Path
from uuid import uuid4
import astroagent
from astroagent.main import app
from fastapi.testclient import TestClient
assert Path(astroagent.__file__).is_relative_to(Path(os.environ['PYTHONPATH']))
assert astroagent.__version__==os.environ['EXPECTED_VERSION']
with TestClient(app,base_url='http://127.0.0.1') as client:
    assert client.get('/health').status_code==200
    assert client.get('/openapi.json').json()['info']['version']==astroagent.__version__
    c=client.post('/api/v1/conversations',json={'title':'wheel API smoke'}).json()
    payload={'message':'No model key configured','client_request_id':str(uuid4()),
             'expected_revision':0}
    response=client.post('/api/v1/conversations/'+c['id']+'/turns',json=payload)
    assert response.status_code==503 and response.json()['turn_id']
    t=client.get('/api/v1/conversations/'+c['id']+'/turns/'+response.json()['turn_id']).json()
    assert t['execution_status']=='failed'
    snapshot={'status':'success','answer':'synthetic package smoke','results':[],
              'literature_results':[],'gaia_results':[],'sources':[],'warnings':[]}
    export={'schema_version':'1','snapshot':snapshot,'plots':[]}
    assert client.post('/api/v1/exports',json=export).status_code==200
    p=client.post('/api/v1/projects',json={'name':'wheel project smoke'}).json()
    assert p['revision']==0
    assignment={'expected_revision':0,'expected_conversation_revision':1,
                'expected_metadata_revision':0}
    assert client.put('/api/v1/projects/'+p['id']+'/conversations/'+c['id'],
                      json=assignment).status_code==200
    archive=client.post('/api/v1/projects/'+p['id']+'/archive',
                        json={'expected_revision':1})
    assert archive.status_code==200
    restored=client.post('/api/v1/projects/import',content=archive.content,
                         headers={'Content-Type':'application/zip'})
    assert restored.status_code==201 and restored.json()['project']['id']!=p['id']
    assert restored.json()['project']['provenance']=='imported_unverified'
print(json.dumps({'imported_from':astroagent.__file__,'version':astroagent.__version__,
                  'health':True,'crud':True,'failed_turn_saved':True,
                  'export_without_key':True,'project_restore_without_key':True}))
"""
                result = subprocess.run(
                    [sys.executable, "-c", code],
                    cwd=cwd,
                    env=environment,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                )
                (out / "wheel-api.txt").write_text(result.stdout + result.stderr, encoding="utf-8")
                report["checks"].append(
                    {"command": ["isolated wheel API smoke"], "exit_code": result.returncode}
                )
    report["outcome"] = (
        "passed"
        if len(report["checks"]) == 3 and all(c["exit_code"] == 0 for c in report["checks"])
        else "failed"
    )
    report["finished_at"] = datetime.now(UTC).isoformat()
    print(write_report(out, report))
    print(report["outcome"])
    return 0 if report["outcome"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
