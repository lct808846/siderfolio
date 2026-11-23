<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { ApiError } from '../api'
import { plottingApi, savePlotFile, type PlotOperation } from '../api/plotting'
import { useAttachments } from '../stores/attachments'
import { useProjects } from '../stores/projects'
import type { ChatAttachment, PlotProposalResult, Turn } from '../types'

export interface PlotResultPayload {
  kind: 'plot'
  projectId: string
  runId: string
  title: string
  files: string[]
}

const props = defineProps<{
  proposal: PlotProposalResult
  turn: Turn
  allTurns: Turn[]
  proposalIndex: number
  projectId?: string
}>()
const emit = defineEmits<{
  refine: [prompt: string]
  'open-result': [payload: PlotResultPayload]
}>()

const projectsStore = useProjects()
const attachmentsStore = useAttachments()
const storageKey = computed(() => `astroagent.chat_plot.${props.turn.turn_id}.${props.proposalIndex}`)

const editing = ref(false)
const draftTitle = ref(props.proposal.title)
const draftEngine = ref<'python' | 'gnuplot'>(props.proposal.engine || 'python')
const draftChart = ref<'scatter' | 'line' | 'histogram' | 'errorbar'>(props.proposal.chart)
const draftScript = ref(props.proposal.script)
const localCsvFile = ref<File | null>(null)
const csvPicker = ref<HTMLInputElement | null>(null)

const busy = ref(false)
const initializing = ref(false)
const needsStorageInit = ref(false)
const error = ref('')
const runOp = ref<PlotOperation | null>(null)
const runProjectId = ref('')
const figureUrl = ref('')
const zoomDialog = ref<HTMLDialogElement | null>(null)

const chartLabels: Record<string, string> = {
  scatter: '散点图',
  line: '折线图',
  histogram: '直方图',
  errorbar: '误差棒图',
}

const proposalNotes = computed(() => (props.proposal.warnings || []).filter(item => item && item.trim()))

const resolvedGaiaTurn = computed(() => {
  if (props.proposal.data_source_kind === 'current_turn_gaia') {
    const idx = props.proposal.gaia_query_index ?? 0
    const res = props.turn.response?.gaia_results?.[idx]
    if (res?.status === 'success' && res.data?.length) {
      return { turn: props.turn, queryIndex: idx, count: res.returned_count }
    }
  }
  if (props.proposal.data_source_kind === 'history_turn_gaia' || props.proposal.data_source_kind === 'current_turn_gaia') {
    const idx = props.proposal.gaia_query_index ?? 0
    if (props.proposal.source_turn_id) {
      const target = props.allTurns.find(t => t.turn_id === props.proposal.source_turn_id)
      const res = target?.response?.gaia_results?.[idx]
      if (target && res?.status === 'success' && res.data?.length) {
        return { turn: target, queryIndex: idx, count: res.returned_count }
      }
    }
    for (let i = props.allTurns.length - 1; i >= 0; i--) {
      const candidate = props.allTurns[i]!
      const list = candidate.response?.gaia_results || []
      for (let q = list.length - 1; q >= 0; q--) {
        if (list[q]?.status === 'success' && list[q]?.data?.length) {
          return { turn: candidate, queryIndex: q, count: list[q]!.returned_count }
        }
      }
    }
  }
  return null
})

const resolvedAttachment = computed<ChatAttachment | null>(() => {
  if (props.proposal.data_source_kind !== 'attachment_csv') return null
  const name = (props.proposal.attachment_filename || '').trim().toLowerCase()
  const isTabular = (att: ChatAttachment) =>
    att.media_type === 'text/csv'
    || att.media_type === 'text/tab-separated-values'
    || /\.(csv|tsv)$/i.test(att.filename)
  const pool: ChatAttachment[] = [
    ...(props.turn.attachments || []),
    ...props.allTurns.slice().reverse().flatMap(t => t.attachments || []),
  ]
  if (name) {
    const exact = pool.find(a => a.filename.toLowerCase() === name)
    if (exact) return exact
  }
  return pool.find(isTabular) || null
})

