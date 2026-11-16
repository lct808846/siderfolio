import { describe, it, expect, vi, afterEach, beforeEach } from 'vitest'
import { api, apiUrl, safeLink, validateApiOrigin, ApiError, download } from '../../src/api'
import { resetCsrf, setCsrf } from '../../src/session-http'

beforeEach(() => setCsrf('fixture-csrf'))
afterEach(() => { vi.unstubAllGlobals(); vi.unstubAllEnvs(); resetCsrf() })
describe('API and unsafe content boundaries', () => {
  it('preserves exact strings and nullable values', async () => {
    const response = { turn_id: 'saved', response: { gaia_results: [{ data: [{ source_id: '5853498713190525696', parallax: null }] }] } }
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify(response), { status: 200 })))
    const result = await api.turn('conversation', 'saved')
    expect(result.response?.gaia_results?.[0].data?.[0].source_id).toBe('5853498713190525696')
    expect(result.response?.gaia_results?.[0].data?.[0].parallax).toBeNull()
  })
  it('uses unchanged idempotency keys and revision', async () => {
    const fetcher = vi.fn().mockResolvedValue(new Response('{}', { status: 202 }))
    vi.stubGlobal('fetch', fetcher)
    await api.submit('id', '问题', 'same-key', 3)
    expect(JSON.parse(fetcher.mock.calls[0][1].body)).toEqual({ message: '问题', client_request_id: 'same-key', expected_revision: 3 })
  })
  it('keeps a safe locator on execution failure', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ error: { code: 'model_timeout', message: '模型超时' }, conversation_id: 'c', turn_id: 't' }), { status: 504 })))
    await expect(api.submit('c', 'q', 'key', 0)).rejects.toMatchObject({ code: 'model_timeout', turnId: 't', conversationId: 'c' })
  })
  it('treats network loss as unknown execution, never automatic retry', async () => {
    const fetcher = vi.fn().mockRejectedValue(new Error('private address'))
    vi.stubGlobal('fetch', fetcher)
    await expect(api.submit('c', 'q', 'key', 0)).rejects.toMatchObject({ code: 'connection_lost' })
    expect(fetcher).toHaveBeenCalledTimes(1)
  })
  it('rejects non-http links, credential links and malformed API addresses', () => {
    expect(safeLink('javascript:alert(1)')).toBeNull()
    expect(safeLink('data:text/html,unsafe')).toBeNull()
    expect(safeLink('https://secret@example.com/')).toBeNull()
    expect(safeLink('https://ui.adsabs.harvard.edu/')).toBe('https://ui.adsabs.harvard.edu/')
    expect(() => validateApiOrigin('https://host.invalid/api/v1')).toThrow()
    expect(() => apiUrl('https://outside.invalid/file')).toThrow()
  })
  it('surfaces expired binary download instead of saving an error as ZIP', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ error: { code: 'artifact_expired', message: '已过期' } }), { status: 410 })))
    await expect(download('/api/v1/artifacts/id/download')).rejects.toBeInstanceOf(ApiError)
  })
  it('reports malformed build configuration without preventing module startup', async () => {
    vi.stubEnv('VITE_API_BASE_URL', 'https://host.invalid/api/v1')
    vi.resetModules()
    const module = await import('../../src/api')
    const fetcher = vi.fn(); vi.stubGlobal('fetch', fetcher)
    await expect(module.api.list()).rejects.toMatchObject({ code: 'invalid_api_configuration' })
    expect(fetcher).not.toHaveBeenCalled()
  })
})
