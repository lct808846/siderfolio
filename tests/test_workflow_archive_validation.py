"""损坏流程归档的离线回归测试。"""

import base64
import hashlib
import json
from io import BytesIO
from uuid import uuid4
from zipfile import ZipFile

import pytest

from astroagent.config import LocalSettings
from astroagent.conversation_service import ConversationService
from astroagent.conversations import ConversationRepository
from astroagent.errors import ServiceError
from astroagent.project_archives import export_archive, import_archive
from astroagent.project_schemas import ProjectCreate
from astroagent.projects import ProjectRepository
from astroagent.schemas import GaiaQuery
from astroagent.workflow_schemas import WorkflowCreate, WorkflowExecute
from astroagent.workflow_service import WorkflowService
from astroagent.workflow_templates import digest
from scripts.synthetic_services import SyntheticGaia


def zip_members(content):
    with ZipFile(BytesIO(content)) as archive:
        return {name: archive.read(name) for name in archive.namelist()}


def zip_bytes(members):
    buffer = BytesIO()
    with ZipFile(buffer, "w") as archive:
        for name, content in members.items():
            archive.writestr(name, content)
    return buffer.getvalue()


def test_import_rejects_png_missing_from_workflow_zip(tmp_path):
    repo = ConversationRepository(LocalSettings(_env_file=None, data_dir=tmp_path))
    repo.initialize()
    try:
        projects = ProjectRepository(repo)
        project = projects.create(ProjectCreate(name="图片完整性"))
        service = WorkflowService(ConversationService(repo))
        run = service.repository.create(
            project["id"],
            WorkflowCreate(
                expected_revision=0,
                name="图片完整性",
                template_id="gaia_field",
                parameters={
                    "input_mode": "coordinates",
                    "ra_deg": 56.75,
                    "dec_deg": 24.12,
                    "radius_arcmin": 5,
                    "limit": 10,
                    "plots": ["proper_motion"],
                },
            ),
        )
        value, _ = service.execute(
            project["id"],
            run.id,
            WorkflowExecute(expected_revision=0, confirmed=True, client_request_id=str(uuid4())),
            lambda: lambda family, args: SyntheticGaia().query(GaiaQuery(**args)),
        )
        assert value["run"]["state"] == "succeeded"
        project = projects.detail(project["id"])
        original = export_archive(projects, project["id"], project["revision"])
        # A valid archive must still import successfully.
        import_archive(projects, original)
        before = projects.list()
        outer = zip_members(original)
        workflows = json.loads(outer["workflows.json"])
        output = next(
            o for o in workflows["outputs"] if o["info"]["filename"] == "workflow-results.zip"
        )
        inner = zip_members(base64.b64decode(output["content_base64"]))
        png_paths = [path for path in inner if path.endswith(".png")]
        assert png_paths
        for path in png_paths:
            del inner[path]
        manifest = json.loads(inner["manifest.json"])
        manifest["files"] = [f for f in manifest["files"] if f["path"] not in png_paths]
        inner["manifest.json"] = json.dumps(manifest).encode()
        replacements = {
            "workflow-results.zip": zip_bytes(inner),
            "export-manifest.json": inner["manifest.json"],
        }
        # Update all hashes so rejection tests the missing PNG relationship.
        for output in workflows["outputs"]:
            content = replacements.get(output["info"]["filename"])
            if content is not None:
                output["content_base64"] = base64.b64encode(content).decode()
                output["info"].update(
                    bytes=len(content), sha256=hashlib.sha256(content).hexdigest()
                )
        step = next(s for s in workflows["runs"][0]["steps"] if s["id"] == "export_results")
        attempt = step["attempts"][-1]
        attempt["output"]["manifest"] = manifest
        attempt["output_sha256"] = digest(attempt["output"])
        outer["workflows.json"] = json.dumps(workflows).encode()
        outer_manifest = json.loads(outer["manifest.json"])
        outer_manifest["files"]["workflows.json"] = {
            "bytes": len(outer["workflows.json"]),
            "sha256": hashlib.sha256(outer["workflows.json"]).hexdigest(),
        }
        outer["manifest.json"] = json.dumps(outer_manifest).encode()
        with pytest.raises(ServiceError) as caught:
            import_archive(projects, zip_bytes(outer))
        assert caught.value.status_code == 422
        assert caught.value.error.code == "invalid_project_archive"
        assert str(caught.value.__cause__) == "PNG preview missing from its ZIP"
        assert projects.list() == before
    finally:
        repo.close()
