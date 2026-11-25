<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { clearPrivateBrowserData, identityRequest, identityUser, logout, refreshIdentity } from '../identity-state'
import { buildOtpAuthUri, encodeQrCode } from '../utils/qrcode'
import StatusNotice from '../components/StatusNotice.vue'
import SuccessToast from '../components/SuccessToast.vue'
import type { RevokeOthersResponse, SessionInfo } from '../types'

const props = withDefaults(defineProps<{
  mode?: 'all' | 'security' | 'account'
}>(), {
  mode: 'all',
})

const showSecurity = computed(() => props.mode === 'all' || props.mode === 'security')
const showAccount = computed(() => props.mode === 'all' || props.mode === 'account')

const busy = ref(false)
const error = ref('')
const message = ref('')

// Profile state
const usernameDraft = ref(identityUser.value?.username || identityUser.value?.email?.split('@')[0] || '')
watch(
  () => identityUser.value?.username,
  val => {
    if (val) usernameDraft.value = val
  },
  { immediate: true },
)

// 2FA / TOTP enrollment state
const dialog = ref<HTMLDialogElement | null>(null)
const panel = ref<'profile' | 'password' | 'mfa-enable' | 'mfa-disable' | 'sessions' | 'revoke' | 'revoke-others'>('profile')
const dialogOpen = ref(false)
const sessionsLoading = ref(false), sessionsLoaded = ref(false)
const totpPassword = ref('')
const totpCurrentCode = ref('')
const secret = ref('')
const otpauthUri = ref('')
const confirmCode = ref('')
const confirmCodeInput = ref<HTMLInputElement | null>(null)
const recovery = ref<string[]>([])
const copiedRecovery = ref(false)

// Password change state
const password = ref('')
const nextPassword = ref('')
const code = ref('')

// Revoke all sessions state
const revokePassword = ref('')
const revokeCode = ref('')

const displayName = computed(() => {
  return (identityUser.value?.username || identityUser.value?.email?.split('@')[0] || 'Siderfolio 用户').trim()
})

const qrCode = computed(() => {
  if (!secret.value) return null
  const uri =
    otpauthUri.value ||
    buildOtpAuthUri(identityUser.value?.email || 'user', secret.value, 'Siderfolio')
  try {
    return encodeQrCode(uri, 3)
  } catch {
    return null
  }
})

const sessions = ref<SessionInfo[]>([])
const selectedSession = ref<SessionInfo | null>(null)
const otherSessionsCount = computed(() => sessions.value.filter(item => !item.current).length)
const anomalousSessionsCount = computed(() => sessions.value.filter(item => item.is_anomalous).length)

const ANOMALY_LABELS: Record<string, string> = {
  different_location: '异地登录',
  new_network: '新网络登录',
  new_device: '新设备登录',
}

const DEVICE_TYPE_LABELS: Record<string, string> = {
  desktop: '桌面端',
  mobile: '移动端',
  tablet: '平板',
  unknown: '未知设备',
}

function deviceTitle(item: SessionInfo) {
  if (item.device_name && item.device_name.trim()) return item.device_name
  return item.current ? '当前设备（升级前会话）' : '其他设备（升级前会话）'
}

function deviceTypeLabel(item: SessionInfo) {
  return DEVICE_TYPE_LABELS[item.device_type] || '未知设备'
}

function anomalyTagLabel(reason: string) {
  return ANOMALY_LABELS[reason] || reason
}

function systemBrowserSummary(item: SessionInfo) {
  const parts = [item.os, item.browser].filter(value => Boolean(value && value.trim()))
  return parts.length ? parts.join(' · ') : '升级前登录，未记录系统与浏览器'
}

function hasNetworkChanged(item: SessionInfo) {
  const ipChanged = Boolean(item.last_ip && item.login_ip && item.last_ip !== item.login_ip)
  const locChanged = Boolean(item.last_location && item.login_location && item.last_location !== item.login_location)
  return ipChanged || locChanged
}

function formatBeijing(iso: string) {
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return iso
  return date.toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai', hour12: false })
}

