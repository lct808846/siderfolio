// Credentials stay in HttpOnly cookies; the CSRF value is held in memory only.
let csrf = ''
let pending: Promise<void> | undefined
export function setCsrf(value: string) { csrf = value }
export function resetCsrf() { csrf = '' }
export async function prepareCsrf() {
  if (!pending) pending = (async () => {
    const response = await fetch('/api/v1/auth/csrf', { credentials: 'same-origin', cache: 'no-store' })
    const body = await response.json()
    if (!response.ok || typeof body.csrf_token !== 'string') throw new Error(body.error?.message || '身份服务暂不可用。')
    csrf = body.csrf_token
  })().finally(() => { pending = undefined })
  await pending
}
export async function sessionFetch(input: string, init: RequestInit = {}) {
  const target = new URL(input, window.location.origin)
  if (target.origin !== window.location.origin) throw new Error('登录后的API仅允许通过本站代理访问。')
  const method = (init.method || 'GET').toUpperCase()
  const headers = new Headers(init.headers)
  if (!['GET', 'HEAD', 'OPTIONS'].includes(method)) {
    if (!csrf) await prepareCsrf()
    headers.set('X-CSRF-Token', csrf)
  }
  const response = await fetch(input, { ...init, method, headers, credentials: 'same-origin', cache: 'no-store' })
  if (response.status === 401) {
    csrf = ''
    if (!target.pathname.startsWith('/api/v1/auth/')) window.dispatchEvent(new Event('astroagent:session-expired'))
  }
  return response
}
