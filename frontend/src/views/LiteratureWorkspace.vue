<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ApiError, safeLink } from '../api'
import { literatureApi } from '../api/literature'
import PanelSwitcher from '../components/PanelSwitcher.vue'
import WorkspaceHeader from '../components/WorkspaceHeader.vue'
import type { LiteratureItem, LiteratureListResponse } from '../types'

const route = useRoute()
const router = useRouter()

const mobilePane = ref<'list' | 'detail'>('list')
const searchText = ref('')
const selectedYear = ref<number | ''>('')
const selectedTag = ref('')
const page = ref(1)
const pageSize = 20

const listing = ref<LiteratureListResponse>({
  items: [],
  total: 0,
  page: 1,
  page_size: pageSize,
  has_more: false,
  available_years: [],
  available_tags: [],
})
const listLoading = ref(false)
const listError = ref('')

const activeItem = ref<LiteratureItem | null>(null)
const detailLoading = ref(false)
const detailError = ref('')

const draftTags = ref<string[]>([])
const newTagInput = ref('')
const draftNote = ref('')
const saving = ref(false)
const saveNotice = ref('')
const saveError = ref('')
const conflictDetected = ref(false)
const bibcodeCopied = ref(false)

const deleteDialog = ref<HTMLDialogElement | null>(null)
const deleting = ref(false)
const deleteError = ref('')

let searchTimer: ReturnType<typeof setTimeout> | undefined
let copyTimer: ReturnType<typeof setTimeout> | undefined
let listToken = 0
let detailToken = 0

const routeItemId = computed(() =>
  typeof route.params.itemId === 'string' && route.params.itemId ? route.params.itemId : '',
)

const hasActiveFilter = computed(() =>
  Boolean(searchText.value.trim() || selectedYear.value !== '' || selectedTag.value),
)

const isLibraryCompletelyEmpty = computed(() =>
  !listLoading.value && !listError.value && listing.value.total === 0 && !hasActiveFilter.value,
)

const totalPages = computed(() => Math.max(1, Math.ceil((listing.value.total || 0) / pageSize)))

const suggestedTags = computed(() =>
  (listing.value.available_tags || []).filter(
    tag => !draftTags.value.some(existing => existing.toLowerCase() === tag.toLowerCase()),
  ),
)

const isDirty = computed(() => {
  if (!activeItem.value) return false
  const sameNote = draftNote.value === (activeItem.value.note || '')
  const origTags = activeItem.value.tags || []
  const sameTags =
    origTags.length === draftTags.value.length &&
    origTags.every((tag, idx) => tag === draftTags.value[idx])
  return !(sameNote && sameTags)
})

const guideSteps = [
  {
    step: '01',
    badge: 'ADS 检索',
    badgeClass: 'ui-pill-ads',
    title: '检索真实天文论文',
    summary: '在查询工作台按主题、作者、年份或 bibcode 检索 NASA ADS 书目与摘要。',
  },
  {
    step: '02',
    badge: '归档入库',
    badgeClass: 'ui-pill-gaia',
    title: '一键收藏至私有库',
    summary: '在结果栏点击「加入文献库」，或在对话中直接让助手保存指定文献。',
  },
  {
    step: '03',
    badge: '精读溯源',
    badgeClass: 'ui-pill-compute',
    title: '标签、笔记与原会话',
    summary: '清晰区分 ADS 原始摘要、模型说明与个人阅读批注，随时跳回原对话上下文。',
  },
]

function syncDraft(item: LiteratureItem | null) {
  draftTags.value = item ? [...(item.tags || [])] : []
  draftNote.value = item?.note || ''
  newTagInput.value = ''
  saveNotice.value = ''
  saveError.value = ''
  conflictDetected.value = false
  deleteError.value = ''
  bibcodeCopied.value = false
}

