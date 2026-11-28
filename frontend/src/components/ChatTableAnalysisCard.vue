<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { tablesApi, type TableOperatorName } from '../api/tables'
import { useProjects } from '../stores/projects'
import type { AnalysisRunResponse, TableAnalysisProposalResult } from '../types'
import DirectPlotDialog from './DirectPlotDialog.vue'
import type { DirectPlotJob } from '../stores/directPlots'
import StatusNotice from './StatusNotice.vue'
import SuccessToast from './SuccessToast.vue'

export interface TableResultPayload {
  kind: 'tables'
  projectId: string
  datasetId?: string
  runId?: string
}

export interface TableDirectPlotPayload {
  kind: 'plot'
  projectId: string
  runId: string
  title: string
  files: string[]
}

const props = defineProps<{
  proposal: TableAnalysisProposalResult
  turnId: string
  proposalIndex: number
  projectId?: string
}>()

const emit = defineEmits<{
  refine: [prompt: string]
  'open-result': [payload: TableResultPayload | TableDirectPlotPayload]
}>()

const projectsStore = useProjects()
const directPlotDialog = ref<InstanceType<typeof DirectPlotDialog> | null>(null)
const storageKey = computed(() => `astroagent.chat_table.${props.turnId}.${props.proposalIndex}`)

const busy = ref(false)
const error = ref('')
const toastMessage = ref('')
const runResult = ref<AnalysisRunResponse | null>(null)
const runSummary = computed(() => runResult.value?.run.summary ?? {})
const resolvedProjectId = ref(props.proposal.project_id || props.projectId || '')

const operatorLabels: Record<string, string> = {
  stats: '统计与检验',
  filter_derive: '筛选与派生列',
  coordinates: '天球坐标变换',
  crossmatch: '天空交叉匹配',
  fit: '科学曲线拟合',
}

const fitModelLabels: Record<string, string> = {
  linear: '线性回归',
  polynomial: '多项式拟合',
  power_law: '幂律拟合',
  gaussian: '单高斯拟合',
}

const summaryItems = computed<Array<{ label: string; value: string }>>(() => {
  const p = (props.proposal.parameters || {}) as Record<string, unknown>
  const items: Array<{ label: string; value: string }> = [
    {
      label: props.proposal.operator === 'crossmatch' ? '左表' : '主表',
      value: props.proposal.dataset_name || props.proposal.dataset_id.slice(0, 8),
    },
  ]
  if (props.proposal.secondary_dataset_id) {
    items.push({
      label: props.proposal.operator === 'crossmatch' ? '右表' : '对比表',
      value: props.proposal.secondary_dataset_name || props.proposal.secondary_dataset_id.slice(0, 8),
    })
  }
  if (props.proposal.operator === 'crossmatch') {
    const mode = p.mode === 'all_within_radius' ? '半径内全候选' : '最近邻'
    const radius = p.radius_arcsec != null ? `${p.radius_arcsec}"` : '2"'
    const join = p.join_type === 'left' ? 'left 保留全部左表' : 'inner 仅保留匹配'
    items.push({ label: '匹配规则', value: `${mode} · 半径 ${radius}` })
    items.push({ label: '连接方式', value: join })
    if (p.left_ra_col && p.right_ra_col) {
      items.push({
        label: '坐标列',
        value: `(${String(p.left_ra_col)}, ${String(p.left_dec_col)}) ↔ (${String(p.right_ra_col)}, ${String(p.right_dec_col)})`,
      })
    }
  } else if (props.proposal.operator === 'fit') {
    const m = fitModelLabels[String(p.model || 'linear')] || String(p.model || 'linear')
    items.push({ label: '拟合模型', value: p.y_err_col ? `${m} (WLS)` : m })
    if (p.x_col && p.y_col) {
      items.push({ label: '变量', value: `${String(p.x_col)} → ${String(p.y_col)}` })
    }
  } else if (props.proposal.operator === 'coordinates') {
    items.push({
      label: '坐标变换',
      value: `${String(p.input_frame || 'icrs').toUpperCase()} → ${String(p.output_frame || '仅角距').toUpperCase()}`,
    })
  } else if (props.proposal.operator === 'filter_derive') {
    const conds = Array.isArray(p.conditions) ? p.conditions.length : 0
    const derived = Array.isArray(p.derived_columns) ? p.derived_columns.length : 0
    items.push({ label: '规则', value: `${conds} 条筛选 · ${derived} 个派生列` })
  } else if (props.proposal.operator === 'stats') {
    const cols = Array.isArray(p.columns) ? p.columns.length : 0
    const parts: string[] = []
    if (cols) parts.push(`${cols} 列描述统计`)
    if (p.corr_x && p.corr_y) parts.push(`相关性 ${String(p.corr_x)}/${String(p.corr_y)}`)
    if (p.ks_column) parts.push(`KS 检验 ${String(p.ks_column)}`)
    if (parts.length) items.push({ label: '统计项', value: parts.join(' · ') })
  }
  if (props.proposal.save_derived) {
    items.push({ label: '派生输出', value: props.proposal.derived_name || '自动命名派生表' })
  }
  return items
})

