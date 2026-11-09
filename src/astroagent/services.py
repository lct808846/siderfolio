"""Compose services only after the PostgreSQL repository is ready."""

from astroagent.artifacts import ArtifactCache
from astroagent.conversation_service import ConversationService
from astroagent.plot_service import PlotService
from astroagent.postgres_knowledge import PostgresKnowledgeService
from astroagent.project_links import ProjectLinks
from astroagent.project_service import ProjectService
from astroagent.rag_service import RagService
from astroagent.workflow_service import WorkflowService


def compose(repository, settings):
    service = ConversationService(repository)
    ArtifactCache(service, settings)
    service.projects = ProjectService(service)
    service.workflows = WorkflowService(service)
    service.knowledge = PostgresKnowledgeService(service)
    service.links = ProjectLinks(service)
    service.rag = RagService(service)
    service.plotting = PlotService(service, settings)
    return service
