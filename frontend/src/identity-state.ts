import { ref } from 'vue'
import { prepareCsrf, resetCsrf, sessionFetch, setCsrf } from './session-http'
import { APPEARANCE_STORAGE_KEY } from './stores/appearance'

export interface IdentityUser { id: string; email: string; username?: string; avatar_url?: string; admin: boolean; totp_enabled: boolean; mfa_verified: boolean }
export const identityUser = ref<IdentityUser | null>(null)
export const identityReady = ref(false)
export const identityError = ref('')
export const sessionPolicy = ref({ idle_seconds: 315360000, absolute_seconds: 315360000 })
const ownerKey = 'astroagent.identity.owner'
const publicPaths = new Set(['/login', '/register', '/activate', '/resend', '/forgot-password', '/reset-password'])
export const isIdentityPage = (path: string) => publicPaths.has(path)

export function safeReturn(value: unknown): string {
  if (typeof value !== 'string' || !value.startsWith('/') || value.startsWith('//') || Array.from(value).some(char => char === '\\' || char.charCodeAt(0) <= 0x20)) return '/'
  try {
    const result = new URL(value, window.location.origin)
    if (result.origin !== window.location.origin || isIdentityPage(result.pathname)) return '/'
    if (result.pathname.startsWith('/admin') && !identityUser.value?.admin) return '/'
    return result.pathname + result.search
  } catch { return '/' }
}

const preservedDeviceKeys = new Set([APPEARANCE_STORAGE_KEY])

export function clearPrivateBrowserData() {
  for (const storage of [localStorage, sessionStorage]) {
    try {
      for (const key of Object.keys(storage)) {
        if (key.startsWith('astroagent.') && !preservedDeviceKeys.has(key)) storage.removeItem(key)
      }
    } catch { /* Memory is discarded by full navigation. */ }
  }
}

export async function identityRequest<T = { message: string }>(path: string, method = 'GET', payload?: unknown): Promise<T> {
  const response = await sessionFetch('/api/v1/' + path, { method, headers: payload === undefined ? undefined : { 'Content-Type': 'application/json' }, body: payload === undefined ? undefined : JSON.stringify(payload) })
  const data = await response.json()
  if (!response.ok) throw new Error(data.error?.message || '身份操作未完成，请重试。')
  return data as T
}

let lastVerifiedAt = 0
let inFlightRefresh: Promise<void> | null = null

export async function refreshIdentity() {
  if (inFlightRefresh) return inFlightRefresh
  inFlightRefresh = (async () => {
    identityError.value = ''
    try {
      const response = await sessionFetch('/api/v1/auth/session')
      if (response.status === 401) { identityUser.value = null; lastVerifiedAt = 0; return }
      const value = await response.json()
      if (!response.ok) throw new Error(value.error?.message || '身份服务尚未就绪。')
      if (identityUser.value && identityUser.value.id !== value.user.id) {
        identityReady.value = false; identityUser.value = null; lastVerifiedAt = 0; clearPrivateBrowserData()
        window.location.replace('/login')
        return
      }
      identityUser.value = value.user
      sessionPolicy.value = { idle_seconds: value.idle_seconds, absolute_seconds: value.absolute_seconds }
      setCsrf(value.csrf_token)
      lastVerifiedAt = Date.now()
      try {
        if (localStorage.getItem(ownerKey) !== value.user.id) { clearPrivateBrowserData(); localStorage.setItem(ownerKey, value.user.id) }
      } catch { /* No private state is restored across a full identity navigation. */ }
    } catch (error) {
      identityUser.value = null
      lastVerifiedAt = 0
      identityError.value = error instanceof Error ? error.message : '身份服务暂不可用。'
    } finally {
      inFlightRefresh = null
    }
  })()
  return inFlightRefresh
}

export async function logout() {
  await identityRequest('auth/logout', 'POST', {})
  identityUser.value = null; lastVerifiedAt = 0; resetCsrf(); clearPrivateBrowserData()
  window.location.replace('/login')
}

export async function identityGuard(to: { path: string; fullPath: string; query: Record<string, unknown> }) {
  const sensitiveRoute = isIdentityPage(to.path) || to.path.startsWith('/admin') || to.path === '/settings'
  const verifiedFresh = identityReady.value && Boolean(identityUser.value) && (Date.now() - lastVerifiedAt) < 30000
  if (!verifiedFresh || sensitiveRoute) {
    if (identityReady.value && Boolean(identityUser.value) && !sensitiveRoute) {
      // Allow instant SPA navigation while silently refreshing session state; API calls still enforce auth strictly.
      void refreshIdentity()
    } else {
      await refreshIdentity()
    }
  }
  identityReady.value = true
  if (!identityUser.value) {
    if (isIdentityPage(to.path)) { try { await prepareCsrf() } catch { /* Page displays configuration status. */ }; return true }
    return { path: '/login', query: { next: safeReturn(to.fullPath) } }
  }
  if (to.path.startsWith('/admin') && !identityUser.value.admin) return '/'
  if (to.path === '/login' || to.path === '/register') return safeReturn(to.query.next)
  return true
}