function formatUtc(value: string | null | undefined) {
  if (!value) return '未知'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

async function copyBibcode(code: string) {
  try {
    await navigator.clipboard.writeText(code)
    bibcodeCopied.value = true
    clearTimeout(copyTimer)
    copyTimer = setTimeout(() => { bibcodeCopied.value = false }, 1800)
  } catch { /* Ignore clipboard denial. */ }
}

function originConversationTarget(item: LiteratureItem) {
  const origin = item.origin
  if (!origin?.source_available) return null
  if (origin.conversation_id) {
    return { path: `/conversations/${encodeURIComponent(origin.conversation_id)}` }
  }
  if (origin.project_id && origin.snapshot_id) {
    return {
      path: '/',
      query: { project: origin.project_id, snapshot: origin.snapshot_id },
    }
  }
  return null
}

async function fetchList(resetPage = false) {
  if (resetPage) page.value = 1
  const token = ++listToken
  listLoading.value = true
  listError.value = ''
  try {
    const result = await literatureApi.list({
      q: searchText.value,
      year: selectedYear.value === '' ? null : Number(selectedYear.value),
      tag: selectedTag.value,
      page: page.value,
      pageSize,
    })
    if (token !== listToken) return
    listing.value = result
    const rows = result.items || []
    if (!routeItemId.value && rows.length > 0 && !activeItem.value) {
      await openItem(rows[0]!.id, false)
    }
  } catch (reason) {
    if (token !== listToken) return
    listError.value = reason instanceof Error ? reason.message : '无法加载文献库列表。'
  } finally {
    if (token === listToken) listLoading.value = false
  }
}

async function loadDetail(itemId: string) {
  const token = ++detailToken
  detailLoading.value = true
  detailError.value = ''
  try {
    const item = await literatureApi.detail(itemId)
    if (token !== detailToken) return
    activeItem.value = item
    syncDraft(item)
  } catch (reason) {
    if (token !== detailToken) return
    activeItem.value = null
    syncDraft(null)
    detailError.value = reason instanceof Error ? reason.message : '无法加载文献详情。'
  } finally {
    if (token === detailToken) detailLoading.value = false
  }
}

async function openItem(itemId: string, switchMobile = true) {
  if (switchMobile) mobilePane.value = 'detail'
  if (routeItemId.value !== itemId) {
    await router.push(`/literature/${encodeURIComponent(itemId)}`)
  } else {
    await loadDetail(itemId)
  }
}

function addTag(explicit?: string) {
  const cleaned = (explicit ?? newTagInput.value).trim()
  if (!cleaned) return
  if (cleaned.length > 32) {
    saveError.value = '单个标签长度不能超过 32 个字符。'
    return
  }
  if (draftTags.value.length >= 20) {
    saveError.value = '单篇文献最多支持 20 个标签。'
    return
  }
  if (!draftTags.value.some(tag => tag.toLowerCase() === cleaned.toLowerCase())) {
    draftTags.value = [...draftTags.value, cleaned]
  }
  if (explicit === undefined) newTagInput.value = ''
  saveError.value = ''
}

function removeTag(tag: string) {
  draftTags.value = draftTags.value.filter(item => item !== tag)
}

function toggleFilterTag(tag: string) {
  selectedTag.value = selectedTag.value === tag ? '' : tag
  void fetchList(true)
}

function clearFilters() {
  searchText.value = ''
  selectedYear.value = ''
  selectedTag.value = ''
  void fetchList(true)
}

async function saveMetadata() {
  if (!activeItem.value || saving.value) return
  if (newTagInput.value.trim()) addTag()
  saving.value = true
  saveNotice.value = ''
  saveError.value = ''
  conflictDetected.value = false
  try {
    const updated = await literatureApi.update(activeItem.value.id, {
      expected_revision: activeItem.value.revision,
      tags: draftTags.value,
      note: draftNote.value,
    })
    activeItem.value = updated
    syncDraft(updated)
    saveNotice.value = '个人标签与备注已保存。'
    void fetchList(false)
  } catch (reason) {
    if (reason instanceof ApiError && reason.status === 409) {
      conflictDetected.value = true
      saveError.value = reason.message || '该文献已在其他标签页更新，请重新载入最新版本后再保存。'
    } else {
      saveError.value = reason instanceof Error ? reason.message : '保存整理信息失败。'
    }
  } finally {
    saving.value = false
  }
}

function requestDelete() {
  deleteError.value = ''
  deleteDialog.value?.showModal()
}

function closeDeleteDialog() {
  deleteDialog.value?.close()
}

async function confirmDelete() {
  if (!activeItem.value || deleting.value) return
  deleting.value = true
  deleteError.value = ''
  const target = activeItem.value
  try {
    await literatureApi.remove(target.id, target.revision)
    deleteDialog.value?.close()
    activeItem.value = null
    syncDraft(null)
    mobilePane.value = 'list'
    await router.replace('/literature')
    await fetchList(false)
  } catch (reason) {
    deleteError.value = reason instanceof Error ? reason.message : '移除文献失败。'
  } finally {
    deleting.value = false
  }
}

watch(searchText, () => {
  clearTimeout(searchTimer)
  searchTimer = setTimeout(() => {
    void fetchList(true)
  }, 260)
})

watch(selectedYear, () => {
  void fetchList(true)
})

watch(routeItemId, id => {
  if (id) {
    void loadDetail(id)
  } else {
    activeItem.value = null
    syncDraft(null)
  }
}, { immediate: true })

onMounted(() => {
  void fetchList(false)
})

onBeforeUnmount(() => {
  clearTimeout(searchTimer)
  clearTimeout(copyTimer)
})
</script>

<template>
  <div class="workbench workspace-panes literature-workspace" :data-mobile-pane="mobilePane">
    <WorkspaceHeader title="个人天文文献库" />

    <PanelSwitcher
      v-model="mobilePane"
      class="lit-mobile-switcher"
      label="文献视图切换"
      :options="[
        { value: 'list', label: `文献列表 (${listing.total})` },
        { value: 'detail', label: '文献详情' },
      ]"
    />

    <div class="lit-layout">
      <!-- Left Frosted Rail -->
      <aside class="lit-list-pane" aria-label="文献列表与筛选">
        <header class="lit-pane-header">
          <div class="lit-pane-title-group">
            <h1>文献管理</h1>
            <span class="lit-count-pill">{{ listing.total }} 篇</span>
          </div>
          <button
            type="button"
            class="lit-icon-btn"
            :class="{ 'is-spinning': listLoading }"
            :disabled="listLoading"
            aria-label="刷新文献库"
            title="刷新文献库"
            @click="fetchList(false)"
          >
            <svg viewBox="0 0 24 24" aria-hidden="true">
              <path d="M21 12a9 9 0 1 1-2.64-6.36L21 8" />
              <path d="M21 3v5h-5" />
            </svg>
          </button>
        </header>

        <div class="lit-filters">
          <label class="lit-search-field">
            <span class="sr-only">搜索文献</span>
            <svg class="lit-search-icon" viewBox="0 0 24 24" aria-hidden="true">
              <circle cx="11" cy="11" r="7" />
              <path d="m20 20-3.5-3.5" />
            </svg>
            <input
              v-model="searchText"
              type="search"
              placeholder="搜索标题、作者、bibcode、标签…"
              autocomplete="off"
            />
            <button
              v-if="searchText"
              type="button"
              class="lit-search-clear"
              aria-label="清空搜索"
              @click="searchText = ''"
            >
              ×
            </button>
          </label>

          <div class="lit-filter-bar">
            <label class="lit-year-pill">
              <svg viewBox="0 0 24 24" aria-hidden="true">
                <rect x="3" y="5" width="18" height="16" rx="3" />
                <path d="M16 3v4M8 3v4M3 10h18" />
              </svg>
              <span class="lit-year-label">年份</span>
              <select v-model="selectedYear" aria-label="按年份筛选">
                <option value="">全部</option>
                <option v-for="yr in listing.available_years || []" :key="yr" :value="yr">{{ yr }}</option>
              </select>
            </label>

            <button
              v-if="hasActiveFilter"
              type="button"
              class="lit-reset-link"
              @click="clearFilters"
            >
              重置筛选
            </button>
          </div>

          <div v-if="(listing.available_tags || []).length" class="lit-tag-bar" role="group" aria-label="按标签筛选">
            <button
              v-for="tag in listing.available_tags || []"
              :key="tag"
              type="button"
              class="lit-filter-chip"
              :class="{ active: selectedTag === tag }"
              :aria-pressed="selectedTag === tag"
              @click="toggleFilterTag(tag)"
            >
              # {{ tag }}
            </button>
          </div>
        </div>

        <p v-if="listError" class="lit-side-alert" role="alert">{{ listError }}</p>

        <div class="lit-list-scroll" :aria-busy="listLoading">
          <div v-if="listLoading && !(listing.items || []).length" class="lit-list-skeleton" role="status">
            <div v-for="n in 3" :key="n" class="lit-skeleton-card" aria-hidden="true">
              <span class="sk-line sk-short" />
              <span class="sk-line sk-full" />
              <span class="sk-line sk-mid" />
            </div>
          </div>

          <!-- Quiet minimalist empty state in sidebar (no competing giant card) -->
          <div v-else-if="!(listing.items || []).length" class="lit-list-quiet-empty">
            <div class="lit-quiet-icon" aria-hidden="true">
              <svg viewBox="0 0 24 24">
                <path d="M4 19.5v-15A2.5 2.5 0 0 1 6.5 2H20v20H6.5a2.5 2.5 0 0 1 0-5H20" />
              </svg>
            </div>
            <strong>{{ hasActiveFilter ? '没有匹配的文献' : '尚未收藏文献' }}</strong>
            <p>
              {{
                hasActiveFilter
                  ? '可尝试放宽关键词、年份或标签条件。'
                  : '在工作台检索 NASA ADS 后即可一键收入私有库。'
              }}
            </p>
            <button v-if="hasActiveFilter" type="button" class="lit-quiet-action" @click="clearFilters">
              清空筛选条件
            </button>
          </div>

          <ul v-else class="lit-items">
            <li v-for="item in listing.items || []" :key="item.id">
              <button
                type="button"
                class="lit-row"
                :class="{ active: activeItem?.id === item.id }"
                :aria-current="activeItem?.id === item.id ? 'true' : undefined"
                @click="openItem(item.id)"
              >
                <div class="lit-row-top">
                  <span class="lit-row-year">{{ item.year || '年份未知' }}</span>
                  <span class="lit-row-bib">{{ item.bibcode }}</span>
                  <span v-if="item.citation_count != null" class="lit-row-cite">被引 {{ item.citation_count }}</span>
                </div>
                <strong class="lit-row-title">{{ item.title || '未提供标题' }}</strong>
                <p class="lit-row-authors">
                  {{ item.authors?.slice(0, 3).join('、') || '作者未提供' }}{{ (item.authors?.length || 0) > 3 ? ' 等' : '' }}
                </p>
                <div v-if="item.tags?.length" class="lit-row-tags">
                  <span v-for="tag in item.tags.slice(0, 3)" :key="tag" class="lit-tag-mini"># {{ tag }}</span>
                  <span v-if="item.tags.length > 3" class="lit-tag-mini">+{{ item.tags.length - 3 }}</span>
                </div>
              </button>
            </li>
          </ul>
        </div>

        <footer v-if="listing.total > pageSize" class="lit-pagination">
          <button type="button" class="lit-page-btn" :disabled="page <= 1 || listLoading" @click="page--; fetchList(false)">上一页</button>
          <span class="lit-page-num">{{ page }} / {{ totalPages }}</span>
          <button type="button" class="lit-page-btn" :disabled="page >= totalPages || listLoading" @click="page++; fetchList(false)">下一页</button>
        </footer>
      </aside>

      <!-- Right Studio Reading Pane -->
      <main class="lit-detail-pane" aria-label="文献详情与个人笔记">
        <!-- Unified 56px Top Bar aligned 1:1 with left rail -->
        <header class="lit-detail-bar">
          <template v-if="activeItem">
            <div class="lit-detail-bar-meta">
              <span class="ui-pill ui-pill-ads">{{ activeItem.year || '年份未知' }}</span>
              <button
                type="button"
                class="lit-bib-copy"
                :title="bibcodeCopied ? '已复制 Bibcode' : '点击复制 Bibcode'"
                @click="copyBibcode(activeItem.bibcode)"
              >
                <code>{{ activeItem.bibcode }}</code>
                <span>{{ bibcodeCopied ? '已复制 ✓' : '复制' }}</span>
              </button>
              <span v-if="activeItem.citation_count != null" class="lit-bar-cite">被引 {{ activeItem.citation_count }}</span>
            </div>
            <div class="lit-detail-bar-actions">
              <a
                v-if="safeLink(activeItem.source.url)"
                :href="safeLink(activeItem.source.url)!"
                class="lit-bar-link is-ads"
                target="_blank"
                rel="noopener noreferrer"
              >
                ADS 原始记录 ↗
              </a>
              <a
                v-for="(doiUrl, idx) in (activeItem.doi_urls || []).slice(0, 1)"
                :key="doiUrl"
                :href="doiUrl"
                class="lit-bar-link"
                target="_blank"
                rel="noopener noreferrer"
              >
                DOI {{ activeItem.doi?.[idx] || '' }} ↗
              </a>
              <button type="button" class="lit-bar-danger" @click="requestDelete">移除</button>
            </div>
          </template>
          <template v-else>
            <div class="lit-detail-bar-meta">
              <span class="lit-bar-heading">个人私有文献库</span>
              <span class="lit-bar-sub">当前账号独立保存 · 来源可追溯</span>
            </div>
            <RouterLink class="lit-bar-link is-ads" to="/">前往查询工作台 ↗</RouterLink>
          </template>
        </header>

        <div class="lit-detail-scroll">
          <div v-if="detailLoading" class="lit-detail-state" role="status">
            <p class="small muted">正在读取文献详情…</p>
          </div>

          <div v-else-if="detailError" class="lit-detail-state">
            <p class="notice danger" role="alert">{{ detailError }}</p>
            <button type="button" class="lit-quiet-action" @click="router.replace('/literature')">返回文献列表</button>
          </div>

          <!-- Editorial Onboarding Hero when Library is Empty -->
          <div v-else-if="!activeItem && isLibraryCompletelyEmpty" class="lit-welcome">
            <div class="lit-welcome-copy">
              <div class="ui-pill-list lit-welcome-pills">
                <span class="ui-pill ui-pill-ads">NASA ADS · 原始书目快照</span>
                <span class="ui-pill ui-pill-gaia">会话来源可追溯</span>
                <span class="ui-pill ui-pill-compute">个人标签与精读笔记</span>
              </div>
              <h2>个人天文文献库</h2>
              <p>统一沉淀你在 NASA ADS 检索到的天文学论文、摘要快照与阅读批注，随时按关键词、年份与标签回溯研究脉络。</p>
            </div>

            <div class="lit-guide-grid">
              <div v-for="step in guideSteps" :key="step.step" class="lit-guide-card">
                <div class="lit-guide-head">
                  <span class="ui-pill" :class="step.badgeClass">{{ step.badge }}</span>
                  <span class="lit-guide-num">{{ step.step }}</span>
                </div>
                <strong>{{ step.title }}</strong>
                <p>{{ step.summary }}</p>
              </div>
            </div>

            <div class="lit-welcome-cta-wrap">
              <RouterLink class="button-primary lit-welcome-cta" to="/">
                前往查询工作台检索 ADS
                <span aria-hidden="true">→</span>
              </RouterLink>
            </div>
          </div>

          <!-- Calm Empty Selection State when library has items (or active filter has 0 results) -->
          <div v-else-if="!activeItem" class="lit-detail-state">
            <div class="lit-quiet-icon is-lg" aria-hidden="true">
              <svg viewBox="0 0 24 24">
                <path d="M4 19.5v-15A2.5 2.5 0 0 1 6.5 2H20v20H6.5a2.5 2.5 0 0 1 0-5H20" />
              </svg>
            </div>
            <h3>{{ hasActiveFilter ? '当前筛选条件下无匹配文献' : '从左侧选择一篇文献' }}</h3>
            <p class="small muted">
              {{
                hasActiveFilter
                  ? '清空或放宽左侧筛选条件即可重新浏览已收藏的论文。'
                  : '选中后将在此完整呈现 ADS 书目摘要、入库来源与个人笔记。'
              }}
            </p>
          </div>

          <!-- Populated Editorial Monograph Detail View -->
          <article v-else class="lit-detail-content">
            <!-- Section 1: ADS Original Snapshot -->
            <section class="lit-glass-card lit-monograph" aria-labelledby="lit-sec-ads">
              <div class="lit-monograph-kicker">
                <span class="ui-pill ui-pill-ads">ADS 原始书目</span>
                <span v-if="activeItem.publication" class="lit-pub-name">{{ activeItem.publication }}</span>
                <span class="lit-snapshot-time">快照 {{ formatUtc(activeItem.source.retrieved_at) }}</span>
              </div>

              <h1 id="lit-sec-ads" class="lit-paper-heading">{{ activeItem.title || '未提供标题' }}</h1>

              <p class="lit-paper-authors">
                {{ activeItem.authors?.length ? activeItem.authors.join('、') : '作者未提供' }}
              </p>

              <dl class="lit-meta-strip">
                <div class="lit-meta-tile">
                  <dt>Bibcode</dt>
                  <dd><code>{{ activeItem.bibcode }}</code></dd>
                </div>
                <div class="lit-meta-tile">
                  <dt>期刊 / 出处</dt>
                  <dd>{{ activeItem.publication || '未提供' }}</dd>
                </div>
                <div class="lit-meta-tile">
                  <dt>DOI</dt>
                  <dd>
                    <template v-if="activeItem.doi?.length">
                      <code v-for="code in activeItem.doi" :key="code" class="lit-doi-code">{{ code }}</code>
                    </template>
                    <span v-else class="muted">未提供</span>
                  </dd>
                </div>
              </dl>

              <div class="lit-abstract-block">
                <div class="lit-subhead">
                  <h2>ADS 摘要快照</h2>
                </div>
                <p v-if="activeItem.abstract" class="lit-abstract-text">{{ activeItem.abstract }}</p>
                <p v-else class="small muted">ADS 原始记录未提供摘要，不推测结论。</p>
              </div>
            </section>

            <!-- Section 2: Provenance & Model Explanation -->
            <section class="lit-glass-card" aria-labelledby="lit-sec-origin">
              <div class="lit-section-head">
                <div class="lit-section-title-row">
                  <h2 id="lit-sec-origin">入库来源与模型说明</h2>
                  <span class="ui-pill ui-pill-neutral">
                    {{ activeItem.origin?.added_via === 'agent' ? '对话直接入库' : '手动加入' }}
                  </span>
                </div>
                <RouterLink
                  v-if="originConversationTarget(activeItem)"
                  class="lit-origin-pill-link"
                  :to="originConversationTarget(activeItem)!"
                >
                  返回原会话 ↗
                </RouterLink>
              </div>

              <div class="lit-origin-meta">
                <span><em>入库时间</em>{{ formatUtc(activeItem.created_at) }}</span>
                <span v-if="activeItem.origin?.query"><em>检索语句</em><code>{{ activeItem.origin.query }}</code></span>
                <span v-if="activeItem.origin?.paper_index"><em>原批次</em>#{{ activeItem.origin.paper_index }}</span>
              </div>

              <p v-if="activeItem.origin && !activeItem.origin.source_available" class="lit-origin-notice" role="status">
                来源会话已删除或不再存在，但该文献的 ADS 书目、摘要与个人标签备注仍完整保留。
              </p>

              <div v-if="activeItem.model_explanation" class="lit-model-note">
                <div class="lit-model-note-head">
                  <span class="ui-pill ui-pill-compute">模型生成说明</span>
                  <span class="small muted">非 ADS 原始字段 · 仅作相关性参考</span>
                </div>
                <p>{{ activeItem.model_explanation }}</p>
              </div>
            </section>

            <!-- Section 3: Personal Tags & Reading Notes -->
            <section class="lit-glass-card" aria-labelledby="lit-sec-personal">
              <div class="lit-section-head">
                <h2 id="lit-sec-personal">个人标签与阅读备注</h2>
                <span class="lit-rev-meta">r{{ activeItem.revision }} · 更新于 {{ formatUtc(activeItem.updated_at) }}</span>
              </div>

              <div class="lit-tags-editor">
                <div class="lit-tag-chips">
                  <span v-for="tag in draftTags" :key="tag" class="lit-tag-chip">
                    # {{ tag }}
                    <button type="button" :aria-label="`移除标签 ${tag}`" @click="removeTag(tag)">×</button>
                  </span>
                  <span v-if="!draftTags.length" class="lit-empty-inline">尚未添加标签</span>
                </div>

                <div class="lit-tag-input-row">
                  <input
                    v-model="newTagInput"
                    type="text"
                    maxlength="32"
                    placeholder="输入标签后回车添加（如：系外行星、M45、重点精读）"
                    @keydown.enter.prevent="addTag()"
                  />
                  <button type="button" class="lit-add-tag-btn" :disabled="!newTagInput.trim()" @click="addTag()">添加</button>
                </div>

                <div v-if="suggestedTags.length" class="lit-suggested-tags">
                  <span class="lit-suggest-label">已有标签：</span>
                  <button
                    v-for="tag in suggestedTags.slice(0, 8)"
                    :key="tag"
                    type="button"
                    class="lit-suggest-chip"
                    @click="addTag(tag)"
                  >
                    + {{ tag }}
                  </button>
                </div>
              </div>

              <label class="lit-note-editor">
                <span class="lit-note-head">
                  <span>个人阅读笔记</span>
                  <span class="lit-char-count">{{ draftNote.length }} / 4000</span>
                </span>
                <textarea
                  v-model="draftNote"
                  rows="5"
                  maxlength="4000"
                  placeholder="记录研究结论、观测方法、关键物理参数或待核对问题…"
                />
              </label>

              <p v-if="saveNotice" class="lit-save-feedback is-success" role="status">{{ saveNotice }}</p>
              <div v-if="saveError" class="lit-save-feedback is-danger" role="alert">
                <span>{{ saveError }}</span>
                <button v-if="conflictDetected" type="button" class="lit-conflict-reload" @click="loadDetail(activeItem.id)">
                  重新载入最新版本
                </button>
              </div>

              <div class="lit-save-bar">
                <span class="lit-sync-status" :class="{ 'is-dirty': isDirty }">
                  <i aria-hidden="true" />
                  {{ isDirty ? '有未保存的更改' : '已与服务端同步' }}
                </span>
                <button
                  type="button"
                  class="button-primary lit-save-btn"
                  :disabled="saving || !isDirty"
                  @click="saveMetadata"
                >
                  {{ saving ? '正在保存…' : '保存整理信息' }}
                </button>
              </div>
            </section>
          </article>
        </div>
      </main>
    </div>

    <dialog ref="deleteDialog" class="lit-dialog" aria-labelledby="lit-delete-title" @click.self="closeDeleteDialog">
      <h2 id="lit-delete-title">确认移除该文献？</h2>
      <p class="small muted">
        将从您的个人文献库中删除「{{ activeItem?.title || activeItem?.bibcode }}」及其个人标签与备注；已有的会话记录不会被修改。
      </p>
      <p v-if="deleteError" class="lit-save-feedback is-danger" role="alert">{{ deleteError }}</p>
      <div class="lit-dialog-actions">
        <button type="button" class="lit-quiet-action" :disabled="deleting" @click="closeDeleteDialog">取消</button>
        <button type="button" class="lit-danger-confirm" :disabled="deleting" @click="confirmDelete">
          {{ deleting ? '正在移除…' : '确认移除' }}
        </button>
      </div>
    </dialog>
  </div>
