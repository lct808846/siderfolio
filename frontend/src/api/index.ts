import type { ArtifactInfo, Conversation, ConversationDetail, Manifest, PlotSpec, Turn } from '../types'

const configured = import.meta.env.VITE_API_BASE_URL || ''
export function validateApiOrigin(value: string): string {
  if (!value) return ''
  const parsed = new URL(value)
  if (!['http:', 'https:'].includes(parsed.protocol) || parsed.username || parsed.password || parsed.pathname !== '/' || parsed.search || parsed.hash) throw new Error('API 地址必须是无凭证的 HTTP(S) origin')
  return parsed.origin
}
let base = ''
let invalidConfiguration = false
try { base = validateApiOrigin(configured) } catch { invalidConfiguration = true }
export const apiUrl = (path: string) => {
  if (!path.startsWith('/api/v1/') || path.startsWith('//') || path.includes('\\')) throw new Error('不支持的服务路径')
  return base + path
}
export class ApiError extends Error {
  constructor(public code: string, message: string, public status = 0, public conversationId?: string, public turnId?: string) { super(message) }
}
export function assertApiConfiguration(): void {
  if (invalidConfiguration) throw new ApiError('invalid_api_configuration', '服务地址配置无效，请检查前端的 VITE_API_BASE_URL。')
}
export async function request<T>(path: string, method = 'GET', payload?: unknown): Promise<T> {
  assertApiConfiguration()
  let response: Response
  try { response = await fetch(apiUrl(path), { method, headers: payload === undefined ? {} : { 'Content-Type': 'application/json' }, body: payload === undefined ? undefined : JSON.stringify(payload), cache: 'no-store' }) }
  catch { throw new ApiError('connection_lost', '连接已断开，处理可能仍在继续。请恢复会话核对状态，不要重复发送。') }
  if (!response.ok) {
    let body: { error?: { code?: string; message?: string }; conversation_id?: string; turn_id?: string } = {}
    try { body = await response.json() } catch { /* A proxy may return plain text. */ }
    throw new ApiError(body.error?.code || 'request_failed', body.error?.message || `服务暂不可用（${response.status}）`, response.status, body.conversation_id, body.turn_id)
  }
  if (response.status === 204) return undefined as T
  return response.json() as Promise<T>
}
export const api = {
  list: () => request<Conversation[]>('/api/v1/conversations'),
  create: (title = '新会话') => request<Conversation>('/api/v1/conversations', 'POST', { title }),
  detail: (id: string) => request<ConversationDetail>(`/api/v1/conversations/${id}`),
  rename: (id: string, title: string, expected_metadata_revision?: number) => request<Conversation>(`/api/v1/conversations/${id}`, 'PATCH', { title, expected_metadata_revision }),
  delete: (id: string) => request<void>(`/api/v1/conversations/${id}`, 'DELETE'),
  submit: (id: string, message: string, client_request_id: string, expected_revision: number) => request<Turn>(`/api/v1/conversations/${id}/turns`, 'POST', { message, client_request_id, expected_revision }),
  turn: (id: string, turn: string) => request<Turn>(`/api/v1/conversations/${id}/turns/${turn}`),
  artifact: (id: string, turn: string, plots: PlotSpec[]) => request<ArtifactInfo>(`/api/v1/conversations/${id}/turns/${turn}/artifacts`, 'POST', { plots }),
  manifest: (path: string) => request<Manifest>(path),
  snapshotArtifact: (path: string, plots: PlotSpec[]) => request<ArtifactInfo>(path, 'POST', { plots }),
}
export async function download(path: string): Promise<void> {
  assertApiConfiguration()
  let response: Response
  try { response = await fetch(apiUrl(path), { cache: 'no-store' }) } catch { throw new ApiError('connection_lost', '下载连接已断开，请重新点击下载。') }
  if (!response.ok) {
    let body: {error?:{code?:string;message?:string}} = {}
    try { body = await response.json() } catch { /* Use safe fallback. */ }
    throw new ApiError(body.error?.code || 'download_failed', body.error?.message || '产物不可用，请重新生成。', response.status)
  }
  if (!(response.headers.get('content-type') || '').includes('application/zip')) throw new ApiError('download_failed', '服务没有返回数据包，请检查连接。')
  const href = URL.createObjectURL(await response.blob())
  const anchor = document.createElement('a'); anchor.href = href; anchor.download = 'astroagent-results.zip'; anchor.click()
  setTimeout(() => URL.revokeObjectURL(href), 1000)
}
export function safeLink(value: string): string | null {
  try { const parsed = new URL(value); return ['http:', 'https:'].includes(parsed.protocol) && !parsed.username && !parsed.password ? parsed.href : null } catch { return null }
}
