<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, useId, watch } from 'vue'
import { useRoute } from 'vue-router'
import { identityRequest } from '../identity-state'
import { sessionFetch } from '../session-http'
import StatusNotice from './StatusNotice.vue'
import UiSelect, { type UiSelectOption } from './UiSelect.vue'
import type { components } from '../types/generated'

type Detail = components['schemas']['FeedbackDetail']
type Page = components['schemas']['FeedbackPage']
type Category = Detail['category']
type Status = Detail['status']

const props = defineProps<{ admin?: boolean; canHandle?: boolean }>()
const route = useRoute()

const idPrefix = useId()
const categoryId = `${idPrefix}-category`
const titleId = `${idPrefix}-title`
const descriptionId = `${idPrefix}-description`
const screenshotId = `${idPrefix}-screenshot`
const filterCategoryId = `${idPrefix}-filter-category`
const filterStatusId = `${idPrefix}-filter-status`
const filterFromId = `${idPrefix}-filter-from`
const filterToId = `${idPrefix}-filter-to`
const replyStatusId = `${idPrefix}-reply-status`
const replyBodyId = `${idPrefix}-reply-body`

const categories: Record<Category, string> = {
  bug: 'Bug 报告',
  suggestion: '功能建议',
  usage: '使用问题',
  calculation: '科研计算问题',
  other: '其他',
}

const categoryHints: Record<Category, string> = {
  bug: '请尽量附上触发步骤、页面位置与预期行为，便于快速定位修复。',
  suggestion: '欢迎分享希望新增的能力、工作流优化或界面交互改进思路。',
  usage: '说明当前所在页面与操作流程，我们会尽快协助解答。',
  calculation: '可说明涉及的天体目标、星表查询、绘图脚本或 N 体计算参数。',
  other: '账号、协作、文档或其他方面的意见与建议。',
}

const categoryTones: Record<Category, string> = {
  bug: 'ui-pill-danger',
  suggestion: 'ui-pill-accent',
  usage: 'ui-pill-ads',
  calculation: 'ui-pill-compute',
  other: 'ui-pill-neutral',
}

const statuses: Record<Status, string> = {
  pending: '待处理',
  in_progress: '处理中',
  resolved: '已解决',
  closed: '已关闭',
}

const categoryFilterOptions: UiSelectOption<string>[] = [
  { value: '', label: '全部类型' },
  ...(Object.entries(categories) as [Category, string][]).map(([value, label]) => ({ value, label })),
]

const statusFilterOptions: UiSelectOption<string>[] = [
  { value: '', label: '全部状态' },
  ...(Object.entries(statuses) as [Status, string][]).map(([value, label]) => ({ value, label })),
]

const tones: Record<Status, string> = {
  pending: 'ui-pill-warning',
  in_progress: 'ui-pill-accent',
  resolved: 'ui-pill-success',
  closed: 'ui-pill-neutral',
}

const endpoint = props.admin ? 'admin/feedback' : 'feedback'
const category = ref<Category>('bug')
const title = ref('')
const description = ref('')
const screenshot = ref<File | null>(null)
const screenshotPreview = ref('')
const draggingFile = ref(false)
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
const copiedId = ref(false)

const formReady = computed(() => Boolean(title.value.trim() && description.value.trim()) && !fileError.value)
const hasActiveFilters = computed(() => Boolean(filterCategory.value || filterStatus.value || from.value || to.value))
const formattedFileSize = computed(() => {
  const file = screenshot.value
  if (!file) return ''
  if (file.size < 1024) return `${file.size} B`
  if (file.size < 1024 ** 2) return `${(file.size / 1024).toFixed(1)} KiB`
  return `${(file.size / 1024 ** 2).toFixed(2)} MiB`
})

let submitId = ''
let replyId = ''
let copyTimer: number | null = null

watch([category, title, description, screenshot], () => { submitId = '' })
watch([status, reply], () => { replyId = '' })
watch(screenshot, (file) => {
  if (screenshotPreview.value) {
    URL.revokeObjectURL(screenshotPreview.value)
    screenshotPreview.value = ''
  }
  if (file) {
    screenshotPreview.value = URL.createObjectURL(file)
  }
})

onBeforeUnmount(() => {
  if (screenshotPreview.value) URL.revokeObjectURL(screenshotPreview.value)
  if (copyTimer) window.clearTimeout(copyTimer)
})

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
  copiedId.value = false
}

function applyScreenshotFile(file: File | null, input?: HTMLInputElement | null) {
  fileError.value = ''
  if (file && (file.size > 5 * 1024 ** 2 || !['image/png', 'image/jpeg', 'image/webp'].includes(file.type))) {
    fileError.value = '请选择不超过 5 MiB 的 PNG、JPEG 或 WebP 截图。'
    if (input) input.value = ''
    else if (fileInput.value) fileInput.value.value = ''
    screenshot.value = null
    return
  }
  screenshot.value = file
}

function pickScreenshot(event: Event) {
  const input = event.target as HTMLInputElement
  applyScreenshotFile(input.files?.[0] ?? null, input)
}

function dropScreenshot(event: DragEvent) {
  draggingFile.value = false
  if (busy.value) return
  const file = event.dataTransfer?.files?.[0] ?? null
  if (!file) return
  applyScreenshotFile(file)
}

