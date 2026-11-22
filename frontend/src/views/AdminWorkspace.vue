<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import SettingsSelect from '../components/SettingsSelect.vue'
import { identityRequest, identityUser } from '../identity-state'

type User = {
  id: string
  email: string
  active: boolean
  disabled?: boolean
  admin: boolean
  created_at?: string
  last_login?: string | null
}
type Mail = {
  id: string
  state: string
  purpose: string
  attempts: number
  error_class: string | null
}
type Audit = {
  id: number
  actor: string | null
  target: string | null
  event: string
  result: string
  reason: string | null
  created_at: string
}
type Overview = {
  users: { total: number; pending: number; disabled: number; administrators: number }
  mail_configured: boolean
  registration_available: boolean
  mail_hour_limit: number
  registration_limit: number
}
type AdminTab = 'users' | 'mail' | 'audit'
type UserFilter = 'all' | 'active' | 'pending' | 'disabled' | 'admin'

const tab = ref<AdminTab>('users')
const page = ref(1)
const overview = ref<Overview | null>(null)
const users = ref<User[]>([])
const mails = ref<Mail[]>([])
const events = ref<Audit[]>([])
const busy = ref(false)
const error = ref('')
const message = ref('')
const password = ref('')
const code = ref('')
const reauthOpen = ref(false)
const reauthUntil = ref(0)
const nowTick = ref(Date.now())
const searchQuery = ref('')
const userFilter = ref<UserFilter>('all')

const dialog = ref<HTMLDialogElement | null>(null)
const target = ref<User | null>(null)
const action = ref('disable')
const reason = ref('account_review')

const mailDialog = ref<HTMLDialogElement | null>(null)
const retryTarget = ref<Mail | null>(null)

let countdownTimer: number | null = null

const labels: Record<string, string> = {
  enable: '启用账号',
  disable: '禁用账号',
  grant_admin: '授予管理员权限',
  revoke_admin: '撤销管理员权限',
}

const reasonOptions = [
  { value: 'account_review', label: '账号复核', description: '日常合规或身份核查调整' },
  { value: 'role_assignment', label: '权限安排', description: '管理员职责分配或变更' },
  { value: 'user_request', label: '用户申请', description: '响应本人提交的账号变更请求' },
  { value: 'security_incident', label: '安全事件', description: '异常登录、凭据泄露或风控处置' },
] as const

const tabItems: readonly { id: AdminTab; label: string }[] = [
  { id: 'users', label: '用户' },
  { id: 'mail', label: '邮件状态' },
  { id: 'audit', label: '审计日志' },
]

const userFilterItems: readonly { id: UserFilter; label: string }[] = [
  { id: 'all', label: '全部' },
  { id: 'active', label: '已激活' },
  { id: 'pending', label: '待激活' },
  { id: 'disabled', label: '已禁用' },
  { id: 'admin', label: '管理员' },
]

const reauthRemainingSec = computed(() => Math.max(0, Math.ceil((reauthUntil.value - nowTick.value) / 1000)))
const reauthRemainingLabel = computed(() => {
  const sec = reauthRemainingSec.value
  const m = Math.floor(sec / 60)
  const s = sec % 60
  return `${m}:${String(s).padStart(2, '0')}`
})

const quotaPercent = computed(() => {
  if (!overview.value || !overview.value.registration_limit) return 0
  return Math.min(100, (overview.value.users.total / overview.value.registration_limit) * 100)
})

const filteredUsers = computed(() => {
  const q = searchQuery.value.trim().toLowerCase()
  return users.value.filter(u => {
    if (userFilter.value === 'active' && (u.disabled || !u.active)) return false
    if (userFilter.value === 'pending' && (u.disabled || u.active)) return false
    if (userFilter.value === 'disabled' && !u.disabled) return false
    if (userFilter.value === 'admin' && !u.admin) return false
    if (q && !`${u.email} ${u.id}`.toLowerCase().includes(q)) return false
    return true
  })
})

const filteredMails = computed(() => {
  const q = searchQuery.value.trim().toLowerCase()
  if (!q) return mails.value
  return mails.value.filter(m => `${m.purpose} ${m.state} ${m.error_class || ''} ${m.id}`.toLowerCase().includes(q))
})

