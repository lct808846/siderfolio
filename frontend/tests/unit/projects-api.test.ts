import { afterEach, expect, it, vi } from 'vitest'
import { importProject, projectsApi } from '../../src/api/projects'

afterEach(() => vi.unstubAllGlobals())
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
  expect(fetch.mock.calls[0]?.[1].headers).toEqual({ 'Content-Type': 'application/zip' })
})
it('preserves the explicit idempotency key and revision in a direct rerun', async () => {
  const fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify({ state: 'running' }), { status: 202, headers: { 'Content-Type': 'application/json' } })); vi.stubGlobal('fetch', fetch)
  const payload = { expected_revision: 4, family: 'gaia' as const, result_index: 0, confirmed: true, client_request_id: 'request-key' }
  await projectsApi.rerun('project', 'snapshot', payload)
  expect(JSON.parse(fetch.mock.calls[0]?.[1].body)).toEqual(payload)
  expect(fetch).toHaveBeenCalledTimes(1)
})
