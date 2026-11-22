import { defineStore } from 'pinia'
import { api } from '../api'
import { knowledgeApi } from '../api/knowledge'
import { projectsApi } from '../api/projects'
import type { Conversation, Project } from '../types'

let ensuring: Promise<Project> | null = null
let pendingLoad: Promise<void> | null = null
const ACTIVE_PROJECT_KEY = 'astroagent.active_project_id.v1'

function readSavedActiveProject() {
  try { return sessionStorage.getItem(ACTIVE_PROJECT_KEY) || '' } catch { return '' }
}

export const useProjects = defineStore('projects', {
  state: () => ({
    projects: [] as Project[],
    defaultProjectId: '',
    activeProjectId: readSavedActiveProject(),
    memberships: {} as Record<string, string>,
    sourceCounts: {} as Record<string, number>,
    loaded: false,
    loading: false,
  }),
  getters: {
    defaultProject: state => state.projects.find(item => item.id === state.defaultProjectId) || null,
    customProjects: state => state.projects.filter(item => item.id !== state.defaultProjectId),
    activeCustomProjectId: state => {
      if (!state.activeProjectId || state.activeProjectId === state.defaultProjectId) return ''
      return state.projects.some(item => item.id === state.activeProjectId) ? state.activeProjectId : ''
    },
    projectFor: state => (conversationId: string): Project | null => {
      const projectId = state.memberships[conversationId]
      if (!projectId || projectId === state.defaultProjectId) return null
      return state.projects.find(item => item.id === projectId) || null
    },
    projectNameFor: state => (conversationId: string) => {
      const projectId = state.memberships[conversationId]
      if (!projectId || projectId === state.defaultProjectId) return ''
      return state.projects.find(item => item.id === projectId)?.name || ''
    },
    labelFor: state => (projectId: string) => {
      if (!projectId) return ''
      if (projectId === state.defaultProjectId) return '个人空间（默认）'
      return state.projects.find(item => item.id === projectId)?.name || '科研项目'
    },
    conversationCountFor: state => (projectId: string) => {
      let count = 0
      for (const value of Object.values(state.memberships)) {
        if (value === projectId) count++
      }
      return count
    },
  },
  actions: {
    load(force = false): Promise<void> {
      if (pendingLoad) return pendingLoad
      if (this.loaded && !force) return Promise.resolve()
      this.loading = true
      const pending: Promise<void> = Promise.all([
        projectsApi.list(),
        projectsApi.memberships(),
        projectsApi.defaultProject(),
      ]).then(([list, memberships, fallback]) => {
        if (pendingLoad !== pending) return
        this.projects = list
        this.memberships = memberships
        this.defaultProjectId = fallback?.id || ''
        this.loaded = true
      }).finally(() => {
        if (pendingLoad !== pending) return
        pendingLoad = null
        this.loading = false
      })
      pendingLoad = pending
      return pending
    },
    async ensureDefault(): Promise<Project> {
      const existing = this.defaultProject
      if (existing) return existing
      if (!ensuring) {
        ensuring = projectsApi.ensureDefault()
          .then(project => {
            this.defaultProjectId = project.id
            if (!this.projects.some(item => item.id === project.id)) {
              this.projects = [project, ...this.projects]
            } else {
              this.projects = this.projects.map(item => item.id === project.id ? project : item)
            }
            return project
          })
          .finally(() => { ensuring = null })
      }
      return ensuring
    },
    async create(name: string, description = ''): Promise<Project> {
      const created = await projectsApi.create(name, description)
      this.projects = [created, ...this.projects.filter(item => item.id !== created.id)]
      this.sourceCounts = { ...this.sourceCounts, [created.id]: 0 }
      return created
    },
    async startConversationDetail(projectId: string): Promise<Conversation> {
      const created = await api.create()
      const detail = await projectsApi.detail(projectId)
      await projectsApi.move(projectId, created.id, {
        expected_revision: detail.revision,
        expected_conversation_revision: created.revision,
        expected_metadata_revision: created.metadata_revision,
        expected_source_project_id: null,
        expected_source_revision: null,
      }, false)
      this.memberships = { ...this.memberships, [created.id]: projectId }
      void this.load(true).catch(() => undefined)
      return created
    },
    async startConversation(projectId: string): Promise<string> {
      const created = await this.startConversationDetail(projectId)
      return created.id
    },
    setSourceCount(projectId: string, count: number) {
      this.sourceCounts = { ...this.sourceCounts, [projectId]: count }
    },
    async refreshSourceCount(projectId: string): Promise<number> {
      const docs = await knowledgeApi.list(projectId)
      const readyCount = docs.filter(doc => doc.state === 'ready' || doc.state === 'partial').length
      this.sourceCounts = { ...this.sourceCounts, [projectId]: readyCount }
      return readyCount
    },
    setActiveProject(projectId: string) {
      const normalized = projectId && projectId !== this.defaultProjectId ? projectId : ''
      this.activeProjectId = normalized
      try {
        if (normalized) sessionStorage.setItem(ACTIVE_PROJECT_KEY, normalized)
        else sessionStorage.removeItem(ACTIVE_PROJECT_KEY)
      } catch { /* Ignore storage restrictions. */ }
    },
    upsert(project: Project) {
      this.projects = [project, ...this.projects.filter(item => item.id !== project.id)]
    },
    removeLocal(projectId: string) {
      this.projects = this.projects.filter(item => item.id !== projectId)
      if (this.defaultProjectId === projectId) this.defaultProjectId = ''
      if (this.activeProjectId === projectId) this.setActiveProject('')
      const next: Record<string, string> = {}
      for (const [cid, pid] of Object.entries(this.memberships)) {
        if (pid !== projectId) next[cid] = pid
      }
      this.memberships = next
      const nextCounts = { ...this.sourceCounts }
      delete nextCounts[projectId]
      this.sourceCounts = nextCounts
    },
    reset() {
      pendingLoad = null
      this.projects = []
      this.defaultProjectId = ''
      this.setActiveProject('')
      this.memberships = {}
      this.sourceCounts = {}
      this.loaded = false
      this.loading = false
    },
  },
})
