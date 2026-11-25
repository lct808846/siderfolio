<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { sessionFetch } from '../session-http'
import StatusNotice from './StatusNotice.vue'

export interface ArtifactPreviewItem {
  id: string
  name: string
  subtitle?: string
  category?: 'image' | 'pdf' | 'table' | 'code' | 'json' | 'text' | 'binary'
  mediaType?: string
  url?: string
  blob?: Blob
  text?: string
  loadBlob?: () => Promise<Blob>
  onDownload?: () => Promise<void> | void
}

const props = defineProps<{
  items: ArtifactPreviewItem[]
  initialId?: string
  compact?: boolean
}>()

const activeId = ref('')
const loading = ref(false)
const loadError = ref('')
const objectUrl = ref('')
const resolvedText = ref('')
const copied = ref(false)
const zoomDialog = ref<HTMLDialogElement | null>(null)
const tablePage = ref(0)

let loadToken = 0
let copyTimer: ReturnType<typeof setTimeout> | undefined

function inferCategory(item: ArtifactPreviewItem): NonNullable<ArtifactPreviewItem['category']> {
  if (item.category) return item.category
  const ext = (item.name.split('.').pop() || '').toLowerCase()
  const mime = (item.mediaType || '').toLowerCase()
  if (mime.startsWith('image/') || ['png', 'jpg', 'jpeg', 'webp', 'gif', 'svg'].includes(ext)) return 'image'
  if (mime === 'application/pdf' || ext === 'pdf') return 'pdf'
  if (mime === 'text/csv' || mime === 'text/tab-separated-values' || ['csv', 'tsv'].includes(ext)) return 'table'
  if (mime === 'application/json' || ext === 'json') return 'json'
  if (['py', 'plt', 'js', 'ts', 'sql', 'adql', 'sh', 'yaml', 'yml', 'toml', 'xml', 'html', 'css'].includes(ext)) return 'code'
  if (mime.startsWith('text/') || ['md', 'markdown', 'txt', 'log'].includes(ext)) return 'text'
  return item.text ? 'text' : 'binary'
}

function fileBadge(item: ArtifactPreviewItem) {
  const ext = (item.name.split('.').pop() || '').toUpperCase()
  if (ext && ext.length <= 5 && ext !== item.name.toUpperCase()) return ext
  const cat = inferCategory(item)
  if (cat === 'image') return 'IMG'
  if (cat === 'pdf') return 'PDF'
  if (cat === 'table') return 'CSV'
  if (cat === 'json') return 'JSON'
  if (cat === 'code') return 'CODE'
  return 'FILE'
}

function badgeClass(item: ArtifactPreviewItem) {
  const cat = inferCategory(item)
  if (cat === 'image') return 'is-image'
  if (cat === 'table') return 'is-data'
  if (cat === 'pdf') return 'is-pdf'
  return ''
}

const activeItem = computed(() =>
  props.items.find(item => item.id === activeId.value) || props.items[0] || null,
)
const activeCategory = computed(() => activeItem.value ? inferCategory(activeItem.value) : 'text')

function revokeUrl() {
  if (objectUrl.value) {
    URL.revokeObjectURL(objectUrl.value)
    objectUrl.value = ''
  }
}

function parseDelimited(raw: string, delimiter: string): { headers: string[]; rows: string[][] } {
  const lines = raw.replace(/\r\n/g, '\n').replace(/\r/g, '\n').split('\n').filter(line => line.trim() !== '')
  if (!lines.length) return { headers: [], rows: [] }
  const parseLine = (line: string) => {
    const out: string[] = []
    let cell = ''
    let inQuotes = false
    for (let i = 0; i < line.length; i++) {
      const ch = line[i]!
      if (inQuotes) {
        if (ch === '"' && line[i + 1] === '"') { cell += '"'; i++ }
        else if (ch === '"') inQuotes = false
        else cell += ch
      } else if (ch === '"') {
        inQuotes = true
      } else if (ch === delimiter) {
        out.push(cell.trim())
        cell = ''
      } else {
        cell += ch
      }
    }
    out.push(cell.trim())
    return out
  }
  const headers = parseLine(lines[0]!)
  const rows = lines.slice(1, 401).map(parseLine)
  return { headers, rows }
}

const parsedTable = computed(() => {
  if (activeCategory.value !== 'table' || !resolvedText.value) return null
  const ext = (activeItem.value?.name.split('.').pop() || '').toLowerCase()
  const delimiter = ext === 'tsv' || activeItem.value?.mediaType === 'text/tab-separated-values' ? '\t' : ','
  return parseDelimited(resolvedText.value, delimiter)
})

const pagedTableRows = computed(() => {
  if (!parsedTable.value) return []
  const start = tablePage.value * 25
  return parsedTable.value.rows.slice(start, start + 25)
})