</template>

<style scoped>
.literature-workspace {
  display: flex;
  flex-direction: column;
  height: 100dvh;
  min-height: 0;
  padding: var(--workspace-padding);
  gap: var(--workspace-gap);
  box-sizing: border-box;
  overflow: hidden;
}

.lit-mobile-switcher {
  display: none;
}

.lit-layout {
  flex: 1 1 auto;
  min-height: 0;
  display: grid;
  grid-template-columns: clamp(296px, 24vw, 356px) minmax(0, 1fr);
  gap: var(--workspace-gap);
}

/* Left Frosted Rail — matches ConversationSidebar */
.lit-list-pane {
  min-height: 0;
  display: flex;
  flex-direction: column;
  background: var(--surface-sidebar);
  -webkit-backdrop-filter: blur(24px) saturate(165%);
  backdrop-filter: blur(24px) saturate(165%);
  border: 1px solid var(--glass-edge);
  border-radius: var(--radius-surface);
  box-shadow: var(--glass-shadow);
  overflow: hidden;
}

/* Right Studio Canvas — matches Chat Panel */
.lit-detail-pane {
  min-height: 0;
  display: flex;
  flex-direction: column;
  background: var(--paper);
  border: 1px solid var(--glass-edge);
  border-radius: var(--radius-surface);
  box-shadow: var(--glass-shadow);
  overflow: hidden;
}