const sourceSummary = computed(() => {
  if (localCsvFile.value) return `本地数据：${localCsvFile.value.name}`
  if (props.proposal.data_source_kind === 'attachment_csv') {
    return resolvedAttachment.value
      ? `附件数据：${resolvedAttachment.value.filename}`
      : props.proposal.attachment_filename
        ? `附件数据：${props.proposal.attachment_filename}（请重新选择原 CSV/TSV 文件）`
        : '本地 CSV / TSV 数据'
  }
  if (props.proposal.data_source_kind === 'project_dataset' && props.proposal.dataset_id) {
    return `项目数据集：${props.proposal.dataset_id.slice(0, 8)}`
  }
  if (resolvedGaiaTurn.value) {
    return `Gaia DR3 查询数据（${resolvedGaiaTurn.value.count} 行）`
  }
  return '待指定数据源（可附加 CSV/TSV 或先查询 Gaia）'
})

const spaceLabel = computed(() => {
  const id = runProjectId.value || props.projectId || ''
  if (!id || id === projectsStore.defaultProjectId) return '个人空间（默认）'
  return projectsStore.labelFor(id)
})

const diagnosticText = computed(() => {
  const runtime = runOp.value?.runtime as Record<string, unknown> | undefined
  return typeof runtime?.diagnostic === 'string' ? runtime.diagnostic : ''
})

function revokeFigure() {
  if (figureUrl.value) {
    URL.revokeObjectURL(figureUrl.value)
    figureUrl.value = ''
  }
}

function resetProposal() {
  draftTitle.value = props.proposal.title
  draftEngine.value = props.proposal.engine || 'python'
  draftChart.value = props.proposal.chart
  draftScript.value = props.proposal.script
  error.value = ''
}

function onPickCsv(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (file) {
    localCsvFile.value = file
    error.value = ''
  }
  input.value = ''
}

function openInResultPanel() {
  if (!runOp.value || !runProjectId.value) return
  emit('open-result', {
    kind: 'plot',
    projectId: runProjectId.value,
    runId: runOp.value.id,
    title: draftTitle.value.trim() || props.proposal.title,
    files: [...(runOp.value.files || [])],
  })
}

async function loadFigure(projectId: string, runId: string) {
  revokeFigure()
  try {
    const blob = await plottingApi.output(projectId, runId, 'figure.png')
    figureUrl.value = URL.createObjectURL(blob)
  } catch (e) {
    error.value = e instanceof Error ? e.message : '读取生成图像失败。'
  }
}

async function initializePlotStorage() {
  if (initializing.value) return
  initializing.value = true
  error.value = ''
  try {
    await plottingApi.initialize()
    needsStorageInit.value = false
  } catch (e) {
    error.value = e instanceof Error ? e.message : '初始化绘图存储失败。'
  } finally {
    initializing.value = false
  }
}