function formatRelative(iso: string) {
  const ts = new Date(iso).getTime()
  if (Number.isNaN(ts)) return ''
  const diffSec = Math.max(0, Math.floor((Date.now() - ts) / 1000))
  if (diffSec < 60) return '刚刚活跃'
  if (diffSec < 3600) return `${Math.floor(diffSec / 60)} 分钟前`
  if (diffSec < 86400) return `${Math.floor(diffSec / 3600)} 小时前`
  return `${Math.floor(diffSec / 86400)} 天前`
}

function clearFeedback() {
  error.value = ''
  message.value = ''
}
watch(() => props.mode, clearFeedback)

async function saveProfile() {
  if (busy.value || !usernameDraft.value.trim()) return
  busy.value = true
  clearFeedback()
  try {
    const value = await identityRequest<{ message: string; username: string }>('auth/profile', 'POST', {
      username: usernameDraft.value.trim(),
    })
    message.value = value.message
    await refreshIdentity()
    closeDialog()
  } catch (e) {
    error.value = e instanceof Error ? e.message : '操作未完成。'
  } finally {
    busy.value = false
  }
}

async function enrollTotp() {
  if (busy.value || !totpPassword.value) return
  busy.value = true
  clearFeedback()
  try {
    const value = await identityRequest<{ secret: string; otpauth_uri?: string; message: string }>(
      'auth/totp/enroll',
      'POST',
      {
        password: totpPassword.value,
        code: totpCurrentCode.value.trim(),
      },
    )
    secret.value = value.secret
    otpauthUri.value =
      value.otpauth_uri ||
      buildOtpAuthUri(identityUser.value?.email || 'user', value.secret, 'Siderfolio')
    totpPassword.value = ''
    totpCurrentCode.value = ''
    confirmCode.value = ''
    recovery.value = []
    await nextTick()
    confirmCodeInput.value?.focus()
  } catch (e) {
    error.value = e instanceof Error ? e.message : '无法生成绑定二维码，请核对当前密码。'
  } finally {
    busy.value = false
  }
}

function cancelTotpEnroll() {
  secret.value = ''
  otpauthUri.value = ''
  confirmCode.value = ''
  clearFeedback()
  closeDialog()
}

async function confirmTotp() {
  const sanitized = confirmCode.value.trim()
  if (busy.value || sanitized.length !== 6) return
  busy.value = true
  clearFeedback()
  try {
    const value = await identityRequest<{ recovery_codes: string[]; message: string }>(
      'auth/totp/confirm',
      'POST',
      { code: sanitized },
    )
    recovery.value = value.recovery_codes
    copiedRecovery.value = false
    secret.value = ''
    otpauthUri.value = ''
    confirmCode.value = ''
    message.value = '多因素身份验证已启用，请妥善保存本次恢复码。'
    await refreshIdentity()
    await loadSessions()
  } catch (e) {
    error.value = e instanceof Error ? e.message : '验证码校验未通过，请核对手机验证器时间。'
  } finally {
    busy.value = false
  }
}

async function copyRecoveryCodes() {
  if (!recovery.value.length) return
  try {
    await navigator.clipboard.writeText(recovery.value.join('\n'))
    copiedRecovery.value = true
    setTimeout(() => {
      copiedRecovery.value = false
    }, 2500)
  } catch {
    error.value = '浏览器未授权剪贴板访问，请使用下载功能或手动选择复制。'
  }
}

