import { ApiError, apiUrl, assertApiConfiguration, request } from './index'
import type { DocumentAction, DocumentDetail, DocumentResult, DocumentUpload, DocumentVersion, EvidenceRecord, EvidenceView, KnowledgeDocument, KnowledgeOperation, KnowledgeQuery, KnowledgeResult, TextPreview } from '../types'

const root = (project: string) => `/api/v1/projects/${project}`
export const knowledgeApi = {
  list: (project: string) => request<KnowledgeDocument[]>(`${root(project)}/documents`),
  detail: (project: string, document: string) => request<DocumentDetail>(`${root(project)}/documents/${document}`),
  text: (project: string, document: string, version: string, position: number) => request<TextPreview>(`${root(project)}/documents/${document}/versions/${version}/text?source_position=${position}`),
  search: (project: string, body: KnowledgeQuery, answer = false) => request<KnowledgeResult>(`${root(project)}/knowledge/${answer ? 'answers' : 'search'}`, 'POST', body),
  evidence: (project: string, id: string) => request<EvidenceView>(`${root(project)}/knowledge/evidence/${id}`),
  references: (project: string) => request<EvidenceRecord[]>(`${root(project)}/knowledge/evidence`),
  operation: (project: string, id: string) => request<KnowledgeOperation>(`${root(project)}/knowledge/operations/${id}`),
  reindex: (project: string, document: string, body: DocumentAction) => reindexDocument(`${root(project)}/documents/${document}/reindex`, body),
  delete: (project: string, document: string, expected_revision: number) => request<void>(`${root(project)}/documents/${document}`, 'DELETE', { expected_revision, confirmed: true }),
}
export async function uploadDocument(project: string, file: File, options: DocumentUpload, document?: string): Promise<DocumentResult> {
  assertApiConfiguration()
  if (!file.size || file.size > 20 * 1024 ** 2) throw new ApiError('knowledge_file_size', '文件必须非空且不超过20 MiB。')
  const body = new FormData(); body.append('file', file); body.append('options', JSON.stringify(options))
  let response: Response
  try { response = await fetch(apiUrl(`${root(project)}/documents${document ? `/${document}/versions` : ''}`), { method: 'POST', body, cache: 'no-store' }) }
  catch { throw new ApiError('connection_lost', '上传连接断开。原文件可能已保存；先使用原请求编号核对，不要创建新的请求。') }
  const value = await response.json().catch(() => { throw new ApiError('knowledge_response_unconfirmed', '服务未返回可核对的JSON，请保留原请求编号读取状态。', response.status) })
  if (!response.ok && !(value?.operation?.id && value?.document?.id)) {
    let message = `文档上传失败（${response.status}）`, code = 'knowledge_upload_failed'
    message = value.error?.message || message; code = value.error?.code || code
    throw new ApiError(code, message, response.status)
  }
  return value as DocumentResult
}
async function reindexDocument(path: string, body: DocumentAction): Promise<DocumentResult> {
  assertApiConfiguration()
  let response: Response
  try { response = await fetch(apiUrl(path), { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body), cache: 'no-store' }) }
  catch { throw new ApiError('connection_lost', '重建连接断开，请保留原请求编号核对状态。') }
  const value = await response.json().catch(() => { throw new ApiError('knowledge_response_unconfirmed', '服务未返回可核对的JSON，请保留原请求编号读取状态。', response.status) })
  if (!response.ok && !(value?.operation?.id && value?.document?.id)) throw new ApiError(value.error?.code || 'knowledge_reindex_failed', value.error?.message || '本地重建未完成。', response.status)
  return value as DocumentResult
}
export async function originalContent(project: string, document: string, version: DocumentVersion): Promise<Blob> {
  assertApiConfiguration()
  const response = await fetch(apiUrl(`${root(project)}/documents/${document}/versions/${version.id}/content`), { cache: 'no-store' })
  if (!response.ok) {
    let message = '原文件不可用，请核对是否为仅元数据归档或原文已删除。'
    try { const value = await response.json(); message = value.error?.message || message } catch { /* Use safe fallback. */ }
    throw new ApiError('knowledge_original_unavailable', message, response.status)
  }
  if (!(response.headers.get('content-type') || '').startsWith(version.media_type)) throw new ApiError('knowledge_content_type', '返回类型与文件记录不符。')
  const buffer = await response.arrayBuffer()
  if (buffer.byteLength !== version.bytes || await fileHash(buffer) !== version.sha256) throw new ApiError('knowledge_content_corrupt', '原文件长度或哈希不符。')
  return new Blob([buffer], { type: version.media_type })
}
export async function fileHash(bytes: ArrayBuffer): Promise<string> {
  return Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', bytes))).map(v => v.toString(16).padStart(2, '0')).join('')
}
