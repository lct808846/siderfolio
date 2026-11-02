import { request } from './index'
import type { GenerateRequest, IndexRequest, IndexStatus, Preview, RagAnswerView, RagPage, RagQuery, RagStatus, SetupStatus } from '../types'

const root = (project: string) => `/api/v1/projects/${project}/rag`
export const setupApi = {
  status: () => request<SetupStatus>('/api/v1/setup/status'),
  initialize: () => request<SetupStatus>('/api/v1/setup/initialize', 'POST', { confirmed: true }),
}
export const ragApi = {
  status: (project: string) => request<RagStatus>(`${root(project)}/status`),
  build: (project: string, payload: IndexRequest) => request<IndexStatus>(`${root(project)}/indexes`, 'POST', payload),
  deleteIndex: (project: string, id: string) => request<void>(`${root(project)}/indexes/${id}`, 'DELETE', { confirmed: true }),
  preview: (project: string, payload: RagQuery) => request<Preview>(`${root(project)}/previews`, 'POST', payload),
  discard: (project: string, id: string) => request<void>(`${root(project)}/previews/${id}`, 'DELETE', {}),
  generate: (project: string, payload: GenerateRequest) => request<RagAnswerView>(`${root(project)}/answers`, 'POST', payload),
  history: (project: string, after?: string) => request<RagPage>(`${root(project)}/answers${after ? `?after=${encodeURIComponent(after)}` : ''}`),
  detail: (project: string, id: string) => request<RagAnswerView>(`${root(project)}/answers/${id}`),
  delete: (project: string, id: string) => request<void>(`${root(project)}/answers/${id}`, 'DELETE', { confirmed: true }),
}