function downloadRecoveryCodes() {
  if (!recovery.value.length) return
  const lines = [
    'Siderfolio 双因素验证 (2FA) 一次性应急恢复码',
    `账号: ${identityUser.value?.email || ''}`,
    `生成时间: ${new Date().toLocaleString('zh-CN')}`,
    '说明: 每个恢复码仅可使用一次，请离线妥善保管。',
    '----------------------------------------',
    ...recovery.value.map((item, idx) => `${String(idx + 1).padStart(2, '0')}. ${item}`),
    '',
  ]
  const blob = new Blob([lines.join('\n')], { type: 'text/plain;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = `astroagent-recovery-codes-${(identityUser.value?.email || 'account').split('@')[0]}.txt`
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
  URL.revokeObjectURL(url)
}

async function changePassword() {
  if (busy.value || !password.value || nextPassword.value.length < 8) return
  busy.value = true
  clearFeedback()
  try {
    const value = await identityRequest('auth/change-password', 'POST', {
      password: password.value,
      code: code.value.trim(),
      new_password: nextPassword.value,
    })
    message.value = value.message
    password.value = ''
    nextPassword.value = ''
    code.value = ''
    clearPrivateBrowserData()
    window.location.replace('/login')
  } catch (e) {
    error.value = e instanceof Error ? e.message : '密码修改未完成，请核对当前密码与验证码。'
  } finally {
    busy.value = false
  }
}

async function revokeSelectedSession() {
  const selected = selectedSession.value
  if (busy.value || !revokePassword.value || !selected || selected.current) return
  busy.value = true
  clearFeedback()
  try {
    const value = await identityRequest('auth/sessions/revoke', 'POST', {
      session_id: selected.id,
      password: revokePassword.value,
      code: revokeCode.value.trim(),
    })
    message.value = value.message
    revokePassword.value = ''
    revokeCode.value = ''
    sessions.value = sessions.value.filter(item => item.id !== selected.id)
    selectedSession.value = null
    panel.value = 'sessions'
    await loadSessions()
  } catch (e) {
    error.value = e instanceof Error ? e.message : '操作未完成，请核对当前密码与验证信息。'
  } finally {
    busy.value = false
  }
}

async function revokeOtherSessions() {
  if (busy.value || !revokePassword.value || otherSessionsCount.value === 0) return
  busy.value = true
  clearFeedback()
  try {
    const value = await identityRequest<RevokeOthersResponse>('auth/sessions/revoke-others', 'POST', {
      password: revokePassword.value,
      code: revokeCode.value.trim(),
    })
    message.value = value.message
    revokePassword.value = ''
    revokeCode.value = ''
    sessions.value = sessions.value.filter(item => item.current)
    panel.value = 'sessions'
    await loadSessions()
  } catch (e) {
    error.value = e instanceof Error ? e.message : '操作未完成，请核对当前密码与验证信息。'
  } finally {
    busy.value = false
  }
}

async function handleLogout() {
  if (busy.value) return
  busy.value = true
  clearFeedback()
  try {
    await logout()
  } catch (e) {
    error.value = e instanceof Error ? e.message : '退出登录失败。'
  } finally {
    busy.value = false
  }
}

const panelTitle = computed(() => ({
  profile: '修改用户名',
  password: '修改登录密码',
  'mfa-enable': recovery.value.length ? '保存恢复码' : '启用身份验证器',
  'mfa-disable': '关闭多因素身份验证',
  sessions: '已登录设备',
  revoke: '强制退出所选设备',
  'revoke-others': '强制退出其他全部设备',
})[panel.value])

function selectSession(item: SessionInfo) {
  if (busy.value || item.current) return
  selectedSession.value = item
  revokePassword.value = ''; revokeCode.value = ''
  clearFeedback()
  panel.value = 'revoke'
}

function openRevokeOthers() {
  if (busy.value || otherSessionsCount.value === 0) return
  selectedSession.value = null
  revokePassword.value = ''; revokeCode.value = ''
  clearFeedback()
  panel.value = 'revoke-others'
}
async function openPanel(value: typeof panel.value) {
  if (busy.value) return
  clearFeedback()
  panel.value = value
  dialogOpen.value = true
  await nextTick()
  dialog.value?.showModal()
  if (value === 'sessions') void loadSessions()
}
function resetSensitiveInputs() {
  totpPassword.value = ''; totpCurrentCode.value = ''; confirmCode.value = ''
  password.value = ''; nextPassword.value = ''; code.value = ''
  revokePassword.value = ''; revokeCode.value = ''
  secret.value = ''; otpauthUri.value = ''
}
function closeDialog() { dialog.value?.close() }
function dialogClosed() { dialogOpen.value = false; selectedSession.value = null; resetSensitiveInputs() }
function toggleMfa(event: Event) {
  const enabled = !!identityUser.value?.totp_enabled
  ;(event.target as HTMLInputElement).checked = enabled
  if (busy.value || (enabled && identityUser.value?.admin)) return
  void openPanel(enabled ? 'mfa-disable' : 'mfa-enable')
}
async function disableMfa() {
  if (busy.value || !totpPassword.value || !totpCurrentCode.value.trim() || identityUser.value?.admin) return
  busy.value = true; clearFeedback()
  try {
    await identityRequest('auth/totp/disable', 'POST', { password: totpPassword.value, code: totpCurrentCode.value.trim() })
    resetSensitiveInputs(); recovery.value = []
    clearPrivateBrowserData()
    window.location.replace('/login')
  } catch (e) { error.value = e instanceof Error ? e.message : '未能关闭身份验证器，请核对验证信息。' }
  finally { busy.value = false }
}
async function loadSessions() {
  if (sessionsLoading.value) return
  sessionsLoading.value = true
  try {
    sessions.value = await identityRequest<SessionInfo[]>('auth/sessions')
    sessionsLoaded.value = true
  } catch (e) { sessionsLoaded.value = false; error.value = e instanceof Error ? e.message : '登录设备读取失败。' }
  finally { sessionsLoading.value = false }
}
onMounted(() => { void loadSessions() })
</script>
<template>
  <div class="account-preferences">
    <SuccessToast v-model:message="message" />
    <StatusNotice v-if="error && !dialogOpen" title="账号操作未完成" :message="error" @dismiss="error = ''" />

    <template v-if="showSecurity">
      <section class="account-preferences-group" aria-labelledby="account-advice-title">
        <h3 id="account-advice-title">安全建议</h3>
        <div
          class="account-security-advice"
          :class="!identityUser?.totp_enabled || (identityUser?.admin && !identityUser?.mfa_verified) || anomalousSessionsCount > 0 ? 'is-warn' : 'is-ok'"
        >
          <div>
            <template v-if="!identityUser?.totp_enabled">
              <strong>建议启用多因素身份验证 (MFA)</strong>
              <p>开启身份验证器一次性验证码，可有效防止密码泄露导致的未授权登录。</p>
            </template>
            <template v-else-if="identityUser?.admin && !identityUser?.mfa_verified">
              <strong>当前会话尚未经过双因素验证</strong>
              <p>管理员账号须退出并使用 6 位动态验证码重新登录后，才可访问控制台与系统设置。</p>
            </template>
            <template v-else-if="anomalousSessionsCount > 0">
              <strong>有 {{ anomalousSessionsCount }} 台设备存在异常登录标记</strong>
              <p>异常登录已发送提醒邮件且未强制退出。请核对设备详情，如非本人操作请及时强制退出并修改密码。</p>
              <button type="button" class="account-recovery-reminder" @click="openPanel('sessions')">查看并核对登录设备 →</button>
            </template>
            <template v-else>
              <strong>当前没有需要处理的安全建议</strong>
              <p>多设备登录状态正常，异常登录将通过邮件及时通知。</p>
            </template>
          </div>
          <span class="account-advice-shield" aria-hidden="true">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round">
              <path d="M12 3 4 6v6c0 5 8 9 8 9s8-4 8-9V6z" />
              <path v-if="identityUser?.totp_enabled && (!identityUser?.admin || identityUser?.mfa_verified) && anomalousSessionsCount === 0" d="m9 12 2 2 4-4" />
              <path v-else d="M12 8.5v4m0 3.2h.01" />
            </svg>
          </span>
        </div>
      </section>

      <section class="account-preferences-group" aria-labelledby="account-signin-title">
        <h3 id="account-signin-title">登录方式</h3>
        <div class="settings-row">
          <div><h4>密码</h4><p>管理你的登录密码</p></div>
          <button type="button" class="account-value-action" :disabled="busy" @click="openPanel('password')">修改<span aria-hidden="true">›</span></button>
        </div>
      </section>

      <section class="account-preferences-group" aria-labelledby="account-mfa-title">
        <h3 id="account-mfa-title">多因素身份验证 (MFA)</h3>
        <div class="settings-row settings-switch-row">
          <div><h4><label for="account-mfa-switch">身份验证器应用</label></h4><p id="account-mfa-description">使用身份验证器应用生成的一次性验证码</p></div>
          <input id="account-mfa-switch" class="settings-switch" type="checkbox" role="switch" :checked="!!identityUser?.totp_enabled" :disabled="busy || (!!identityUser?.admin && !!identityUser?.totp_enabled)" aria-describedby="account-mfa-description account-mfa-policy" @change="toggleMfa" />
        </div>
        <p id="account-mfa-policy" class="settings-footnote">{{ identityUser?.admin ? identityUser.totp_enabled ? '管理员账号须保持 MFA 开启，以保护管理操作。' : '管理员账号须先开启 MFA，才能使用工作台与管理功能。' : '开启时需扫码并验证；关闭时需确认密码及验证码，并重新登录。' }}</p>
        <button v-if="recovery.length" type="button" class="account-recovery-reminder" @click="openPanel('mfa-enable')">查看并保存本次恢复码 →</button>
      </section>

      <section class="account-preferences-group" aria-labelledby="account-sessions-title">
        <h3 id="account-sessions-title">登录设备与会话</h3>
        <div class="settings-row">
          <div>
            <h4>已登录设备</h4>
            <p>支持多设备同时登录；查看各设备系统、浏览器、IP、位置详情并可强制登出指定设备</p>
          </div>
          <div class="account-sessions-entry">
            <span v-if="anomalousSessionsCount > 0" class="ui-pill ui-pill-warning">含异常登录</span>
            <button type="button" class="account-value-action" :disabled="busy" @click="openPanel('sessions')">
              {{ sessionsLoading ? '正在读取…' : sessionsLoaded ? `${sessions.length} 台设备` : '查看设备' }}<span aria-hidden="true">›</span>
            </button>
          </div>
        </div>
        <div class="settings-row">
          <div><h4>退出当前登录</h4><p>仅结束当前设备上的 Siderfolio 登录会话，其他设备不受影响</p></div>
          <button type="button" :disabled="busy" @click="handleLogout">退出登录</button>
        </div>
        <p class="settings-footnote">异常登录（如异地登录、新网络或新设备登录）会向您的邮箱发送包含登录详情的安全提醒，不会自动强制下线任何设备。</p>
      </section>
    </template>

    <template v-if="showAccount">
      <section class="account-preferences-group" aria-labelledby="account-details-title">
        <h3 id="account-details-title">详情</h3>
        <div class="settings-row">
          <div><h4>用户名</h4><p>你在科研工作台中的显示名称</p></div>
          <div class="account-name-value"><span>{{ displayName }}</span><button type="button" class="account-edit-button" aria-label="编辑用户名" data-tooltip="编辑用户名" :disabled="busy" @click="openPanel('profile')"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="m16 3 5 5-12 12H4v-5zM14 5l5 5" /></svg></button></div>
        </div>
        <div class="settings-row">
          <div><h4>电子邮箱</h4><p>用于登录和接收账号安全通知</p></div>
          <span class="account-detail-value">{{ identityUser?.email }}</span>
        </div>
        <div class="settings-row">
          <div><h4>账户身份</h4><p>当前账号在工作台中的权限级别</p></div>
          <span class="account-detail-value">{{ identityUser?.admin ? '管理员' : '普通用户' }}</span>
        </div>
        <div class="settings-row">
          <div><h4>多因素验证</h4><p>账号登录与敏感操作的双重验证状态</p></div>
          <span class="account-detail-value">{{ identityUser?.totp_enabled ? '已启用' : '未启用' }}</span>
        </div>
      </section>
    </template>

    <dialog ref="dialog" class="project-dialog account-preferences-dialog" :class="{ 'account-dialog-wide': panel === 'sessions' || (panel === 'mfa-enable' && (!!secret || !!recovery.length)) }" aria-labelledby="account-panel-title" @close="dialogClosed" @cancel="busy && $event.preventDefault()">
      <header class="account-dialog-heading"><h2 id="account-panel-title">{{ panelTitle }}</h2><button type="button" class="account-dialog-close" aria-label="关闭" :disabled="busy" @click="closeDialog">×</button></header>
      <StatusNotice v-if="error && dialogOpen" title="操作未完成" :message="error" @dismiss="error = ''" />

      <form v-if="panel === 'profile'" class="identity-form" @submit.prevent="saveProfile">
        <label>用户名<input v-model="usernameDraft" type="text" autocomplete="nickname" maxlength="32" required :disabled="busy" /></label>
        <p class="settings-footnote">1–32 个字符，用于工作台与个人菜单。</p>
        <div class="project-actions"><button type="button" :disabled="busy" @click="closeDialog">取消</button><button class="button-primary" :disabled="busy || !usernameDraft.trim()">{{ busy ? '正在保存…' : '保存用户名' }}</button></div>
      </form>
      <form v-else-if="panel === 'password'" class="identity-form" @submit.prevent="changePassword">
        <p>修改后所有旧会话会退出，请使用新密码重新登录。</p>
        <label>当前密码<input v-model="password" type="password" autocomplete="current-password" maxlength="128" required :disabled="busy" /></label>
        <label>新密码（至少 8 位）<input v-model="nextPassword" type="password" autocomplete="new-password" minlength="8" maxlength="128" required :disabled="busy" /></label>
        <label v-if="identityUser?.totp_enabled">验证码或恢复码<input v-model="code" type="text" autocomplete="one-time-code" maxlength="80" required :disabled="busy" /></label>
        <div class="project-actions"><button type="button" :disabled="busy" @click="closeDialog">取消</button><button class="button-primary" :disabled="busy || !password || nextPassword.length < 8 || (!!identityUser?.totp_enabled && !code.trim())">{{ busy ? '正在修改…' : '修改密码并退出' }}</button></div>
      </form>

      <template v-else-if="panel === 'mfa-enable'">
        <div v-if="recovery.length" class="account-recovery-workbench">
          <p>恢复码仅显示一次。每个恢复码只能使用一次，请离线保存；不要与他人分享。</p>
          <div class="account-recovery-grid" role="list" aria-label="一次性恢复码"><div v-for="(item, idx) in recovery" :key="item" class="account-recovery-chip" role="listitem"><span class="account-recovery-index">{{ String(idx + 1).padStart(2, '0') }}</span><code>{{ item }}</code></div></div>
          <div class="project-actions"><button type="button" @click="copyRecoveryCodes">{{ copiedRecovery ? '已复制' : '复制恢复码' }}</button><button type="button" @click="downloadRecoveryCodes">下载恢复码</button><button type="button" class="button-primary" @click="recovery = []; closeDialog()">我已保存</button></div>
        </div>
        <form v-else-if="secret" class="identity-form" @submit.prevent="confirmTotp">
          <p>在手机身份验证器中扫描二维码，再输入 6 位验证码完成启用。</p>
          <div class="account-mfa-setup">
            <div class="account-mfa-qr"><svg v-if="qrCode" :viewBox="'0 0 ' + qrCode.viewBoxSize + ' ' + qrCode.viewBoxSize" role="img" aria-label="身份验证器绑定二维码" shape-rendering="crispEdges"><rect width="100%" height="100%" fill="#fff" /><path :d="qrCode.path" fill="#183228" /></svg><p class="settings-footnote">10 分钟内有效，请勿分享</p></div>
            <div class="account-mfa-verify"><p>支持标准 TOTP 验证器，如 Microsoft Authenticator、Google Authenticator。</p><details class="account-manual-key"><summary>无法扫码？手动输入密钥</summary><code>{{ secret }}</code><p>基于时间，30 秒周期，6 位验证码。</p></details><label for="totp-confirm-code">6 位动态验证码</label><input id="totp-confirm-code" ref="confirmCodeInput" v-model="confirmCode" type="text" inputmode="numeric" pattern="[0-9]{6}" autocomplete="one-time-code" minlength="6" maxlength="6" required :disabled="busy" /></div>
          </div>
          <div class="project-actions"><button type="button" :disabled="busy" @click="cancelTotpEnroll">取消</button><button class="button-primary" :disabled="busy || !/^[0-9]{6}$/.test(confirmCode.trim())">{{ busy ? '正在验证…' : '验证并启用' }}</button></div>
        </form>
        <form v-else class="identity-form" @submit.prevent="enrollTotp"><p>先确认当前密码，再通过身份验证器扫码绑定。验证完成后开关才会开启。</p><label>当前密码<input v-model="totpPassword" type="password" autocomplete="current-password" maxlength="128" required :disabled="busy" /></label><div class="project-actions"><button type="button" :disabled="busy" @click="closeDialog">取消</button><button class="button-primary" :disabled="busy || !totpPassword">{{ busy ? '正在准备…' : '继续' }}</button></div></form>
      </template>
      <form v-else-if="panel === 'mfa-disable'" class="identity-form" @submit.prevent="disableMfa">
        <p>关闭后登录将不再要求动态验证码，现有恢复码会失效，所有旧会话会退出。</p>
        <label>当前密码<input v-model="totpPassword" type="password" autocomplete="current-password" maxlength="128" required :disabled="busy" /></label>
        <label>验证码或恢复码<input v-model="totpCurrentCode" type="text" autocomplete="one-time-code" maxlength="80" required :disabled="busy" /></label>
        <div class="project-actions"><button type="button" :disabled="busy" @click="closeDialog">取消</button><button class="button-danger" :disabled="busy || !totpPassword || !totpCurrentCode.trim() || !!identityUser?.admin">{{ busy ? '正在关闭…' : '关闭 MFA 并退出' }}</button></div>
      </form>
      <div v-else-if="panel === 'sessions'" class="account-session-detail">
        <div class="account-session-toolbar">
          <span class="small muted">
            {{ sessionsLoaded ? `共 ${sessions.length} 台设备在线${otherSessionsCount > 0 ? `（含其他 ${otherSessionsCount} 台）` : '（仅当前设备）'}` : '正在同步登录设备…' }}
          </span>
          <div v-if="otherSessionsCount > 0" class="account-session-toolbar-actions">
            <button
              type="button"
              class="button-danger"
              :disabled="busy || sessionsLoading"
              @click="openRevokeOthers"
            >
              退出其他全部设备
            </button>
          </div>
        </div>
        <p v-if="sessionsLoading && !sessions.length" role="status" class="small muted">正在读取登录设备详情…</p>
        <div v-else-if="sessionsLoaded && sessions.length" class="account-session-list">
          <article
            v-for="item in sessions"
            :key="item.id"
            class="account-device-card"
            :class="{ 'is-current': item.current, 'is-anomalous': item.is_anomalous }"
          >
            <div class="account-device-head">
              <span class="account-device-icon" aria-hidden="true">
                <svg v-if="item.device_type === 'mobile'" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round">
                  <rect x="7" y="2.5" width="10" height="19" rx="2.2" />
                  <path d="M11 18.5h2" />
                </svg>
                <svg v-else-if="item.device_type === 'tablet'" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round">
                  <rect x="4" y="3" width="16" height="18" rx="2.2" />
                  <path d="M11 18h2" />
                </svg>
                <svg v-else viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round">
                  <rect x="3" y="4" width="18" height="12" rx="2" />
                  <path d="M8 20h8M12 16v4" />
                </svg>
              </span>
              <div class="account-device-title-wrap">
                <h4>{{ deviceTitle(item) }}</h4>
                <div class="ui-pill-list">
                  <span v-if="item.current" class="ui-pill ui-pill-success">当前设备</span>
                  <span class="ui-pill ui-pill-neutral">{{ deviceTypeLabel(item) }}</span>
                  <span v-if="item.mfa_verified" class="ui-pill ui-pill-accent">已通过 MFA</span>
                  <span
                    v-for="reason in item.anomaly_reasons || []"
                    :key="reason"
                    class="ui-pill ui-pill-warning"
                  >
                    {{ anomalyTagLabel(reason) }}
                  </span>
                </div>
              </div>
              <span v-if="item.current" class="ui-pill ui-pill-success account-device-status">当前使用</span>
              <button
                v-else
                type="button"
                class="button-danger account-device-revoke"
                :disabled="busy || sessionsLoading"
                :aria-label="`强制退出 ${deviceTitle(item)}`"
                @click="selectSession(item)"
              >
                强制退出
              </button>
            </div>
            <dl class="account-device-meta">
              <div>
                <dt>系统与浏览器</dt>
                <dd>{{ systemBrowserSummary(item) }}</dd>
              </div>
              <div>
                <dt>登录位置与 IP</dt>
                <dd>
                  <span>{{ item.login_location || '位置未记录' }}</span>
                  <code v-if="item.login_ip" class="account-device-ip">{{ item.login_ip }}</code>
                </dd>
              </div>
              <div v-if="hasNetworkChanged(item)">
                <dt>最近活动网络</dt>
                <dd>
                  <span>{{ item.last_location || '位置未记录' }}</span>
                  <code v-if="item.last_ip" class="account-device-ip">{{ item.last_ip }}</code>
                </dd>
              </div>
              <div>
                <dt>登录时间（北京时间）</dt>
                <dd class="tabular">{{ formatBeijing(item.created_at) }}</dd>
              </div>
              <div>
                <dt>最近活动</dt>
                <dd class="tabular">{{ formatRelative(item.last_seen) }} · {{ formatBeijing(item.last_seen) }}</dd>
              </div>
            </dl>
            <details v-if="item.user_agent" class="account-device-ua">
              <summary>原始浏览器标识 (User-Agent)</summary>
              <code>{{ item.user_agent }}</code>
            </details>
          </article>
        </div>
        <p v-else-if="sessionsLoaded">没有读取到有效登录设备。</p>
        <p class="settings-footnote">支持多设备同时登录；当前设备不能在此强退，其他设备可单独或一键强制退出。检测到异地、新网络或新设备登录时会发邮件告知，不会自动强制下线。</p>
      </div>
      <form v-else-if="panel === 'revoke'" class="identity-form" @submit.prevent="revokeSelectedSession">
        <p>仅强制退出所选设备，当前设备及其他已登录设备保持在线。</p>
        <div v-if="selectedSession" class="account-revoke-preview">
          <strong>{{ deviceTitle(selectedSession) }}</strong>
          <p>系统与浏览器：{{ systemBrowserSummary(selectedSession) }}</p>
          <p>登录位置与 IP：{{ selectedSession.login_location || '位置未记录' }}<template v-if="selectedSession.login_ip"> · <code>{{ selectedSession.login_ip }}</code></template></p>
          <p>登录时间：{{ formatBeijing(selectedSession.created_at) }}（北京时间）</p>
        </div>
        <label>当前密码<input v-model="revokePassword" type="password" autocomplete="current-password" maxlength="128" required :disabled="busy" /></label>
        <label v-if="identityUser?.totp_enabled">验证码或恢复码<input v-model="revokeCode" type="text" autocomplete="one-time-code" maxlength="80" required :disabled="busy" /></label>
        <div class="project-actions"><button type="button" :disabled="busy" @click="panel = 'sessions'; selectedSession = null; revokePassword = ''; revokeCode = ''; clearFeedback()">取消</button><button class="button-danger" :disabled="busy || !selectedSession || !!selectedSession.current || !revokePassword || (!!identityUser?.totp_enabled && !revokeCode.trim())">{{ busy ? '正在退出…' : '确认强制退出' }}</button></div>
      </form>
      <form v-else-if="panel === 'revoke-others'" class="identity-form" @submit.prevent="revokeOtherSessions">
        <p>将强制退出除当前设备外的其余 <strong>{{ otherSessionsCount }}</strong> 台已登录设备，当前设备保持登录。</p>
        <label>当前密码<input v-model="revokePassword" type="password" autocomplete="current-password" maxlength="128" required :disabled="busy" /></label>
        <label v-if="identityUser?.totp_enabled">验证码或恢复码<input v-model="revokeCode" type="text" autocomplete="one-time-code" maxlength="80" required :disabled="busy" /></label>
        <div class="project-actions"><button type="button" :disabled="busy" @click="panel = 'sessions'; revokePassword = ''; revokeCode = ''; clearFeedback()">取消</button><button class="button-danger" :disabled="busy || otherSessionsCount === 0 || !revokePassword || (!!identityUser?.totp_enabled && !revokeCode.trim())">{{ busy ? '正在退出…' : `退出其他 ${otherSessionsCount} 台设备` }}</button></div>
      </form>
    </dialog>
  </div>
</template>
