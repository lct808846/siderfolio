import { request } from './index'
import type { LinkCreate, LinkCreated, LinkDelete, LinkDetail, LinkPage, LinkPatch, LinkTarget, ProjectOverview } from '../types'

const prefix = (project: string) => `/api/v1/projects/${project}`
export const linksApi = {
  overview: (project: string) => request<ProjectOverview>(`${prefix(project)}/overview`),
  list: (project: string, filters: { after?: string; target_type?: LinkTarget['type']; target_id?: string; evidence_id?: string } = {}) => {
    const query = new URLSearchParams({ limit: '25' })
    for (const [name, value] of Object.entries(filters)) if (value) query.set(name, value)
    return request<LinkPage>(`${prefix(project)}/links?${query}`)
  },
  create: (project: string, body: LinkCreate) => request<LinkCreated>(`${prefix(project)}/links`, 'POST', body),
  detail: (project: string, id: string) => request<LinkDetail>(`${prefix(project)}/links/${id}`),
  update: (project: string, id: string, body: LinkPatch) => request<LinkDetail>(`${prefix(project)}/links/${id}`, 'PATCH', body),
  delete: (project: string, id: string, body: LinkDelete) => request<void>(`${prefix(project)}/links/${id}`, 'DELETE', body),
}
