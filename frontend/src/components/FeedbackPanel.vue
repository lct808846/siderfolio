<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { identityRequest } from '../identity-state'
import { sessionFetch } from '../session-http'
import type { components } from '../types/generated'
import WorkspacePaneHeader from './WorkspacePaneHeader.vue'

type Detail = components['schemas']['FeedbackDetail']
type Page = components['schemas']['FeedbackPage']
type Category = Detail['category']
type Status = Detail['status']

const props = defineProps<{ admin?: boolean; canHandle?: boolean }>()
const route = useRoute()
const categories: Record<Category, string> = {
  bug: 'Bug 报告',
  suggestion: '功能建议',
  usage: '使用问题',
  calculation: '科研计算问题',
  other: '其他',
}
const statuses: Record<Status, string> = {
  pending: '待处理',
  in_progress: '处理中',
  resolved: '已解决',
  closed: '已关闭',
}
const tones: Record<Status, string> = {
  pending: 'ui-pill-warning',
  in_progress: 'ui-pill-neutral',
  resolved: 'ui-pill-success',
  closed: 'ui-pill-neutral',
}
const endpoint = props.admin ? 'admin/feedback' : 'feedback'
const category = ref<Category>('bug')
const title = ref('')
const description = ref('')
const screenshot = ref<File | null>(null)
const fileInput = ref<HTMLInputElement | null>(null)
const list = ref<Page | null>(null)
const detail = ref<Detail | null>(null)
const page = ref(1)
const filterCategory = ref('')
const filterStatus = ref('')
const from = ref('')
const to = ref('')
const status = ref<Status>('pending')
const reply = ref('')
const busy = ref(false)
const error = ref('')
const message = ref('')
const fileError = ref('')
const formReady = computed(() => Boolean(title.value.trim() && description.value.trim()) && !fileError.value)
let submitId = ''
let replyId = ''

watch([category, title, description, screenshot], () => { submitId = '' })
watch([status, reply], () => { replyId = '' })

function dateTime(value: string) {
  return new Date(value).toLocaleString('zh-CN', { dateStyle: 'medium', timeStyle: 'short' })
}

function dateBoundary(value: string, followingDay = false) {
  const date = new Date(value + 'T00:00:00')
  if (followingDay) date.setDate(date.getDate() + 1)
  return date.toISOString()
}

function listPath(number: number) {
  const query = new URLSearchParams({ page: String(number) })
  if (props.admin) {
    if (filterCategory.value) query.set('category', filterCategory.value)
    if (filterStatus.value) query.set('status', filterStatus.value)
    if (from.value) query.set('created_from', dateBoundary(from.value))
    if (to.value) query.set('created_before', dateBoundary(to.value, true))
  }
  return endpoint + '?' + query
}

async function load(number = page.value) {
  list.value = await identityRequest<Page>(listPath(number))
  page.value = number
}

async function run(action: () => Promise<void>) {
  if (busy.value) return
  busy.value = true
  error.value = ''
  message.value = ''
  try {
    await action()
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '暂时无法处理反馈，请重试。'
  } finally {
    busy.value = false
  }
}

async function open(id: string) {
  const record = await identityRequest<Detail>(endpoint + '/' + id)
  detail.value = record
  status.value = record.status
  reply.value = ''
  replyId = ''
}

function pickScreenshot(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0] ?? null
  fileError.value = ''
  if (file && (file.size > 5 * 1024 ** 2 || !['image/png', 'image/jpeg', 'image/webp'].includes(file.type))) {
    fileError.value = '请选择不超过 5 MiB 的 PNG、JPEG 或 WebP 截图。'
    input.value = ''
    screenshot.value = null
    return
  }
  screenshot.value = file
}

function clearScreenshot() {
  screenshot.value = null
  fileError.value = ''
  if (fileInput.value) fileInput.value.value = ''
}

async function submit() {
  if (!formReady.value) return
  if (!submitId) submitId = crypto.randomUUID()
  const body = new FormData()
  body.set('request_id', submitId)
  body.set('category', category.value)
  body.set('title', title.value.trim())
  body.set('description', description.value.trim())
  if (screenshot.value) body.set('screenshot', screenshot.value)
  const response = await sessionFetch('/api/v1/feedback', { method: 'POST', body, cache: 'no-store' })
  const result = await response.json()
  if (!response.ok) throw new Error(result.error?.message || '反馈提交失败，请重试。')
  detail.value = result as Detail
  title.value = ''
  description.value = ''
  clearScreenshot()
  message.value = '反馈已提交，可以在历史记录中查看处理进度。'
  await load(1)
}