function clearScreenshot() {
  screenshot.value = null
  fileError.value = ''
  if (fileInput.value) fileInput.value.value = ''
}

function resetFilters() {
  filterCategory.value = ''
  filterStatus.value = ''
  from.value = ''
  to.value = ''
  void run(() => load(1))
}

async function copyRecordId(id: string) {
  try {
    await navigator.clipboard.writeText(id)
    copiedId.value = true
    if (copyTimer) window.clearTimeout(copyTimer)
    copyTimer = window.setTimeout(() => { copiedId.value = false }, 1800)
  } catch {
    /* Ignore clipboard errors on restricted contexts. */
  }
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
    <StatusNotice v-if="error" title="反馈操作未完成" :message="error" @dismiss="error = ''" />
    <div v-if="message" class="notice success feedback-banner" role="status">
      <span>{{ message }}</span>
      <button type="button" class="feedback-banner-close" aria-label="关闭状态提示" @click="message = ''">×</button>
    </div>

    <form v-if="admin" class="feedback-filter-bar" aria-label="反馈筛选" @submit.prevent="run(() => load(1))">
      <div class="feedback-filter-field">
        <label :for="filterCategoryId">类型</label>
        <UiSelect
          :id="filterCategoryId"
          v-model="filterCategory"
          variant="compact"
          aria-label="按类型筛选"
          :disabled="busy"
          :options="categoryFilterOptions"
        />
      </div>

      <div class="feedback-filter-field">
        <label :for="filterStatusId">状态</label>
        <UiSelect
          :id="filterStatusId"
          v-model="filterStatus"
          variant="compact"
          aria-label="按状态筛选"
          :disabled="busy"
          :options="statusFilterOptions"
        />
      </div>

      <div class="feedback-filter-field">
        <label :for="filterFromId">开始日期</label>
        <input :id="filterFromId" v-model="from" type="date" :max="to || undefined" :disabled="busy" />
      </div>

      <div class="feedback-filter-field">
        <label :for="filterToId">结束日期</label>
        <input :id="filterToId" v-model="to" type="date" :min="from || undefined" :disabled="busy" />
      </div>

      <div class="feedback-filter-actions">
        <button type="submit" class="button-primary" :disabled="busy">应用筛选</button>
        <button v-if="hasActiveFilters" type="button" class="button-secondary" :disabled="busy" @click="resetFilters">重置</button>
      </div>
    </form>

    <div class="feedback-grid" :class="{ 'is-admin': admin, 'has-detail': Boolean(detail) }">
      <section v-if="!admin" class="ui-card feedback-card feedback-compose-card">
        <header class="feedback-card-head">
          <div class="feedback-card-heading">
            <span class="feedback-card-icon is-accent" aria-hidden="true">
              <svg viewBox="0 0 24 24">
                <path d="M12 20h9" />
                <path d="M16.5 3.5a2.12 2.12 0 1 1 3 3L7 19l-4 1 1-4 12.5-12.5Z" />
              </svg>
            </span>
            <div class="feedback-card-copy">
              <h2>提交反馈</h2>
              <p>清晰的问题描述与截图能帮助团队更快复现与处理</p>
            </div>
          </div>
        </header>

        <form class="feedback-form" @submit.prevent="run(submit)">
          <fieldset :disabled="busy">
            <div class="feedback-field">
              <div class="feedback-field-head">
                <label :for="categoryId">反馈类型</label>
                <span class="ui-pill feedback-category-tag" :class="categoryTones[category]">{{ categories[category] }}</span>
              </div>
              <UiSelect
                :id="categoryId"
                v-model="category"
                aria-label="反馈类型"
                :disabled="busy"
                :options="(Object.entries(categories) as [Category, string][]).map(([value, label]) => ({ value, label })) as UiSelectOption<Category>[]"
              />
              <p class="feedback-field-hint">{{ categoryHints[category] }}</p>
            </div>

            <div class="feedback-field">
              <div class="feedback-field-head">
                <label :for="titleId">标题</label>
                <span class="feedback-counter">{{ title.length }} / 120</span>
              </div>
              <input
                :id="titleId"
                v-model="title"
                required
                maxlength="120"
                placeholder="用一句话概括遇到的情况或改进建议"
              />
            </div>

            <div class="feedback-field">
              <div class="feedback-field-head">
                <label :for="descriptionId">详细描述</label>
                <span class="feedback-counter">{{ description.length }} / 4000</span>
              </div>
              <textarea
                :id="descriptionId"
                v-model="description"
                required
                maxlength="4000"
                rows="5"
                placeholder="请描述遇到的情况和希望改进的地方"
              />
            </div>

            <div class="feedback-field">
              <div class="feedback-field-head">
                <label :for="screenshotId">截图附件（选填）</label>
                <span class="feedback-counter">PNG / JPEG / WebP · ≤ 5 MiB</span>
              </div>

              <div
                class="feedback-dropzone"
                :class="{ 'is-dragging': draggingFile, 'has-file': Boolean(screenshot), 'has-error': Boolean(fileError) }"
                @dragenter.prevent="draggingFile = true"
                @dragover.prevent="draggingFile = true"
                @dragleave.prevent="draggingFile = false"
                @drop.prevent="dropScreenshot"
              >
                <input
                  :id="screenshotId"
                  ref="fileInput"
                  class="feedback-file-sr"
                  type="file"
                  accept="image/png,image/jpeg,image/webp"
                  @change="pickScreenshot"
                />

                <div v-if="!screenshot" class="feedback-dropzone-empty" @click="!busy && fileInput?.click()">
                  <span class="feedback-dropzone-icon" aria-hidden="true">
                    <svg viewBox="0 0 24 24">
                      <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                      <polyline points="17 8 12 3 7 8" />
                      <line x1="12" y1="3" x2="12" y2="15" />
                    </svg>
                  </span>
                  <div class="feedback-dropzone-copy">
                    <strong>点击选择或拖拽截图到此处</strong>
                    <span>附带界面或报错截图有助于快速排查</span>
                  </div>
                </div>

                <div v-else class="feedback-file-preview">
                  <img v-if="screenshotPreview" :src="screenshotPreview" alt="" class="feedback-file-thumb" />
                  <div class="feedback-file-meta">
                    <strong class="feedback-file-name">{{ screenshot.name }}</strong>
                    <span class="feedback-file-size">{{ formattedFileSize }}</span>
                  </div>
                  <div class="feedback-file-actions">
                    <button type="button" class="feedback-chip-btn" @click="fileInput?.click()">更换</button>
                    <button type="button" class="feedback-chip-btn is-danger" @click="clearScreenshot">移除截图</button>
                  </div>
                </div>
              </div>

              <StatusNotice v-if="fileError" title="截图校验未通过" :message="fileError" @dismiss="fileError = ''" />
              <p class="feedback-privacy-note">
                <svg viewBox="0 0 24 24" aria-hidden="true">
                  <path d="M12 3 5 6v6c0 4.5 3 7.7 7 9 4-1.3 7-4.5 7-9V6l-7-3Z" />
                  <path d="M12 9v4" />
                  <path d="M12 16h.01" />
                </svg>
                <span>PNG、JPEG 或 WebP，最多 5 MiB。上传前请遮盖密钥、密码和私人内容。</span>
              </p>
            </div>

            <div class="feedback-form-footer">
              <span class="feedback-footer-tip">提交后可在右侧实时查看进度与回复</span>
              <div class="feedback-actions">
                <button v-if="fileError" type="button" @click="clearScreenshot">移除截图</button>
                <button class="button-primary feedback-submit-btn" type="submit" :disabled="busy || !formReady">
                  <svg v-if="!busy" viewBox="0 0 24 24" aria-hidden="true">
                    <path d="M22 2 11 13" />
                    <path d="M22 2 15 22l-4-9-9-4 20-7Z" />
                  </svg>
                  <span>{{ busy ? '请稍候…' : '提交反馈' }}</span>
                </button>
              </div>
            </div>
          </fieldset>
        </form>
      </section>

      <section v-if="admin || !detail" class="feedback-card feedback-list-card" :class="admin ? 'ui-card-subtle' : 'ui-card'">
        <header class="feedback-card-head">
          <div class="feedback-card-heading">
            <span class="feedback-card-icon" aria-hidden="true">
              <svg viewBox="0 0 24 24">
                <path d="M4 6h16" />
                <path d="M4 12h16" />
                <path d="M4 18h10" />
              </svg>
            </span>
            <div class="feedback-card-copy">
              <div class="feedback-card-title-row">
                <h2>{{ admin ? '反馈列表' : '我的反馈' }}</h2>
                <span v-if="list" class="ui-pill ui-pill-neutral feedback-count-pill">
                  {{ list.items.length }} 条
                </span>
              </div>
              <p>{{ admin ? '点击任意记录查看完整内容、截图并回复用户' : '跟踪已提交反馈的处理状态与管理员回复' }}</p>
            </div>
          </div>
        </header>

        <div v-if="!list && busy" class="feedback-loading" role="status">
          <div class="feedback-skeleton-row" aria-hidden="true" />
          <div class="feedback-skeleton-row" aria-hidden="true" />
          <p class="feedback-loading-label">正在加载反馈…</p>
        </div>

        <div v-else-if="list && !list.items.length" class="feedback-empty">
          <span class="ui-empty-icon" aria-hidden="true">
            <svg viewBox="0 0 24 24">
              <path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5Z" />
            </svg>
          </span>
          <h3>暂无反馈记录</h3>
          <p>{{ admin ? '当前筛选条件下没有匹配的用户反馈记录。' : '在左侧填写并提交后，记录会显示在这里，并同步展示处理进度与管理员回复。' }}</p>
          <div v-if="!admin" class="feedback-flow-rail" aria-hidden="true">
            <span class="feedback-flow-step"><b>1</b> 提交问题</span>
            <span class="feedback-flow-sep">→</span>
            <span class="feedback-flow-step"><b>2</b> 排查处理</span>
            <span class="feedback-flow-sep">→</span>
            <span class="feedback-flow-step"><b>3</b> 回复通知</span>
          </div>
        </div>

        <ul v-if="list?.items.length" class="feedback-list">
          <li v-for="item in list.items" :key="item.id">
            <button
              type="button"
              class="feedback-item"
              :aria-current="detail?.id === item.id ? 'true' : undefined"
              :disabled="busy"
              @click="run(() => open(item.id))"
            >
              <span class="feedback-item-main">
                <span class="feedback-item-top">
                  <strong class="feedback-item-title">{{ item.title }}</strong>
                  <span class="ui-pill" :class="tones[item.status]">
                    <span class="ui-dot" aria-hidden="true" />
                    {{ statuses[item.status] }}
                  </span>
                </span>
                <span class="feedback-item-meta">
                  <span class="ui-pill feedback-mini-pill" :class="categoryTones[item.category]">{{ categories[item.category] }}</span>
                  <span class="feedback-item-time">{{ dateTime(item.created_at) }}</span>
                </span>
              </span>
              <svg class="feedback-item-arrow" viewBox="0 0 24 24" aria-hidden="true"><path d="m9 6 6 6-6 6" /></svg>
            </button>
          </li>
        </ul>

        <nav v-if="page > 1 || list?.has_more" class="feedback-pagination" aria-label="反馈分页">
          <button type="button" :disabled="busy || page === 1" @click="run(() => load(page - 1))">上一页</button>
          <span class="feedback-page-indicator">第 {{ page }} 页</span>
          <button type="button" :disabled="busy || !list?.has_more" @click="run(() => load(page + 1))">下一页</button>
        </nav>
      </section>

      <section v-if="detail" class="feedback-card feedback-detail-card" :class="admin ? 'ui-card-subtle' : 'ui-card'">
        <header class="feedback-card-head">
          <div class="feedback-card-heading">
            <span class="feedback-card-icon is-accent" aria-hidden="true">
              <svg viewBox="0 0 24 24">
                <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8Z" />
                <polyline points="14 2 14 8 20 8" />
                <line x1="8" y1="13" x2="16" y2="13" />
                <line x1="8" y1="17" x2="13" y2="17" />
              </svg>
            </span>
            <div class="feedback-card-copy">
              <h2>反馈详情</h2>
              <p>查看原始描述、截图附件及处理记录</p>
            </div>
          </div>

          <button type="button" class="feedback-back-btn" :disabled="busy" @click="detail = null; error = ''">
            <svg viewBox="0 0 24 24" aria-hidden="true"><path d="m15 18-6-6 6-6" /></svg>
            <span>返回列表</span>
          </button>
        </header>

        <div class="feedback-detail-hero">
          <div class="feedback-detail-head">
            <h3>{{ detail.title }}</h3>
            <span class="ui-pill" :class="tones[detail.status]">
              <span class="ui-dot" aria-hidden="true" />
              {{ statuses[detail.status] }}
            </span>
          </div>

          <div class="ui-pill-list feedback-detail-pills">
            <span class="ui-pill" :class="categoryTones[detail.category]">{{ categories[detail.category] }}</span>
            <span class="ui-pill ui-pill-neutral feedback-time-pill">{{ dateTime(detail.created_at) }}</span>
          </div>

          <div class="feedback-identifiers">
            <p class="feedback-number">
              <span>反馈编号</span>
              <code>{{ detail.id }}</code>
              <button
                type="button"
                class="feedback-copy-btn"
                :aria-label="copiedId ? '已复制反馈编号' : '复制反馈编号'"
                @click="copyRecordId(detail.id)"
              >
                {{ copiedId ? '已复制' : '复制' }}
              </button>
            </p>
            <p v-if="admin" class="feedback-number">
              <span>用户编号</span>
              <code>{{ detail.user_id }}</code>
            </p>
          </div>
        </div>

        <div class="feedback-body-surface">
          <p class="feedback-body">{{ detail.description }}</p>
        </div>

        <a
          v-if="detail.has_screenshot"
          class="feedback-screenshot"
          :href="'/api/v1/' + endpoint + '/' + detail.id + '/screenshot'"
          target="_blank"
          rel="noopener noreferrer"
        >
          <span class="feedback-screenshot-frame">
            <img :src="'/api/v1/' + endpoint + '/' + detail.id + '/screenshot'" alt="用户上传的截图" loading="lazy" />
          </span>
          <span class="feedback-screenshot-caption">
            <span>截图附件</span>
            <strong>查看原图 ↗</strong>
          </span>
        </a>

        <div class="feedback-replies">
          <div class="feedback-section-subhead">
            <h3>管理员回复</h3>
            <span v-if="detail.replies.length" class="ui-pill ui-pill-neutral">{{ detail.replies.length }} 条</span>
          </div>
          <p v-if="!detail.replies.length" class="feedback-empty-reply">暂无回复，团队跟进后将同步显示于此。</p>
          <div v-else class="feedback-reply-list">
            <article v-for="item in detail.replies" :key="item.id" class="feedback-reply">
              <div class="feedback-reply-meta">
                <span class="ui-pill ui-pill-accent feedback-mini-pill">管理员</span>
                <time :datetime="item.created_at">{{ dateTime(item.created_at) }}</time>
              </div>
              <p class="feedback-body">{{ item.body }}</p>
            </article>
          </div>
        </div>

        <form v-if="admin" class="feedback-form feedback-admin-reply-form" @submit.prevent="run(save)">
          <div class="feedback-section-subhead">
            <h3>处理与回复</h3>
          </div>
          <fieldset :disabled="busy">
            <div class="feedback-field">
              <label :for="replyStatusId">处理状态</label>
              <UiSelect
                :id="replyStatusId"
                v-model="status"
                aria-label="处理状态"
                :disabled="busy"
                :options="(Object.entries(statuses) as [Status, string][]).map(([value, label]) => ({ value, label })) as UiSelectOption<Status>[]"
              />
            </div>

            <div class="feedback-field">
              <div class="feedback-field-head">
                <label :for="replyBodyId">给用户的回复</label>
                <span class="feedback-counter">{{ reply.length }} / 2000</span>
              </div>
              <textarea
                :id="replyBodyId"
                v-model="reply"
                rows="3"
                maxlength="2000"
                placeholder="填写处理进展、定位说明或解决方案（可选）"
              />
            </div>

            <p v-if="!canHandle" class="notice warning feedback-reauth-tip">
              请先在上方完成管理员身份确认，再保存处理结果。
            </p>

            <div class="feedback-actions">
              <button
                type="submit"
                class="button-primary"
                :disabled="!canHandle || busy || (status === detail.status && !reply.trim())"
              >
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
.feedback-panel {
  display: grid;
  gap: 18px;
  min-width: 0;
}

.feedback-banner {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin: 0;
}

.feedback-banner-close {
  display: inline-grid;
  place-items: center;
  width: 26px;
  height: 26px;
  min-height: 26px;
  padding: 0;
  border: 0;
  border-radius: 6px;
  background: transparent;
  box-shadow: none;
  color: currentColor;
  font-size: 16px;
  line-height: 1;
}

.feedback-banner-close:hover:not(:disabled) {
  background: color-mix(in srgb, currentColor 12%, transparent);
  box-shadow: none;
  transform: none;
}

/* Admin filter toolbar */
.feedback-filter-bar {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr)) auto;
  align-items: end;
  gap: 12px;
  padding: 14px 16px;
  border: 1px solid var(--line);
  border-radius: var(--radius-card);
  background: var(--surface-subtle);
}

