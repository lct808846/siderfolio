import { apiUrl, ApiError, assertApiConfiguration } from './index'
import type { ChatAttachment } from '../types'

export const attachmentAccept = '.pdf,.docx,.txt,.md,.markdown,.csv,.json'
export const attachmentExtensions = new Set(attachmentAccept.split(','))
export const attachmentFileLimit = 10 * 1024 * 1024
export async function parseAttachment(file: File, signal?: AbortSignal): Promise<ChatAttachment> {
  assertApiConfiguration()
  const body = new FormData()
  body.set('file', file)
  let response: Response
  try { response = await fetch(apiUrl('/api/v1/chat/attachments'), { method: 'POST', body, signal, cache: 'no-store' }) }
  catch (error) {
    if (signal?.aborted) throw error
    throw new ApiError('attachment_connection_lost', '附件读取连接断开，请重新选择文件。')
  }
  const value = await response.json().catch(() => { throw new ApiError('attachment_invalid_response', '附件解析未完成，请稍后重试。') })
  if (!response.ok) throw new ApiError(value.error?.code || 'attachment_parse_failed', value.error?.message || '附件解析失败。', response.status)
  return value as ChatAttachment
}