async function save() {
  if (!detail.value || !props.canHandle) return
  if (!replyId) replyId = crypto.randomUUID()
  detail.value = await identityRequest<Detail>(endpoint + '/' + detail.value.id, 'PATCH', {
    status: status.value,
    expected_updated_at: detail.value.updated_at,
    request_id: replyId,
    reply: reply.value.trim() || undefined,
  })
  replyId = ''
  reply.value = ''
  message.value = '反馈已更新。'
  await load()
}

onMounted(() => {
  void run(async () => {
    if (typeof route.query.id === 'string' && /^[0-9a-f-]{36}$/i.test(route.query.id)) {
      await open(route.query.id)
    }
    await load()
  })
})
</script>

<template>
  <div class="feedback-panel">
    <p v-if="error" class="notice danger" role="alert">{{ error }}</p>
    <p v-if="message" class="notice success" role="status">{{ message }}</p>

    <form v-if="admin" class="feedback-filters" aria-label="反馈筛选" @submit.prevent="run(() => load(1))">
      <label>类型
        <select v-model="filterCategory" :disabled="busy">
          <option value="">全部类型</option>
          <option v-for="(label, value) in categories" :key="value" :value="value">{{ label }}</option>
        </select>
      </label>
      <label>状态
        <select v-model="filterStatus" :disabled="busy">
          <option value="">全部状态</option>
          <option v-for="(label, value) in statuses" :key="value" :value="value">{{ label }}</option>
        </select>
      </label>
      <label>开始日期<input v-model="from" type="date" :max="to || undefined" :disabled="busy" /></label>
      <label>结束日期<input v-model="to" type="date" :min="from || undefined" :disabled="busy" /></label>
      <button type="submit" :disabled="busy">应用筛选</button>
    </form>

    <div class="feedback-grid" :class="{ 'is-admin': admin, 'has-detail': detail }">
      <section v-if="!admin" class="ui-card-subtle feedback-section">
        <WorkspacePaneHeader title="提交反馈" :level="2" />
        <form class="feedback-form" @submit.prevent="run(submit)">
          <fieldset :disabled="busy">
            <label>反馈类型
              <select v-model="category">
                <option v-for="(label, value) in categories" :key="value" :value="value">{{ label }}</option>
              </select>
            </label>
            <label>标题<input v-model="title" required maxlength="120" /></label>
            <label>详细描述
              <textarea v-model="description" required maxlength="4000" rows="5" placeholder="请描述遇到的情况和希望改进的地方" />
            </label>
            <label>截图附件（选填）
              <input ref="fileInput" type="file" accept="image/png,image/jpeg,image/webp" @change="pickScreenshot" />
            </label>
            <p v-if="fileError" class="notice danger" role="alert">{{ fileError }}</p>
            <p v-else class="muted">PNG、JPEG 或 WebP，最多 5 MiB。上传前请遮盖密钥、密码和私人内容。</p>
            <div class="feedback-actions">
              <button v-if="screenshot || fileError" type="button" @click="clearScreenshot">移除截图</button>
              <button class="button-primary" type="submit" :disabled="busy || !formReady">{{ busy ? '请稍候…' : '提交反馈' }}</button>
            </div>
          </fieldset>
        </form>
      </section>

      <section v-if="admin || !detail" class="ui-card-subtle feedback-section">
        <WorkspacePaneHeader :title="admin ? '反馈列表' : '我的反馈'" :level="2">
          <template #actions><button type="button" :disabled="busy" @click="run(() => load())">刷新</button></template>
        </WorkspacePaneHeader>
        <p v-if="!list && busy" class="muted" role="status">正在加载反馈…</p>
        <p v-else-if="list && !list.items.length" class="muted">暂无反馈记录。</p>
        <ul v-if="list?.items.length" class="feedback-list">
          <li v-for="item in list.items" :key="item.id">
            <button
              type="button"
              class="feedback-item"
              :aria-current="detail?.id === item.id ? 'true' : undefined"
              :disabled="busy"
              @click="run(() => open(item.id))"
            >
              <span class="feedback-item-copy">
                <strong>{{ item.title }}</strong>
                <span class="muted">{{ categories[item.category] }} · {{ dateTime(item.created_at) }}</span>
              </span>
              <span class="ui-pill" :class="tones[item.status]">{{ statuses[item.status] }}</span>
            </button>
          </li>
        </ul>
        <nav v-if="page > 1 || list?.has_more" class="feedback-actions" aria-label="反馈分页">
          <button type="button" :disabled="busy || page === 1" @click="run(() => load(page - 1))">上一页</button>
          <span class="muted">第 {{ page }} 页</span>
          <button type="button" :disabled="busy || !list?.has_more" @click="run(() => load(page + 1))">下一页</button>
        </nav>
      </section>

      <section v-if="detail" class="ui-card-subtle feedback-section">
        <WorkspacePaneHeader title="反馈详情" :level="2">
          <template #actions><button type="button" :disabled="busy" @click="detail = null; error = ''">返回列表</button></template>
        </WorkspacePaneHeader>
        <div class="feedback-detail-head">
          <h3>{{ detail.title }}</h3>
          <span class="ui-pill" :class="tones[detail.status]">{{ statuses[detail.status] }}</span>
        </div>
        <p class="muted">{{ categories[detail.category] }} · {{ dateTime(detail.created_at) }}</p>
        <p class="feedback-number">反馈编号 <code>{{ detail.id }}</code></p>
        <p v-if="admin" class="feedback-number">用户编号 <code>{{ detail.user_id }}</code></p>
        <p class="feedback-body">{{ detail.description }}</p>
        <a
          v-if="detail.has_screenshot"
          class="feedback-screenshot"
          :href="'/api/v1/' + endpoint + '/' + detail.id + '/screenshot'"
          target="_blank"
          rel="noopener noreferrer"
        >
          <img :src="'/api/v1/' + endpoint + '/' + detail.id + '/screenshot'" alt="用户上传的截图" loading="lazy" />
          查看原图 ↗
        </a>
        <div class="feedback-replies">
          <h3>管理员回复</h3>
          <p v-if="!detail.replies.length" class="muted">暂无回复。</p>
          <article v-for="item in detail.replies" :key="item.id" class="feedback-reply">
            <time :datetime="item.created_at" class="muted">{{ dateTime(item.created_at) }}</time>
            <p class="feedback-body">{{ item.body }}</p>
          </article>
        </div>
        <form v-if="admin" class="feedback-form" @submit.prevent="run(save)">
          <fieldset :disabled="busy">
            <label>处理状态
              <select v-model="status">
                <option v-for="(label, value) in statuses" :key="value" :value="value">{{ label }}</option>
              </select>
            </label>
            <label>给用户的回复<textarea v-model="reply" rows="3" maxlength="2000" /></label>
            <p v-if="!canHandle" class="muted">请先在上方完成管理员身份确认，再保存处理结果。</p>
            <div class="feedback-actions">
              <button type="submit" class="button-primary" :disabled="!canHandle || busy || (status === detail.status && !reply.trim())">
                {{ reply.trim() ? '保存并回复' : '保存状态' }}
              </button>
            </div>
          </fieldset>
        </form>
      </section>
    </div>
  </div>
