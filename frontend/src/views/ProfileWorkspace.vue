<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import StatusNotice from '../components/StatusNotice.vue'
import SuccessToast from '../components/SuccessToast.vue'
import { fetchProfileSummary, uploadProfileAvatar, deleteProfileAvatar, type ModelUsageEntry, type ProfileSummary } from '../api/profile'
import { identityRequest, identityUser, refreshIdentity } from '../identity-state'

const MAX_AVATAR_BYTES = 5 * 1024 * 1024

const summary = ref<ProfileSummary | null>(null)
const loading = ref(false)
const busy = ref(false)
const error = ref('')
const message = ref('')

const avatarInput = ref<HTMLInputElement | null>(null)
const avatarBroken = ref(false)

const editingName = ref(false)
const nameInput = ref<HTMLInputElement | null>(null)
const usernameDraft = ref('')

const displayName = computed(() => {
  return (summary.value?.account.username || identityUser.value?.username || identityUser.value?.email?.split('@')[0] || 'AstroAgent 用户').trim()
})

const avatarText = computed(() => (displayName.value.slice(0, 2) || 'AA').toUpperCase())
const avatarUrl = computed(() => {
  if (avatarBroken.value) return ''
  return summary.value?.account.avatar_url || identityUser.value?.avatar_url || ''
})

watch(
  () => [summary.value?.account.avatar_url, identityUser.value?.avatar_url],
  () => { avatarBroken.value = false },
)

const totalResearchQueries = computed(() => {
  const ws = summary.value?.workspace
  if (!ws) return 0
  return ws.simbad_queries + ws.ads_queries + ws.gaia_queries
})

const storagePercent = computed(() => {
  const ws = summary.value?.workspace
  if (!ws || !ws.budget_bytes) return 0
  return Math.min(100, (ws.used_bytes / ws.budget_bytes) * 100)
})

function formatBytes(value?: number | null) {
  if (value == null) return '—'
  if (value < 1024) return `${value} B`
  const unit = value < 1024 ** 2 ? 'KiB' : value < 1024 ** 3 ? 'MiB' : 'GiB'
  const size = value / 1024 ** (unit === 'KiB' ? 1 : unit === 'MiB' ? 2 : 3)
  return `${size.toLocaleString('zh-CN', { maximumFractionDigits: 1 })} ${unit}`
}

function formatDate(value?: string | null) {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '—'
  return date.toLocaleDateString('zh-CN', { timeZone: 'Asia/Shanghai' })
}

function formatDateTime(value?: string | null) {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '—'
  return date.toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai' })
}

function channelTags(entry: ModelUsageEntry) {
  const tags: string[] = []
  if (entry.chat_calls > 0) tags.push(`对话 ${entry.chat_calls}`)
  if (entry.plot_calls > 0) tags.push(`绘图 ${entry.plot_calls}`)
  if (entry.rag_calls > 0) tags.push(`文献问答 ${entry.rag_calls}`)
  if (entry.local_calls > 0) tags.push(`本地助手 ${entry.local_calls}`)
  return tags
}

async function loadSummary() {
  if (loading.value) return
  loading.value = true
  error.value = ''
  try {
    summary.value = await fetchProfileSummary()
  } catch (e) {
    error.value = e instanceof Error ? e.message : '个人资料读取失败，请稍后重试。'
  } finally {
    loading.value = false
  }
}

function chooseAvatar() {
  if (busy.value) return
  avatarInput.value?.click()
}

async function handleAvatarChange(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file || busy.value) return
  if (file.size > MAX_AVATAR_BYTES) {
    error.value = '头像图片不能超过 5 MiB，请选择更小的图片。'
    return
  }
  busy.value = true
  error.value = ''
  message.value = ''
  try {
    const result = await uploadProfileAvatar(file)
    avatarBroken.value = false
    message.value = result.message
    await refreshIdentity()
    await loadSummary()
  } catch (e) {
    error.value = e instanceof Error ? e.message : '头像上传未完成，请重试。'
  } finally {
    busy.value = false
  }
}

async function removeAvatar() {
  if (busy.value || !avatarUrl.value) return
  busy.value = true
  error.value = ''
  message.value = ''
  try {
    const result = await deleteProfileAvatar()
    message.value = result.message
    await refreshIdentity()
    await loadSummary()
  } catch (e) {
    error.value = e instanceof Error ? e.message : '移除头像失败，请重试。'
  } finally {
    busy.value = false
  }
}

async function startInlineEdit() {
  if (busy.value || editingName.value) return
  error.value = ''
  usernameDraft.value = displayName.value
  editingName.value = true
  await nextTick()
  nameInput.value?.focus()
  nameInput.value?.select()
}

function cancelInlineEdit() {
  editingName.value = false
  usernameDraft.value = displayName.value
}

