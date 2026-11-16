<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { identityError, identityRequest, refreshIdentity, safeReturn } from '../identity-state'
const route = useRoute(), router = useRouter()
const email = ref(''), username = ref(''), password = ref(''), confirmPassword = ref(''), code = ref(''), busy = ref(false), error = ref(''), message = ref(''), resentNotice = ref('')
const errorField = ref<'email' | 'username' | 'password' | 'confirm' | 'code' | ''>('')
const setupToken = ref(''), linkToken = ref('')
const loginStep = ref<'email' | 'password' | 'code'>('email')
const totpRequired = ref(false)
const resendCooldown = ref(0)
let cooldownTimer: ReturnType<typeof setInterval> | null = null
let authChannel: BroadcastChannel | null = null
const passwordInput = ref<HTMLInputElement | null>(null)
const codeInput = ref<HTMLInputElement | null>(null)
const mode = computed(() => ['activate', 'resend', 'forgot-password', 'reset-password'].includes(route.path.slice(1)) ? route.path.slice(1) : 'login')
const titles: Record<string, string> = { activate: '确认邮箱', resend: '重发激活邮件', 'forgot-password': '找回密码', 'reset-password': '设置新密码' }
const title = computed(() => {
  if (message.value) return ['activate', 'reset-password'].includes(mode.value) ? '密码已设置' : '检查你的收件箱'
  if (mode.value === 'activate' && setupToken.value) return '设置密码'
  return titles[mode.value] || '登录 AstroAgent'
})
const statusText = computed(() => {
  if (!message.value) return ''
  const target = email.value || '你的邮箱'
  if (mode.value === 'forgot-password') return `点击我们刚刚发送至 ${target} 的重置链接，即可设置新密码。`
  if (['login', 'resend'].includes(mode.value)) return `点击我们刚刚发送至 ${target} 的验证链接，即可完成账号创建。`
  return message.value
})
const emailMode = computed(() => (mode.value === 'login' && loginStep.value === 'email') || ['resend', 'forgot-password'].includes(mode.value))
const passwordMode = computed(() => (mode.value === 'login' && loginStep.value === 'password') || mode.value === 'reset-password' || !!setupToken.value)
const codeMode = computed(() => mode.value === 'login' && loginStep.value === 'code')
function clearCooldown() {
  if (cooldownTimer) { clearInterval(cooldownTimer); cooldownTimer = null }
  resendCooldown.value = 0
}
function startCooldown(seconds = 60) {
  clearCooldown()
  resendCooldown.value = seconds
  cooldownTimer = setInterval(() => {
    if (resendCooldown.value <= 1) clearCooldown()
    else resendCooldown.value -= 1
  }, 1000)
}
async function enterPasswordStep(targetEmail: string, totp = false) {
  clearCooldown()
  if (route.path !== '/login') await router.replace('/login')
  error.value = ''; errorField.value = ''; message.value = ''; resentNotice.value = ''
  password.value = ''; confirmPassword.value = ''; code.value = ''
  setupToken.value = ''; linkToken.value = ''
  if (targetEmail) email.value = targetEmail
  totpRequired.value = totp
  loginStep.value = 'password'
  await nextTick()
  passwordInput.value?.focus()
}
function onStorageSignal(event: StorageEvent) {
  if (event.key === 'astroagent.identity.logged_in' && event.newValue) {
    window.location.replace(safeReturn(route.query.next))
    return
  }
  if (event.key !== 'astroagent.identity.password_ready' || !event.newValue) return
  try {
    const data = JSON.parse(event.newValue) as { email?: string; totp_enabled?: boolean }
    void enterPasswordStep(data.email || email.value, Boolean(data.totp_enabled))
  } catch { /* ignore malformed storage event */ }
}
onMounted(() => {
  window.addEventListener('storage', onStorageSignal)
  if (typeof BroadcastChannel !== 'undefined') {
    authChannel = new BroadcastChannel('astroagent.identity.channel')
    authChannel.onmessage = (event: MessageEvent<{ type?: string; email?: string; totp_enabled?: boolean }>) => {
      if (event.data?.type === 'logged_in') {
        window.location.replace(safeReturn(route.query.next))
      } else if (event.data?.type === 'password_ready') {
        window.focus()
        setTimeout(() => window.focus(), 120)
        void enterPasswordStep(event.data.email || email.value, Boolean(event.data.totp_enabled))
      }
    }
  }
})
onBeforeUnmount(() => {
  clearCooldown()
  window.removeEventListener('storage', onStorageSignal)
  authChannel?.close()
  authChannel = null
})
function resetToEmail() {
  error.value = ''; errorField.value = ''; message.value = ''; resentNotice.value = ''; password.value = ''; confirmPassword.value = ''; code.value = ''
  loginStep.value = 'email'; totpRequired.value = false; clearCooldown()
  if (route.path !== '/login') void router.push('/login')
}
async function resendInline() {
  if (busy.value || resendCooldown.value > 0 || !email.value) return
  busy.value = true; error.value = ''; errorField.value = ''; resentNotice.value = ''
  try {
    const endpoint = mode.value === 'forgot-password' ? 'auth/forgot-password' : 'auth/resend'
    await identityRequest(endpoint, 'POST', { email: email.value, request_id: crypto.randomUUID() })
    resentNotice.value = '已重新发送电子邮件'
    startCooldown(60)
  } catch (e) {
    error.value = e instanceof Error ? e.message : '操作未完成。'
  } finally {
    busy.value = false
  }
}
watch(() => route.fullPath, () => {
  error.value = ''; errorField.value = ''; message.value = ''; resentNotice.value = ''; password.value = ''; confirmPassword.value = ''; code.value = ''; setupToken.value = ''
  if (route.path !== '/login') { loginStep.value = 'email'; totpRequired.value = false }
  clearCooldown()
  linkToken.value = new URLSearchParams(window.location.hash.slice(1)).get('token') || ''
  if (window.location.hash) window.history.replaceState(window.history.state, '', window.location.pathname + window.location.search)
}, { immediate: true })
async function submit() {
  if (busy.value) return
  error.value = ''; errorField.value = ''; resentNotice.value = ''
  if (emailMode.value) {
    const trimmed = email.value.trim()
    if (!trimmed) { error.value = '请输入邮箱地址'; errorField.value = 'email'; return }
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(trimmed)) { error.value = '请输入有效的邮箱地址'; errorField.value = 'email'; return }
    email.value = trimmed
  }
  if (passwordMode.value) {
    if (mode.value === 'activate') {
      const trimmedName = username.value.trim()
      if (!trimmedName) {
        error.value = '请输入用户名'
        errorField.value = 'username'
        return
      }
      if (trimmedName.length > 32) {
        error.value = '用户名不能超过 32 个字符'
        errorField.value = 'username'
        return
      }
      username.value = trimmedName
    }
    if (!password.value) {
      error.value = mode.value === 'login' ? '请输入密码' : '请输入新密码'
      errorField.value = 'password'
      return
    }
    if (mode.value !== 'login') {
      if (password.value.length < 8) {
        error.value = '密码必须至少包含 8 个字符'
        errorField.value = 'password'
        return
      }
      if (!confirmPassword.value) {
        error.value = '请再次输入确认密码'
        errorField.value = 'confirm'
        return
      }
      if (password.value !== confirmPassword.value) {
        error.value = '两次输入的密码不一致'
        errorField.value = 'confirm'
        return
      }
    }
  }
  if (codeMode.value && !code.value.trim()) {
    error.value = '请输入验证码'
    errorField.value = 'code'
    return
  }
  busy.value = true; message.value = ''
  try {
    if (mode.value === 'login' && loginStep.value === 'email') {
      const value = await identityRequest<{ action: string; totp_enabled?: boolean; message?: string; cooldown?: number }>('auth/continue', 'POST', { email: email.value, request_id: crypto.randomUUID() })
      if (value.action === 'login') {
        loginStep.value = 'password'
        totpRequired.value = Boolean(value.totp_enabled)
        await nextTick()
        passwordInput.value?.focus()
      } else {
        message.value = value.message || '验证邮件已发送。'
        startCooldown(value.cooldown ?? 60)
      }
    } else if (mode.value === 'login') {
      const value = await identityRequest<{ action?: string; message?: string }>('auth/login', 'POST', {
        email: email.value,
        password: password.value,
        code: loginStep.value === 'code' ? code.value : '',
      })
      if (value.action === 'totp_required') {
        error.value = ''; errorField.value = ''; code.value = ''
        totpRequired.value = true
        loginStep.value = 'code'
        await nextTick()
        codeInput.value?.focus()
        return
      }
      await refreshIdentity()
      authChannel?.postMessage({ type: 'logged_in', ts: Date.now() })
      try {
        localStorage.setItem('astroagent.identity.logged_in', String(Date.now()))
        localStorage.removeItem('astroagent.identity.logged_in')
      } catch { /* ignore storage quota errors */ }
      window.location.replace(safeReturn(route.query.next))
    } else if (mode.value === 'activate' && !setupToken.value) {
      const value = await identityRequest<{ setup_token: string }>('auth/activate/confirm', 'POST', { token: linkToken.value })
      linkToken.value = ''; setupToken.value = value.setup_token
    } else if (mode.value === 'activate' || mode.value === 'reset-password') {
      const value = await identityRequest<{ message: string; email?: string; totp_enabled?: boolean }>('auth/' + (mode.value === 'activate' ? 'activate/complete' : 'reset-password'), 'POST', {
        token: setupToken.value || linkToken.value,
        password: password.value,
        ...(mode.value === 'activate' ? { username: username.value.trim() } : {}),
      })
      const payload = { type: 'password_ready', email: value.email || email.value, totp_enabled: Boolean(value.totp_enabled), ts: Date.now() }
      authChannel?.postMessage(payload)
      try {
        localStorage.setItem('astroagent.identity.password_ready', JSON.stringify(payload))
        localStorage.removeItem('astroagent.identity.password_ready')
      } catch { /* ignore storage quota errors */ }
      window.close()
      await enterPasswordStep(payload.email, payload.totp_enabled)
    } else {
      const value = await identityRequest('auth/' + mode.value, 'POST', { email: email.value, request_id: crypto.randomUUID() })
      message.value = value.message
      startCooldown(60)
    }
  } catch (e) {
    error.value = e instanceof Error ? e.message : '操作未完成。'
    if (emailMode.value) errorField.value = 'email'
    else if (codeMode.value) errorField.value = 'code'
    else if (passwordMode.value) errorField.value = 'password'
  }
  finally { busy.value = false }
}
</script>
<template>
  <main class="identity-screen">
    <header class="identity-topbar">
      <div class="identity-brand">
        <span class="identity-brand-mark" aria-hidden="true">
          <svg viewBox="0 0 24 24" fill="none">
            <ellipse cx="12" cy="12" rx="9.5" ry="4.2" transform="rotate(-28 12 12)" stroke="currentColor" stroke-opacity="0.48" stroke-width="1.4" />
            <path d="M12 3.2L13.85 10.15L20.8 12L13.85 13.85L12 20.8L10.15 13.85L3.2 12L10.15 10.15L12 3.2Z" fill="currentColor" />
          </svg>
        </span>
        <span>AstroAgent</span>
      </div>
    </header>
    <div class="identity-shell">
      <section class="identity-stage" :aria-busy="busy">
        <div v-if="message" class="identity-status-view" role="status">
          <h1>{{ title }}</h1>
          <p class="identity-status-desc">{{ statusText }}</p>
          <p v-if="error" class="identity-error" role="alert">
            <svg viewBox="0 0 20 20" fill="currentColor" aria-hidden="true"><path fill-rule="evenodd" d="M18 10a8 8 0 1 1-16 0 8 8 0 0 1 16 0Zm-8-5a.75.75 0 0 1 .75.75v4.5a.75.75 0 0 1-1.5 0v-4.5A.75.75 0 0 1 10 5Zm0 10a1 1 0 1 0 0-2 1 1 0 0 0 0 2Z" clip-rule="evenodd" /></svg>
            <span>{{ error }}</span>
          </p>
          <p v-if="resentNotice" class="identity-resent-tip">{{ resentNotice }}</p>
          <button
            v-if="['activate', 'reset-password'].includes(mode)"
            type="button"
            class="button-primary identity-submit"
            @click="resetToEmail"
          >
            前往登录
          </button>
          <button
            v-else
            type="button"
            class="identity-resend-btn"
            :disabled="busy || resendCooldown > 0"
            @click="resendInline"
          >
            {{ busy ? '正在发送…' : resendCooldown > 0 ? `重新发送电子邮件 (${resendCooldown}s)` : '重新发送电子邮件' }}
          </button>
        </div>
        <template v-else>
          <h1>{{ title }}</h1>
          <p v-if="mode === 'activate' && !setupToken" class="identity-subtitle">点击下方按钮确认邮箱并设置登录密码</p>
          <p v-else-if="codeMode" class="identity-subtitle">请输入双因素身份验证器中的验证码或恢复码</p>
          <p v-if="identityError || (error && !errorField)" class="identity-error" role="alert">
            <svg viewBox="0 0 20 20" fill="currentColor" aria-hidden="true"><path fill-rule="evenodd" d="M18 10a8 8 0 1 1-16 0 8 8 0 0 1 16 0Zm-8-5a.75.75 0 0 1 .75.75v4.5a.75.75 0 0 1-1.5 0v-4.5A.75.75 0 0 1 10 5Zm0 10a1 1 0 1 0 0-2 1 1 0 0 0 0 2Z" clip-rule="evenodd" /></svg>
            <span>{{ error || identityError }}</span>
          </p>
          <form class="identity-form" novalidate @submit.prevent="submit">
            <div v-if="mode === 'login' && (loginStep === 'password' || loginStep === 'code')" class="identity-account-pill">
              <span class="identity-account-email">{{ email }}</span>
              <button type="button" class="identity-text-btn" :disabled="busy" @click="resetToEmail">编辑</button>
            </div>
            <div v-if="emailMode" class="identity-field-group">
              <div class="identity-floating-field" :class="{ 'has-error': errorField === 'email' }">
                <label for="identity-email">邮箱地址</label>
                <input id="identity-email" v-model="email" type="email" aria-label="邮箱" :aria-invalid="errorField === 'email' ? 'true' : undefined" autocomplete="username" maxlength="254" required :disabled="busy" @input="if (errorField === 'email') { error = ''; errorField = '' }">
              </div>
              <p v-if="error && errorField === 'email'" class="identity-field-error" role="alert">
                <svg viewBox="0 0 20 20" fill="currentColor" aria-hidden="true"><path fill-rule="evenodd" d="M18 10a8 8 0 1 1-16 0 8 8 0 0 1 16 0Zm-8-5a.75.75 0 0 1 .75.75v4.5a.75.75 0 0 1-1.5 0v-4.5A.75.75 0 0 1 10 5Zm0 10a1 1 0 1 0 0-2 1 1 0 0 0 0 2Z" clip-rule="evenodd" /></svg>
                <span>{{ error }}</span>
              </p>
            </div>
            <div v-if="passwordMode && mode === 'activate'" class="identity-field-group">
              <div class="identity-floating-field" :class="{ 'has-error': errorField === 'username' }">
                <label for="identity-username">用户名</label>
                <input
                  id="identity-username"
                  v-model="username"
                  type="text"
                  autocomplete="nickname"
                  maxlength="32"
                  required
                  :aria-invalid="errorField === 'username' ? 'true' : undefined"
                  :disabled="busy"
                  @input="if (errorField === 'username') { error = ''; errorField = '' }"
                >
              </div>
              <p v-if="error && errorField === 'username'" class="identity-field-error" role="alert">
                <svg viewBox="0 0 20 20" fill="currentColor" aria-hidden="true"><path fill-rule="evenodd" d="M18 10a8 8 0 1 1-16 0 8 8 0 0 1 16 0Zm-8-5a.75.75 0 0 1 .75.75v4.5a.75.75 0 0 1-1.5 0v-4.5A.75.75 0 0 1 10 5Zm0 10a1 1 0 1 0 0-2 1 1 0 0 0 0 2Z" clip-rule="evenodd" /></svg>
                <span>{{ error }}</span>
              </p>
            </div>
            <div v-if="passwordMode" class="identity-field-group">
              <div class="identity-floating-field" :class="{ 'has-error': errorField === 'password' }">
                <label for="identity-password">{{ mode === 'login' ? '密码' : '新密码' }}</label>
                <input
                  id="identity-password"
                  ref="passwordInput"
                  v-model="password"
                  type="password"
                  :autocomplete="mode === 'login' ? 'current-password' : 'new-password'"
                  :minlength="mode === 'login' ? undefined : 8"
                  maxlength="128"
                  required
                  :aria-invalid="errorField === 'password' ? 'true' : undefined"
                  :disabled="busy"
                  @input="if (errorField === 'password') { error = ''; errorField = '' }"
                >
              </div>
              <p v-if="error && errorField === 'password'" class="identity-field-error" role="alert">
                <svg viewBox="0 0 20 20" fill="currentColor" aria-hidden="true"><path fill-rule="evenodd" d="M18 10a8 8 0 1 1-16 0 8 8 0 0 1 16 0Zm-8-5a.75.75 0 0 1 .75.75v4.5a.75.75 0 0 1-1.5 0v-4.5A.75.75 0 0 1 10 5Zm0 10a1 1 0 1 0 0-2 1 1 0 0 0 0 2Z" clip-rule="evenodd" /></svg>
                <span>{{ error }}</span>
              </p>
            </div>
            <div v-if="passwordMode && mode !== 'login'" class="identity-field-group">
              <div class="identity-floating-field" :class="{ 'has-error': errorField === 'confirm' }">
                <label for="identity-confirm-password">确认密码</label>
                <input
                  id="identity-confirm-password"
                  v-model="confirmPassword"
                  type="password"
                  autocomplete="new-password"
                  minlength="8"
                  maxlength="128"
                  required
                  :aria-invalid="errorField === 'confirm' ? 'true' : undefined"
                  :disabled="busy"
                  @input="if (errorField === 'confirm') { error = ''; errorField = '' }"
                >
              </div>
              <p v-if="error && errorField === 'confirm'" class="identity-field-error" role="alert">
                <svg viewBox="0 0 20 20" fill="currentColor" aria-hidden="true"><path fill-rule="evenodd" d="M18 10a8 8 0 1 1-16 0 8 8 0 0 1 16 0Zm-8-5a.75.75 0 0 1 .75.75v4.5a.75.75 0 0 1-1.5 0v-4.5A.75.75 0 0 1 10 5Zm0 10a1 1 0 1 0 0-2 1 1 0 0 0 0 2Z" clip-rule="evenodd" /></svg>
                <span>{{ error }}</span>
              </p>
            </div>
            <div v-if="codeMode" class="identity-field-group">
              <div class="identity-floating-field" :class="{ 'has-error': errorField === 'code' }">
                <label for="identity-code">验证码</label>
                <input
                  id="identity-code"
                  ref="codeInput"
                  v-model="code"
                  aria-label="验证码或恢复码（已启用时填写）"
                  autocomplete="one-time-code"
                  maxlength="80"
                  required
                  :aria-invalid="errorField === 'code' ? 'true' : undefined"
                  :disabled="busy"
                  @input="if (errorField === 'code') { error = ''; errorField = '' }"
                >
              </div>
              <p v-if="error && errorField === 'code'" class="identity-field-error" role="alert">
                <svg viewBox="0 0 20 20" fill="currentColor" aria-hidden="true"><path fill-rule="evenodd" d="M18 10a8 8 0 1 1-16 0 8 8 0 0 1 16 0Zm-8-5a.75.75 0 0 1 .75.75v4.5a.75.75 0 0 1-1.5 0v-4.5A.75.75 0 0 1 10 5Zm0 10a1 1 0 1 0 0-2 1 1 0 0 0 0 2Z" clip-rule="evenodd" /></svg>
                <span>{{ error }}</span>
              </p>
            </div>
            <button type="submit" class="button-primary identity-submit" :disabled="busy || ((mode === 'activate' || mode === 'reset-password') && !setupToken && !linkToken)">
              {{ busy ? '正在处理…' : mode === 'activate' && !setupToken ? '确认邮箱并继续' : mode === 'login' && loginStep === 'email' ? '继续' : mode === 'login' ? '继续' : passwordMode ? '保存密码' : '继续' }}
            </button>
            <div v-if="mode === 'login' && loginStep === 'password'" class="identity-center-action">
              <RouterLink to="/forgot-password" class="identity-resend-btn">忘记密码？</RouterLink>
            </div>
          </form>
        </template>
      </section>
    </div>
  </main>
</template>