const formattedText = computed(() => {
  if (!resolvedText.value) return ''
  if (activeCategory.value === 'json') {
    try { return JSON.stringify(JSON.parse(resolvedText.value), null, 2) }
    catch { return resolvedText.value }
  }
  return resolvedText.value
})

async function resolveActive(item: ArtifactPreviewItem | null) {
  const token = ++loadToken
  revokeUrl()
  resolvedText.value = ''
  loadError.value = ''
  tablePage.value = 0
  if (!item) return

  const cat = inferCategory(item)
  if (item.text !== undefined && ['table', 'code', 'json', 'text'].includes(cat) && !item.loadBlob && !item.blob) {
    resolvedText.value = item.text
    return
  }

  if (cat === 'image' && item.url && !item.blob && !item.loadBlob) {
    return
  }

  if (item.blob || item.loadBlob || item.url) {
    loading.value = true
    try {
      let blob: Blob | undefined = item.blob
      if (!blob && item.loadBlob) {
        blob = await item.loadBlob()
      } else if (!blob && item.url) {
        const res = await sessionFetch(item.url, { cache: 'no-store' })
        if (!res.ok) throw new Error(`读取文件失败（${res.status}）`)
        blob = await res.blob()
      }
      if (token !== loadToken || !blob) return
      if (cat === 'pdf') {
        const pdfBlob = blob.type === 'application/pdf' ? blob : new Blob([blob], { type: 'application/pdf' })
        objectUrl.value = URL.createObjectURL(pdfBlob)
      } else if (cat === 'image') {
        objectUrl.value = URL.createObjectURL(blob)
      } else if (['table', 'code', 'json', 'text'].includes(cat)) {
        resolvedText.value = await blob.text()
      } else {
        objectUrl.value = URL.createObjectURL(blob)
      }
    } catch (e) {
      if (token === loadToken) {
        if (item.text) resolvedText.value = item.text
        else loadError.value = e instanceof Error ? e.message : '加载预览内容失败。'
      }
    } finally {
      if (token === loadToken) loading.value = false
    }
  } else if (item.text) {
    resolvedText.value = item.text
  }
}

const effectiveImageSrc = computed(() => {
  if (!activeItem.value || activeCategory.value !== 'image') return ''
  return objectUrl.value || activeItem.value.url || ''
})

async function copyText() {
  if (!formattedText.value) return
  try {
    await navigator.clipboard.writeText(formattedText.value)
    copied.value = true
    clearTimeout(copyTimer)
    copyTimer = setTimeout(() => { copied.value = false }, 1800)
  } catch { /* Ignore clipboard errors. */ }
}