.feedback-filter-field {
  display: grid;
  gap: 6px;
  min-width: 0;
}

.feedback-filter-field label {
  font-size: 12px;
  font-weight: 550;
  color: var(--muted);
}

.feedback-filter-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

/* Main two-column layout */
.feedback-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.18fr) minmax(320px, 0.88fr);
  gap: 20px;
  align-items: start;
  min-width: 0;
}

.feedback-grid.is-admin:not(.has-detail) {
  grid-template-columns: minmax(0, 1fr);
}

.feedback-grid.is-admin.has-detail {
  grid-template-columns: minmax(0, 0.92fr) minmax(0, 1.08fr);
}

/* Cards */
.feedback-card {
  display: grid;
  gap: 18px;
  align-content: start;
  padding: 22px 24px 24px;
  border-radius: var(--radius-surface);
}

.feedback-card-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  padding-bottom: 16px;
  border-bottom: 1px solid var(--line);
}

.feedback-card-heading {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  min-width: 0;
}

.feedback-card-icon {
  display: grid;
  place-items: center;
  width: 34px;
  height: 34px;
  flex: 0 0 34px;
  border-radius: var(--radius-control);
  border: 1px solid var(--line);
  background: var(--surface-subtle);
  color: var(--muted);
}

.feedback-card-icon.is-accent {
  border-color: color-mix(in srgb, var(--accent) 24%, var(--line));
  background: var(--accent-soft);
  color: var(--accent);
}