/* Unified 56px Headers across both panes */
.lit-pane-header,
.lit-detail-bar {
  flex: none;
  min-height: var(--pane-header-height);
  padding: 8px 14px 8px 18px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  border-bottom: 1px solid var(--line);
  background: var(--pane-header-bg);
}

.lit-pane-title-group {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.lit-pane-title-group h1 {
  margin: 0;
  font-size: 15px;
  font-weight: 600;
  color: var(--ink);
  white-space: nowrap;
}

.lit-count-pill {
  padding: 2px 8px;
  border-radius: var(--radius-pill);
  background: var(--accent-soft);
  color: var(--accent);
  font-size: 11.5px;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}

.lit-icon-btn {
  width: 32px;
  height: 32px;
  min-height: 32px;
  padding: 0;
  border-radius: 9px;
  border: 1px solid var(--line);
  background: color-mix(in srgb, var(--surface-card) 72%, transparent);
  box-shadow: none;
  color: var(--muted);
  display: grid;
  place-items: center;
  cursor: pointer;
  flex-shrink: 0;
  transition: border-color 160ms ease, color 160ms ease, background 160ms ease;
}

.lit-icon-btn svg {
  width: 15px;
  height: 15px;
  fill: none;
  stroke: currentColor;
  stroke-width: 1.8;
  stroke-linecap: round;
  stroke-linejoin: round;
}

.lit-icon-btn:hover:not(:disabled) {
  border-color: color-mix(in srgb, var(--accent) 45%, var(--line-strong));
  color: var(--accent);
  background: color-mix(in srgb, var(--accent) 8%, var(--surface-card));
}

.lit-icon-btn.is-spinning svg {
  animation: lit-spin 0.9s linear infinite;
}

@keyframes lit-spin {
  to { transform: rotate(360deg); }
}

/* Search & Filter Dock */
.lit-filters {
  padding: 12px 14px;
  border-bottom: 1px solid var(--line);
  display: grid;
  gap: 10px;
}

.lit-search-field {
  position: relative;
  display: flex;
  align-items: center;
}

.lit-search-icon {
  position: absolute;
  left: 11px;
  width: 15px;
  height: 15px;
  fill: none;
  stroke: var(--muted);
  stroke-width: 1.8;
  stroke-linecap: round;
  pointer-events: none;
}

.lit-search-field input {
  width: 100%;
  min-height: 36px;
  padding: 6px 30px 6px 33px;
  border-radius: 10px;
  border: 1px solid color-mix(in srgb, var(--line-strong) 82%, transparent);
  background: color-mix(in srgb, var(--surface-card) 82%, transparent);
  color: var(--ink);
  font-size: 13px;
  box-shadow: inset 0 1px 2px rgb(15 23 42 / 4%);
  transition: border-color 160ms ease, box-shadow 160ms ease, background 160ms ease;
}

.lit-search-field input:focus {
  outline: none;
  border-color: color-mix(in srgb, var(--accent) 55%, var(--line-strong));
  background: var(--surface-card);
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--accent) 14%, transparent);
}

