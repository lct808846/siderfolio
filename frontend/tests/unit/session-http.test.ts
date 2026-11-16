import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest'
import { resetCsrf, sessionFetch, setCsrf } from '../../src/session-http'
import { clearPrivateBrowserData, identityUser, safeReturn } from '../../src/identity-state'

describe('identity browser boundary', () => {
  beforeEach(() => { resetCsrf(); localStorage.clear(); sessionStorage.clear(); identityUser.value = null })
  afterEach(() => { vi.unstubAllGlobals() })

  it('rejects cross-origin credentials and redirect tricks', async () => {
    const fetch = vi.fn()
    vi.stubGlobal('fetch', fetch)
    await expect(sessionFetch('https://evil.example.org/api')).rejects.toThrow()
    expect(fetch).not.toHaveBeenCalled()
    for (const value of ['//evil.example.org', '/\\evil.example.org', '/%2f%2fevil.example.org', '/\nunsafe', '/login', '/admin']) {
      const result = safeReturn(value)
      expect(new URL(result, window.location.origin).origin).toBe(window.location.origin)
      if (value !== '/%2f%2fevil.example.org') expect(result).toBe('/')
    }
  })

  it('uses same-origin HttpOnly cookie transport and in-memory csrf', async () => {
    const fetch = vi.fn().mockResolvedValue(new Response('{}', { status: 200 }))
    vi.stubGlobal('fetch', fetch)
    setCsrf('synthetic-csrf')
    await sessionFetch('/api/v1/conversations', { method: 'POST', body: '{}' })
    const options = fetch.mock.calls[0]![1] as RequestInit
    expect(options.credentials).toBe('same-origin')
    expect(options.cache).toBe('no-store')
    expect(new Headers(options.headers).get('X-CSRF-Token')).toBe('synthetic-csrf')
    expect(Object.keys(localStorage)).toEqual([])
    expect(Object.keys(sessionStorage)).toEqual([])
  })

  it('clears private account preferences while retaining other sites data', () => {
    localStorage.setItem('astroagent.draft', 'private')
    sessionStorage.setItem('astroagent.upload', 'private')
    localStorage.setItem('unrelated.setting', 'keep')
    clearPrivateBrowserData()
    expect(localStorage.getItem('astroagent.draft')).toBeNull()
    expect(sessionStorage.getItem('astroagent.upload')).toBeNull()
    expect(localStorage.getItem('unrelated.setting')).toBe('keep')
  })

  it('signals business session expiry but keeps login failures on their form', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('{}', { status: 401 })))
    const listener = vi.fn()
    window.addEventListener('astroagent:session-expired', listener)
    await sessionFetch('/api/v1/conversations')
    expect(listener).toHaveBeenCalledTimes(1)
    await sessionFetch('/api/v1/auth/session')
    expect(listener).toHaveBeenCalledTimes(1)
    window.removeEventListener('astroagent:session-expired', listener)
  })
})