async function confirmAndExecute() {
  if (busy.value) return
  if (!draftScript.value.trim()) {
    error.value = '绘图脚本不能为空。'
    return
  }
  busy.value = true
  error.value = ''
  needsStorageInit.value = false
  try {
    let targetProject = props.projectId || ''
    if (!targetProject) {
      const fallback = await projectsStore.ensureDefault()
      targetProject = fallback.id
    }

    let datasetId = ''
    if (localCsvFile.value) {
      const uploaded = await plottingApi.upload(targetProject, crypto.randomUUID(), localCsvFile.value)
      datasetId = uploaded.id
    } else if (props.proposal.data_source_kind === 'project_dataset' && props.proposal.dataset_id) {
      datasetId = props.proposal.dataset_id
    } else if (props.proposal.data_source_kind === 'attachment_csv') {
      const att = resolvedAttachment.value
      if (!att) {
        error.value = '未找到对应的 CSV/TSV 附件，请点击「选择本地 CSV/TSV」后重试。'
        return
      }
      const raw = attachmentsStore.rawFile(att.sha256)
      let fileToUpload: File
      if (raw) {
        fileToUpload = raw
      } else if (!att.truncated) {
        fileToUpload = new File([att.text], att.filename, { type: att.media_type })
      } else {
        error.value = `附件「${att.filename}」原始文件超过会话文本缓存，请点击「选择本地 CSV/TSV」重新选取原文件。`
        return
      }
      const uploaded = await plottingApi.upload(targetProject, crypto.randomUUID(), fileToUpload)
      datasetId = uploaded.id
    } else if (resolvedGaiaTurn.value) {
      const frozen = await plottingApi.turn(targetProject, crypto.randomUUID(), {
        conversation_id: resolvedGaiaTurn.value.turn.conversation_id,
        turn_id: resolvedGaiaTurn.value.turn.turn_id,
        query_index: resolvedGaiaTurn.value.queryIndex,
      })
      datasetId = frozen.id
    } else {
      error.value = '当前会话没有可直接绘图的 Gaia 结果或 CSV/TSV 数据，请点击「选择本地 CSV/TSV」或先让模型查询数据。'
      return
    }

    const planOp = await plottingApi.customPlan(targetProject, crypto.randomUUID(), {
      dataset_id: datasetId,
      model_id: props.turn.model || 'chat-proposal',
      question: props.turn.message,
      proposal: {
        engine: draftEngine.value,
        chart: draftChart.value,
        title: draftTitle.value.trim() || props.proposal.title,
        columns: props.proposal.columns,
        axes: props.proposal.axes || {},
        filters: props.proposal.filters || [],
        explanation: props.proposal.explanation,
        warnings: props.proposal.warnings || [],
        script: draftScript.value,
      },
    })

    const executed = await plottingApi.run(targetProject, crypto.randomUUID(), {
      plan_id: planOp.id,
      confirm_execute: true,
    })
    editing.value = false
    runProjectId.value = targetProject
    runOp.value = executed
    try {
      sessionStorage.setItem(storageKey.value, JSON.stringify({ projectId: targetProject, runId: executed.id }))
    } catch { /* Ignore storage restrictions. */ }

    if (executed.state === 'completed') {
      if ((executed.files || []).includes('figure.png')) {
        await loadFigure(targetProject, executed.id)
      }
      emit('open-result', {
        kind: 'plot',
        projectId: targetProject,
        runId: executed.id,
        title: draftTitle.value.trim() || props.proposal.title,
        files: [...(executed.files || [])],
      })
    } else if (executed.state === 'failed') {
      error.value = executed.error || '隔离容器执行绘图脚本失败。'
    }
  } catch (e) {
    if (e instanceof ApiError && e.code === 'plot_storage_not_initialized') {
      needsStorageInit.value = true
    }
    error.value = e instanceof Error ? e.message : '执行绘图失败，请检查脚本或数据源。'
  } finally {
    busy.value = false
  }
}

async function downloadFile(filename: string) {
  if (!runOp.value || !runProjectId.value) return
  try {
    const blob = await plottingApi.output(runProjectId.value, runOp.value.id, filename)
    savePlotFile(blob, filename)
  } catch (e) {
    error.value = e instanceof Error ? e.message : `下载 ${filename} 失败。`
  }
}

async function downloadBundle() {
  if (!runOp.value || !runProjectId.value) return
  try {
    const files = (runOp.value.files || []).slice(0, 9)
    if (!files.length) return
    const blob = await plottingApi.bundle(runProjectId.value, runOp.value.id, files)
    savePlotFile(blob, `astroagent-plot-${runOp.value.id.slice(0, 8)}.zip`)
  } catch (e) {
    error.value = e instanceof Error ? e.message : '打包下载失败。'
  }
}

function askModelToRefine() {
  emit('refine', `针对刚才「${draftTitle.value}」的科研绘图方案，请帮我继续微调：`)
}

function askModelToFix() {
  const reason = [error.value, diagnosticText.value].filter(Boolean).join('\n').slice(0, 1200)
  emit('refine', `刚才「${draftTitle.value}」的绘图脚本在隔离容器中执行失败，请根据以下报错修复脚本并重新生成方案：\n${reason}`)
}

onMounted(async () => {
  try {
    const saved = sessionStorage.getItem(storageKey.value)
    if (!saved) return
    const parsed = JSON.parse(saved) as { projectId?: string; runId?: string }
    if (!parsed.projectId || !parsed.runId) return
    runProjectId.value = parsed.projectId
    const op = await plottingApi.page(parsed.projectId)
      .then(page => page.operations.find(item => item.id === parsed.runId) || null)
      .catch(() => null)
    if (op) {
      runOp.value = op
      if (op.state === 'completed' && (op.files || []).includes('figure.png')) {
        await loadFigure(parsed.projectId, op.id)
      }
    }
  } catch { /* Ignore stale cache. */ }
})

onBeforeUnmount(() => {
  revokeFigure()
  zoomDialog.value?.close()
})
</script>