</template>

<style scoped>
.feedback-panel, .feedback-form fieldset { display: grid; gap: var(--space-4); min-width: 0; }
.feedback-form fieldset { margin: 0; padding: 0; border: 0; min-inline-size: 0; }
.feedback-grid { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: var(--space-4); align-items: start; }
.feedback-grid.is-admin:not(.has-detail) { grid-template-columns: minmax(0, 1fr); }
.feedback-section { align-content: start; }
.feedback-filters, .feedback-actions, .feedback-detail-head {
  display: flex; flex-wrap: wrap; align-items: end; gap: var(--space-3);
}
.feedback-actions { justify-content: flex-end; align-items: center; }
.feedback-detail-head { align-items: start; justify-content: space-between; }
.feedback-panel label { display: grid; min-width: 0; gap: var(--space-1); font-weight: 550; }
.feedback-panel :is(input, select, textarea) { width: 100%; min-width: 0; }
.feedback-panel textarea { resize: vertical; }
.feedback-panel :is(h3, p) { margin: 0; }
.feedback-list { display: grid; gap: var(--space-2); list-style: none; padding: 0; margin: 0; }
.feedback-item {
  width: 100%; display: flex; justify-content: space-between; gap: var(--space-2);
  align-items: center; text-align: start;
}
.feedback-item[aria-current] { background: var(--accent-soft); border-color: var(--accent); }
.feedback-item-copy { display: grid; gap: var(--space-1); min-width: 0; overflow-wrap: anywhere; }
.feedback-detail-head h3, .feedback-number, .feedback-body { overflow-wrap: anywhere; }
.feedback-number { color: var(--muted); font-size: 0.82em; }
.feedback-body { white-space: pre-wrap; }
.feedback-screenshot { display: grid; gap: var(--space-1); justify-items: start; color: var(--accent); }
.feedback-screenshot img { max-width: 100%; max-height: 300px; object-fit: contain; border-radius: var(--radius-card); }
.feedback-replies, .feedback-reply { display: grid; gap: var(--space-2); border-top: 1px solid var(--line); padding-top: var(--space-3); }
@media (max-width: 800px) {
  .feedback-grid { grid-template-columns: minmax(0, 1fr); }
  .feedback-filters > label { flex: 1 1 8rem; }
}
</style>
