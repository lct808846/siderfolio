<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { plottingApi, savePlotFile, type PlotOperation } from '../api/plotting'
import ArtifactFileViewer, { type ArtifactPreviewItem } from './ArtifactFileViewer.vue'

const props = defineProps<{
  projectId: string
  runId?: string
  initialTitle?: string
  initialFiles?: string[]
  allowedRunIds?: string[]
}>()

const emit = defineEmits<{
  'select-run': [runId: string]
}>()

const runs = ref<PlotOperation[]>([])
const loading = ref(false)
const busy = ref(false)
const error = ref('')
const selectedRunId = ref('')

let loadToken = 0

const selectedRun = computed(() =>
  runs.value.find(item => item.id === selectedRunId.value) || runs.value[0] || null,
)

function runTitle(op: PlotOperation) {
  if (op.id === props.runId && props.initialTitle) return props.initialTitle
  const reqTitle = typeof op.request?.title === 'string' ? op.request.title : ''
  return op.proposal?.title || reqTitle || `绘图记录 ${op.id.slice(0, 8)}`
}

function runSubtitle(op: PlotOperation) {
  const parts: string[] = []
  const engine = op.proposal?.engine || (typeof op.runtime?.engine === 'string' ? op.runtime.engine : '')
  if (engine) parts.push(engine === 'gnuplot' ? 'Gnuplot' : 'Python / Matplotlib')
  if (op.completed_at || op.created_at) {
    parts.push(new Date(op.completed_at || op.created_at).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }))
  }
  return parts.join(' · ')
}

function fileDescription(name: string) {
  if (name === 'figure.png') return '高分辨率科研栅格图（300 DPI PNG）'
  if (name === 'figure.pdf') return '矢量出版级 PDF 图件（支持页内浏览）'
  if (name === 'script.py') return '独立可复现 Python / Matplotlib 脚本'
  if (name === 'script.plt') return '独立可复现 Gnuplot 脚本'
  if (name.endsWith('.csv') || name.endsWith('.tsv')) return '绘图输入数据表'
  return '隔离绘图容器产物文件'
}

function filePriority(name: string) {
  if (name === 'figure.png') return 0
  if (name === 'figure.pdf') return 1
  if (name === 'script.py' || name === 'script.plt') return 2
  return 3
}

const activeFiles = computed(() => {
  const fromRun = selectedRun.value?.files || []
  const list = fromRun.length
    ? fromRun
    : (selectedRunId.value === props.runId && props.initialFiles?.length ? props.initialFiles : [])
  return [...list].sort((a, b) => filePriority(a) - filePriority(b))
})

const effectiveRunId = computed(() => selectedRun.value?.id || props.runId || '')

const previewItems = computed<ArtifactPreviewItem[]>(() => {
  const runId = effectiveRunId.value
  if (!props.projectId || !runId) return []
  return activeFiles.value.map(name => ({
    id: `${runId}:${name}`,
    name,
    subtitle: fileDescription(name),
    loadBlob: () => plottingApi.output(props.projectId, runId, name),
    onDownload: async () => {
      const blob = await plottingApi.output(props.projectId, runId, name)
      savePlotFile(blob, name)
    },
  }))
})

async function refresh() {
  if (!props.projectId) {
    runs.value = []
    return
  }
  const token = ++loadToken
  loading.value = true
  error.value = ''
  try {
    const page = await plottingApi.page(props.projectId)
    if (token !== loadToken) return
    const allowed = props.allowedRunIds ? new Set([...props.allowedRunIds, ...(props.runId ? [props.runId] : [])]) : null
    const completedRuns = page.operations
      .filter(op => op.kind === 'run' && op.state === 'completed' && (op.files?.length || 0) > 0 && (!allowed || allowed.has(op.id)))
      .sort((a, b) => Date.parse(b.completed_at || b.created_at) - Date.parse(a.completed_at || a.created_at))
    runs.value = completedRuns
    if (props.runId && completedRuns.some(item => item.id === props.runId)) {
      selectedRunId.value = props.runId
    } else if (!selectedRunId.value || !completedRuns.some(item => item.id === selectedRunId.value)) {
      selectedRunId.value = props.runId || completedRuns[0]?.id || ''
    }
  } catch (reason) {
    if (token === loadToken) {
      error.value = reason instanceof Error ? reason.message : '无法加载科研绘图记录。'
    }
  } finally {
    if (token === loadToken) loading.value = false
  }
}

function chooseRun(id: string) {
  selectedRunId.value = id
  emit('select-run', id)
}

async function downloadBundle() {
  const runId = effectiveRunId.value
  if (!props.projectId || !runId || !activeFiles.value.length) return
  busy.value = true
  error.value = ''
  try {
    const blob = await plottingApi.bundle(props.projectId, runId, activeFiles.value)
    savePlotFile(blob, `astroagent-plot-${runId.slice(0, 8)}.zip`)
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : '打包下载失败。'
  } finally {
    busy.value = false
  }
}

async function downloadSingle(name: string) {
  const runId = effectiveRunId.value
  if (!props.projectId || !runId) return
  busy.value = true
  error.value = ''
  try {
    const blob = await plottingApi.output(props.projectId, runId, name)
    savePlotFile(blob, name)
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : `下载 ${name} 失败。`
  } finally {
    busy.value = false
  }
}

