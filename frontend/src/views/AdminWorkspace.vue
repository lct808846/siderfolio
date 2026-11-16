<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { identityRequest, identityUser } from '../identity-state'
type User = { id: string; email: string; active: boolean; disabled: boolean; admin: boolean; created_at: string; last_login: string | null }
type Mail = { id: string; state: string; purpose: string; attempts: number; error_class: string | null }
type Audit = { id: number; actor: string | null; target: string | null; event: string; result: string; reason: string | null; created_at: string }
type Overview = { users: { total: number; pending: number; disabled: number; administrators: number }; mail_configured: boolean; registration_available: boolean; mail_hour_limit: number; registration_limit: number }
const tab = ref('users'), page = ref(1), overview = ref<Overview | null>(null), users = ref<User[]>([]), mails = ref<Mail[]>([]), events = ref<Audit[]>([])
const busy = ref(false), error = ref(''), message = ref(''), password = ref(''), code = ref('')
const dialog = ref<HTMLDialogElement | null>(null), target = ref<User | null>(null), action = ref('disable'), reason = ref('account_review')
const labels: Record<string, string> = { enable: '启用', disable: '禁用', grant_admin: '授予管理员', revoke_admin: '撤销管理员' }
const hasMore = computed(() => {
  if (tab.value === 'users') return users.value.length >= 30 && (!overview.value || page.value * 30 < overview.value.users.total)
  if (tab.value === 'mail') return mails.value.length >= 30
  return events.value.length >= 50
})
const showPagination = computed(() => page.value > 1 || hasMore.value)
async function load() {
  error.value = ''; busy.value = true
  try {
    overview.value = await identityRequest<Overview>('admin/overview')
    if (tab.value === 'users') users.value = await identityRequest<User[]>('admin/users?page=' + page.value)
    if (tab.value === 'mail') mails.value = await identityRequest<Mail[]>('admin/mail?page=' + page.value)
    if (tab.value === 'audit') events.value = await identityRequest<Audit[]>('admin/audit?page=' + page.value)
  } catch (e) { error.value = e instanceof Error ? e.message : '管理状态读取失败。' }
  finally { busy.value = false }
}
function changeTab(value: string) { tab.value = value; page.value = 1; void load() }
function open(user: User, kind: string) { target.value = user; action.value = kind; reason.value = kind.includes('admin') ? 'role_assignment' : 'account_review'; dialog.value?.showModal() }
async function confirm() {
  if (!target.value || busy.value) return
  busy.value = true; error.value = ''
  try {
    const result = await identityRequest('admin/users/' + target.value.id, 'PATCH', { action: action.value, reason: reason.value })
    message.value = result.message; dialog.value?.close(); await load()
  } catch (e) { error.value = e instanceof Error ? e.message : '操作未完成。' }
  finally { busy.value = false }
}
async function authenticate() {
  busy.value = true; error.value = ''
  try { message.value = (await identityRequest('auth/reauthenticate', 'POST', { password: password.value, code: code.value })).message; password.value = ''; code.value = '' }
  catch (e) { error.value = e instanceof Error ? e.message : '重新认证失败。' }
  finally { busy.value = false }
}
async function retry(mail: Mail) {
  if (!window.confirm('确认重试这封邮件？提交服务商不代表用户已收到。')) return
  busy.value = true
  try { message.value = (await identityRequest('admin/mail/' + mail.id + '/retry', 'POST', {})).message; await load() }
  catch (e) { error.value = e instanceof Error ? e.message : '重试未完成。' }
  finally { busy.value = false }
}
onMounted(load)
</script>
<template>
  <main class="account-screen admin-screen">
    <header class="identity-page-header">
      <div class="account-header-brand">
        <RouterLink to="/" class="identity-brand">
          <span class="identity-brand-mark" aria-hidden="true">
            <svg viewBox="0 0 24 24" fill="none">
              <ellipse cx="12" cy="12" rx="9.5" ry="4.2" transform="rotate(-28 12 12)" stroke="currentColor" stroke-opacity="0.48" stroke-width="1.4" />
              <path d="M12 3.2L13.85 10.15L20.8 12L13.85 13.85L12 20.8L10.15 13.85L3.2 12L10.15 10.15L12 3.2Z" fill="currentColor" />
            </svg>
          </span>
          <span>AstroAgent</span>
        </RouterLink>
        <span class="account-header-divider" aria-hidden="true"></span>
        <span class="account-header-title">管理控制台</span>
      </div>
      <div class="identity-actions">
        <RouterLink to="/settings" class="account-nav-pill">本机设置</RouterLink>
        <RouterLink to="/" class="account-nav-pill">返回工作台</RouterLink>
      </div>
    </header>
    <section class="identity-card account-card admin-card">
      <div class="admin-card-head">
        <div>
          <h1>账号与服务状态</h1>
          <p class="identity-intro">仅管理身份、邮件与安全事件，不提供用户科研内容访问。</p>
        </div>
        <div v-if="overview" class="admin-quota-pills" aria-label="系统配额策略">
          <span class="admin-quota-pill">注册总上限 {{ overview.registration_limit }}</span>
          <span class="admin-quota-pill">每小时发信上限 {{ overview.mail_hour_limit }}</span>
        </div>
      </div>
      <p v-if="error" class="notice danger" role="alert">{{ error }}</p>
      <p v-if="message" class="notice success" role="status">{{ message }}</p>
      <div v-if="overview" class="admin-metrics">
        <div class="admin-metric-card">
          <span>账号总数</span>
          <b>{{ overview.users.total }}</b>
        </div>
        <div class="admin-metric-card">
          <span>待激活</span>
          <b>{{ overview.users.pending }}</b>
        </div>
        <div class="admin-metric-card">
          <span>已禁用</span>
          <b>{{ overview.users.disabled }}</b>
        </div>
        <div class="admin-metric-card" :class="overview.mail_configured ? 'is-ok' : 'is-warn'">
          <span>邮件服务</span>
          <b>{{ overview.mail_configured ? '已配置' : '未配置' }}</b>
        </div>
      </div>
      <details class="identity-reauth">
        <summary>敏感操作重新认证（有效期5分钟）</summary>
        <form class="identity-form admin-reauth-form" @submit.prevent="authenticate">
          <label>
            <span>当前密码</span>
            <input v-model="password" type="password" autocomplete="current-password" placeholder="输入管理员密码" required maxlength="128">
          </label>
          <label>
            <span>验证码或恢复码</span>
            <input v-model="code" autocomplete="one-time-code" placeholder="6 位动态口令或恢复码" required maxlength="80">
          </label>
          <button :disabled="busy" class="button-primary admin-reauth-submit">确认身份</button>
        </form>
      </details>
      <div class="admin-toolbar">
        <nav class="identity-actions admin-tabs" aria-label="管理分类">
          <button v-for="item in [{id:'users',label:'用户'},{id:'mail',label:'邮件状态'},{id:'audit',label:'审计日志'}]" :key="item.id" type="button" :aria-pressed="tab===item.id" :disabled="busy" @click="changeTab(item.id)">{{ item.label }}</button>
        </nav>
      </div>
      <div class="table-scroll admin-table-wrap">
        <table v-if="tab==='users'" class="admin-table">
          <thead><tr><th>邮箱</th><th>状态</th><th>角色</th><th>操作</th></tr></thead>
          <tbody>
            <tr v-for="user in users" :key="user.id">
              <td>
                <span class="admin-user-email">{{ user.email }}</span>
                <small class="admin-identifier">{{ user.id }}</small>
              </td>
              <td>
                <span class="admin-badge" :class="user.disabled ? 'is-danger' : user.active ? 'is-success' : 'is-warning'">
                  {{ user.disabled ? '已禁用' : user.active ? '已激活' : '待激活' }}
                </span>
              </td>
              <td>
                <span class="admin-badge" :class="user.admin ? 'is-role-admin' : 'is-role-user'">
                  {{ user.admin ? '管理员' : '用户' }}
                </span>
              </td>
              <td>
                <span v-if="user.id === identityUser?.id" class="admin-self-tag">当前账号</span>
                <div v-else class="identity-actions admin-row-actions">
                  <button type="button" :disabled="busy" @click="open(user,user.disabled?'enable':'disable')">{{ user.disabled ? '启用' : '禁用' }}</button>
                  <button type="button" :disabled="busy || !user.active || user.disabled" @click="open(user,user.admin?'revoke_admin':'grant_admin')">{{ user.admin ? '撤销管理员' : '授予管理员' }}</button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
        <table v-else-if="tab==='mail'" class="admin-table">
          <thead><tr><th>用途</th><th>提交状态</th><th>尝试</th><th>诊断类别</th><th>操作</th></tr></thead>
          <tbody>
            <tr v-if="!mails.length" class="admin-empty-row"><td colspan="5">暂无邮件发送队列记录</td></tr>
            <tr v-for="mail in mails" :key="mail.id">
              <td>{{ mail.purpose }}</td>
              <td>
                <span class="admin-badge" :class="mail.state === 'submitted' ? 'is-success' : mail.state === 'failed' ? 'is-danger' : 'is-warning'">
                  {{ mail.state }}
                </span>
              </td>
              <td>{{ mail.attempts }}</td>
              <td>{{ mail.error_class || '—' }}</td>
              <td>
                <button v-if="mail.state === 'failed'" type="button" :disabled="busy" @click="retry(mail)">重试</button>
                <span v-else class="muted">—</span>
              </td>
            </tr>
          </tbody>
        </table>
        <table v-else class="admin-table">
          <thead><tr><th>时间</th><th>事件</th><th>结果</th><th>目标</th></tr></thead>
          <tbody>
            <tr v-if="!events.length" class="admin-empty-row"><td colspan="4">暂无安全审计日志</td></tr>
            <tr v-for="event in events" :key="event.id">
              <td>{{ new Date(event.created_at).toLocaleString('zh-CN') }}</td>
              <td><code class="admin-event-code">{{ event.event }}</code></td>
              <td>
                <span class="admin-badge" :class="event.result === 'ok' || event.result === 'accepted' ? 'is-success' : event.result === 'denied' ? 'is-danger' : 'is-role-user'">
                  {{ event.result }}
                </span>
              </td>
              <td><span class="admin-identifier">{{ event.target || '—' }}</span></td>
            </tr>
          </tbody>
        </table>
      </div>
      <div v-if="showPagination" class="identity-actions admin-pagination">
        <button type="button" :disabled="busy || page<=1" @click="page--; load()">上一页</button>
        <span>第 {{ page }} 页</span>
        <button type="button" :disabled="busy || !hasMore" @click="page++; load()">下一页</button>
      </div>
    </section>
    <dialog ref="dialog" class="project-dialog"><form class="identity-form" @submit.prevent="confirm"><h2>{{ labels[action] }}</h2><p>确认对 {{ target?.email }} 执行此操作？旧登录会话将撤销。</p><label>操作原因<select v-model="reason"><option value="user_request">用户申请</option><option value="security_incident">安全事件</option><option value="role_assignment">权限安排</option><option value="account_review">账号复核</option></select></label><p v-if="error" class="notice danger">{{ error }}</p><div class="identity-actions"><button type="button" :disabled="busy" @click="dialog?.close()">取消</button><button class="button-primary" :disabled="busy">确认操作</button></div></form></dialog>
  </main>
</template>