.feedback-card-icon svg {
  width: 17px;
  height: 17px;
  fill: none;
  stroke: currentColor;
  stroke-width: 1.75;
  stroke-linecap: round;
  stroke-linejoin: round;
}

.feedback-card-copy {
  display: grid;
  gap: 3px;
  min-width: 0;
}

.feedback-card-title-row {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.feedback-card-copy h2 {
  margin: 0;
  font-size: 16px;
  font-weight: 620;
  line-height: 1.35;
  letter-spacing: -0.01em;
  color: var(--ink);
}

.feedback-card-copy p {
  margin: 0;
  font-size: 12.5px;
  line-height: 1.5;
  color: var(--muted);
}

.feedback-count-pill {
  min-height: 22px;
  padding: 0 8px;
  font-size: 11px;
  font-variant-numeric: tabular-nums;
}

/* Header icon buttons */
.feedback-back-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  flex: none;
  min-height: 32px;
  padding: 5px 11px;
  font-size: 12.5px;
  border-radius: var(--radius-control);
}

.feedback-back-btn svg {
  width: 14px;
  height: 14px;
  fill: none;
  stroke: currentColor;
  stroke-width: 1.8;
  stroke-linecap: round;
  stroke-linejoin: round;
}

/* Form fields */
.feedback-form,
.feedback-form fieldset {
  display: grid;
  gap: 16px;
  min-width: 0;
}

