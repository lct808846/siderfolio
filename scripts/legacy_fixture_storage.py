"""SQLite test double for old browser contracts. Never imported by the production app."""

from contextlib import asynccontextmanager

from fastapi import Request

from astroagent.artifacts import ArtifactCache
from astroagent.config import LocalSettings
from astroagent.conversation_service import ConversationService
from astroagent.errors import ServiceError
from astroagent.knowledge_service import KnowledgeService
from astroagent.local_model_service import LocalModelService
from astroagent.project_links import ProjectLinks
from astroagent.project_service import ProjectService
from astroagent.workflow_service import WorkflowService


def get_service(request: Request):
    service = getattr(request.app.state, "conversation_service", None)
    if service is None:
        raise ServiceError(503, "database_not_configured", "旧业务合成测试仓储尚未就绪。")
    return service


async def legacy_identity_passthrough(self, scope, receive, send):
    """Only patched by explicit legacy tests; never installed in the production app."""
    return await self.app(scope, receive, send)


@asynccontextmanager
async def lifespan(app):
    """Keep V1.5 contract tests separate from real V1.6 identity acceptance."""
    import astroagent.main as main
    import astroagent.services as services

    repository = None
    app.state.conversation_service = app.state.repository = app.state.identity = None
    try:
        settings = LocalSettings()
        repository = main.PostgresRepository(settings)
        repository.initialize()
        app.state.conversation_service = services.compose(repository, settings)
        app.state.repository = repository
    except Exception as exc:
        app.state.storage_code = (
            exc.error.code if isinstance(exc, ServiceError) else "database_configuration_invalid"
        )
        if repository is not None:
            repository.close()
    try:
        yield
    finally:
        service = app.state.conversation_service
        if service is not None and service.local_assistant is not None:
            service.local_assistant.close()
        app.state.conversation_service = None
        active = getattr(app.state, "repository", repository)
        if active is not None:
            active.close()


class UnavailableRag:
    """SQLite browser fixtures cannot claim real PostgreSQL RAG readiness."""

    def status(self, project_id):
        raise ServiceError(503, "rag_fixture_unavailable", "合成页面服务不提供PostgreSQL语义检索。")

    def history(self, project_id, after=None):
        return self.status(project_id)


def compose(repository, settings):
    service = ConversationService(repository)
    ArtifactCache(service, settings)
    service.projects = ProjectService(service)
    service.workflows = WorkflowService(service)
    service.knowledge = KnowledgeService(service)
    service.links = ProjectLinks(service)
    service.local_assistant = LocalModelService(service, settings)
    service.rag = UnavailableRag()
    return service