.lit-search-clear {
  position: absolute;
  right: 6px;
  width: 22px;
  height: 22px;
  min-height: 22px;
  padding: 0;
  border: 0;
  border-radius: 999px;
  background: transparent;
  box-shadow: none;
  color: var(--muted);
  font-size: 15px;
  cursor: pointer;
  display: grid;
  place-items: center;
}

.lit-search-clear:hover {
  background: var(--hover-veil);
  color: var(--ink);
}

.lit-filter-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.lit-year-pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 0 10px;
  min-height: 30px;
  border-radius: var(--radius-pill);
  border: 1px solid color-mix(in srgb, var(--line-strong) 75%, transparent);
  background: color-mix(in srgb, var(--surface-card) 74%, transparent);
  color: var(--muted);
  font-size: 12px;
  white-space: nowrap;
}

.lit-year-pill svg {
  width: 13px;
  height: 13px;
  fill: none;
  stroke: currentColor;
  stroke-width: 1.7;
  flex-shrink: 0;
}

.lit-year-label {
  white-space: nowrap;
  flex-shrink: 0;
}

.lit-year-pill select {
  border: 0;
  padding: 2px 2px 2px 0;
  min-height: 0;
  background: transparent;
  box-shadow: none;
  color: var(--ink);
  font-size: 12px;
  font-weight: 560;
  cursor: pointer;
}

.lit-year-pill select:focus {
  outline: none;
}

.lit-reset-link {
  min-height: 26px;
  padding: 0 8px;
  border: 0;
  border-radius: var(--radius-pill);
  background: transparent;
  box-shadow: none;
  color: var(--accent);
  font-size: 12px;
  font-weight: 560;
  white-space: nowrap;
  cursor: pointer;
}

.lit-reset-link:hover {
  background: var(--accent-soft);
}

.lit-tag-bar {
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
}

.lit-filter-chip {
  min-height: 24px;
  padding: 2px 9px;
  border-radius: var(--radius-pill);
  border: 1px solid var(--line);
  background: color-mix(in srgb, var(--surface-card) 72%, transparent);
  box-shadow: none;
  color: var(--muted);
  font-size: 11.5px;
  cursor: pointer;
  transition: background 150ms ease, border-color 150ms ease, color 150ms ease;
}

.lit-filter-chip:hover {
  border-color: var(--line-strong);
  color: var(--ink);
}

.lit-filter-chip.active {
  background: var(--accent-soft);
  color: var(--accent);
  border-color: color-mix(in srgb, var(--accent) 42%, transparent);
  font-weight: 600;
}

.lit-side-alert {
  margin: 10px 14px 0;
  padding: 9px 12px;
  border-radius: 10px;
  border: 1px solid color-mix(in srgb, var(--danger) 28%, transparent);
  background: color-mix(in srgb, var(--danger-soft) 78%, transparent);
  color: var(--danger);
  font-size: 12.5px;
}

/* Sidebar List Area */
.lit-list-scroll {
  flex: 1 1 auto;
  min-height: 0;
  overflow-y: auto;
  padding: 10px 10px 14px;
  display: flex;
  flex-direction: column;
}

.lit-list-skeleton {
  display: grid;
  gap: 8px;
}

