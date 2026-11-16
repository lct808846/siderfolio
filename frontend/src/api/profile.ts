import { sessionFetch } from '../session-http'
import { ApiError, apiUrl, assertApiConfiguration } from './index'

export interface ModelUsageEntry {
  model: string
  label: string
  calls: number
  succeeded: number
  failed: number
  chat_calls: number
  plot_calls: number
  rag_calls: number
  local_calls: number
  input_tokens?: number | null
  output_tokens?: number | null
  total_tokens?: number | null
  last_used_at?: string | null
}

export interface WorkspaceUsageStats {
  conversations_count: number
  turns_count: number
  completed_turns: number
  failed_turns: number
  projects_count: number
  snapshots_count: number
  workflows_count: number
  knowledge_documents_count: number
  plot_datasets_count: number
  plot_operations_count: number
  rag_answers_count: number
  local_tasks_count: number
  simbad_queries: number
  ads_queries: number
  gaia_queries: number
  used_bytes: number
  budget_bytes: number
  storage_ready: boolean
}

export interface ProfileAccountInfo {
  id: string
  email: string
  username: string
  avatar_url: string
  admin: boolean
  totp_enabled: boolean
  mfa_verified: boolean
  created_at: string
  last_login?: string | null
  active_sessions: number
}

export interface ProfileSummary {
  account: ProfileAccountInfo
  total_model_calls: number
  distinct_models_count: number
  known_total_tokens?: number | null
  models: ModelUsageEntry[]
  workspace: WorkspaceUsageStats
}

export interface AvatarResponse {
  message: string
  avatar_url: string
}

async function parseJsonResponse<T>(response: Response, fallbackMessage: string): Promise<T> {
  const payload = await response.json().catch(() => {
    throw new ApiError('profile_invalid_response', fallbackMessage, response.status)
  })
  if (!response.ok) {
    throw new ApiError(
      payload?.error?.code || 'profile_request_failed',
      payload?.error?.message || fallbackMessage,
      response.status,
    )
  }
  return payload as T
}

export async function fetchProfileSummary(): Promise<ProfileSummary> {
  assertApiConfiguration()
  let response: Response
  try {
    response = await sessionFetch(apiUrl('/api/v1/profile/summary'), { method: 'GET', cache: 'no-store' })
  } catch {
    throw new ApiError('connection_lost', '暂时无法连接服务，请稍后重试。')
  }
  return parseJsonResponse<ProfileSummary>(response, '个人资料读取失败，请稍后重试。')
}

export async function uploadProfileAvatar(file: File): Promise<AvatarResponse> {
  assertApiConfiguration()
  const body = new FormData()
  body.set('file', file)
  let response: Response
  try {
    response = await sessionFetch(apiUrl('/api/v1/profile/avatar'), {
      method: 'POST',
      body,
      cache: 'no-store',
    })
  } catch {
    throw new ApiError('connection_lost', '头像上传连接已断开，请重试。')
  }
  return parseJsonResponse<AvatarResponse>(response, '头像上传未完成，请更换图片后重试。')
}

export async function deleteProfileAvatar(): Promise<AvatarResponse> {
  assertApiConfiguration()
  let response: Response
  try {
    response = await sessionFetch(apiUrl('/api/v1/profile/avatar'), {
      method: 'DELETE',
      cache: 'no-store',
    })
  } catch {
    throw new ApiError('connection_lost', '恢复默认头像连接已断开，请重试。')
  }
  return parseJsonResponse<AvatarResponse>(response, '未能移除头像，请重试。')
}