watch(
  [() => props.projectId, () => props.runId],
  ([, incomingRunId]) => {
    if (incomingRunId) selectedRunId.value = incomingRunId
    void refresh()
  },
  { immediate: true },
)
</script>

<template>
  <div class="plot-result-panel">
    <div v-if="error" class="plot-alert" role="alert">{{ error }}</div>

    <div v-if="loading && !previewItems.length" class="plot-empty-card">
      <p>正在加载科研绘图产物…</p>
    </div>

    <div v-else-if="!previewItems.length" class="plot-empty-card">
      <strong>当前空间尚无已生成的科研绘图</strong>
      <p>在对话中勾选「科研绘图」或在绘图审阅卡片点击「确认执行隔离绘图」后，高清 PNG、矢量 PDF 与独立复现脚本会直接展示在这里。</p>
    </div>

    <template v-else>
      <header class="plot-toolbar">
        <div class="plot-toolbar-top">
          <select
            v-if="runs.length > 1"
            class="plot-run-select"
            :value="effectiveRunId"
            aria-label="切换本空间科研绘图记录"
            @change="chooseRun(($event.target as HTMLSelectElement).value)"
          >
            <option v-for="run in runs" :key="run.id" :value="run.id">
              {{ runTitle(run) }} ({{ run.files?.length || 0 }} 文件)
            </option>
          </select>
          <h3 v-else class="plot-single-title">{{ selectedRun ? runTitle(selectedRun) : (initialTitle || '科研绘图产物') }}</h3>
        </div>
        <div class="plot-toolbar-bottom">
          <span v-if="selectedRun" class="plot-detail-meta">{{ runSubtitle(selectedRun) }}</span>
          <div class="plot-quick-downloads">
            <button
              v-for="name in activeFiles"
              :key="name"
              type="button"
              class="plot-dl-chip"
              :disabled="busy"
              @click="downloadSingle(name)"
            >
              ↓ {{ name }}
            </button>
            <button
              v-if="activeFiles.length > 1"
              type="button"
              class="button-primary plot-dl-chip"
              :disabled="busy"
              @click="downloadBundle"
            >
              ZIP
            </button>
          </div>
        </div>
      </header>

      <ArtifactFileViewer :items="previewItems" :initial-id="`${effectiveRunId}:figure.png`" />
    </template>
  </div>
</template>

<style scoped>
.plot-result-panel {
  display: grid;
  gap: 10px;
}

.plot-toolbar {
  display: grid;
  gap: 7px;
  padding: 10px 12px;
  border-radius: 12px;
  border: 1px solid color-mix(in srgb, var(--border-subtle) 85%, transparent);
  background: color-mix(in srgb, var(--surface-muted) 56%, transparent);
}

.plot-toolbar-top {
  display: flex;
  align-items: center;
  gap: 7px;
  min-width: 0;
}

.plot-run-select {
  flex: 1 1 auto;
  min-width: 0;
  min-height: 30px;
  padding: 3px 8px;
  border-radius: 8px;
  border: 1px solid color-mix(in srgb, var(--border-strong) 70%, transparent);
  background: color-mix(in srgb, var(--surface-card) 86%, transparent);
  color: var(--text-primary);
  font-size: 12.5px;
  font-weight: 620;
  box-shadow: none;
}

.plot-single-title {
  flex: 1 1 auto;
  margin: 0;
  min-width: 0;
  font-size: 13.5px;
  font-weight: 680;
  color: var(--text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.plot-toolbar-bottom {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
}

.plot-alert {
  padding: 9px 12px;
  border-radius: 10px;
  border: 1px solid color-mix(in srgb, var(--danger-text) 28%, transparent);
  background: color-mix(in srgb, var(--danger-bg) 70%, transparent);
  color: var(--danger-text);
  font-size: 12.5px;
}

.plot-empty-card {
  padding: 20px 16px;
  border-radius: 14px;
  border: 1px dashed var(--border-strong);
  background: color-mix(in srgb, var(--surface-muted) 45%, transparent);
  text-align: center;
  display: grid;
  gap: 6px;
}

.plot-empty-card strong {
  font-size: 13.5px;
  color: var(--text-primary);
}

.plot-empty-card p {
  margin: 0;
  font-size: 12.5px;
  color: var(--text-muted);
  line-height: 1.6;
}

.plot-detail-meta {
  margin: 0;
  font-size: 11px;
  color: var(--text-muted);
}

.plot-quick-downloads {
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
}

.plot-dl-chip {
  min-height: 25px;
  padding: 0 9px;
  border-radius: 999px;
  border: 1px solid var(--border-subtle);
  background: color-mix(in srgb, var(--surface-card) 86%, transparent);
  box-shadow: none;
  color: var(--text-secondary);
  font-size: 11px;
  font-weight: 600;
  cursor: pointer;
}

.plot-dl-chip:hover:not(:disabled) {
  border-color: var(--accent);
  color: var(--accent);
}

.plot-dl-chip.button-primary {
  background: var(--accent);
  border-color: var(--accent);
  color: #fff;
}

.plot-dl-chip.button-primary:hover:not(:disabled) {
  color: #fff;
  filter: brightness(1.06);
}
</style>
