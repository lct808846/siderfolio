"""离线测试禁止真实 HTTP 请求；live 测试需要单独显式启用。"""

import httpx
import pytest
import requests


@pytest.fixture(autouse=True)
def isolate_local_storage(tmp_path, monkeypatch, request):
    monkeypatch.setenv("ASTROAGENT_DATA_DIR", str(tmp_path / "local-data"))
    monkeypatch.setenv("ASTROAGENT_DATABASE_URL", "")
    monkeypatch.setenv("ASTROAGENT_ALLOWED_HOSTS", '["testserver","127.0.0.1","localhost","[::1]"]')
    if request.node.get_closest_marker("identity"):
        return
    # Old business contract fixtures intentionally exclude identity. New identity
    # tests run the unmodified production middleware and real tenant repositories.
    import astroagent.main as main
    from astroagent.api import conversations
    from astroagent.auth_access import IdentityAccess
    from astroagent.postgres import PostgresRepository
    from scripts.legacy_fixture_storage import get_service, legacy_identity_passthrough, lifespan

    monkeypatch.setattr(main, "PostgresRepository", PostgresRepository, raising=False)
    monkeypatch.setattr(main.app.router, "lifespan_context", lifespan)
    monkeypatch.setattr(IdentityAccess, "__call__", legacy_identity_passthrough)
    monkeypatch.setitem(main.app.dependency_overrides, conversations.get_service, get_service)
    monkeypatch.setattr(conversations, "get_service", get_service)
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
    # Proxy transports override HTTPTransport.handle_request. Check the selected
    # transport before dispatch as well, while allowing MockTransport/TestClient.
    send = httpx.Client._send_single_request
    async_send = httpx.AsyncClient._send_single_request

    def guarded_send(client, outbound):
        if isinstance(client._transport_for_url(outbound.url), httpx.HTTPTransport):
            return blocked()
        return send(client, outbound)

    async def guarded_async_send(client, outbound):
        if isinstance(client._transport_for_url(outbound.url), httpx.AsyncHTTPTransport):
            return blocked()
        return await async_send(client, outbound)

    monkeypatch.setattr(httpx.Client, "_send_single_request", guarded_send)
    monkeypatch.setattr(httpx.AsyncClient, "_send_single_request", guarded_async_send)
