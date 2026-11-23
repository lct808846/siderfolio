import { request } from './index'

export interface ProviderModel {
  id: string
  label: string
  selection_id?: string
  input_price_per_1m?: number | null
  output_price_per_1m?: number | null
  price_currency?: 'USD' | 'CNY'
  reference_input_price_per_1m?: number | null
  reference_output_price_per_1m?: number | null
  reference_price_currency?: 'USD' | 'CNY'
}
export type ProviderProtocol = 'openai_chat' | 'openai_responses' | 'anthropic' | 'gemini'
export interface ModelProvider {
  id: string; name: string; base_url: string; protocol: ProviderProtocol; enabled: boolean
  thinking_parameter: 'none' | 'thinking' | 'enable_thinking'; key_configured: boolean
  models: ProviderModel[]
}
export interface ProviderCatalog { revision: number; default_model: string; providers: ModelProvider[] }
export interface ProviderDraft {
  revision: number; id: string; name: string; base_url: string; protocol: ProviderProtocol
  enabled: boolean; thinking_parameter: ModelProvider['thinking_parameter']; models: ProviderModel[]
  api_key?: string
}
const root = '/api/v1/admin/model-providers'
export const providersApi = {
  list: () => request<ProviderCatalog>(root),
  save: (body: ProviderDraft) => request<ProviderCatalog>(root, 'PUT', body),
  remove: (id: string, revision: number) => request<ProviderCatalog>(root + '/' + encodeURIComponent(id), 'DELETE', { revision }),
  defaultModel: (model: string, revision: number) => request<ProviderCatalog>(root + '/default', 'POST', { model, revision }),
  discover: (body: ProviderDraft) => request<{ models: ProviderModel[]; truncated: boolean }>(root + '/discover', 'POST', body),
}
