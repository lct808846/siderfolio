import { request } from './index'
import type {
  MemoryCreateRequest,
  MemoryItem,
  MemoryPreferences,
  MemoryPreferencesUpdate,
  MemorySummaryOverview,
} from '../types'

export const memoryApi = {
  summary: () => request<MemorySummaryOverview>('/api/v1/memories/summary'),
  preferences: () => request<MemoryPreferences>('/api/v1/memories/preferences'),
  updatePreferences: (payload: MemoryPreferencesUpdate) =>
    request<MemoryPreferences>('/api/v1/memories/preferences', 'PUT', payload),
  create: (payload: MemoryCreateRequest) =>
    request<MemoryItem>('/api/v1/memories', 'POST', payload),
}
