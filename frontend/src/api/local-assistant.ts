import { request } from './index'
import type { components } from '../types/generated'

export type LocalStatus = components['schemas']['LocalStatus']
export type LocalTask = components['schemas']['LocalTask']
export type LocalTaskRequest = components['schemas']['LocalTaskRequest']
export type LocalTaskView = components['schemas']['LocalTaskView']
export interface LocalConditionResult {
  conditions: { field: string; status: 'explicit' | 'ambiguous'; value: string | null; unit: string | null; comparison: string; evidence: string }[]
  suggestions: { kind: string; evidence: string }[]
  missing: string[]
  clarification: string[]
}
export const conditionLabels: Record<string, string> = { object_name: '天体名称', source_id: 'DR3 编号', ra: '赤经', dec: '赤纬', radius: '查询半径', year_start: '起始年份', year_end: '结束年份', ruwe_max: 'RUWE 上限', parallax_snr_min: '视差信噪比下限' }
export const intentLabels: Record<string, string> = { object_query: '天体查询', literature_search: '文献检索', gaia_query: 'Gaia 数据查询', plot: '数据绘图', knowledge_search: '本地知识库检索', other_or_unclear: '需要进一步说明' }
const root = '/api/v1/local-assistant'
export const localAssistantApi = {
  status: () => request<LocalStatus>(root),
  probe: () => request<LocalStatus>(`${root}/probe`, 'POST', {}),
  initialize: () => request<LocalStatus>(`${root}/initialize`, 'POST', { confirm_create_tables: true }),
  preferences: (state: LocalStatus, enabled: boolean, auto_titles: boolean) => request<LocalStatus>(`${root}/preferences`, 'PUT', { expected_revision: state.preferences.revision, enabled, auto_titles }),
  clear: () => request<LocalStatus>(`${root}/clear`, 'POST', { confirm_clear_records: true }),
  submit: (id: string, payload: LocalTaskRequest) => request<LocalTaskView>(`${root}/jobs/${id}`, 'PUT', payload),
  task: (id: string) => request<LocalTaskView>(`${root}/jobs/${id}`),
  titles: (conversation: string) => request<LocalTaskView[]>(`/api/v1/conversations/${conversation}/local-title`),
}
export const localTaskLabels: Record<LocalTask['state'], string> = { queued: '等待处理', running: '本地处理中', completed: '已完成', failed: '未完成', interrupted: '已中断', superseded: '结果已丢弃', skipped: '已跳过' }
