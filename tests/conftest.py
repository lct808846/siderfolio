"""离线测试禁止真实 HTTP 请求；live 测试需要单独显式启用。"""

import httpx
import pytest
import requests


@pytest.fixture(autouse=True)
def isolate_local_storage(tmp_path, monkeypatch, request):
    monkeypatch.setenv("ASTROAGENT_DATA_DIR", str(tmp_path / "local-data"))
    monkeypatch.setenv("ASTROAGENT_DATABASE_URL", "")
    monkeypatch.setenv("ASTROAGENT_ALLOWED_HOSTS", '["testserver","127.0.0.1","localhost","[::1]"]')
    if not request.node.get_closest_marker("postgres"):
        # Explicit legacy contract double, never a production fallback. This also
        # prevents an ordinary old test from opening a personal PostgreSQL DB.
        import astroagent.main as main
        import astroagent.services as services
        from astroagent.artifacts import ArtifactCache
        from astroagent.conversation_service import ConversationService
        from astroagent.conversations import ConversationRepository
        from astroagent.knowledge_service import KnowledgeService
        from astroagent.project_links import ProjectLinks
        from astroagent.project_service import ProjectService
        from astroagent.workflow_service import WorkflowService

        def legacy_compose(repository, settings):
            service = ConversationService(repository)
            ArtifactCache(service, settings)
            service.projects = ProjectService(service)
            service.workflows = WorkflowService(service)
            service.knowledge = KnowledgeService(service)
            service.links = ProjectLinks(service)
            return service

        monkeypatch.setattr(main, "PostgresRepository", ConversationRepository)
        monkeypatch.setattr(services, "compose", legacy_compose)


@pytest.fixture(autouse=True)
def block_external_http(request, monkeypatch):
    if request.node.get_closest_marker("live"):
        return

    def blocked(*args, **kwargs):
        raise AssertionError("Offline tests must not access external HTTP services")

    monkeypatch.setattr(requests.Session, "request", blocked)
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", blocked)
