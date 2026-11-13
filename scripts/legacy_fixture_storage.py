"""SQLite test double for old browser contracts. Never imported by the production app."""

from astroagent.artifacts import ArtifactCache
from astroagent.conversation_service import ConversationService
from astroagent.errors import ServiceError
from astroagent.knowledge_service import KnowledgeService
from astroagent.local_model_service import LocalModelService
from astroagent.project_links import ProjectLinks
from astroagent.project_service import ProjectService
from astroagent.workflow_service import WorkflowService


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