function formatNum(value: unknown, digits = 4): string {
  if (typeof value !== 'number' || !Number.isFinite(value)) return '—'
  if (Math.abs(value) >= 1e5 || (value !== 0 && Math.abs(value) < 1e-3)) {
    return value.toExponential(digits)
  }
  return Number(value.toFixed(digits)).toString()
}

async function resolveProject(): Promise<string> {
  if (resolvedProjectId.value) return resolvedProjectId.value
  const def = await projectsStore.ensureDefault()
  resolvedProjectId.value = def.id
  return def.id
}

async function confirmAndRun() {
  if (busy.value) return
  busy.value = true
  error.value = ''
  try {
    const pid = await resolveProject()
    const payload = { ...(props.proposal.parameters || {}) }
    const res = await tablesApi.runOperator(pid, props.proposal.operator as TableOperatorName, payload)
    runResult.value = res
    try {
      sessionStorage.setItem(
        storageKey.value,
        JSON.stringify({
          projectId: pid,
          runId: res.run.id,
          datasetId: res.output_dataset?.id || props.proposal.dataset_id,
        }),
      )
    } catch {
      // Ignore storage restriction.
    }
    emit('open-result', {
      kind: 'tables',
      projectId: pid,
      datasetId: res.output_dataset?.id || props.proposal.dataset_id,
      runId: res.run.id,
    })
  } catch (e) {
    error.value = e instanceof Error ? e.message : '执行天文数据表分析失败。'
  } finally {
    busy.value = false
  }
}

async function openDirectPlot() {
  const pid = resolvedProjectId.value
  const outDs = runResult.value?.output_dataset
  if (!pid || !outDs || busy.value) return
  await directPlotDialog.value?.open(pid, outDs)
}

function onDirectPlotSubmitted(job: DirectPlotJob) {
  toastMessage.value = `已提交后台绘图「${job.title}」，完成后将自动展示在右侧结果栏`
}

async function openInResultPanel(useDerived = false) {
  const pid = await resolveProject()
  const dsid = useDerived
    ? (runResult.value?.output_dataset?.id || props.proposal.dataset_id)
    : (props.proposal.dataset_id || runResult.value?.output_dataset?.id)
  emit('open-result', {
    kind: 'tables',
    projectId: pid,
    datasetId: dsid,
    runId: runResult.value?.run.id,
  })
}

async function downloadBundle() {
  const pid = resolvedProjectId.value
  const rid = runResult.value?.run.id
  if (!pid || !rid || busy.value) return
  busy.value = true
  error.value = ''
  try {
    await tablesApi.exportBundle(pid, rid)
  } catch (e) {
    error.value = e instanceof Error ? e.message : '下载分析 ZIP 包失败。'
  } finally {
    busy.value = false
  }
}

onMounted(() => {
  try {
    const raw = sessionStorage.getItem(storageKey.value)
    if (!raw) return
    const parsed = JSON.parse(raw) as { projectId?: string; runId?: string }
    if (parsed.projectId) resolvedProjectId.value = parsed.projectId
  } catch {
    // Ignore stale storage.
  }
})
</script>