async function commitInlineEdit() {
  if (!editingName.value || busy.value) return
  const trimmed = usernameDraft.value.trim()
  editingName.value = false
  if (!trimmed || trimmed === displayName.value) return
  busy.value = true
  error.value = ''
  message.value = ''
  try {
    const result = await identityRequest<{ message: string; username: string }>('auth/profile', 'POST', {
      username: trimmed,
    })
    message.value = result.message
    await refreshIdentity()
    await loadSummary()
  } catch (e) {
    error.value = e instanceof Error ? e.message : '用户名修改失败，请重试。'
  } finally {
    busy.value = false
  }
}

onMounted(() => { void loadSummary() })
</script>

<template>
  <div class="chat-scroll profile-scroll">
    <div class="profile-reading">
      <SuccessToast v-model:message="message" />
      <StatusNotice
        v-if="error"
        class="profile-notice"
        title="操作或读取未完成"
        :message="error"
      />

      <section class="profile-hero-centered" aria-label="个人身份与头像">
        <div class="profile-avatar-block">
          <button
            type="button"
            class="profile-avatar-trigger"
            :disabled="busy"
            aria-label="更换用户头像"
            data-tooltip="点击上传或更换头像（支持 PNG / JPEG / WEBP / GIF，最大 5 MiB）"
            @click="chooseAvatar"
          >
            <img v-if="avatarUrl" :src="avatarUrl" alt="当前用户头像" class="profile-avatar-img" @error="avatarBroken = true" />
            <span v-else class="profile-avatar-fallback" aria-hidden="true">{{ avatarText }}</span>
            <span class="profile-avatar-badge" aria-hidden="true">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
                <path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z" />
                <circle cx="12" cy="13" r="4" />
              </svg>
            </span>
          </button>
          <button
            v-if="avatarUrl"
            type="button"
            class="profile-avatar-remove"
            :disabled="busy"
            @click="removeAvatar"
          >
            移除头像
          </button>
          <input
            ref="avatarInput"
            type="file"
            class="sr-only"
            accept="image/png,image/jpeg,image/webp,image/gif"
            aria-label="选择头像图片"
            @change="handleAvatarChange"
          />
        </div>

        <div class="profile-name-row">
          <form v-if="editingName" class="profile-inline-rename" @submit.prevent="commitInlineEdit">
            <input
              ref="nameInput"
              v-model="usernameDraft"
              type="text"
              class="profile-name-input"
              autocomplete="nickname"
              maxlength="32"
              aria-label="编辑用户名"
              :disabled="busy"
              @keydown.esc.prevent="cancelInlineEdit"
              @blur="commitInlineEdit"
            />
          </form>
          <h2 v-else>
            <button
              type="button"
              class="profile-name-trigger"
              :disabled="busy"
              aria-label="点击编辑用户名"
              @click="startInlineEdit"
            >
              {{ displayName }}
            </button>
          </h2>
        </div>

        <p class="profile-email">{{ summary?.account.email || identityUser?.email }}</p>

        <div class="profile-meta-pills">
          <span class="tag">{{ (summary?.account.admin ?? identityUser?.admin) ? '管理员' : '科研用户' }}</span>
          <span class="tag" :class="(summary?.account.totp_enabled ?? identityUser?.totp_enabled) ? '' : 'partial'">
            {{ (summary?.account.totp_enabled ?? identityUser?.totp_enabled) ? 'MFA 已启用' : '未启用 MFA' }}
          </span>
        </div>

        <p class="profile-timestamps">
          <span>加入于 {{ formatDate(summary?.account.created_at) }}</span>
          <span aria-hidden="true">·</span>
          <span>最近登录 {{ formatDateTime(summary?.account.last_login) }}</span>
          <span aria-hidden="true">·</span>
          <span>活动会话 {{ summary?.account.active_sessions ?? '—' }} 个</span>
        </p>
      </section>

      <section class="profile-stats-strip" aria-label="核心使用统计">
        <div class="profile-stat-cell">
          <b>{{ summary ? summary.total_model_calls.toLocaleString('zh-CN') : '—' }}</b>
          <span class="profile-stat-label">模型累计调用</span>
          <small>{{ summary ? `已使用 ${summary.distinct_models_count} 个模型` : '正在读取…' }}</small>
        </div>
        <div class="profile-stat-cell">
          <b>{{ summary?.known_total_tokens != null ? summary.known_total_tokens.toLocaleString('zh-CN') : '—' }}</b>
          <span class="profile-stat-label">已记录 Token</span>
          <small>绘图与本地助手记录</small>
        </div>
        <div class="profile-stat-cell">
          <b>{{ summary ? totalResearchQueries.toLocaleString('zh-CN') : '—' }}</b>
          <span class="profile-stat-label">天文数据检索</span>
          <small v-if="summary">SIMBAD {{ summary.workspace.simbad_queries }} · ADS {{ summary.workspace.ads_queries }} · Gaia {{ summary.workspace.gaia_queries }}</small>
          <small v-else>SIMBAD / ADS / Gaia DR3</small>
        </div>
        <div class="profile-stat-cell">
          <b>{{ summary ? formatBytes(summary.workspace.used_bytes) : '—' }}</b>
          <span class="profile-stat-label">科研空间已用</span>
          <small>{{ summary ? `总配额 ${formatBytes(summary.workspace.budget_bytes)}（${storagePercent.toFixed(1)}%）` : '正在统计…' }}</small>
          <div v-if="summary" class="profile-storage-track" aria-hidden="true">
            <span class="profile-storage-fill" :style="{ width: `${storagePercent}%` }"></span>
          </div>
        </div>
      </section>

      <section class="settings-group profile-section" aria-labelledby="profile-models-title">
        <div class="settings-group-head">
          <div>
            <h2 id="profile-models-title">模型使用情况</h2>
            <p class="profile-section-sub">按模型与功能场景统计账号私域记录中的历史调用</p>
          </div>
        </div>

        <div v-if="summary?.models.length" class="profile-table-wrap">
          <table class="profile-table">
            <thead>
              <tr>
                <th scope="col">模型</th>
                <th scope="col">调用场景</th>
                <th scope="col" class="is-num">调用次数</th>
                <th scope="col" class="is-num">已记录 Token</th>
                <th scope="col">最近使用（北京时间）</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="entry in summary.models" :key="entry.model">
                <td>
                  <div class="profile-model-cell">
                    <strong>{{ entry.label }}</strong>
                    <code v-if="entry.label !== entry.model">{{ entry.model }}</code>
                  </div>
                </td>
                <td>
                  <div class="profile-channel-tags">
                    <span v-for="tag in channelTags(entry)" :key="tag" class="tag">{{ tag }}</span>
                  </div>
                </td>
                <td class="is-num">
                  <strong>{{ entry.calls }}</strong>
                  <span class="profile-subcount">
                    成功 {{ entry.succeeded }}<template v-if="entry.failed > 0"> · 失败 {{ entry.failed }}</template>
                  </span>
                </td>
                <td class="is-num">
                  <template v-if="entry.total_tokens != null">
                    <strong>{{ entry.total_tokens.toLocaleString('zh-CN') }}</strong>
                    <span class="profile-subcount">
                      输入 {{ entry.input_tokens == null ? '—' : entry.input_tokens.toLocaleString('zh-CN') }} / 输出 {{ entry.output_tokens == null ? '—' : entry.output_tokens.toLocaleString('zh-CN') }}
                    </span>
                  </template>
                  <span v-else class="muted">—</span>
                </td>
                <td>{{ formatDateTime(entry.last_used_at) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <div v-else-if="summary" class="profile-empty-state">
          <p>当前账号下还没有模型调用记录。</p>
          <RouterLink to="/" class="settings-action-link">前往查询工作台开始提问 →</RouterLink>
        </div>
        <p v-else class="settings-loading" role="status">正在读取模型使用情况…</p>
        <p class="settings-footnote">注：按已完成、失败或中断的模型请求记录统计，等待中、执行中与跳过的任务不计入；不等于服务商计费调用数。Token 明细仅汇总已记录的科研绘图方案与本地助手用量，缺失值显示“—”。</p>
      </section>

      <section class="settings-group profile-section" aria-labelledby="profile-workspace-title">
        <div class="settings-group-head">
          <div>
            <h2 id="profile-workspace-title">科研工作区资产概览</h2>
            <p class="profile-section-sub">统计范围仅限当前登录账号的独立数据空间</p>
          </div>
          <RouterLink to="/projects" class="settings-action-link">管理科研项目 ↗</RouterLink>
        </div>

        <div v-if="summary" class="profile-asset-grid">
          <div class="profile-asset-item">
            <span>对话与轮次</span>
            <strong>{{ summary.workspace.conversations_count }} 个会话 · {{ summary.workspace.turns_count }} 轮</strong>
            <small>完成 {{ summary.workspace.completed_turns }} 轮<template v-if="summary.workspace.failed_turns > 0"> · 未完成 {{ summary.workspace.failed_turns }} 轮</template></small>
          </div>
          <div class="profile-asset-item">
            <span>项目与快照</span>
            <strong>{{ summary.workspace.projects_count }} 个项目 · {{ summary.workspace.snapshots_count }} 份快照</strong>
            <small>科研流程 {{ summary.workspace.workflows_count }} 条运行记录</small>
          </div>
          <div class="profile-asset-item">
            <span>本地知识库与文献问答</span>
            <strong>{{ summary.workspace.knowledge_documents_count }} 篇文档 · {{ summary.workspace.rag_answers_count }} 次问答</strong>
            <small>仅包含上传至本账号的科研材料</small>
          </div>
          <div class="profile-asset-item">
            <span>科研绘图与本地助手</span>
            <strong>{{ summary.workspace.plot_datasets_count }} 份数据集 · {{ summary.workspace.plot_operations_count }} 次绘图</strong>
            <small>本地轻量助手任务 {{ summary.workspace.local_tasks_count }} 次</small>
          </div>
        </div>
      </section>
    </div>
  </div>
</template>