.lit-skeleton-card {
  padding: 12px;
  border-radius: 12px;
  background: color-mix(in srgb, var(--surface-card) 58%, transparent);
  display: grid;
  gap: 8px;
}

.sk-line {
  height: 10px;
  border-radius: 99px;
  background: var(--surface-tint);
}

.sk-short { width: 42%; }
.sk-mid { width: 68%; }
.sk-full { width: 92%; }

.lit-list-quiet-empty {
  margin: auto 8px;
  padding: 28px 14px;
  display: grid;
  justify-items: center;
  text-align: center;
  gap: 7px;
}

.lit-quiet-icon {
  width: 38px;
  height: 38px;
  border-radius: 11px;
  display: grid;
  place-items: center;
  color: var(--accent);
  background: color-mix(in srgb, var(--accent) 10%, var(--surface-card));
  border: 1px solid color-mix(in srgb, var(--accent) 22%, var(--line));
}

.lit-quiet-icon.is-lg {
  width: 44px;
  height: 44px;
  border-radius: 13px;
}

.lit-quiet-icon svg {
  width: 18px;
  height: 18px;
  fill: none;
  stroke: currentColor;
  stroke-width: 1.7;
  stroke-linecap: round;
  stroke-linejoin: round;
}

.lit-list-quiet-empty strong {
  font-size: 13.5px;
  font-weight: 620;
  color: var(--ink);
}

.lit-list-quiet-empty p {
  margin: 0;
  font-size: 12px;
  line-height: 1.65;
  color: var(--muted);
  max-width: 220px;
}

.lit-quiet-action {
  min-height: 30px;
  padding: 0 12px;
  border-radius: var(--radius-pill);
  border: 1px solid var(--line-strong);
  background: color-mix(in srgb, var(--surface-card) 85%, transparent);
  box-shadow: none;
  color: var(--ink);
  font-size: 12px;
  font-weight: 560;
  cursor: pointer;
}

.lit-quiet-action:hover:not(:disabled) {
  border-color: var(--accent);
  color: var(--accent);
}

.lit-items {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  gap: 6px;
}

.lit-row {
  position: relative;
  width: 100%;
  text-align: left;
  padding: 11px 12px 11px 14px;
  border-radius: 12px;
  border: 1px solid transparent;
  background: color-mix(in srgb, var(--surface-card) 56%, transparent);
  box-shadow: none;
  display: grid;
  gap: 5px;
  cursor: pointer;
  transition: background 160ms var(--ease-out), border-color 160ms var(--ease-out), box-shadow 160ms var(--ease-out);
}

.lit-row:hover {
  background: color-mix(in srgb, var(--surface-card) 84%, transparent);
  border-color: var(--line);
}

.lit-row.active {
  background: var(--surface-glass-card);
  border-color: color-mix(in srgb, var(--accent) 34%, var(--line-strong));
  box-shadow:
    inset 0 1px 0 var(--inset-highlight),
    0 6px 18px -10px color-mix(in srgb, var(--accent) 38%, rgb(15 23 42 / 18%));
}

.lit-row.active::before {
  content: '';
  position: absolute;
  left: 5px;
  top: 50%;
  transform: translateY(-50%);
  width: 3px;
  height: 22px;
  border-radius: 99px;
  background: var(--accent);
}

.lit-row-top {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 11px;
  font-variant-numeric: tabular-nums;
  min-width: 0;
}

.lit-row-year {
  padding: 1px 7px;
  border-radius: var(--radius-pill);
  background: var(--badge-ads-bg);
  color: var(--badge-ads-fg);
  font-weight: 620;
  flex-shrink: 0;
}

