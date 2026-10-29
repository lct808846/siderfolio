import { ApiError, apiUrl, assertApiConfiguration, request } from './index'
import type { Comparison, ImportResult, Project, ProjectDetail, Rerun, RerunRequest, Snapshot } from '../types'

const prefix = '/api/v1/projects'
export const projectsApi = {
  list: () => request<Project[]>(prefix),
  create: (name: string, description = '') => request<Project>(prefix, 'POST', { name, description }),
  detail: (id: string) => request<ProjectDetail>(`${prefix}/${id}`),
  memberships: () => request<Record<string, string>>(`${prefix}/memberships`),
  update: (p: Project, name: string, description: string) => request<Project>(`${prefix}/${p.id}`, 'PATCH', { expected_revision: p.revision, name, description }),
  delete: (p: Project) => request<void>(`${prefix}/${p.id}`, 'DELETE', { expected_revision: p.revision, confirm: true }),
  move: (id: string, conversation: string, body: unknown, remove = false) => request<ProjectDetail>(`${prefix}/${id}/conversations/${conversation}`, remove ? 'DELETE' : 'PUT', body),
  save: (p: Project, conversation_id: string, turn_id: string, name: string) => request<Snapshot>(`${prefix}/${p.id}/snapshots`, 'POST', { expected_revision: p.revision, conversation_id, turn_id, name }),
  snapshot: (id: string, snapshot: string) => request<Snapshot>(`${prefix}/${id}/snapshots/${snapshot}`),
  renameSnapshot: (p: Project, id: string, name: string) => request<Snapshot>(`${prefix}/${p.id}/snapshots/${id}`, 'PATCH', { expected_revision: p.revision, name }),
  deleteSnapshot: (p: Project, id: string) => request<void>(`${prefix}/${p.id}/snapshots/${id}`, 'DELETE', { expected_revision: p.revision }),
  compare: (id: string, left_id: string, right_id: string, match_identifiers: boolean) => request<Comparison>(`${prefix}/${id}/comparisons`, 'POST', { left_id, right_id, match_identifiers }),
  rerun: (id: string, snapshot: string, payload: RerunRequest) => request<Rerun>(`${prefix}/${id}/snapshots/${snapshot}/reruns`, 'POST', payload),
}

async function binaryRequest(path: string, body: BodyInit, media: string): Promise<Response> {
  assertApiConfiguration()
  let response: Response
  try { response = await fetch(apiUrl(path), { method: 'POST', headers: { 'Content-Type': media }, body, cache: 'no-store' }) }
  catch { throw new ApiError('connection_lost', '连接已断开。先刷新项目列表核对状态，操作不会自动重试。') }
  if (!response.ok) {
    let message = `项目归档操作失败（${response.status}）`, code = 'project_archive_failed'
    try { const data = await response.json(); message = data.error?.message || message; code = data.error?.code || code } catch { /* Use safe text. */ }
    throw new ApiError(code, message, response.status)
  }
  return response
}
export async function importProject(file: File): Promise<ImportResult> {
  if (file.size > 32 * 1024 ** 2) throw new ApiError('project_archive_too_large', '项目归档超过32 MiB。')
  const response = await binaryRequest(`${prefix}/import`, file, 'application/zip')
  return response.json() as Promise<ImportResult>
}
export async function exportProject(project: Project): Promise<void> {
  const response = await binaryRequest(`${prefix}/${project.id}/archive`, JSON.stringify({ expected_revision: project.revision }), 'application/json')
  if (!(response.headers.get('content-type') || '').includes('application/zip')) throw new ApiError('invalid_archive_response', '服务没有返回项目归档。')
  const url = URL.createObjectURL(await response.blob())
  const anchor = document.createElement('a'); anchor.href = url; anchor.download = 'astroagent-project.zip'; anchor.click()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}