async function triggerDownload() {
  const item = activeItem.value
  if (!item) return
  if (item.onDownload) {
    await item.onDownload()
    return
  }
  const href = objectUrl.value || item.url
  if (href) {
    const anchor = document.createElement('a')
    anchor.href = href
    anchor.download = item.name
    anchor.click()
    return
  }
  if (formattedText.value) {
    const blob = new Blob([formattedText.value], { type: item.mediaType || 'text/plain;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = item.name
    anchor.click()
    setTimeout(() => URL.revokeObjectURL(url), 1000)
  }
}

watch(
  () => [props.items, props.initialId] as const,
  ([items, initialId]) => {
    if (!items.length) { activeId.value = ''; return }
    if (initialId && items.some(item => item.id === initialId)) {
      activeId.value = initialId
    } else if (!items.some(item => item.id === activeId.value)) {
      activeId.value = items[0]!.id
    }
  },
  { immediate: true },
)

watch(activeItem, item => { void resolveActive(item) }, { immediate: true })

onBeforeUnmount(() => {
  loadToken++
  clearTimeout(copyTimer)
  revokeUrl()
  zoomDialog.value?.close()
})
</script>

<template>
  <div class="afv-shell" :class="{ 'is-compact': compact }">
    <div v-if="items.length > 1" class="afv-tabs" role="tablist" aria-label="产物与文件列表">
      <button
        v-for="item in items"
        :key="item.id"
        type="button"
        role="tab"
        class="afv-tab"
        :aria-selected="activeItem?.id === item.id"
        :class="{ 'is-active': activeItem?.id === item.id }"
        @click="activeId = item.id"
      >
        <span class="ui-file-badge afv-badge" :class="badgeClass(item)">{{ fileBadge(item) }}</span>
        <span class="afv-tab-name">{{ item.name }}</span>
      </button>
    </div>

    <div v-if="activeItem" class="afv-stage">
      <header class="afv-bar">
        <div class="afv-meta">
          <span class="ui-file-badge" :class="badgeClass(activeItem)">{{ fileBadge(activeItem) }}</span>
          <div class="afv-meta-copy">
            <strong>{{ activeItem.name }}</strong>
            <small v-if="activeItem.subtitle">{{ activeItem.subtitle }}</small>
          </div>
        </div>
        <div class="afv-actions">
          <button v-if="effectiveImageSrc" type="button" class="afv-action-btn" @click="zoomDialog?.showModal()">放大</button>
          <a v-if="activeCategory === 'pdf' && objectUrl" :href="objectUrl" target="_blank" rel="noopener noreferrer" class="afv-action-btn afv-link-btn">新窗口 ↗</a>
          <button v-if="formattedText" type="button" class="afv-action-btn" @click="copyText">{{ copied ? '已复制' : '复制' }}</button>
          <button type="button" class="afv-action-btn afv-download-btn" @click="triggerDownload">下载</button>
        </div>
      </header>

      <StatusNotice v-if="loadError" title="文件预览加载失败" :message="loadError" @dismiss="loadError = ''" />

      <div v-if="loading" class="afv-loading" role="status">
        <span class="thinking-shimmer-text">正在加载文件预览…</span>
      </div>

      <p v-else-if="loadError" class="small muted">文件暂时无法预览，可尝试直接下载查看。</p>

      <div v-else-if="activeCategory === 'image' && effectiveImageSrc" class="afv-image-wrap">
        <button type="button" class="afv-image-trigger" aria-label="点击放大查看图片" @click="zoomDialog?.showModal()">
          <img :src="effectiveImageSrc" :alt="activeItem.name">
        </button>
      </div>

      <div v-else-if="activeCategory === 'pdf' && objectUrl" class="afv-pdf-wrap">
        <iframe :src="objectUrl" :title="activeItem.name" class="afv-pdf-frame" />
      </div>

      <div v-else-if="activeCategory === 'pdf' && formattedText" class="afv-text-wrap">
        <p class="afv-fallback-note">当前展示为已解析的 PDF 文本内容（原始 PDF 仅在本次上传会话内存中保留）。</p>
        <pre class="afv-code">{{ formattedText }}</pre>
      </div>

      <div v-else-if="activeCategory === 'table' && parsedTable && parsedTable.headers.length" class="afv-table-wrap">
        <div class="afv-table-summary">
          <span>{{ parsedTable.rows.length }} 行 × {{ parsedTable.headers.length }} 列</span>
          <span v-if="parsedTable.rows.length >= 400">预览前 400 行 · 点击右上角下载完整文件</span>
        </div>
        <div class="table-scroll afv-table-scroll" tabindex="0">
          <table>
            <thead>
              <tr>
                <th v-for="(header, idx) in parsedTable.headers" :key="idx">{{ header }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(row, rIdx) in pagedTableRows" :key="rIdx">
                <td v-for="(header, cIdx) in parsedTable.headers" :key="cIdx">{{ row[cIdx] ?? '' }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <div v-if="parsedTable.rows.length > 25" class="pagination afv-pagination">
          <button type="button" :disabled="tablePage === 0" @click="tablePage--">上一页</button>
          <span>{{ tablePage + 1 }} / {{ Math.ceil(parsedTable.rows.length / 25) }}</span>
          <button type="button" :disabled="(tablePage + 1) * 25 >= parsedTable.rows.length" @click="tablePage++">下一页</button>
        </div>
      </div>

      <div v-else-if="formattedText" class="afv-text-wrap">
        <pre class="afv-code">{{ formattedText }}</pre>
      </div>

      <div v-else class="afv-binary-empty">
        <p class="small muted">此格式暂不支持直接内联渲染，点击右上角「下载」即可获取原始文件。</p>
      </div>
    </div>

    <dialog ref="zoomDialog" class="plot-zoom afv-lightbox">
      <div class="afv-lightbox-head">
        <b>{{ activeItem?.name }}</b>
        <button type="button" class="dialog-close" aria-label="关闭大图预览" @click="zoomDialog?.close()">
          <svg viewBox="0 0 24 24" aria-hidden="true"><path d="m6 6 12 12M6 18 18 6" /></svg>
        </button>
      </div>
      <img v-if="effectiveImageSrc" :src="effectiveImageSrc" :alt="activeItem?.name" class="afv-lightbox-img">
    </dialog>
  </div>
</template>

<style scoped>
.afv-shell {
  display: grid;
  gap: 10px;
  min-width: 0;
}

.afv-tabs {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.afv-tab {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  min-height: 30px;
  max-width: 100%;
  padding: 4px 10px 4px 6px;
  border: 1px solid var(--line);
  border-radius: 9px;
  background: color-mix(in srgb, var(--surface-card) 66%, transparent);
  color: var(--muted);
  font-size: 12px;
  font-weight: 500;
  box-shadow: none;
  transition: background-color 140ms var(--ease-out), border-color 140ms var(--ease-out), color 140ms var(--ease-out);
}

.afv-tab:hover {
  color: var(--ink);
  border-color: color-mix(in srgb, var(--accent) 34%, var(--line-strong));
  background: color-mix(in srgb, var(--accent) 7%, var(--surface-card));
  transform: none;
}

.afv-tab.is-active {
  color: var(--accent);
  border-color: color-mix(in srgb, var(--accent) 44%, transparent);
  background: color-mix(in srgb, var(--accent) 12%, var(--surface-card));
  font-weight: 600;
}

.afv-tab-name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 170px;
}

.afv-badge {
  min-width: 28px;
  height: 18px;
  padding: 0 5px;
  font-size: 9.5px;
}

.ui-file-badge.is-pdf {
  border-color: color-mix(in srgb, var(--danger) 30%, var(--line));
  background: var(--danger-soft);
  color: var(--danger);
}

.afv-stage {
  display: grid;
  gap: 10px;
  padding: 12px;
  border: 1px solid var(--line-strong);
  border-radius: var(--radius-card);
  background: var(--specular-spot), var(--surface-glass-card);
  box-shadow: var(--shadow-card);
  min-width: 0;
}

.afv-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  flex-wrap: wrap;
  padding-bottom: 10px;
  border-bottom: 1px solid var(--line);
}

.afv-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
  flex: 1;
}

.afv-meta-copy {
  display: grid;
  min-width: 0;
  gap: 1px;
}

.afv-meta-copy strong {
  font-size: 12.5px;
  font-weight: 600;
  color: var(--ink);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.afv-meta-copy small {
  font-size: 11px;
  color: var(--muted);
}

.afv-actions {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}

.afv-action-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-height: 28px;
  padding: 3px 10px;
  border: 1px solid var(--line-strong);
  border-radius: 7px;
  background: color-mix(in srgb, var(--surface-card) 86%, transparent);
  color: var(--ink);
  font-size: 11.5px;
  font-weight: 500;
  text-decoration: none;
  box-shadow: none;
}

.afv-action-btn:hover {
  border-color: color-mix(in srgb, var(--accent) 44%, var(--line-strong));
  color: var(--accent);
  text-decoration: none;
}

.afv-download-btn {
  color: var(--accent);
  border-color: color-mix(in srgb, var(--accent) 32%, var(--line));
  background: var(--accent-soft);
}

.afv-loading {
  padding: 24px 12px;
  text-align: center;
  font-size: 13px;
}

.afv-image-wrap {
  display: grid;
}

.afv-image-trigger {
  display: block;
  width: 100%;
  padding: 8px;
  border: 1px solid var(--line);
  border-radius: 10px;
  background: #fff;
  box-shadow: none;
  cursor: zoom-in;
}

.afv-image-trigger:hover {
  border-color: color-mix(in srgb, var(--accent) 48%, var(--line-strong));
  transform: none;
}

.afv-image-trigger img {
  display: block;
  width: 100%;
  height: auto;
  max-height: 440px;
  object-fit: contain;
  border-radius: 6px;
}

.afv-pdf-wrap {
  border: 1px solid var(--line);
  border-radius: 10px;
  overflow: hidden;
  background: var(--surface-subtle);
}

.afv-pdf-frame {
  display: block;
  width: 100%;
  height: min(64dvh, 560px);
  border: 0;
  background: #fff;
}

.afv-table-wrap {
  display: grid;
  gap: 8px;
  min-width: 0;
}

.afv-table-summary {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  flex-wrap: wrap;
  font-size: 11px;
  color: var(--muted);
  font-variant-numeric: tabular-nums;
}

.afv-table-scroll {
  margin-top: 0;
  max-height: 360px;
  border-radius: 9px;
}

.afv-pagination {
  margin-top: 0;
}

.afv-text-wrap {
  display: grid;
  gap: 8px;
  min-width: 0;
}

.afv-fallback-note {
  margin: 0;
  font-size: 11.5px;
  color: var(--muted);
}

.afv-code {
  margin: 0;
  max-height: 420px;
  overflow: auto;
  padding: 12px 14px;
  border: 1px solid var(--line);
  border-radius: 9px;
  background: var(--surface-subtle);
  color: var(--ink);
  font-family: var(--font-mono);
  font-size: 11.5px;
  line-height: 1.65;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}

.afv-binary-empty {
  padding: 20px 10px;
  text-align: center;
}

.afv-lightbox {
  max-width: min(94vw, 1280px);
  max-height: 92dvh;
  padding: 16px 20px 20px;
}

.afv-lightbox-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
}

.afv-lightbox-img {
  display: block;
  max-width: 100%;
  max-height: calc(92dvh - 86px);
  background: #fff;
  border-radius: 8px;
}
</style>
