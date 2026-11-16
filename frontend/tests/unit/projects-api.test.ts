import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { importProject, projectsApi } from '../../src/api/projects'
import { resetCsrf, setCsrf } from '../../src/session-http'

beforeEach(() => setCsrf('fixture-csrf'))
afterEach(() => { vi.unstubAllGlobals(); resetCsrf() })
it('rejects an oversized archive before any upload', async () => {
  const fetch = vi.fn(); vi.stubGlobal('fetch', fetch)
  const file = new File(['x'], 'too-large.zip'); Object.defineProperty(file, 'size', { value: 33 * 1024 ** 2 })
  await expect(importProject(file)).rejects.toMatchObject({ code: 'project_archive_too_large' })
  expect(fetch).not.toHaveBeenCalled()
})
it('keeps binary upload separate from JSON and does not retry a lost connection', async () => {
  const fetch = vi.fn().mockRejectedValue(new TypeError('offline')); vi.stubGlobal('fetch', fetch)
  await expect(importProject(new File(['zip'], 'input.zip'))).rejects.toMatchObject({ code: 'connection_lost' })
  expect(fetch).toHaveBeenCalledTimes(1)
  const headers = new Headers(fetch.mock.calls[0]?.[1].headers)
  expect(headers.get('Content-Type')).toBe('application/zip')
  expect(headers.get('X-CSRF-Token')).toBe('fixture-csrf')
})
it('preserves the explicit idempotency key and revision in a direct rerun', async () => {
  const fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify({ state: 'running' }), { status: 202, headers: { 'Content-Type': 'application/json' } })); vi.stubGlobal('fetch', fetch)
  const payload = { expected_revision: 4, family: 'gaia' as const, result_index: 0, confirmed: true, client_request_id: 'request-key' }
  await projectsApi.rerun('project', 'snapshot', payload)
  expect(JSON.parse(fetch.mock.calls[0]?.[1].body)).toEqual(payload)
  expect(fetch).toHaveBeenCalledTimes(1)
})