<template>
  <section class="chat-tool-card chat-table-card" aria-label="天文数据表分析方案">
    <header class="tool-card-head">
      <div class="tool-card-title-row">
        <span class="ui-pill ui-pill-gaia">表分析</span>
        <h3>{{ proposal.title }}</h3>
        <span class="ui-pill ui-pill-neutral">{{ operatorLabels[proposal.operator] || proposal.operator }}</span>
        <span v-if="runResult" class="ui-pill ui-pill-success">已完成</span>
      </div>
      <div class="tool-card-head-actions">
        <button
          type="button"
          class="tool-card-ghost"
          @click="emit('refine', `针对「${proposal.title}」的数据表分析参数，请调整：`)"
        >
          让模型调整
        </button>
      </div>
    </header>

    <p v-if="proposal.explanation" class="table-card-desc">{{ proposal.explanation }}</p>

    <dl class="table-summary-grid">
      <div v-for="item in summaryItems" :key="item.label" class="table-summary-tile">
        <dt>{{ item.label }}</dt>
        <dd :title="item.value">{{ item.value }}</dd>
      </div>
    </dl>

    <div class="table-disclosures">
      <details class="table-disclosure-row">
        <summary>
          <span>审阅算子参数 JSON</span>
          <em>{{ proposal.operator }}</em>
        </summary>
        <div class="table-disclosure-body">
          <pre>{{ JSON.stringify(proposal.parameters, null, 2) }}</pre>
        </div>
      </details>

      <details v-if="proposal.warnings?.length" class="table-disclosure-row">
        <summary>
          <span class="notes-badge">执行前留意 · {{ proposal.warnings.length }} 条</span>
          <span class="notes-preview">{{ proposal.warnings[0] }}</span>
        </summary>
        <ul class="tool-notes-list">
          <li v-for="w in proposal.warnings" :key="w">{{ w }}</li>
        </ul>
      </details>
    </div>

    <StatusNotice v-if="error" title="表分析操作未完成" :message="error" @dismiss="error = ''" />

    <footer class="tool-card-footer">
      <span class="tool-space-meta">Astropy / NumPy / SciPy 确定性执行</span>
      <div class="tool-card-actions">
        <button type="button" class="tool-result-link" @click="openInResultPanel(false)">
          查看数据表
        </button>
        <button type="button" class="button-primary" :disabled="busy" @click="confirmAndRun">
          {{ busy ? '正在计算…' : runResult ? '重新执行分析' : '确认执行分析' }}
        </button>
      </div>
    </footer>

    <div v-if="runResult" class="tool-result-section">
      <div v-if="runResult.run.operator === 'fit'" class="table-kpi-grid">
        <div class="table-kpi-tile">
          <span class="table-kpi-label">决定系数 R²</span>
          <strong class="table-kpi-value">{{ formatNum(runSummary.r2, 5) }}</strong>
          <small>RMSE {{ formatNum(runSummary.rmse, 4) }}</small>
        </div>
        <div
          v-for="p in ((runSummary.parameters as Array<{ name: string; value: number; err: number }>) || [])"
          :key="p.name"
          class="table-kpi-tile"
        >
          <span class="table-kpi-label">{{ p.name }}</span>
          <strong class="table-kpi-value">{{ formatNum(p.value, 5) }}</strong>
          <small>± {{ formatNum(p.err, 5) }}</small>
        </div>
      </div>

      <div v-else-if="runResult.run.operator === 'crossmatch'" class="table-kpi-grid">
        <div class="table-kpi-tile">
          <span class="table-kpi-label">匹配源数</span>
          <strong class="table-kpi-value">{{ runSummary.matched_left_rows ?? '—' }}</strong>
          <small>匹配率 {{ formatNum(Number(runSummary.match_rate) * 100, 1) }}%</small>
        </div>
        <div class="table-kpi-tile">
          <span class="table-kpi-label">角距中位 / P90</span>
          <strong class="table-kpi-value">{{ formatNum(runSummary.sep_median_arcsec, 3) }}"</strong>
          <small>P90 {{ formatNum(runSummary.sep_p90_arcsec, 3) }}" · 输出 {{ runSummary.output_rows ?? '—' }} 行</small>
        </div>
      </div>

      <pre v-else class="table-run-json">{{ JSON.stringify(runSummary, null, 2) }}</pre>

      <details v-if="runResult.run.warnings?.length" class="table-disclosure-row is-standalone">
        <summary>
          <span class="notes-badge">结果边界提示 · {{ runResult.run.warnings.length }} 条</span>
          <span class="notes-preview">{{ runResult.run.warnings[0] }}</span>
        </summary>
        <ul class="tool-notes-list">
          <li v-for="w in runResult.run.warnings" :key="w">{{ w }}</li>
        </ul>
      </details>

      <div class="plot-download-bar">
        <button
          v-if="runResult.output_dataset"
          type="button"
          class="tool-card-ghost"
          @click="openInResultPanel(true)"
        >
          查看派生表「{{ runResult.output_dataset.name }}」
        </button>
        <button
          v-if="runResult.output_dataset"
          type="button"
          class="tool-result-link"
          :disabled="busy"
          @click="openDirectPlot"
        >
          直接绘图
        </button>
        <button type="button" class="tool-card-ghost" :disabled="busy" @click="downloadBundle">
          ↓ ZIP 复现包
        </button>
      </div>
    </div>

    <SuccessToast v-model:message="toastMessage" />
    <DirectPlotDialog ref="directPlotDialog" @submitted="onDirectPlotSubmitted" />
  </section>