<template>
  <section class="ui-card chat-tool-card chat-plot-card" aria-label="科研绘图方案">
    <header class="tool-card-head">
      <div class="tool-card-title-row">
        <span class="ui-pill ui-pill-gaia">科研绘图</span>
        <h3>{{ draftTitle }}</h3>
        <span class="ui-pill ui-pill-neutral">{{ draftEngine === 'gnuplot' ? 'Gnuplot' : 'Python · Matplotlib' }}</span>
        <span class="ui-pill ui-pill-neutral">{{ chartLabels[draftChart] || draftChart }}</span>
        <span v-if="runOp" class="ui-pill" :class="runOp.state === 'completed' ? 'ui-pill-success' : runOp.state === 'failed' ? 'ui-pill-danger' : 'ui-pill-warning'">
          {{ runOp.state === 'completed' ? '已出图' : runOp.state === 'failed' ? '执行失败' : runOp.state }}
        </span>
      </div>
      <div class="tool-card-head-actions">
        <button type="button" class="tool-card-ghost" :disabled="busy" @click="editing = !editing">
          {{ editing ? '收起编辑' : '修改脚本' }}
        </button>
        <button type="button" class="tool-card-ghost" @click="askModelToRefine">让模型微调</button>
      </div>
    </header>

    <div class="plot-meta-bar">
      <span class="plot-meta-item"><b>数据源</b>{{ sourceSummary }}</span>
      <span class="plot-meta-item">
        <b>使用列</b>
        <code v-for="col in proposal.columns" :key="col" class="plot-col-chip">{{ col }}</code>
      </span>
      <button type="button" class="tool-card-ghost plot-pick-btn" :disabled="busy" @click="csvPicker?.click()">
        {{ localCsvFile ? '更换 CSV/TSV' : '选择本地 CSV/TSV' }}
      </button>
      <input ref="csvPicker" type="file" accept=".csv,.tsv,text/csv,text/tab-separated-values" class="sr-only" @change="onPickCsv">
    </div>

    <div v-if="Object.keys(proposal.axes || {}).length" class="plot-axes-pills">
      <span v-for="(val, key) in proposal.axes" :key="key" class="ui-pill ui-pill-mono">{{ key.toUpperCase() }}: {{ val }}</span>
    </div>

    <!-- Inline Editor -->
    <div v-if="editing" class="tool-edit-panel">
      <div class="tool-edit-grid">
        <label>
          <span>图标题</span>
          <input v-model="draftTitle" maxlength="200" :disabled="busy">
        </label>
        <label>
          <span>绘图引擎</span>
          <select v-model="draftEngine" :disabled="busy">
            <option value="python">Python (Matplotlib)</option>
            <option value="gnuplot">Gnuplot</option>
          </select>
        </label>
        <label>
          <span>图种</span>
          <select v-model="draftChart" :disabled="busy">
            <option value="scatter">散点图 (scatter)</option>
            <option value="line">折线图 (line)</option>
            <option value="histogram">直方图 (histogram)</option>
            <option value="errorbar">误差棒图 (errorbar)</option>
          </select>
        </label>
      </div>
      <label class="plot-script-label">
        <div class="plot-script-head">
          <span>可执行脚本（读取 <code>/input/data.csv</code>，输出 <code>/output/figure.png</code> 与 <code>/output/figure.pdf</code>）</span>
          <button type="button" class="tool-card-ghost" :disabled="busy" @click="resetProposal">恢复模型脚本</button>
        </div>
        <textarea v-model="draftScript" rows="12" spellcheck="false" class="plot-script-editor" :disabled="busy" />
      </label>
    </div>

    <details v-else class="plot-script-preview">
      <summary>审阅将执行的 {{ draftEngine === 'gnuplot' ? 'Gnuplot' : 'Python' }} 绘图脚本</summary>
      <pre>{{ draftScript }}</pre>
    </details>

    <!-- Compact Collapsible Notes -->
    <details v-if="proposalNotes.length" class="tool-notes-disclosure">
      <summary>
        <span class="notes-badge">绘图说明与注意事项 · {{ proposalNotes.length }} 条</span>
        <span class="notes-preview">{{ proposalNotes[0] }}</span>
      </summary>
      <ul class="tool-notes-list">
        <li v-for="note in proposalNotes" :key="note">{{ note }}</li>
      </ul>
    </details>

    <div v-if="needsStorageInit" class="tool-inline-alert is-info" role="status">
      <p>尚未初始化绘图扩展数据表，请先确认创建后再执行绘图。</p>
      <button type="button" class="button-primary" :disabled="initializing" @click="initializePlotStorage">
        {{ initializing ? '正在初始化…' : '确认初始化绘图存储表' }}
      </button>
    </div>

    <div v-if="error" class="tool-inline-alert is-danger" role="alert">
      <p>{{ error }}</p>
      <details v-if="diagnosticText" class="plot-diag-details">
        <summary>查看容器运行日志</summary>
        <pre>{{ diagnosticText }}</pre>
      </details>
      <button v-if="runOp?.state === 'failed'" type="button" class="tool-card-ghost plot-fix-btn" @click="askModelToFix">
        把报错发给模型修复脚本
      </button>
    </div>

    <footer class="tool-card-footer">
      <span class="tool-space-meta">空间 <b>{{ spaceLabel }}</b> · 隔离只读容器出图</span>
      <div class="tool-card-actions">
        <button v-if="runOp?.state === 'completed'" type="button" class="tool-result-link" @click="openInResultPanel">
          在右侧结果栏查看 ↗
        </button>
        <button type="button" class="button-primary" :disabled="busy || initializing" @click="confirmAndExecute">
          {{ busy ? '正在隔离容器中出图…' : runOp?.state === 'completed' ? '重新执行出图' : '确认执行隔离绘图' }}
        </button>
      </div>
    </footer>

    <!-- Rendered High-DPI Figure -->
    <div v-if="figureUrl && runOp?.state === 'completed'" class="tool-result-section">
      <figure class="plot-figure-box">
        <button type="button" class="plot-figure-zoom" aria-label="放大查看科研图形" @click="zoomDialog?.showModal()">
          <img :src="figureUrl" :alt="draftTitle">
        </button>
        <figcaption class="plot-figure-caption">
          <span>点击可全屏放大 · 已同步至右侧结果栏（支持 PNG / PDF / 脚本预览）</span>
          <button type="button" class="tool-card-ghost" @click="openInResultPanel">在右侧打开 ↗</button>
        </figcaption>
      </figure>
      <div class="plot-download-bar">
        <button v-if="(runOp.files || []).includes('figure.png')" type="button" class="tool-card-ghost" @click="downloadFile('figure.png')">下载 PNG</button>
        <button v-if="(runOp.files || []).includes('figure.pdf')" type="button" class="tool-card-ghost" @click="downloadFile('figure.pdf')">下载 PDF</button>
        <button v-if="(runOp.files || []).includes('script.py')" type="button" class="tool-card-ghost" @click="downloadFile('script.py')">下载 script.py</button>
        <button v-if="(runOp.files || []).includes('script.plt')" type="button" class="tool-card-ghost" @click="downloadFile('script.plt')">下载 script.plt</button>
        <button v-if="(runOp.files || []).length" type="button" class="button-secondary tool-card-ghost" @click="downloadBundle">打包下载 ZIP</button>
      </div>
    </div>

    <dialog ref="zoomDialog" class="plot-zoom plot-lightbox" @click.self="zoomDialog?.close()">
      <div class="plot-lightbox-head">
        <b>{{ draftTitle }}</b>
        <button type="button" class="dialog-close" aria-label="关闭大图预览" @click="zoomDialog?.close()">
          <svg viewBox="0 0 24 24" aria-hidden="true"><path d="m6 6 12 12M6 18 18 6" /></svg>
        </button>
      </div>
      <img v-if="figureUrl" :src="figureUrl" :alt="draftTitle" class="plot-lightbox-img">
    </dialog>
  </section>
