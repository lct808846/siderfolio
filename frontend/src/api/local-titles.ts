import { request } from './index'
import type { components } from '../types/generated'

export type LocalStatus = components['schemas']['LocalStatus']
export type LocalTask = components['schemas']['LocalTask']
export type LocalTaskView = components['schemas']['LocalTaskView']
const root = '/api/v1/local-titles'
export const localTitlesApi = {
  status: () => request<LocalStatus>(root),
  probe: () => request<LocalStatus>(`${root}/probe`, 'POST', {}),
  preferences: (state: LocalStatus, enabled: boolean) => request<LocalStatus>(`${root}/preferences`, 'PUT', { expected_revision: state.preferences.revision, enabled, auto_titles: enabled }),
  titles: (conversation: string) => request<LocalTaskView[]>(`/api/v1/conversations/${conversation}/local-title`),
}
export const localTaskLabels: Record<LocalTask['state'], string> = { queued: '等待处理', running: '本地处理中', completed: '已完成', failed: '未完成', interrupted: '已中断', superseded: '结果已丢弃', skipped: '已跳过' }