.lit-row-bib {
  font-family: var(--font-mono);
  color: var(--muted);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.lit-row-cite {
  margin-left: auto;
  color: var(--muted);
  flex-shrink: 0;
}

.lit-row-title {
  font-size: 13.5px;
  font-weight: 600;
  line-height: 1.45;
  color: var(--ink);
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.lit-row-authors {
  margin: 0;
  font-size: 12px;
  color: var(--muted);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.lit-row-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  padding-top: 2px;
}

.lit-tag-mini {
  font-size: 11px;
  padding: 1px 7px;
  border-radius: var(--radius-pill);
  background: var(--surface-tint);
  color: var(--muted);
}

.lit-pagination {
  padding: 10px 14px;
  border-top: 1px solid var(--line);
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.lit-page-btn {
  min-height: 28px;
  padding: 0 10px;
  border-radius: var(--radius-pill);
  border: 1px solid var(--line);
  background: color-mix(in srgb, var(--surface-card) 80%, transparent);
  box-shadow: none;
  font-size: 12px;
  color: var(--ink);
}

.lit-page-num {
  font-size: 12px;
  color: var(--muted);
  font-variant-numeric: tabular-nums;
}

/* Right Detail Header Controls */
.lit-detail-bar-meta {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
}

.lit-bar-heading {
  font-size: 14.5px;
  font-weight: 600;
  color: var(--ink);
  white-space: nowrap;
}

.lit-bar-sub {
  font-size: 12px;
  color: var(--muted);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.lit-bib-copy {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  min-height: 26px;
  padding: 0 9px;
  border-radius: var(--radius-pill);
  border: 1px solid var(--line);
  background: color-mix(in srgb, var(--surface-card) 75%, transparent);
  box-shadow: none;
  color: var(--muted);
  font-size: 11.5px;
  cursor: pointer;
}

.lit-bib-copy code {
  font-family: var(--font-mono);
  font-size: 11.5px;
  color: var(--ink);
  background: transparent;
  padding: 0;
}

.lit-bib-copy:hover {
  border-color: color-mix(in srgb, var(--accent) 45%, var(--line-strong));
  color: var(--accent);
}

.lit-bar-cite {
  font-size: 12px;
  color: var(--muted);
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}

.lit-detail-bar-actions {
  display: flex;
  align-items: center;
  gap: 7px;
  flex-shrink: 0;
}

.lit-bar-link {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  min-height: 28px;
  padding: 0 11px;
  border-radius: var(--radius-pill);
  border: 1px solid var(--line);
  background: color-mix(in srgb, var(--surface-card) 78%, transparent);
  color: var(--ink);
  font-size: 12px;
  font-weight: 560;
  text-decoration: none;
  white-space: nowrap;
  transition: border-color 150ms ease, color 150ms ease, background 150ms ease;
}

.lit-bar-link.is-ads {
  border-color: var(--badge-ads-border);
  background: var(--badge-ads-bg);
  color: var(--badge-ads-fg);
}

.lit-bar-link:hover {
  border-color: color-mix(in srgb, var(--accent) 48%, var(--line-strong));
  color: var(--accent);
  text-decoration: none;
}

.lit-bar-danger {
  min-height: 28px;
  padding: 0 11px;
  border-radius: var(--radius-pill);
  border: 1px solid color-mix(in srgb, var(--danger) 28%, transparent);
  background: color-mix(in srgb, var(--danger-soft) 72%, transparent);
  box-shadow: none;
  color: var(--danger);
  font-size: 12px;
  font-weight: 560;
  cursor: pointer;
}

.lit-bar-danger:hover {
  border-color: color-mix(in srgb, var(--danger) 55%, transparent);
  background: var(--danger-soft);
}

/* Right Detail Scroll Area */
.lit-detail-scroll {
  flex: 1 1 auto;
  min-height: 0;
  overflow-y: auto;
  padding: clamp(20px, 3vw, 36px) clamp(20px, 4vw, 52px);
  display: flex;
  flex-direction: column;
}

.lit-detail-state {
  margin: auto;
  max-width: 360px;
  display: grid;
  justify-items: center;
  text-align: center;
  gap: 10px;
}

.lit-detail-state h3 {
  margin: 0;
  font-size: 15px;
  font-weight: 620;
  color: var(--ink);
}

.lit-detail-state p {
  margin: 0;
  line-height: 1.65;
}

/* Editorial Welcome View (Empty Library) */
.lit-welcome {
  width: 100%;
  max-width: 780px;
  margin: auto;
  padding: 16px 0 28px;
  display: grid;
  gap: 24px;
}

.lit-welcome-copy {
  text-align: center;
  display: grid;
  justify-items: center;
  gap: 12px;
}

.lit-welcome-pills {
  justify-content: center;
}

.lit-welcome-copy h2 {
  margin: 0;
  font-family: var(--font-editorial);
  font-size: clamp(26px, 2.4vw, 32px);
  font-weight: 600;
  letter-spacing: -0.025em;
  line-height: 1.25;
  color: var(--ink);
}

.lit-welcome-copy p {
  margin: 0;
  max-width: 560px;
  font-size: 13.5px;
  line-height: 1.75;
  color: var(--muted);
}

.lit-guide-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 14px;
}

.lit-guide-card {
  position: relative;
  display: grid;
  gap: 8px;
  padding: 16px 18px;
  border-radius: 15px;
  border: 1px solid var(--glass-edge);
  background: var(--surface-glass-card);
  -webkit-backdrop-filter: blur(18px) saturate(155%);
  backdrop-filter: blur(18px) saturate(155%);
  box-shadow: var(--shadow-card);
  overflow: hidden;
}

.lit-guide-card::before {
  content: '';
  position: absolute;
  inset: 0 16px auto 16px;
  height: 1.5px;
  background: var(--specular-sheen);
  opacity: 0.7;
  pointer-events: none;
}

.lit-guide-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.lit-guide-num {
  font-family: var(--font-mono);
  font-size: 11px;
  font-weight: 600;
  color: var(--ink-tertiary);
}

.lit-guide-card strong {
  font-size: 14px;
  font-weight: 640;
  color: var(--ink);
}

.lit-guide-card p {
  margin: 0;
  font-size: 12.5px;
  line-height: 1.65;
  color: var(--muted);
}

.lit-welcome-cta-wrap {
  display: flex;
  justify-content: center;
}

.lit-welcome-cta {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  min-height: 40px;
  padding: 0 22px;
  border-radius: var(--radius-pill);
  font-size: 13.5px;
  font-weight: 600;
  text-decoration: none;
}

.lit-welcome-cta:hover {
  text-decoration: none;
}

/* Monograph Detail Reading Content */
.lit-detail-content {
  width: 100%;
  max-width: var(--reading-max-width, 880px);
  margin: 0 auto;
  display: grid;
  gap: 16px;
}

.lit-glass-card {
  position: relative;
  padding: 20px 22px;
  border-radius: 16px;
  border: 1px solid var(--glass-edge);
  background: var(--surface-glass-card);
  -webkit-backdrop-filter: blur(18px) saturate(150%);
  backdrop-filter: blur(18px) saturate(150%);
  box-shadow: var(--shadow-card);
  display: grid;
  gap: 14px;
  overflow: hidden;
}

.lit-glass-card::before {
  content: '';
  position: absolute;
  inset: 0 18px auto 18px;
  height: 1.5px;
  background: var(--specular-sheen);
  opacity: 0.65;
  pointer-events: none;
}

.lit-monograph-kicker {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px 12px;
}

.lit-pub-name {
  font-size: 12.5px;
  font-weight: 550;
  color: var(--muted);
}

.lit-snapshot-time {
  margin-left: auto;
  font-size: 11.5px;
  color: var(--ink-tertiary);
  font-variant-numeric: tabular-nums;
}

.lit-paper-heading {
  margin: 0;
  font-family: var(--reading-font, var(--font-ui));
  font-size: clamp(19px, 1.9vw, 23px);
  font-weight: 650;
  line-height: 1.38;
  letter-spacing: -0.015em;
  color: var(--ink);
  word-break: break-word;
}

.lit-paper-authors {
  margin: 0;
  font-size: 13.5px;
  line-height: 1.65;
  color: var(--muted);
}

.lit-meta-strip {
  margin: 0;
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  border-radius: 12px;
  border: 1px solid var(--line);
  background: color-mix(in srgb, var(--surface-subtle) 65%, transparent);
  overflow: hidden;
}

.lit-meta-tile {
  padding: 10px 13px;
  display: grid;
  gap: 3px;
  min-width: 0;
  border-bottom: 0;
}

.lit-meta-tile + .lit-meta-tile {
  border-left: 1px solid var(--line);
}

.lit-meta-tile dt {
  margin: 0;
  padding: 0;
  border: 0;
  font-size: 11px;
  color: var(--muted);
}

.lit-meta-tile dd {
  margin: 0;
  padding: 0;
  border: 0;
  font-size: 12.5px;
  font-weight: 560;
  color: var(--ink);
  word-break: break-all;
}

.lit-doi-code {
  margin-right: 6px;
}

.lit-abstract-block {
  padding-top: 12px;
  border-top: 1px solid var(--line);
  display: grid;
  gap: 8px;
}

.lit-subhead h2 {
  margin: 0;
  font-size: 12.5px;
  font-weight: 640;
  letter-spacing: 0.03em;
  color: var(--muted);
}

.lit-abstract-text {
  margin: 0;
  font-family: var(--reading-font, var(--font-ui));
  font-size: 14px;
  line-height: 1.85;
  color: var(--ink);
  white-space: pre-wrap;
}

/* Section 2: Provenance & Model Explanation */
.lit-section-head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.lit-section-title-row {
  display: flex;
  align-items: center;
  gap: 8px;
}

.lit-section-head h2 {
  margin: 0;
  font-size: 15px;
  font-weight: 640;
  color: var(--ink);
}

.lit-rev-meta {
  font-size: 11.5px;
  color: var(--muted);
  font-variant-numeric: tabular-nums;
}

.lit-origin-pill-link {
  display: inline-flex;
  align-items: center;
  min-height: 28px;
  padding: 0 11px;
  border-radius: var(--radius-pill);
  border: 1px solid color-mix(in srgb, var(--accent) 32%, var(--line));
  background: var(--accent-soft);
  color: var(--accent);
  font-size: 12px;
  font-weight: 600;
  text-decoration: none;
}

.lit-origin-pill-link:hover {
  border-color: var(--accent);
  text-decoration: none;
}

.lit-origin-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 18px;
  font-size: 12.5px;
  color: var(--ink);
}

.lit-origin-meta em {
  font-style: normal;
  color: var(--muted);
  margin-right: 6px;
}

.lit-origin-notice {
  margin: 0;
  padding: 9px 12px;
  border-radius: 10px;
  background: color-mix(in srgb, var(--surface-subtle) 75%, transparent);
  border: 1px solid var(--line);
  font-size: 12.5px;
  color: var(--muted);
}

.lit-model-note {
  padding: 13px 15px;
  border-radius: 12px;
  background: color-mix(in srgb, var(--badge-compute-bg) 72%, var(--surface-card));
  border: 1px solid var(--badge-compute-border);
  display: grid;
  gap: 7px;
}

.lit-model-note-head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}

.lit-model-note p {
  margin: 0;
  font-size: 13.5px;
  line-height: 1.7;
  color: var(--ink);
  white-space: pre-wrap;
}

/* Section 3: Personal Tags & Reading Notes */
.lit-tags-editor {
  display: grid;
  gap: 10px;
}

.lit-tag-chips {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
}

.lit-empty-inline {
  font-size: 12px;
  color: var(--muted);
}

.lit-tag-chip {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 3px 8px 3px 11px;
  border-radius: var(--radius-pill);
  border: 1px solid color-mix(in srgb, var(--accent) 26%, transparent);
  background: var(--accent-soft);
  color: var(--accent);
  font-size: 12.5px;
  font-weight: 560;
}

.lit-tag-chip button {
  padding: 0 3px;
  min-height: 0;
  border: 0;
  background: transparent;
  box-shadow: none;
  color: inherit;
  cursor: pointer;
  font-size: 14px;
  line-height: 1;
}

.lit-tag-input-row {
  display: flex;
  gap: 8px;
}

.lit-tag-input-row input {
  flex: 1 1 auto;
  min-height: 36px;
  padding: 6px 12px;
  border-radius: 10px;
  border: 1px solid color-mix(in srgb, var(--line-strong) 82%, transparent);
  background: color-mix(in srgb, var(--surface-card) 85%, transparent);
  color: var(--ink);
  font-size: 13px;
}

.lit-add-tag-btn {
  min-height: 36px;
  padding: 0 14px;
  border-radius: 10px;
  border: 1px solid var(--line-strong);
  background: color-mix(in srgb, var(--surface-card) 85%, transparent);
  box-shadow: none;
  color: var(--ink);
  font-size: 12.5px;
  font-weight: 560;
  cursor: pointer;
}

.lit-add-tag-btn:hover:not(:disabled) {
  border-color: var(--accent);
  color: var(--accent);
}

.lit-suggested-tags {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
}

.lit-suggest-label {
  font-size: 11.5px;
  color: var(--muted);
}

.lit-suggest-chip {
  min-height: 23px;
  padding: 0 8px;
  border-radius: var(--radius-pill);
  border: 1px dashed var(--line-strong);
  background: transparent;
  box-shadow: none;
  color: var(--muted);
  font-size: 11.5px;
  cursor: pointer;
}

.lit-suggest-chip:hover {
  border-style: solid;
  border-color: var(--accent);
  color: var(--accent);
  background: var(--accent-soft);
}

.lit-note-editor {
  display: grid;
  gap: 6px;
}

.lit-note-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 12.5px;
  font-weight: 560;
  color: var(--muted);
}