const filteredEvents = computed(() => {
  const q = searchQuery.value.trim().toLowerCase()
  if (!q) return events.value
  return events.value.filter(ev => `${ev.event} ${ev.result} ${ev.target || ''} ${ev.reason || ''}`.toLowerCase().includes(q))
})

const visibleCount = computed(() => {
  if (tab.value === 'users') return filteredUsers.value.length
  if (tab.value === 'mail') return filteredMails.value.length
  return filteredEvents.value.length
})

const hasMore = computed(() => {
  if (tab.value === 'users') return users.value.length >= 30 && (!overview.value || page.value * 30 < overview.value.users.total)
  if (tab.value === 'mail') return mails.value.length >= 30
  return events.value.length >= 50
})

const showPagination = computed(() => page.value > 1 || hasMore.value)

function userInitial(email: string): string {
  const ch = email.trim().charAt(0)
  return ch ? ch.toUpperCase() : 'U'
}

function formatDateTime(value?: string | null): string {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '—'
  return date.toLocaleString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function formatDate(value?: string | null): string {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '—'
  return date.toLocaleDateString('zh-CN', { year: 'numeric', month: '2-digit', day: '2-digit' })
}

function mailPurposeLabel(purpose: string): string {
  const map: Record<string, string> = {
    activate: '账号激活',
    activation: '账号激活',
    reset_password: '密码重置',
    password_reset: '密码重置',
    verify: '邮箱验证',
    security_alert: '安全通知',
  }
  return map[purpose] || purpose
}

function mailStateTone(state: string): string {
  if (state === 'submitted' || state === 'sent') return 'ui-pill-success'
  if (state === 'failed') return 'ui-pill-danger'
  return 'ui-pill-warning'
}

function auditResultTone(result: string): string {
  if (result === 'ok' || result === 'accepted') return 'ui-pill-success'
  if (result === 'denied' || result === 'failed' || result === 'error') return 'ui-pill-danger'
  return 'ui-pill-neutral'
}

async function load() {
  error.value = ''
  busy.value = true
  try {
    overview.value = await identityRequest<Overview>('admin/overview')
    if (tab.value === 'users') users.value = await identityRequest<User[]>('admin/users?page=' + page.value)
    if (tab.value === 'mail') mails.value = await identityRequest<Mail[]>('admin/mail?page=' + page.value)
    if (tab.value === 'audit') events.value = await identityRequest<Audit[]>('admin/audit?page=' + page.value)
  } catch (e) {
    error.value = e instanceof Error ? e.message : '管理状态读取失败。'
  } finally {
    busy.value = false
  }
}

function changeTab(value: AdminTab) {
  tab.value = value
  page.value = 1
  searchQuery.value = ''
  userFilter.value = 'all'
  void load()
}

function open(user: User, kind: string) {
  target.value = user
  action.value = kind
  reason.value = kind.includes('admin') ? 'role_assignment' : 'account_review'
  dialog.value?.showModal()
}

function closeActionDialog() {
  dialog.value?.close()
}

async function confirm() {
  if (!target.value || busy.value) return
  busy.value = true
  error.value = ''
  try {
    const result = await identityRequest('admin/users/' + target.value.id, 'PATCH', {
      action: action.value,
      reason: reason.value,
    })
    message.value = result.message
    dialog.value?.close()
    await load()
  } catch (e) {
    error.value = e instanceof Error ? e.message : '操作未完成。'
  } finally {
    busy.value = false
  }
}

async function authenticate() {
  busy.value = true
  error.value = ''
  try {
    message.value = (
      await identityRequest('auth/reauthenticate', 'POST', {
        password: password.value,
        code: code.value,
      })
    ).message
    password.value = ''
    code.value = ''
    reauthUntil.value = Date.now() + 5 * 60 * 1000
    nowTick.value = Date.now()
    reauthOpen.value = false
  } catch (e) {
    error.value = e instanceof Error ? e.message : '重新认证失败。'
  } finally {
    busy.value = false
  }
}

function openRetryDialog(mail: Mail) {
  retryTarget.value = mail
  mailDialog.value?.showModal()
}

async function confirmRetryMail() {
  if (!retryTarget.value || busy.value) return
  busy.value = true
  error.value = ''
  try {
    message.value = (
      await identityRequest('admin/mail/' + retryTarget.value.id + '/retry', 'POST', {})
    ).message
    mailDialog.value?.close()
    retryTarget.value = null
    await load()
  } catch (e) {
    error.value = e instanceof Error ? e.message : '重试未完成。'
  } finally {
    busy.value = false
  }
}

function onReauthToggle(event: Event) {
  reauthOpen.value = (event.target as HTMLDetailsElement).open
}

onMounted(() => {
  void load()
  countdownTimer = window.setInterval(() => {
    if (reauthUntil.value > Date.now()) {
      nowTick.value = Date.now()
    }
  }, 1000)
})

onBeforeUnmount(() => {
  if (countdownTimer !== null) window.clearInterval(countdownTimer)
})
</script>

<template>
  <main class="workspace-panes primary-workspace admin-workspace">
    <header class="topbar workspace-header">
      <div class="workspace-header-main">
        <div class="admin-topbar-left">
          <RouterLink to="/" class="brand">
            <span class="brand-mark" aria-hidden="true">
              <svg viewBox="0 0 24 24" fill="none">
                <ellipse cx="12" cy="12" rx="9.5" ry="4.2" transform="rotate(-28 12 12)" stroke="currentColor" stroke-opacity="0.48" stroke-width="1.4" />
                <path d="M12 3.2L13.85 10.15L20.8 12L13.85 13.85L12 20.8L10.15 13.85L3.2 12L10.15 10.15L12 3.2Z" fill="currentColor" />
              </svg>
            </span>
            <b>AstroAgent</b>
          </RouterLink>
          <span class="admin-topbar-badge">
            <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3 5 6v6c0 4.5 3 7.7 7 9 4-1.3 7-4.5 7-9V6l-7-3Z" /><path d="m9.5 12 1.8 1.8L15 10" /></svg>
            管理控制台
          </span>
        </div>

        <nav class="workspace-global-nav" aria-label="控制台导航">
          <RouterLink to="/settings">本机设置</RouterLink>
          <RouterLink to="/">返回工作台</RouterLink>
        </nav>
      </div>
    </header>

    <section class="admin-shell-panel" aria-labelledby="admin-page-heading">
      <header class="workspace-pane-header admin-pane-header">
        <div class="admin-header-title-group">
          <span class="admin-header-icon" aria-hidden="true">
            <svg viewBox="0 0 24 24"><path d="M12 3 5 6v6c0 4.5 3 7.7 7 9 4-1.3 7-4.5 7-9V6l-7-3Z" /><path d="M12 8v4" /><path d="M12 16h.01" /></svg>
          </span>
          <div class="admin-header-copy">
            <div class="admin-header-title-row">
              <h1 id="admin-page-heading">账号与服务状态</h1>
              <span class="ui-pill ui-pill-neutral">隐私隔离 · 不访问科研内容</span>
            </div>
            <p class="admin-header-subtitle">仅管理身份状态、邮件投递与安全审计事件，所有敏感变更均需重新认证并记录审计。</p>
          </div>
        </div>

        <div v-if="overview" class="ui-pill-list" aria-label="系统配额策略">
          <span class="ui-pill" :class="overview.registration_available ? 'ui-pill-success' : 'ui-pill-warning'">
            <span class="ui-dot" aria-hidden="true" />
            {{ overview.registration_available ? '注册开放' : '注册已达上限' }}
          </span>
          <span class="ui-pill ui-pill-mono">配额 {{ overview.users.total }} / {{ overview.registration_limit }}</span>
          <span class="ui-pill ui-pill-mono">发信上限 {{ overview.mail_hour_limit }}/h</span>
        </div>
      </header>

      <div class="admin-scroll">
        <div class="admin-reading">
          <div v-if="error" class="notice danger admin-banner" role="alert">
            <span>{{ error }}</span>
            <button type="button" class="admin-banner-close" aria-label="关闭错误提示" @click="error = ''">×</button>
          </div>
          <div v-if="message" class="notice success admin-banner" role="status">
            <span>{{ message }}</span>
            <button type="button" class="admin-banner-close" aria-label="关闭状态提示" @click="message = ''">×</button>
          </div>

          <section v-if="overview" class="admin-kpi-grid" aria-label="核心运行指标">
            <article class="admin-kpi-card">
              <div class="admin-kpi-top">
                <span class="admin-kpi-label">账号总数</span>
                <span class="admin-kpi-icon is-accent" aria-hidden="true">
                  <svg viewBox="0 0 24 24"><path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2" /><circle cx="9" cy="7" r="4" /><path d="M22 21v-2a4 4 0 0 0-3-3.87" /><path d="M16 3.13a4 4 0 0 1 0 7.75" /></svg>
                </span>
              </div>
              <b class="admin-kpi-value">{{ overview.users.total }}</b>
              <div class="admin-kpi-foot">
                <span class="admin-kpi-sub">含 {{ overview.users.administrators }} 位管理员 · 占配额 {{ quotaPercent.toFixed(1) }}%</span>
                <div class="ui-progress" aria-hidden="true">
                  <div class="ui-progress-fill" :style="{ width: `${Math.max(quotaPercent, overview.users.total > 0 ? 2 : 0)}%` }" />
                </div>
              </div>
            </article>

            <article class="admin-kpi-card" :class="{ 'is-warn': overview.users.pending > 0 }">
              <div class="admin-kpi-top">
                <span class="admin-kpi-label">待激活</span>
                <span class="admin-kpi-icon" :class="overview.users.pending > 0 ? 'is-warning' : 'is-success'" aria-hidden="true">
                  <svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 2" /></svg>
                </span>
              </div>
              <b class="admin-kpi-value">{{ overview.users.pending }}</b>
              <div class="admin-kpi-foot">
                <span class="ui-pill" :class="overview.users.pending > 0 ? 'ui-pill-warning' : 'ui-pill-success'">
                  <span class="ui-dot" aria-hidden="true" />
                  {{ overview.users.pending > 0 ? '等待邮箱激活' : '已全部激活' }}
                </span>
              </div>
            </article>

            <article class="admin-kpi-card" :class="{ 'is-danger': overview.users.disabled > 0 }">
              <div class="admin-kpi-top">
                <span class="admin-kpi-label">已禁用</span>
                <span class="admin-kpi-icon" :class="overview.users.disabled > 0 ? 'is-danger' : 'is-neutral'" aria-hidden="true">
                  <svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="9" /><path d="m5.6 5.6 12.8 12.8" /></svg>
                </span>
              </div>
              <b class="admin-kpi-value">{{ overview.users.disabled }}</b>
              <div class="admin-kpi-foot">
                <span class="ui-pill" :class="overview.users.disabled > 0 ? 'ui-pill-danger' : 'ui-pill-neutral'">
                  <span class="ui-dot" aria-hidden="true" />
                  {{ overview.users.disabled > 0 ? '已限制访问' : '无受限账号' }}
                </span>
              </div>
            </article>

            <article class="admin-kpi-card" :class="overview.mail_configured ? 'is-ok' : 'is-warn'">
              <div class="admin-kpi-top">
                <span class="admin-kpi-label">邮件服务</span>
                <span class="admin-kpi-icon" :class="overview.mail_configured ? 'is-success' : 'is-warning'" aria-hidden="true">
                  <svg viewBox="0 0 24 24"><rect x="3" y="5" width="18" height="14" rx="2.5" /><path d="m4 7 8 6 8-6" /></svg>
                </span>
              </div>
              <b class="admin-kpi-value">{{ overview.mail_configured ? '已配置' : '未配置' }}</b>
              <div class="admin-kpi-foot">
                <span class="ui-pill" :class="overview.mail_configured ? 'ui-pill-success' : 'ui-pill-warning'">
                  <span class="ui-dot" aria-hidden="true" />
                  {{ overview.mail_configured ? `发信通道就绪 · ${overview.mail_hour_limit}/h` : '需检查服务端邮件配置' }}
                </span>
              </div>
            </article>
          </section>

          <details class="admin-reauth-card" :open="reauthOpen" @toggle="onReauthToggle">
            <summary class="admin-reauth-summary">
              <div class="admin-reauth-left">
                <span class="admin-reauth-icon" :class="{ 'is-unlocked': reauthRemainingSec > 0 }" aria-hidden="true">
                  <svg viewBox="0 0 24 24"><rect x="4" y="11" width="16" height="10" rx="2" /><path d="M8 11V7a4 4 0 0 1 8 0v4" /></svg>
                </span>
                <div class="admin-reauth-copy">
                  <span class="admin-reauth-title">敏感操作重新认证（有效期5分钟）</span>
                  <small>禁用/启用账号、变更管理员权限前需确认当前管理员身份</small>
                </div>
              </div>
              <div class="admin-reauth-right">
                <span class="ui-pill" :class="reauthRemainingSec > 0 ? 'ui-pill-success' : 'ui-pill-neutral'">
                  <span class="ui-dot" aria-hidden="true" />
                  {{ reauthRemainingSec > 0 ? `已验证 · 剩余 ${reauthRemainingLabel}` : '点击展开验证' }}
                </span>
                <svg class="admin-reauth-chevron" viewBox="0 0 24 24" aria-hidden="true"><path d="m6 9 6 6 6-6" /></svg>
              </div>
            </summary>

            <form class="admin-reauth-form" @submit.prevent="authenticate">
              <label class="admin-reauth-field">
                <span>当前密码</span>
                <input
                  v-model="password"
                  type="password"
                  autocomplete="current-password"
                  placeholder="输入管理员密码"
                  required
                  maxlength="128"
                />
              </label>
              <label class="admin-reauth-field">
                <span>验证码或恢复码</span>
                <input
                  v-model="code"
                  autocomplete="one-time-code"
                  placeholder="6 位动态口令或恢复码"
                  required
                  maxlength="80"
                />
              </label>
              <button type="submit" :disabled="busy" class="button-primary admin-reauth-submit">确认身份</button>
            </form>
          </details>

          <section class="ui-card admin-ops-card" aria-label="管理明细">
            <div class="admin-ops-toolbar">
              <nav class="ui-segmented" aria-label="管理分类">
                <button
                  v-for="item in tabItems"
                  :key="item.id"
                  type="button"
                  :aria-pressed="tab === item.id"
                  :disabled="busy"
                  @click="changeTab(item.id)"
                >
                  <svg v-if="item.id === 'users'" class="admin-tab-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2" /><circle cx="9" cy="7" r="4" /></svg>
                  <svg v-else-if="item.id === 'mail'" class="admin-tab-icon" viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="5" width="18" height="14" rx="2.5" /><path d="m4 7 8 6 8-6" /></svg>
                  <svg v-else class="admin-tab-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9Z" /><path d="M14 3v6h6" /><path d="M8 13h8" /><path d="M8 17h5" /></svg>
                  {{ item.label }}
                </button>
              </nav>

              <div class="admin-ops-controls">
                <label class="admin-search-box">
                  <svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="11" cy="11" r="7" /><path d="m20 20-3.5-3.5" /></svg>
                  <input
                    v-model="searchQuery"
                    type="search"
                    :placeholder="tab === 'users' ? '筛选邮箱或账号 ID…' : tab === 'mail' ? '筛选邮件用途或状态…' : '筛选事件、结果或目标…'"
                    aria-label="筛选当前列表"
                  />
                </label>
                <span class="ui-pill ui-pill-neutral">当前页 {{ visibleCount }} 条</span>
              </div>
            </div>

            <div v-if="tab === 'users'" class="admin-filter-row" role="group" aria-label="按账号状态筛选">
              <button
                v-for="f in userFilterItems"
                :key="f.id"
                type="button"
                class="admin-filter-pill"
                :aria-pressed="userFilter === f.id"
                @click="userFilter = f.id"
              >
                {{ f.label }}
              </button>
            </div>

            <div class="admin-table-wrap">
              <table v-if="tab === 'users'" class="admin-table">
                <thead>
                  <tr>
                    <th scope="col">邮箱与标识</th>
                    <th scope="col">状态</th>
                    <th scope="col">角色</th>
                    <th scope="col">活跃记录</th>
                    <th scope="col" class="admin-col-actions">操作</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-if="!filteredUsers.length">
                    <td colspan="5" class="admin-empty-row">
                      {{ users.length ? '当前筛选条件下没有匹配的账号' : '暂无账号记录' }}
                    </td>
                  </tr>
                  <tr v-for="user in filteredUsers" :key="user.id">
                    <td>
                      <div class="admin-user-cell">
                        <span class="admin-user-avatar" :class="{ 'is-admin': user.admin, 'is-disabled': user.disabled }" aria-hidden="true">
                          {{ userInitial(user.email) }}
                        </span>
                        <div class="admin-user-meta">
                          <strong class="admin-user-email">{{ user.email }}</strong>
                          <small class="admin-identifier">{{ user.id }}</small>
                        </div>
                      </div>
                    </td>
                    <td>
                      <span
                        class="ui-pill"
                        :class="user.disabled ? 'ui-pill-danger' : user.active ? 'ui-pill-success' : 'ui-pill-warning'"
                      >
                        <span class="ui-dot" aria-hidden="true" />
                        {{ user.disabled ? '已禁用' : user.active ? '已激活' : '待激活' }}
                      </span>
                    </td>
                    <td>
                      <span class="ui-pill" :class="user.admin ? 'ui-pill-accent' : 'ui-pill-neutral'">
                        {{ user.admin ? '管理员' : '用户' }}
                      </span>
                    </td>
                    <td>
                      <div class="admin-activity-cell">
                        <span>{{ user.last_login ? `最近登录 ${formatDateTime(user.last_login)}` : '暂无登录记录' }}</span>
                        <small v-if="user.created_at">创建于 {{ formatDate(user.created_at) }}</small>
                      </div>
                    </td>
                    <td class="admin-col-actions">
                      <span v-if="user.id === identityUser?.id" class="ui-pill ui-pill-accent">当前账号</span>
                      <div v-else class="admin-row-actions">
                        <button
                          type="button"
                          :class="user.disabled ? '' : 'admin-btn-subtle-danger'"
                          :disabled="busy"
                          @click="open(user, user.disabled ? 'enable' : 'disable')"
                        >
                          {{ user.disabled ? '启用' : '禁用' }}
                        </button>
                        <button
                          type="button"
                          :disabled="busy || !user.active || user.disabled"
                          @click="open(user, user.admin ? 'revoke_admin' : 'grant_admin')"
                        >
                          {{ user.admin ? '撤销管理员' : '授予管理员' }}
                        </button>
                      </div>
                    </td>
                  </tr>
                </tbody>
              </table>

              <table v-else-if="tab === 'mail'" class="admin-table">
                <thead>
                  <tr>
                    <th scope="col">用途</th>
                    <th scope="col">提交状态</th>
                    <th scope="col">尝试</th>
                    <th scope="col">诊断类别</th>
                    <th scope="col" class="admin-col-actions">操作</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-if="!filteredMails.length">
                    <td colspan="5" class="admin-empty-row">
                      {{ mails.length ? '当前筛选条件下没有匹配的邮件记录' : '暂无邮件发送队列记录' }}
                    </td>
                  </tr>
                  <tr v-for="mail in filteredMails" :key="mail.id">
                    <td>
                      <div class="admin-user-meta">
                        <strong>{{ mailPurposeLabel(mail.purpose) }}</strong>
                        <small v-if="mailPurposeLabel(mail.purpose) !== mail.purpose" class="admin-identifier">{{ mail.purpose }}</small>
                      </div>
                    </td>
                    <td>
                      <span class="ui-pill" :class="mailStateTone(mail.state)">
                        <span class="ui-dot" aria-hidden="true" />
                        {{ mail.state }}
                      </span>
                    </td>
                    <td><span class="ui-pill ui-pill-mono">{{ mail.attempts }} 次</span></td>
                    <td>
                      <code v-if="mail.error_class" class="admin-event-code">{{ mail.error_class }}</code>
                      <span v-else class="muted">—</span>
                    </td>
                    <td class="admin-col-actions">
                      <button v-if="mail.state === 'failed'" type="button" :disabled="busy" @click="openRetryDialog(mail)">重试</button>
                      <span v-else class="muted">—</span>
                    </td>
                  </tr>
                </tbody>
              </table>

              <table v-else class="admin-table">
                <thead>
                  <tr>
                    <th scope="col">时间</th>
                    <th scope="col">事件</th>
                    <th scope="col">结果</th>
                    <th scope="col">目标</th>
                    <th scope="col">备注</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-if="!filteredEvents.length">
                    <td colspan="5" class="admin-empty-row">
                      {{ events.length ? '当前筛选条件下没有匹配的审计记录' : '暂无安全审计日志' }}
                    </td>
                  </tr>
                  <tr v-for="event in filteredEvents" :key="event.id">
                    <td class="admin-time-cell">{{ formatDateTime(event.created_at) }}</td>
                    <td><code class="admin-event-code">{{ event.event }}</code></td>
                    <td>
                      <span class="ui-pill" :class="auditResultTone(event.result)">
                        <span class="ui-dot" aria-hidden="true" />
                        {{ event.result }}
                      </span>
                    </td>
                    <td><span class="admin-identifier">{{ event.target || '—' }}</span></td>
                    <td>
                      <span v-if="event.reason" class="ui-pill ui-pill-neutral">{{ event.reason }}</span>
                      <span v-else class="muted">—</span>
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>

            <div v-if="showPagination" class="admin-pagination">
              <button type="button" :disabled="busy || page <= 1" @click="page--; void load()">上一页</button>
              <span class="admin-page-indicator">第 {{ page }} 页</span>
              <button type="button" :disabled="busy || !hasMore" @click="page++; void load()">下一页</button>
            </div>
          </section>
        </div>
      </div>
    </section>

    <dialog ref="dialog" class="project-dialog admin-action-dialog">
      <form class="admin-dialog-form" @submit.prevent="confirm">
        <div class="dialog-header">
          <div class="dialog-header-copy">
            <h2>{{ labels[action] || action }}</h2>
            <p class="dialog-subtitle">此操作会写入安全审计日志，并立即撤销目标账号的旧登录会话。</p>
          </div>
          <button type="button" class="dialog-close" aria-label="关闭弹窗" :disabled="busy" @click="closeActionDialog">
            <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 6l12 12M18 6 6 18" /></svg>
          </button>
        </div>

        <div v-if="target" class="admin-dialog-target">
          <span class="admin-user-avatar" :class="{ 'is-admin': target.admin }" aria-hidden="true">{{ userInitial(target.email) }}</span>
          <div class="admin-user-meta">
            <strong>{{ target.email }}</strong>
            <small class="admin-identifier">{{ target.id }}</small>
          </div>
        </div>

        <div class="admin-dialog-field">
          <span class="admin-dialog-label">操作原因</span>
          <SettingsSelect v-model="reason" label="操作原因" :options="reasonOptions" :disabled="busy" />
        </div>

        <p v-if="error" class="notice danger" role="alert">{{ error }}</p>

        <div class="project-actions">
          <button type="button" :disabled="busy" @click="closeActionDialog">取消</button>
          <button type="submit" class="button-primary" :disabled="busy">确认操作</button>
        </div>
      </form>
    </dialog>

    <dialog ref="mailDialog" class="project-dialog admin-action-dialog">
      <form class="admin-dialog-form" @submit.prevent="confirmRetryMail">
        <div class="dialog-header">
          <div class="dialog-header-copy">
            <h2>重试投递邮件</h2>
            <p class="dialog-subtitle">重新提交给邮件服务商不代表用户已实际收到，请结合诊断类别核对。</p>
          </div>
          <button type="button" class="dialog-close" aria-label="关闭弹窗" :disabled="busy" @click="mailDialog?.close()">
            <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 6l12 12M18 6 6 18" /></svg>
          </button>
        </div>

        <div v-if="retryTarget" class="admin-dialog-target">
          <div class="admin-user-meta">
            <strong>{{ mailPurposeLabel(retryTarget.purpose) }}</strong>
            <small class="admin-identifier">已尝试 {{ retryTarget.attempts }} 次 · {{ retryTarget.error_class || '未知错误' }}</small>
          </div>
        </div>

        <div class="project-actions">
          <button type="button" :disabled="busy" @click="mailDialog?.close()">取消</button>
          <button type="submit" class="button-primary" :disabled="busy">确认重试</button>
        </div>
      </form>
    </dialog>
  </main>
</template>