</template>

<style scoped>
.chat-tool-card {
  position: relative;
  margin-top: 14px;
  padding: 16px 18px;
  gap: 12px;
  border-radius: 16px;
  border: 1px solid color-mix(in srgb, var(--accent) 22%, var(--border-subtle));
  background: var(--surface-glass-card);
  backdrop-filter: blur(18px) saturate(145%);
  box-shadow:
    inset 0 1.5px 0 var(--surface-specular),
    0 12px 30px -18px rgba(15, 23, 42, 0.24);
  overflow: hidden;
}

.chat-tool-card::before {
  content: '';
  position: absolute;
  inset: 0 18px auto 18px;
  height: 1.5px;
  background: linear-gradient(90deg, transparent, color-mix(in srgb, var(--accent) 55%, var(--surface-specular)), transparent);
  pointer-events: none;
}

.tool-card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  flex-wrap: wrap;
}

.tool-card-title-row {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  min-width: 0;
}

.tool-card-title-row h3 {
  margin: 0;
  font-size: 14.5px;
  font-weight: 680;
  color: var(--text-primary);
  letter-spacing: -0.01em;
  overflow-wrap: anywhere;
}

.tool-card-head-actions {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}

.tool-card-ghost {
  min-height: 29px;
  padding: 0 11px;
  border-radius: 999px;
  border: 1px solid color-mix(in srgb, var(--border-subtle) 90%, transparent);
  background: color-mix(in srgb, var(--surface-card) 72%, transparent);
  color: var(--text-secondary);
  font-size: 12px;
  font-weight: 560;
  cursor: pointer;
  transition: border-color 0.16s ease, color 0.16s ease, background 0.16s ease;
}