.feedback-form fieldset {
  margin: 0;
  padding: 0;
  border: 0;
  min-inline-size: 0;
}

.feedback-field {
  display: grid;
  gap: 7px;
  min-width: 0;
}

.feedback-field-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  flex-wrap: wrap;
}

.feedback-field label {
  margin: 0;
  font-size: 13px;
  font-weight: 580;
  color: var(--ink);
}

.feedback-counter {
  font-size: 11.5px;
  color: var(--muted);
  font-variant-numeric: tabular-nums;
}

.feedback-category-tag {
  min-height: 22px;
  padding: 0 9px;
  font-size: 11px;
}

.feedback-field-hint {
  margin: 0;
  font-size: 12px;
  line-height: 1.55;
  color: var(--muted);
}

.feedback-panel :is(input:not([type=file]), select, textarea) {
  width: 100%;
  min-width: 0;
  color: var(--ink);
  border: 1px solid color-mix(in srgb, var(--ink) 16%, transparent);
  border-radius: var(--radius-control);
  background: var(--paper);
  box-shadow: inset 0 1px 2px rgb(0 0 0 / 3%);
  font-size: 14px;
  line-height: 1.65;
  padding: 9px 12px;
  transition:
    border-color var(--duration-fast) var(--ease-out),
    box-shadow var(--duration-fast) var(--ease-out),
    background-color var(--duration-fast) var(--ease-out);
}

