"""SQLite test double for old browser contracts. Never imported by the production app."""

from astroagent.artifacts import ArtifactCache
from astroagent.conversation_service import ConversationService
from astroagent.knowledge_service import KnowledgeService
from astroagent.project_links import ProjectLinks
from astroagent.project_service import ProjectService
from astroagent.workflow_service import WorkflowService


def compose(repository, settings):
    service = ConversationService(repository)
    ArtifactCache(service, settings)
    service.projects = ProjectService(service)
    service.workflows = WorkflowService(service)
    service.knowledge = KnowledgeService(service)
    service.links = ProjectLinks(service)
    return service
