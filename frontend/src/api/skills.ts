import { request } from './index'
import { identityRequest } from '../identity-state'
import type {
  AdminMcpServersResponse,
  ExternalMcpConfirmationRecord,
  ExternalMcpConfirmRequest,
  ExternalMcpServerStatus,
  SkillPreferences,
  SkillsCatalogResponse,
  UserToolCatalogResponse,
} from '../types'

export const skillsApi = {
  catalog: () => request<SkillsCatalogResponse>('/api/v1/skills'),
  updatePreferences: (preferences: SkillPreferences) =>
    request<SkillsCatalogResponse>('/api/v1/skills/preferences', 'PUT', preferences),
  tools: () => request<UserToolCatalogResponse>('/api/v1/skills/tools'),
  confirmExternalMcp: (
    conversationId: string,
    turnId: string,
    confirmationId: string,
    payload: ExternalMcpConfirmRequest,
  ) =>
    request<ExternalMcpConfirmationRecord>(
      `/api/v1/conversations/${conversationId}/turns/${turnId}/external-mcp/${confirmationId}/confirm`,
      'POST',
      payload,
    ),
  cancelExternalMcp: (conversationId: string, turnId: string, confirmationId: string) =>
    request<ExternalMcpConfirmationRecord>(
      `/api/v1/conversations/${conversationId}/turns/${turnId}/external-mcp/${confirmationId}/cancel`,
      'POST',
      {},
    ),
}

export const adminMcpApi = {
  listServers: () => identityRequest<AdminMcpServersResponse>('admin/mcp/servers'),
  toggleServer: (serverId: string, enabled: boolean) =>
    identityRequest<ExternalMcpServerStatus>(`admin/mcp/servers/${encodeURIComponent(serverId)}/toggle`, 'POST', {
      enabled,
    }),
  discoverServer: (serverId: string) =>
    identityRequest<ExternalMcpServerStatus>(`admin/mcp/servers/${encodeURIComponent(serverId)}/discover`, 'POST', {}),
  approveTool: (serverId: string, remoteName: string, expectedDefinitionSha256: string) =>
    identityRequest<ExternalMcpServerStatus>(
      `admin/mcp/servers/${encodeURIComponent(serverId)}/tools/${encodeURIComponent(remoteName)}/approve`,
      'POST',
      { expected_definition_sha256: expectedDefinitionSha256 },
    ),
  revokeTool: (serverId: string, remoteName: string) =>
    identityRequest<ExternalMcpServerStatus>(
      `admin/mcp/servers/${encodeURIComponent(serverId)}/tools/${encodeURIComponent(remoteName)}/revoke`,
      'POST',
      {},
    ),
}