.feedback-panel :is(input:not([type=file]), select, textarea):hover:not(:disabled) {
  border-color: color-mix(in srgb, var(--accent) 44%, var(--line-strong));
}

.feedback-panel :is(input:not([type=file]), select, textarea):focus {
  outline: none;
  border-color: var(--accent);
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--accent) 16%, transparent);
}

.feedback-panel textarea {
  min-height: 132px;
  resize: vertical;
  line-height: 1.72;
}

/* Custom-chevron native select */
.feedback-select-wrap {
  position: relative;
  display: grid;
  min-width: 0;
}

.feedback-select-wrap select {
  appearance: none;
  -webkit-appearance: none;
  padding-right: 36px;
  cursor: pointer;
}

.feedback-select-chevron {
  position: absolute;
  right: 11px;
  top: 50%;
  width: 16px;
  height: 16px;
  transform: translateY(-50%);
  pointer-events: none;
  fill: none;
  stroke: var(--muted);
  stroke-width: 1.9;
  stroke-linecap: round;
  stroke-linejoin: round;
}

/* Screenshot dropzone */
.feedback-dropzone {
  position: relative;
  border: 1.5px dashed color-mix(in srgb, var(--ink) 18%, transparent);
  border-radius: var(--radius-card);
  background: var(--surface-subtle);
  transition:
    border-color var(--duration-fast) var(--ease-out),
    background-color var(--duration-fast) var(--ease-out),
    box-shadow var(--duration-fast) var(--ease-out);
}

.feedback-dropzone:hover:not(.has-file),
.feedback-dropzone.is-dragging {
  border-color: var(--accent);
  background: color-mix(in srgb, var(--accent) 6%, var(--surface-subtle));
}

.feedback-dropzone:focus-within {
  border-color: var(--accent);
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--accent) 16%, transparent);
}

.feedback-dropzone.has-file {
  border-style: solid;
  border-color: color-mix(in srgb, var(--accent) 26%, var(--line));
  background: var(--paper);
}

.feedback-dropzone.has-error {
  border-color: color-mix(in srgb, var(--danger) 50%, var(--line));
}

.feedback-file-sr {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip: rect(0 0 0 0);
  white-space: nowrap;
  border: 0;
}

.feedback-dropzone-empty {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 16px 18px;
  cursor: pointer;
}

.feedback-dropzone-icon {
  display: grid;
  place-items: center;
  width: 38px;
  height: 38px;
  flex: 0 0 38px;
  border-radius: var(--radius-control);
  border: 1px solid var(--line);
  background: var(--paper);
  color: var(--accent);
  box-shadow: var(--specular-top);
}

.feedback-dropzone-icon svg {
  width: 18px;
  height: 18px;
  fill: none;
  stroke: currentColor;
  stroke-width: 1.75;
  stroke-linecap: round;
  stroke-linejoin: round;
}

.feedback-dropzone-copy {
  display: grid;
  gap: 2px;
  min-width: 0;
}

.feedback-dropzone-copy strong {
  font-size: 13px;
  font-weight: 560;
  color: var(--ink);
}

.feedback-dropzone-copy span {
  font-size: 12px;
  color: var(--muted);
}

.feedback-file-preview {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 12px;
  flex-wrap: wrap;
}

.feedback-file-thumb {
  width: 52px;
  height: 52px;
  flex: 0 0 52px;
  border-radius: 7px;
  object-fit: cover;
  border: 1px solid var(--line);
  background: var(--surface-subtle);
}

.feedback-file-meta {
  display: grid;
  gap: 2px;
  flex: 1 1 140px;
  min-width: 0;
}

