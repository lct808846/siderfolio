import { sessionFetch } from '../session-http'
import { ApiError, apiUrl, assertApiConfiguration, request } from './index'
import type {
  AnalysisDataset,
  AnalysisRunResponse,
  ProjectTablesPage,
  SendToPlotResponse,
  TableImportGaiaRequest,
  TableImportVizierTurnRequest,
  TableInspectResponse,
  TablePreviewResponse,
  VizierPreset,
  VizierQueryHttpRequest,
  VizierQueryHttpResponse,
} from '../types'

export type TableOperatorName = 'stats' | 'filter_derive' | 'coordinates' | 'crossmatch' | 'fit'

const projectRoot = (projectId: string) => `/api/v1/projects/${encodeURIComponent(projectId)}/tables`

async function parseError(response: Response, fallbackMessage: string): Promise<ApiError> {
  let code = 'table_request_failed'
  let message = fallbackMessage
  try {
    const body = (await response.json()) as { error?: { code?: string; message?: string } }
    if (body.error?.code) code = body.error.code
    if (body.error?.message) message = body.error.message
  } catch {
    // Use fallback message if body is not JSON.
  }
  return new ApiError(code, message, response.status)
}

async function multipartRequest<T>(path: string, form: FormData, fallbackMessage: string): Promise<T> {
  assertApiConfiguration()
  let response: Response
  try {
    response = await sessionFetch(apiUrl(path), { method: 'POST', body: form, cache: 'no-store' })
  } catch {
    throw new ApiError('table_connection_lost', '请求连接断开，请检查服务后重试。')
  }
  if (!response.ok) throw await parseError(response, fallbackMessage)
  return response.json() as Promise<T>
}

async function downloadBinary(path: string, defaultFilename: string): Promise<void> {
  assertApiConfiguration()
  let response: Response
  try {
    response = await sessionFetch(apiUrl(path), { cache: 'no-store' })
  } catch {
    throw new ApiError('table_download_lost', '下载连接已断开，请重试。')
  }
  if (!response.ok) throw await parseError(response, '导出数据表失败。')
  const disposition = response.headers.get('content-disposition') || ''
  let filename = disposition.match(/filename="([^"]+)"/)?.[1] || defaultFilename
  const encodedFilename = disposition.match(/filename\*=UTF-8''([^;]+)/i)?.[1]?.trim()
  if (encodedFilename) {
    try {
      filename = decodeURIComponent(encodedFilename)
    } catch {
      // Keep the fallback filename if the extended value is malformed.
    }
  }
  const blob = await response.blob()
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  anchor.click()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

export const tablesApi = {
  vizierPresets: () => request<VizierPreset[]>('/api/v1/tables/vizier/presets'),
  vizierQuery: (payload: VizierQueryHttpRequest) =>
    request<VizierQueryHttpResponse>('/api/v1/tables/vizier/query', 'POST', payload),
  list: (projectId: string) => request<ProjectTablesPage>(projectRoot(projectId)),
  inspect: (projectId: string, file: File) => {
    const form = new FormData()
    form.set('file', file)
    return multipartRequest<TableInspectResponse>(
      `${projectRoot(projectId)}/inspect`,
      form,
      '预检天文数据表失败。',
    )
  },
  upload: (
    projectId: string,
    file: File,
    options?: { name?: string; hduIndex?: number | null; selectedColumns?: string[] | null },
  ) => {
    const form = new FormData()
    form.set('file', file)
    if (options?.name) form.set('name', options.name)
    if (options?.hduIndex !== undefined && options.hduIndex !== null) {
      form.set('hdu_index', String(options.hduIndex))
    }
    if (options?.selectedColumns?.length) {
      form.set('selected_columns', JSON.stringify(options.selectedColumns))
    }
    return multipartRequest<AnalysisDataset>(
      `${projectRoot(projectId)}/upload`,
      form,
      '导入天文数据表失败。',
    )
  },
  importFromGaia: (projectId: string, payload: TableImportGaiaRequest) =>
    request<AnalysisDataset>(`${projectRoot(projectId)}/from-gaia`, 'POST', payload),
  importFromVizierTurn: (projectId: string, payload: TableImportVizierTurnRequest) =>
    request<AnalysisDataset>(`${projectRoot(projectId)}/from-vizier`, 'POST', payload),
  detail: (projectId: string, datasetId: string) =>
    request<AnalysisDataset>(`${projectRoot(projectId)}/${encodeURIComponent(datasetId)}`),
  preview: (projectId: string, datasetId: string, offset = 0, limit = 50) =>
    request<TablePreviewResponse>(
      `${projectRoot(projectId)}/${encodeURIComponent(datasetId)}/preview?offset=${offset}&limit=${limit}`,
    ),
  remove: (projectId: string, datasetId: string) =>
    request<void>(`${projectRoot(projectId)}/${encodeURIComponent(datasetId)}`, 'DELETE'),
  runOperator: (projectId: string, operator: TableOperatorName, payload: Record<string, unknown>) =>
    request<AnalysisRunResponse>(`${projectRoot(projectId)}/runs/${operator}`, 'POST', payload),
  sendToPlot: (projectId: string, datasetId: string, name?: string) =>
    request<SendToPlotResponse>(
      `${projectRoot(projectId)}/${encodeURIComponent(datasetId)}/send-to-plot`,
      'POST',
      name ? { name } : {},
    ),
  exportTable: (projectId: string, datasetId: string, format: 'csv' | 'ecsv' | 'fits') =>
    downloadBinary(
      `${projectRoot(projectId)}/${encodeURIComponent(datasetId)}/export?format=${format}`,
      `table.${format}`,
    ),
  exportBundle: (projectId: string, runId: string) =>
    downloadBinary(
      `${projectRoot(projectId)}/runs/${encodeURIComponent(runId)}/bundle`,
      `table-analysis-${runId.slice(0, 8)}.zip`,
    ),
}