</template>

<style scoped>
.chat-tool-card {
  position: relative;
  margin-top: 14px;
  padding: 16px 18px;
  display: grid;
  gap: 12px;
  border-radius: 16px;
  border: 1px solid color-mix(in srgb, var(--accent) 22%, var(--border-subtle, var(--line)));
  background: var(--surface-glass-card, var(--surface-card));
  backdrop-filter: blur(18px) saturate(145%);
  box-shadow:
    inset 0 1.5px 0 var(--surface-specular, rgba(255, 255, 255, 0.7)),
    0 12px 30px -18px rgba(15, 23, 42, 0.24);
  overflow: hidden;
}

.chat-tool-card::before {
  content: '';
  position: absolute;
  inset: 0 18px auto 18px;
  height: 1.5px;
  background: linear-gradient(90deg, transparent, color-mix(in srgb, var(--accent) 55%, var(--surface-specular, #fff)), transparent);
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
  font-weight: 660;
  color: var(--text-primary, var(--ink));
  letter-spacing: -0.01em;
  overflow-wrap: anywhere;
}

.tool-card-head-actions {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-shrink: 0;
}

.tool-card-ghost {
  min-height: 30px;
  padding: 0 12px;
  border-radius: 999px;
  border: 1px solid color-mix(in srgb, var(--border-subtle, var(--line)) 90%, transparent);
  background: color-mix(in srgb, var(--surface-card) 78%, transparent);
  color: var(--text-secondary, var(--muted));
  font-size: 12px;
  font-weight: 560;
  cursor: pointer;
  transition: border-color 0.16s ease, color 0.16s ease, background 0.16s ease;
}

.tool-card-ghost:hover:not(:disabled) {
  border-color: color-mix(in srgb, var(--accent) 50%, var(--line));
  color: var(--accent);
  background: color-mix(in srgb, var(--accent) 8%, var(--surface-card));
}

.table-card-desc {
  margin: 0;
  font-size: 12.5px;
  line-height: 1.62;
  color: var(--text-secondary, var(--muted));
}

.table-summary-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
  gap: 8px;
  margin: 0;
}

.table-summary-tile {
  display: grid;
  gap: 3px;
  padding: 8px 11px;
  border-radius: 10px;
  border: 1px solid color-mix(in srgb, var(--border-subtle, var(--line)) 86%, transparent);
  background: color-mix(in srgb, var(--surface-subtle) 78%, var(--surface-card));
  min-width: 0;
}

.table-summary-tile dt {
  margin: 0;
  padding: 0;
  border: 0;
  font-size: 11px;
  font-weight: 550;
  color: var(--text-muted, var(--muted));
  line-height: 1.3;
}

.table-summary-tile dd {
  margin: 0;
  padding: 0;
  border: 0;
  font-size: 12.5px;
  font-weight: 600;
  color: var(--text-primary, var(--ink));
  line-height: 1.35;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.table-disclosures {
  display: grid;
  border-radius: 11px;
  border: 1px solid color-mix(in srgb, var(--border-subtle, var(--line)) 86%, transparent);
  background: color-mix(in srgb, var(--surface-muted, var(--surface-subtle)) 52%, var(--surface-card));
  overflow: hidden;
}

.table-disclosure-row {
  padding: 0;
  border-top: 0;
}

.table-disclosure-row + .table-disclosure-row {
  border-top: 1px solid color-mix(in srgb, var(--border-subtle, var(--line)) 80%, transparent);
}

.table-disclosure-row.is-standalone {
  border-radius: 11px;
  border: 1px solid color-mix(in srgb, var(--border-subtle, var(--line)) 86%, transparent);
  background: color-mix(in srgb, var(--surface-muted, var(--surface-subtle)) 52%, var(--surface-card));
  overflow: hidden;
}

.table-disclosure-row > summary {
  list-style: none;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 9px 12px;
  cursor: pointer;
  user-select: none;
  font-size: 12px;
  font-weight: 560;
  color: var(--text-secondary, var(--ink));
  transition: background-color 140ms ease;
}

.table-disclosure-row > summary::-webkit-details-marker {
  display: none;
}

.table-disclosure-row > summary:hover {
  background: color-mix(in srgb, var(--accent) 5%, transparent);
}

.table-disclosure-row > summary::after {
  content: '▾';
  margin-left: auto;
  color: var(--text-muted, var(--muted));
  font-size: 11px;
  transition: transform 0.18s ease;
}

.table-disclosure-row[open] > summary::after {
  transform: rotate(180deg);
}

.table-disclosure-row > summary em {
  font-style: normal;
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--text-muted, var(--muted));
}

.table-disclosure-body {
  padding: 0 12px 12px;
}

.table-disclosure-body pre {
  margin: 0;
  max-height: 240px;
  border-radius: 8px;
  border: 1px solid var(--line);
}

.notes-badge {
  display: inline-flex;
  align-items: center;
  gap: 6px;
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
  opacity: 0.85;
}

.notes-preview {
  color: var(--text-muted, var(--muted));
  font-size: 12px;
  font-weight: 400;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  min-width: 0;
}

.table-disclosure-row[open] .notes-preview {
  display: none;
}

.tool-notes-list {
  margin: 0;
  padding: 6px 14px 10px 26px;
  border-top: 1px solid color-mix(in srgb, var(--border-subtle, var(--line)) 65%, transparent);
  display: grid;
  gap: 5px;
  font-size: 12px;
  line-height: 1.55;
  color: var(--text-secondary, var(--muted));
}

.tool-card-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  padding-top: 10px;
  border-top: 1px solid color-mix(in srgb, var(--border-subtle, var(--line)) 80%, transparent);
}

.tool-space-meta {
  font-size: 12px;
  color: var(--text-muted, var(--muted));
}

.tool-card-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.tool-result-link {
  min-height: 34px;
  padding: 0 13px;
  border-radius: 999px;
  border: 1px solid color-mix(in srgb, var(--accent) 36%, var(--line));
  background: color-mix(in srgb, var(--accent) 10%, transparent);
  color: var(--accent);
  font-size: 12.5px;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.16s ease, border-color 0.16s ease;
}

.tool-result-link:hover:not(:disabled) {
  background: color-mix(in srgb, var(--accent) 16%, transparent);
  border-color: var(--accent);
}

.tool-result-section {
  display: grid;
  gap: 10px;
  padding-top: 12px;
  border-top: 1px solid color-mix(in srgb, var(--border-subtle, var(--line)) 80%, transparent);
}

.table-kpi-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
  gap: 8px;
}

.table-kpi-tile {
  display: grid;
  gap: 3px;
  padding: 10px 12px;
  border-radius: 11px;
  border: 1px solid var(--line);
  background: var(--surface-card);
  box-shadow: var(--shadow-card);
}

.table-kpi-label {
  font-size: 11px;
  color: var(--muted);
}

.table-kpi-value {
  font-size: 17px;
  font-weight: 680;
  color: var(--ink);
  font-variant-numeric: tabular-nums;
}

.table-kpi-tile small {
  font-size: 11px;
  color: var(--muted);
  font-variant-numeric: tabular-nums;
}

.plot-download-bar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}

.table-run-json {
  margin: 0;
  max-height: 220px;
  overflow: auto;
  font-size: 11.5px;
  border-radius: 9px;
  border: 1px solid var(--line);
}
</style>
