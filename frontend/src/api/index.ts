import { sessionFetch } from '../session-http'
import type { ArchivedConversation, ArtifactInfo, ChatAttachment, ChatModelCatalog, ChatToolMode, Conversation, ConversationBundle, ConversationDetail, Manifest, PlotSpec, Turn } from '../types'

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
  try { response = await sessionFetch(apiUrl(path), { method, headers: payload === undefined ? {} : { 'Content-Type': 'application/json' }, body: payload === undefined ? undefined : JSON.stringify(payload), cache: 'no-store' }) }
  catch { throw new ApiError('connection_lost', '连接已断开，处理可能仍在继续。请恢复会话核对状态，不要重复发送。') }
  if (!response.ok) {
    let body: { error?: { code?: string; message?: string }; conversation_id?: string; turn_id?: string } = {}
    try { body = await response.json() } catch { /* A proxy may return plain text. */ }
    throw new ApiError(body.error?.code || 'request_failed', body.error?.message || `服务暂不可用（${response.status}）`, response.status, body.conversation_id, body.turn_id)
  }
  if (response.status === 204) return undefined as T
  return response.json() as Promise<T>
}
export interface TurnStreamHandlers {
  onStatus?: (status: { phase?: string; tool?: string | null; label?: string }) => void
  onDelta?: (text: string) => void
  onReset?: () => void
}

async function submitTurnStream(
  id: string,
  payload: {
    message: string
    client_request_id: string
    expected_revision: number
    model?: string
    attachments?: ChatAttachment[]
    tool_mode?: ChatToolMode
    skill_id?: string
  },
  handlers: TurnStreamHandlers = {},
): Promise<Turn> {
  assertApiConfiguration()
  let response: Response
  try {
    response = await sessionFetch(apiUrl(`/api/v1/conversations/${id}/turns/stream`), {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Accept: 'text/event-stream',
      },
      body: JSON.stringify(payload),
      cache: 'no-store',
    })
  } catch {
    throw new ApiError('connection_lost', '连接已断开，处理可能仍在继续。请恢复会话核对状态，不要重复发送。')
  }
  if (!response.ok) {
    let body: { error?: { code?: string; message?: string }; conversation_id?: string; turn_id?: string } = {}
    try { body = await response.json() } catch { /* A proxy may return plain text. */ }
    throw new ApiError(body.error?.code || 'request_failed', body.error?.message || `服务暂不可用（${response.status}）`, response.status, body.conversation_id, body.turn_id)
  }
  const contentType = response.headers.get('content-type') || ''
  if (!contentType.includes('text/event-stream') || !response.body) {
    return response.json() as Promise<Turn>
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder('utf-8')
  let buffer = ''
  let finalTurn: Turn | null = null

  const processFrame = (rawFrame: string) => {
    const lines = rawFrame.split(/\r?\n/)
    let eventName = 'message'
    const dataLines: string[] = []
    for (const line of lines) {
      if (!line || line.startsWith(':')) continue
      if (line.startsWith('event:')) eventName = line.slice(6).trim()
      else if (line.startsWith('data:')) dataLines.push(line.slice(5).replace(/^ /, ''))
    }
    if (!dataLines.length) return
    const rawData = dataLines.join('\n')
    let parsed: Record<string, unknown>
    try { parsed = JSON.parse(rawData) as Record<string, unknown> } catch { return }
    if (eventName === 'delta') {
      const text = typeof parsed.text === 'string' ? parsed.text : ''
      if (text) handlers.onDelta?.(text)
    } else if (eventName === 'status') {
      handlers.onStatus?.({
        phase: typeof parsed.phase === 'string' ? parsed.phase : undefined,
        tool: typeof parsed.tool === 'string' ? parsed.tool : null,
        label: typeof parsed.label === 'string' ? parsed.label : undefined,
      })
    } else if (eventName === 'reset') {
      handlers.onReset?.()
    } else if (eventName === 'done') {
      if (parsed.turn && typeof parsed.turn === 'object') {
        finalTurn = parsed.turn as Turn
      }
    } else if (eventName === 'error') {
      const errObj = (parsed.error && typeof parsed.error === 'object' ? parsed.error : {}) as { code?: string; message?: string }
      throw new ApiError(
        errObj.code || 'request_failed',
        errObj.message || '回答未能完成，请重试。',
        typeof parsed.status === 'number' ? parsed.status : 502,
        typeof parsed.conversation_id === 'string' ? parsed.conversation_id : undefined,
        typeof parsed.turn_id === 'string' ? parsed.turn_id : undefined,
      )
    }
  }

  try {
    while (true) {
      const { value, done } = await reader.read()
      if (value) buffer += decoder.decode(value, { stream: !done })
      const frames = buffer.split(/\r?\n\r?\n/)
      buffer = frames.pop() || ''
      for (const frame of frames) {
        if (frame.trim()) processFrame(frame)
      }
      if (done) {
        buffer += decoder.decode()
        if (buffer.trim()) processFrame(buffer)
        break
      }
    }
  } catch (error) {
    if (error instanceof ApiError) throw error
    throw new ApiError('connection_lost', '连接已断开，处理可能仍在继续。请恢复会话核对状态，不要重复发送。')
  } finally {
    reader.releaseLock()
  }

  if (!finalTurn) {
    throw new ApiError('connection_lost', '连接已断开，处理可能仍在继续。请恢复会话核对状态，不要重复发送。')
  }
  return finalTurn
}