.feedback-file-name {
  font-size: 13px;
  font-weight: 560;
  color: var(--ink);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.feedback-file-size {
  font-size: 11.5px;
  color: var(--muted);
  font-variant-numeric: tabular-nums;
}

.feedback-file-actions {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}

.feedback-chip-btn {
  min-height: 30px;
  padding: 4px 10px;
  font-size: 12px;
  border-radius: 7px;
}

.feedback-chip-btn.is-danger {
  color: var(--danger);
  border-color: color-mix(in srgb, var(--danger) 30%, var(--line));
}

.feedback-chip-btn.is-danger:hover:not(:disabled) {
  background: var(--danger-soft);
  border-color: color-mix(in srgb, var(--danger) 48%, var(--line));
}

.feedback-file-alert {
  margin: 2px 0 0;
}

.feedback-privacy-note {
  display: flex;
  align-items: flex-start;
  gap: 7px;
  margin: 0;
  font-size: 12px;
  line-height: 1.55;
  color: var(--muted);
}

.feedback-privacy-note svg {
  width: 14px;
  height: 14px;
  margin-top: 2px;
  flex: none;
  fill: none;
  stroke: currentColor;
  stroke-width: 1.75;
  stroke-linecap: round;
  stroke-linejoin: round;
  opacity: 0.8;
}

/* Form footer */
.feedback-form-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  padding-top: 14px;
  border-top: 1px solid var(--line);
}

.feedback-footer-tip {
  font-size: 12px;
  color: var(--muted);
}

.feedback-actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 10px;
  flex-wrap: wrap;
}

.feedback-submit-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 7px;
  min-width: 118px;
  padding: 9px 18px;
}

.feedback-submit-btn svg {
  width: 15px;
  height: 15px;
  fill: none;
  stroke: currentColor;
  stroke-width: 1.8;
  stroke-linecap: round;
  stroke-linejoin: round;
}

/* Loading skeleton */
.feedback-loading {
  display: grid;
  gap: 10px;
}

.feedback-skeleton-row {
  height: 68px;
  border-radius: var(--radius-card);
  border: 1px solid var(--line);
  background: linear-gradient(
    90deg,
    var(--surface-subtle) 0%,
    color-mix(in srgb, var(--accent) 7%, var(--surface-subtle)) 50%,
    var(--surface-subtle) 100%
  );
  background-size: 200% 100%;
  animation: skeleton-shimmer 1.6s ease-in-out infinite;
}

.feedback-loading-label {
  margin: 0;
  font-size: 12.5px;
  color: var(--muted);
  text-align: center;
}

/* Empty state */
.feedback-empty {
  display: grid;
  justify-items: center;
  text-align: center;
  gap: 10px;
  padding: 28px 16px 24px;
  border: 0;
  background: transparent;
}

.feedback-empty h3 {
  margin: 4px 0 0;
  font-size: 15px;
  font-weight: 600;
  color: var(--ink);
}

.feedback-empty p {
  margin: 0;
  max-width: 34ch;
  font-size: 12.5px;
  line-height: 1.65;
  color: var(--muted);
}

.feedback-flow-rail {
  display: flex;
  align-items: center;
  justify-content: center;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 6px;
}

.feedback-flow-step {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 4px 9px;
  border-radius: var(--radius-pill);
  border: 1px solid var(--line);
  background: var(--paper);
  font-size: 11.5px;
  color: var(--muted);
}

.feedback-flow-step b {
  display: inline-grid;
  place-items: center;
  width: 16px;
  height: 16px;
  border-radius: 999px;
  background: var(--accent-soft);
  color: var(--accent);
  font-size: 10.5px;
  font-weight: 650;
}

.feedback-flow-sep {
  font-size: 11px;
  color: var(--ink-tertiary);
}

/* Feedback list */
.feedback-list {
  display: grid;
  gap: 10px;
  list-style: none;
  padding: 0;
  margin: 0;
}

.feedback-item {
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 13px 15px;
  border: 1px solid var(--line);
  border-radius: var(--radius-card);
  background: var(--paper);
  box-shadow: var(--specular-top);
  text-align: start;
}

.feedback-item:hover:not(:disabled) {
  border-color: color-mix(in srgb, var(--accent) 42%, var(--line-strong));
  background: color-mix(in srgb, var(--accent) 4%, var(--paper));
  transform: translateY(-1px);
}

.feedback-item[aria-current="true"] {
  background: var(--accent-soft);
  border-color: color-mix(in srgb, var(--accent) 55%, var(--line));
}

.feedback-item-main {
  display: grid;
  gap: 8px;
  flex: 1;
  min-width: 0;
}

.feedback-item-top {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 10px;
}

.feedback-item-title {
  font-size: 14px;
  font-weight: 580;
  line-height: 1.45;
  color: var(--ink);
  overflow-wrap: anywhere;
}

.feedback-item-meta {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
}

.feedback-mini-pill {
  min-height: 21px;
  padding: 0 8px;
  font-size: 11px;
}

.feedback-item-time {
  font-size: 12px;
  color: var(--muted);
  font-variant-numeric: tabular-nums;
}

.feedback-item-arrow {
  width: 16px;
  height: 16px;
  flex: none;
  fill: none;
  stroke: var(--muted);
  stroke-width: 1.8;
  stroke-linecap: round;
  stroke-linejoin: round;
  opacity: 0.7;
  transition: transform var(--duration-fast) var(--ease-out), opacity var(--duration-fast) var(--ease-out);
}

.feedback-item:hover .feedback-item-arrow {
  transform: translateX(2px);
  opacity: 1;
}