.tool-card-ghost:hover:not(:disabled) {
  border-color: color-mix(in srgb, var(--accent) 50%, var(--border-strong));
  color: var(--accent);
  background: color-mix(in srgb, var(--accent) 8%, var(--surface-card));
}

.plot-meta-bar {
  display: flex;
  align-items: center;
  gap: 10px 14px;
  flex-wrap: wrap;
  padding: 9px 12px;
  border: 1px solid color-mix(in srgb, var(--border-subtle) 85%, transparent);
  border-radius: 12px;
  background: color-mix(in srgb, var(--surface-muted) 56%, transparent);
  font-size: 12px;
  color: var(--text-secondary);
}

.plot-meta-item {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}

.plot-meta-item b {
  color: var(--text-muted);
  font-weight: 600;
  font-size: 11.5px;
}

.plot-pick-btn {
  margin-left: auto;
}

.plot-col-chip {
  padding: 2px 7px;
  border-radius: 6px;
  border: 1px solid color-mix(in srgb, var(--border-subtle) 80%, transparent);
  background: color-mix(in srgb, var(--surface-card) 86%, transparent);
  color: var(--text-primary);
  font-size: 11px;
  font-family: var(--font-mono);
}

.plot-axes-pills {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.tool-edit-panel {
  display: grid;
  gap: 12px;
  padding: 13px;
  border: 1px solid color-mix(in srgb, var(--border-subtle) 90%, transparent);
  border-radius: 13px;
  background: color-mix(in srgb, var(--surface-muted) 50%, transparent);
}

.tool-edit-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
  gap: 10px;
}

.tool-edit-grid label {
  display: grid;
  gap: 4px;
  font-size: 11.5px;
  font-weight: 550;
  color: var(--text-muted);
}

.tool-edit-grid input,
.tool-edit-grid select {
  min-height: 33px;
  padding: 5px 10px;
  border-radius: 9px;
  border: 1px solid color-mix(in srgb, var(--border-strong) 65%, transparent);
  background: color-mix(in srgb, var(--surface-card) 86%, transparent);
  color: var(--text-primary);
  font-size: 12.5px;
}

.plot-script-label {
  display: grid;
  gap: 6px;
  font-size: 12px;
  color: var(--text-muted);
}

.plot-script-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  flex-wrap: wrap;
}

.plot-script-editor {
  width: 100%;
  font-family: var(--font-mono, Consolas, monospace);
  font-size: 12px;
  line-height: 1.65;
  resize: vertical;
  border-radius: 10px;
}

.plot-script-preview {
  padding: 8px 12px;
  border: 1px solid color-mix(in srgb, var(--border-subtle) 85%, transparent);
  border-radius: 11px;
  background: color-mix(in srgb, var(--surface-muted) 48%, transparent);
}

.plot-script-preview summary {
  cursor: pointer;
  font-size: 12px;
  font-weight: 600;
  color: var(--text-secondary);
}

.plot-script-preview pre {
  margin-top: 8px;
  max-height: 300px;
}

.tool-notes-disclosure {
  border-radius: 11px;
  border: 1px solid color-mix(in srgb, var(--border-subtle) 82%, transparent);
  background: color-mix(in srgb, var(--surface-muted) 48%, transparent);
  overflow: hidden;
}

.tool-notes-disclosure summary {
  list-style: none;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 12px;
  cursor: pointer;
  user-select: none;
  font-size: 12px;
  color: var(--text-secondary);
}