export const api = {
  models: () => request<ChatModelCatalog>('/api/v1/models'),
  list: (includeArchived = false) => request<Conversation[]>(includeArchived ? '/api/v1/conversations?include_archived=true' : '/api/v1/conversations'),
  archived: () => request<ArchivedConversation[]>('/api/v1/conversations/archived'),
  create: (title = '新会话') => request<Conversation>('/api/v1/conversations', 'POST', { title }),
  detail: (id: string) => request<ConversationDetail>(`/api/v1/conversations/${id}`),
  bundle: (id: string) => request<ConversationBundle>(`/api/v1/conversations/${id}/bundle`),
  rename: (id: string, title: string, expected_metadata_revision?: number) => request<Conversation>(`/api/v1/conversations/${id}`, 'PATCH', { title, expected_metadata_revision }),
  archive: (id: string) => request<ArchivedConversation>(`/api/v1/conversations/${id}/archive`, 'POST'),
  unarchive: (id: string) => request<Conversation>(`/api/v1/conversations/${id}/archive`, 'DELETE'),
  delete: (id: string) => request<void>(`/api/v1/conversations/${id}`, 'DELETE'),
  submit: (id: string, message: string, client_request_id: string, expected_revision: number, model?: string, attachments?: ChatAttachment[], tool_mode?: ChatToolMode, skill_id?: string | null) => request<Turn>(`/api/v1/conversations/${id}/turns`, 'POST', { message, client_request_id, expected_revision, model, attachments, ...(tool_mode && tool_mode !== 'auto' ? { tool_mode } : {}), ...(skill_id ? { skill_id } : {}) }),
  submitStream: (id: string, message: string, client_request_id: string, expected_revision: number, model?: string, attachments?: ChatAttachment[], tool_mode?: ChatToolMode, handlers?: TurnStreamHandlers, skill_id?: string | null) => submitTurnStream(id, { message, client_request_id, expected_revision, model, attachments, ...(tool_mode && tool_mode !== 'auto' ? { tool_mode } : {}), ...(skill_id ? { skill_id } : {}) }, handlers),
  turn: (id: string, turn: string) => request<Turn>(`/api/v1/conversations/${id}/turns/${turn}`),
  artifact: (id: string, turn: string, plots: PlotSpec[]) => request<ArtifactInfo>(`/api/v1/conversations/${id}/turns/${turn}/artifacts`, 'POST', { plots }),
  manifest: (path: string) => request<Manifest>(path),
  snapshotArtifact: (path: string, plots: PlotSpec[]) => request<ArtifactInfo>(path, 'POST', { plots }),
}
export async function download(path: string, filename = 'astroagent-results.zip', mediaType = 'application/zip'): Promise<void> {
  assertApiConfiguration()
  let response: Response
  try { response = await sessionFetch(apiUrl(path), { cache: 'no-store' }) } catch { throw new ApiError('connection_lost', '下载连接已断开，请重新点击下载。') }
  if (!response.ok) {
    let body: {error?:{code?:string;message?:string}} = {}
    try { body = await response.json() } catch { /* Use safe fallback. */ }
    throw new ApiError(body.error?.code || 'download_failed', body.error?.message || '产物不可用，请重新生成。', response.status)
  }
  if (response.headers.get('content-type')?.split(';', 1)[0] !== mediaType) throw new ApiError('download_failed', '服务返回的文件格式有误，请检查连接。')
  const href = URL.createObjectURL(await response.blob())
  const anchor = document.createElement('a'); anchor.href = href; anchor.download = filename; anchor.click()
  setTimeout(() => URL.revokeObjectURL(href), 1000)
}
export function safeLink(value: string): string | null {
  try { const parsed = new URL(value); return ['http:', 'https:'].includes(parsed.protocol) && !parsed.username && !parsed.password ? parsed.href : null } catch { return null }
}