/* Pagination */
.feedback-pagination {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding-top: 12px;
  border-top: 1px solid var(--line);
}

.feedback-page-indicator {
  font-size: 12.5px;
  color: var(--muted);
  font-variant-numeric: tabular-nums;
}

/* Detail view */
.feedback-detail-hero {
  display: grid;
  gap: 10px;
}

.feedback-detail-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}

.feedback-detail-head h3 {
  margin: 0;
  font-size: 16px;
  font-weight: 620;
  line-height: 1.45;
  color: var(--ink);
  overflow-wrap: anywhere;
}

.feedback-time-pill {
  font-variant-numeric: tabular-nums;
}

.feedback-identifiers {
  display: grid;
  gap: 6px;
  padding: 10px 12px;
  border-radius: var(--radius-control);
  border: 1px solid var(--line);
  background: var(--surface-subtle);
}

.feedback-number {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  margin: 0;
  font-size: 12px;
  color: var(--muted);
  overflow-wrap: anywhere;
}

.feedback-number code {
  font-family: var(--font-mono);
  font-size: 11.5px;
  color: var(--ink);
  overflow-wrap: anywhere;
}

.feedback-copy-btn {
  margin-left: auto;
  min-height: 24px;
  padding: 2px 8px;
  font-size: 11px;
  border-radius: 6px;
}

.feedback-body-surface {
  padding: 14px 16px;
  border-radius: var(--radius-card);
  border: 1px solid var(--line);
  background: var(--paper);
}

.feedback-body {
  margin: 0;
  font-size: 14px;
  line-height: 1.75;
  color: var(--ink);
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}

.feedback-screenshot {
  display: grid;
  border: 1px solid var(--line);
  border-radius: var(--radius-card);
  background: var(--surface-subtle);
  overflow: hidden;
  text-decoration: none;
  transition: border-color var(--duration-fast) var(--ease-out), box-shadow var(--duration-fast) var(--ease-out);
}

.feedback-screenshot:hover {
  text-decoration: none;
  border-color: color-mix(in srgb, var(--accent) 44%, var(--line-strong));
  box-shadow: var(--shadow-card-hover);
}

.feedback-screenshot-frame {
  display: grid;
  place-items: center;
  padding: 10px;
  background: color-mix(in srgb, var(--ink) 3%, var(--surface-subtle));
}

.feedback-screenshot img {
  display: block;
  max-width: 100%;
  max-height: 300px;
  object-fit: contain;
  border-radius: 8px;
}

.feedback-screenshot-caption {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 9px 14px;
  border-top: 1px solid var(--line);
  font-size: 12px;
  color: var(--muted);
}

.feedback-screenshot-caption strong {
  color: var(--accent);
  font-weight: 560;
}

/* Replies */
.feedback-replies {
  display: grid;
  gap: 12px;
  padding-top: 16px;
  border-top: 1px solid var(--line);
}

.feedback-section-subhead {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.feedback-section-subhead h3 {
  margin: 0;
  font-size: 14px;
  font-weight: 600;
  color: var(--ink);
}

.feedback-empty-reply {
  margin: 0;
  padding: 12px 14px;
  border-radius: var(--radius-control);
  border: 1px dashed var(--line-strong);
  background: var(--surface-subtle);
  font-size: 12.5px;
  color: var(--muted);
}

.feedback-reply-list {
  display: grid;
  gap: 10px;
}

.feedback-reply {
  display: grid;
  gap: 8px;
  padding: 13px 15px;
  border-radius: var(--radius-card);
  border: 1px solid var(--line);
  border-left: 3px solid var(--accent);
  background: var(--paper);
}

.feedback-reply-meta {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  flex-wrap: wrap;
}

.feedback-reply-meta time {
  font-size: 11.5px;
  color: var(--muted);
  font-variant-numeric: tabular-nums;
}

.feedback-admin-reply-form {
  padding-top: 16px;
  border-top: 1px solid var(--line);
}

.feedback-reauth-tip {
  margin: 0;
}

/* Responsive */
@media (max-width: 960px) {
  .feedback-grid,
  .feedback-grid.is-admin.has-detail {
    grid-template-columns: minmax(0, 1fr);
  }

  .feedback-filter-bar {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .feedback-filter-actions {
    grid-column: 1 / -1;
    justify-content: flex-end;
  }
}

@media (max-width: 680px) {
  .feedback-card {
    padding: 16px;
    gap: 14px;
  }

  .feedback-card-head {
    padding-bottom: 12px;
  }

  .feedback-filter-bar {
    grid-template-columns: minmax(0, 1fr);
    padding: 12px;
  }

  .feedback-filter-actions {
    justify-content: stretch;
  }

  .feedback-filter-actions button {
    flex: 1;
  }

  .feedback-dropzone-empty {
    padding: 14px 12px;
  }

  .feedback-form-footer {
    flex-direction: column;
    align-items: stretch;
  }

  .feedback-submit-btn {
    width: 100%;
  }

  .feedback-item {
    padding: 12px;
  }

  .feedback-panel :is(input:not([type=file]), select, textarea) {
    font-size: 16px;
  }
}

@media (prefers-reduced-motion: reduce) {
  .feedback-skeleton-row {
    animation: none;
  }
}
</style>
