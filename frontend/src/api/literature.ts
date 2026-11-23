import { request } from './index'
import type {
  LiteratureItem,
  LiteratureListResponse,
  LiteratureManualAddRequest,
  LiteratureSaveReceipt,
  LiteratureStatusResponse,
  LiteratureUpdateRequest,
  RunTrace,
} from '../types'

const prefix = '/api/v1/literature'

export interface LiteratureListParams {
  q?: string
  year?: number | null
  tag?: string
  page?: number
  pageSize?: number
}

export const literatureApi = {
  list(params: LiteratureListParams = {}): Promise<LiteratureListResponse> {
    const query = new URLSearchParams()
    if (params.q && params.q.trim()) query.set('q', params.q.trim())
    if (params.year != null && Number.isFinite(params.year)) query.set('year', String(params.year))
    if (params.tag && params.tag.trim()) query.set('tag', params.tag.trim())
    if (params.page && params.page > 1) query.set('page', String(params.page))
    if (params.pageSize) query.set('page_size', String(params.pageSize))
    const suffix = query.toString()
    return request<LiteratureListResponse>(`${prefix}/items${suffix ? `?${suffix}` : ''}`)
  },

  status(bibcodes: string[]): Promise<LiteratureStatusResponse> {
    const query = new URLSearchParams()
    const unique = Array.from(new Set(bibcodes.map(code => code.trim()).filter(Boolean)))
    for (const code of unique.slice(0, 50)) {
      query.append('bibcode', code)
    }
    const suffix = query.toString()
    if (!suffix) {
      return Promise.resolve({ saved: {} })
    }
    return request<LiteratureStatusResponse>(`${prefix}/items/status?${suffix}`)
  },

  detail(itemId: string): Promise<LiteratureItem> {
    return request<LiteratureItem>(`${prefix}/items/${encodeURIComponent(itemId)}`)
  },

  add(payload: LiteratureManualAddRequest): Promise<LiteratureSaveReceipt> {
    return request<LiteratureSaveReceipt>(`${prefix}/items`, 'POST', payload)
  },

  update(itemId: string, payload: LiteratureUpdateRequest): Promise<LiteratureItem> {
    return request<LiteratureItem>(`${prefix}/items/${encodeURIComponent(itemId)}`, 'PATCH', payload)
  },

  remove(itemId: string, expectedRevision: number): Promise<void> {
    return request<void>(
      `${prefix}/items/${encodeURIComponent(itemId)}?expected_revision=${encodeURIComponent(String(expectedRevision))}`,
      'DELETE',
    )
  },

  turnTrace(conversationId: string, turnId: string): Promise<RunTrace> {
    return request<RunTrace>(
      `/api/v1/conversations/${encodeURIComponent(conversationId)}/turns/${encodeURIComponent(turnId)}/trace`,
    )
  },
}
