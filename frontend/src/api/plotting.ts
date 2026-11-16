import { sessionFetch } from '../session-http'
import { ApiError, apiUrl, assertApiConfiguration, request } from './index'
import type { components } from '../types/generated'

export type PlotDataset = components['schemas']['PlotDataset']
export type PlotOperation = components['schemas']['PlotOperation']
export type PlotPage = components['schemas']['PlotPage']
export type PlotStatus = components['schemas']['PlotStatus']
export type PlotPlanRequest = components['schemas']['PlotPlanRequest']
export type PlotRunRequest = components['schemas']['PlotRunRequest']
export type DatasetPreview = components['schemas']['PlotDataPreview']
const root = (project: string) => `/api/v1/projects/${encodeURIComponent(project)}/plotting`

async function binary(path: string, method = 'GET', body?: BodyInit, json = false): Promise<Response> {
  assertApiConfiguration()
  let response: Response
  try { response = await sessionFetch(apiUrl(path), { method, body, headers: json ? { 'Content-Type': 'application/json' } : undefined, cache: 'no-store' }) }
  catch { throw new ApiError('plot_connection_lost', '连接中断，状态未确认。请先刷新记录，不会自动重试。') }
  if (!response.ok) {
    let message = '绘图操作失败，请刷新记录核对。', code = 'plot_request_failed'
    try { const result = await response.json(); message = result.error?.message || message; code = result.error?.code || code } catch { /* Safe fallback. */ }
    throw new ApiError(code, message, response.status)
  }
  return response
}
export const plottingApi = {
  status: () => request<PlotStatus>('/api/v1/setup/plotting'),
  initialize: () => request<PlotStatus>('/api/v1/setup/plotting', 'POST', { confirm_create_tables: true }),
  page: (project: string) => request<PlotPage>(root(project)),
  upload: async (project: string, id: string, file: File): Promise<PlotDataset> => {
    if (file.size > 5 * 1024 ** 2) throw new ApiError('plot_dataset_too_large', '文件超过5 MiB。')
    const form = new FormData(); form.set('file', file)
    return (await binary(`${root(project)}/datasets/${id}/upload`, 'PUT', form)).json() as Promise<PlotDataset>
  },
  snapshot: (project: string, id: string, snapshot_id: string, query_index: number) => request<PlotDataset>(`${root(project)}/datasets/${id}/snapshot`, 'PUT', { snapshot_id, query_index }),
  turn: (project: string, id: string, source: { conversation_id: string; turn_id: string; query_index: number }) => request<PlotDataset>(`${root(project)}/datasets/${id}/turn`, 'PUT', source),
  preview: (project: string, id: string) => request<DatasetPreview>(`${root(project)}/datasets/${id}/preview`),
  plan: (project: string, id: string, payload: PlotPlanRequest) => request<PlotOperation>(`${root(project)}/plans/${id}`, 'PUT', payload),
  run: (project: string, id: string, payload: PlotRunRequest) => request<PlotOperation>(`${root(project)}/runs/${id}`, 'PUT', payload),
  output: async (project: string, id: string, name: string) => (await binary(`${root(project)}/runs/${id}/files/${encodeURIComponent(name)}`)).blob(),
  data: async (project: string, id: string) => (await binary(`${root(project)}/datasets/${id}/data.csv`)).blob(),
  bundle: async (project: string, id: string, files: string[]) => (await binary(`${root(project)}/runs/${id}/bundle`, 'POST', JSON.stringify({ files }), true)).blob(),
}

export function savePlotFile(blob: Blob, name: string) {
  const url = URL.createObjectURL(blob), anchor = document.createElement('a')
  anchor.href = url; anchor.download = name; anchor.click()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}