.lit-char-count {
  font-size: 11.5px;
  font-weight: 500;
  font-variant-numeric: tabular-nums;
}

.lit-note-editor textarea {
  width: 100%;
  box-sizing: border-box;
  padding: 12px 14px;
  border-radius: 12px;
  border: 1px solid color-mix(in srgb, var(--line-strong) 82%, transparent);
  background: color-mix(in srgb, var(--surface-card) 86%, transparent);
  color: var(--ink);
  font-family: var(--reading-font, var(--font-ui));
  font-size: 13.5px;
  line-height: 1.72;
  resize: vertical;
}

.lit-note-editor textarea:focus {
  outline: none;
  border-color: color-mix(in srgb, var(--accent) 55%, var(--line-strong));
  background: var(--surface-card);
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--accent) 14%, transparent);
}

.lit-save-feedback {
  margin: 0;
  padding: 9px 12px;
  border-radius: 10px;
  font-size: 12.5px;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}

.lit-save-feedback.is-success {
  border: 1px solid color-mix(in srgb, var(--success) 26%, transparent);
  background: color-mix(in srgb, var(--success-soft) 78%, transparent);
  color: var(--success);
}

.lit-save-feedback.is-danger {
  border: 1px solid color-mix(in srgb, var(--danger) 28%, transparent);
  background: color-mix(in srgb, var(--danger-soft) 78%, transparent);
  color: var(--danger);
}

.lit-save-bar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding-top: 6px;
  border-top: 1px solid var(--line);
}

.lit-sync-status {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  font-size: 12px;
  color: var(--muted);
}

.lit-sync-status i {
  width: 7px;
  height: 7px;
  border-radius: 999px;
  background: var(--success);
}

.lit-sync-status.is-dirty {
  color: var(--warning);
  font-weight: 560;
}

.lit-sync-status.is-dirty i {
  background: var(--warning);
}

.lit-save-btn {
  min-height: 36px;
  padding: 0 18px;
  border-radius: var(--radius-pill);
  font-size: 13px;
}

.lit-conflict-reload {
  min-height: 26px;
  padding: 0 10px;
  border-radius: var(--radius-pill);
  font-size: 12px;
}

/* Delete Dialog */
.lit-dialog {
  max-width: 420px;
  width: calc(100vw - 32px);
  padding: 22px 24px;
  border: 1px solid var(--line-strong);
  border-radius: var(--radius-dialog);
  background: var(--surface-glass-float);
  -webkit-backdrop-filter: blur(24px) saturate(160%);
  backdrop-filter: blur(24px) saturate(160%);
  color: var(--ink);
  box-shadow: var(--shadow-float);
}

.lit-dialog::backdrop {
  background: rgb(8 14 24 / 42%);
  backdrop-filter: blur(4px);
}

.lit-dialog h2 {
  margin: 0 0 8px;
  font-size: 16.5px;
}

.lit-dialog-actions {
  margin-top: 18px;
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}

.lit-danger-confirm {
  min-height: 34px;
  padding: 0 16px;
  border-radius: var(--radius-pill);
  background: var(--danger);
  color: #fff;
  border: 1px solid var(--danger);
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
}

.sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  border: 0;
}

@media (max-width: 1120px) {
  .lit-guide-grid {
    grid-template-columns: 1fr;
  }

  .lit-meta-strip {
    grid-template-columns: 1fr;
  }

  .lit-meta-tile + .lit-meta-tile {
    border-left: 0;
    border-top: 1px solid var(--line);
  }
}

@media (max-width: 980px) {
  .lit-mobile-switcher {
    display: flex;
  }

  .lit-layout {
    grid-template-columns: 1fr;
  }

  .literature-workspace[data-mobile-pane='list'] .lit-detail-pane {
    display: none;
  }

  .literature-workspace[data-mobile-pane='detail'] .lit-list-pane {
    display: none;
  }
}
</style>