.tool-notes-disclosure summary::-webkit-details-marker {
  display: none;
}

.tool-notes-disclosure summary::after {
  content: '▾';
  margin-left: auto;
  color: var(--text-muted);
  font-size: 11px;
  transition: transform 0.2s ease;
}

.tool-notes-disclosure[open] summary::after {
  transform: rotate(180deg);
}

.notes-badge {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 11.5px;
  font-weight: 620;
  color: var(--accent);
  white-space: nowrap;
  flex-shrink: 0;
}

.notes-badge::before {
  content: '';
  width: 6px;
  height: 6px;
  border-radius: 999px;
  background: var(--accent);
  opacity: 0.8;
}

.notes-preview {
  color: var(--text-muted);
  font-size: 12px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  min-width: 0;
}

.tool-notes-disclosure[open] .notes-preview {
  display: none;
}

.tool-notes-list {
  margin: 0;
  padding: 4px 14px 10px 26px;
  border-top: 1px solid color-mix(in srgb, var(--border-subtle) 65%, transparent);
  display: grid;
  gap: 5px;
  font-size: 12px;
  line-height: 1.55;
  color: var(--text-secondary);
}

.tool-inline-alert {
  margin: 0;
  padding: 9px 12px;
  border-radius: 10px;
  font-size: 12px;
  line-height: 1.5;
  display: grid;
  gap: 6px;
}

.tool-inline-alert p {
  margin: 0;
}

.tool-inline-alert.is-danger {
  border: 1px solid color-mix(in srgb, var(--danger-text) 28%, transparent);
  background: color-mix(in srgb, var(--danger-bg) 68%, transparent);
  color: var(--danger-text);
}

.tool-inline-alert.is-info {
  border: 1px solid color-mix(in srgb, var(--accent) 24%, var(--border-subtle));
  background: color-mix(in srgb, var(--accent) 7%, var(--surface-card));
  color: var(--text-secondary);
}

.plot-diag-details {
  margin-top: 4px;
}

.plot-fix-btn {
  justify-self: start;
}

.tool-card-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  padding-top: 10px;
  border-top: 1px solid color-mix(in srgb, var(--border-subtle) 80%, transparent);
}

.tool-space-meta {
  font-size: 12px;
  color: var(--text-muted);
}

.tool-space-meta b {
  color: var(--text-secondary);
  font-weight: 600;
}

.tool-card-actions {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.tool-result-link {
  min-height: 32px;
  padding: 0 12px;
  border-radius: 999px;
  border: 1px solid color-mix(in srgb, var(--accent) 36%, var(--border-subtle));
  background: color-mix(in srgb, var(--accent) 10%, transparent);
  color: var(--accent);
  font-size: 12.5px;
  font-weight: 620;
  cursor: pointer;
  transition: background 0.16s ease, border-color 0.16s ease, transform 0.16s ease;
}

.tool-result-link:hover {
  background: color-mix(in srgb, var(--accent) 16%, transparent);
  border-color: var(--accent);
  transform: translateY(-1px);
}

.tool-result-section {
  display: grid;
  gap: 10px;
  padding-top: 12px;
  border-top: 1px solid color-mix(in srgb, var(--border-subtle) 80%, transparent);
}

.plot-figure-box {
  margin: 0;
  display: grid;
  gap: 6px;
}

.plot-figure-zoom {
  display: block;
  width: 100%;
  padding: 8px;
  border: 1px solid color-mix(in srgb, var(--border-subtle) 85%, transparent);
  border-radius: 12px;
  background: #ffffff;
  box-shadow: none;
  cursor: zoom-in;
}

.plot-figure-zoom:hover {
  border-color: var(--accent);
}

.plot-figure-zoom img {
  display: block;
  width: 100%;
  height: auto;
  max-height: 440px;
  object-fit: contain;
}

.plot-figure-caption {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  font-size: 11.5px;
  color: var(--text-muted);
}

.plot-download-bar {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.plot-lightbox {
  max-width: min(94vw, 1280px);
  max-height: 92dvh;
  padding: 16px 20px 20px;
}

.plot-lightbox-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
}

.plot-lightbox-img {
  display: block;
  max-width: 100%;
  max-height: calc(92dvh - 86px);
  background: #ffffff;
  border-radius: 8px;
}
</style>
