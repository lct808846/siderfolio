import { sessionFetch } from '../session-http'
import { ApiError, apiUrl, assertApiConfiguration, request } from './index'
import type { WorkflowCreate, WorkflowDetail, WorkflowExecute, WorkflowExecution, WorkflowOutput, WorkflowSummary, WorkflowTemplate } from '../types'

const prefix = (projectId: string) => `/api/v1/projects/${projectId}/workflows`
export const workflowsApi = {
  templates: () => request<WorkflowTemplate[]>('/api/v1/workflow-templates'),
  list: (projectId: string) => request<WorkflowSummary[]>(prefix(projectId)),
  detail: (projectId: string, runId: string) => request<WorkflowDetail>(`${prefix(projectId)}/${runId}`),
  create: (projectId: string, body: WorkflowCreate) => request<WorkflowDetail>(prefix(projectId), 'POST', body),
  execute: (projectId: string, runId: string, body: WorkflowExecute) => request<WorkflowExecution>(`${prefix(projectId)}/${runId}/execute`, 'POST', body),
  delete: (projectId: string, runId: string, expected_revision: number) => request<void>(`${prefix(projectId)}/${runId}`, 'DELETE', { expected_revision, confirmed: true }),
}
export const outputPath = (output: WorkflowOutput) => `${prefix(output.project_id)}/${output.run_id}/outputs/${output.id}`
export async function downloadWorkflowOutput(output: WorkflowOutput): Promise<void> {
  assertApiConfiguration()
  let response: Response
  try { response = await sessionFetch(apiUrl(outputPath(output)), { cache: 'no-store' }) }
  catch { throw new ApiError('connection_lost', '下载连接已断开，请重新点击下载。') }
  if (!response.ok) {
    let text = `流程输出不可用（${response.status}）`
    try { const body = await response.json(); text = body.error?.message || text } catch { /* Keep safe fallback. */ }
    throw new ApiError('workflow_download_failed', text, response.status)
  }
  if (!(response.headers.get('content-type') || '').startsWith(output.media_type)) throw new ApiError('workflow_download_failed', '返回类型与已登记文件不符。')
  const data = await response.arrayBuffer()
  const checksum = Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', data))).map(v => v.toString(16).padStart(2, '0')).join('')
  if (data.byteLength !== output.bytes || checksum !== output.sha256) throw new ApiError('workflow_download_failed', '下载文件的长度或哈希与登记信息不符。')
  const url = URL.createObjectURL(new Blob([data], { type: output.media_type }))
  const anchor = document.createElement('a'); anchor.href = url; anchor.download = output.filename; anchor.click()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}
