<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { tablesApi } from '../api/tables'
import type { AnalysisDataset, AnalysisRunRecord, TablePreviewResponse } from '../types'
import DirectPlotDialog from './DirectPlotDialog.vue'
import type { DirectPlotJob } from '../stores/directPlots'
import StatusNotice from './StatusNotice.vue'
import SuccessToast from './SuccessToast.vue'
import UiSelect, { type UiSelectOption } from './UiSelect.vue'

const props = defineProps<{
  projectId: string
  datasetId?: string
  runId?: string
}>()

const emit = defineEmits<{
  'select-dataset': [datasetId: string]
  'select-run': [runId: string]
}>()

const directPlotDialog = ref<InstanceType<typeof DirectPlotDialog> | null>(null)

const loading = ref(false)
const busy = ref(false)
const error = ref('')
const toastMessage = ref('')

const datasets = ref<AnalysisDataset[]>([])
const runs = ref<AnalysisRunRecord[]>([])
const selectedDatasetId = ref('')
const activeRunId = ref('')
const activeSubView = ref<'preview' | 'runs'>('preview')

const preview = ref<TablePreviewResponse | null>(null)
const previewOffset = ref(0)
const previewLimit = ref(50)

const deleteDialog = ref<HTMLDialogElement | null>(null)
const deleteTarget = ref<AnalysisDataset | null>(null)

const selectedDataset = computed(
  () => datasets.value.find(d => d.id === selectedDatasetId.value) || null,
)
const activeRun = computed(
  () => runs.value.find(r => r.id === activeRunId.value) || runs.value[0] || null,
)
const runOutputDataset = computed(
  () => datasets.value.find(d => d.id === activeRun.value?.output_dataset_id) || null,
)

const sourceLabels: Record<string, string> = {
  upload: '本地上传',
  gaia_turn: 'Gaia DR3',
  gaia_snapshot: 'Gaia 快照',
  vizier: 'VizieR',
  derived: '派生表',
}
const sourcePillClass: Record<string, string> = {
  upload: 'ui-pill-neutral',
  gaia_turn: 'ui-pill-gaia',
  gaia_snapshot: 'ui-pill-gaia',
  vizier: 'ui-pill-accent',
  derived: 'ui-pill-success',
}
const operatorLabels: Record<string, string> = {
  stats: '统计与检验',
  filter_derive: '筛选与派生列',
  coordinates: '天球坐标变换',
  crossmatch: '天空交叉匹配',
  fit: '科学曲线拟合',
}
const pageSizeOptions: UiSelectOption<number>[] = [
  { value: 25, label: '25 行/页' },
  { value: 50, label: '50 行/页' },
  { value: 100, label: '100 行/页' },
]

function formatNum(value: unknown, digits = 4): string {
  if (typeof value !== 'number' || !Number.isFinite(value)) return '—'
  if (Math.abs(value) >= 1e5 || (value !== 0 && Math.abs(value) < 1e-3)) {
    return value.toExponential(digits)
  }
  return Number(value.toFixed(digits)).toString()
}

function formatShortTime(raw?: string | null): string {
  if (!raw) return ''
  const match = raw.match(/^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2})/)
  return match ? `${match[1]} ${match[2]}` : raw
}

function isRunSuccess(state?: string | null): boolean {
  return state === 'completed' || state === 'succeeded'
}

let loadSeq = 0
async function refresh() {
  const pid = props.projectId
  if (!pid) {
    datasets.value = []
    runs.value = []
    selectedDatasetId.value = ''
    activeRunId.value = ''
    preview.value = null
    return
  }
  const seq = ++loadSeq
  loading.value = true
  error.value = ''
  try {
    const page = await tablesApi.list(pid)
    if (seq !== loadSeq) return
    datasets.value = page.datasets || []
    runs.value = page.runs || []
    if (props.runId && runs.value.some(r => r.id === props.runId)) {
      activeRunId.value = props.runId
      activeSubView.value = 'runs'
    } else if (!runs.value.some(r => r.id === activeRunId.value)) {
      activeRunId.value = runs.value[0]?.id || ''
    }
    if (props.datasetId && datasets.value.some(d => d.id === props.datasetId)) {
      selectedDatasetId.value = props.datasetId
    } else if (!datasets.value.some(d => d.id === selectedDatasetId.value)) {
      selectedDatasetId.value = datasets.value[0]?.id || ''
    }
  } catch (e) {
    if (seq === loadSeq) {
      error.value = e instanceof Error ? e.message : '读取项目数据表失败。'
    }
  } finally {
    if (seq === loadSeq) loading.value = false
  }
}

let previewSeq = 0
async function loadPreview() {
  const pid = props.projectId
  const dsid = selectedDatasetId.value
  if (!pid || !dsid) {
    preview.value = null
    return
  }
  const seq = ++previewSeq
  if (preview.value?.dataset_id !== dsid) preview.value = null
  try {
    const res = await tablesApi.preview(pid, dsid, previewOffset.value, previewLimit.value)
    if (seq === previewSeq) {
      preview.value = res
    }
  } catch (e) {
    if (seq === previewSeq) {
      preview.value = null
      error.value = e instanceof Error ? e.message : '读取数据表预览失败。'
    }
  }
}

watch(
  () => props.projectId,
  () => {
    previewOffset.value = 0
    void refresh()
  },
  { immediate: true },
)

watch(
  () => props.datasetId,
  nextId => {
    if (nextId && datasets.value.some(d => d.id === nextId)) {
      selectedDatasetId.value = nextId
      previewOffset.value = 0
      activeSubView.value = 'preview'
    } else if (nextId) {
      void refresh()
    }
  },
)

watch(
  () => props.runId,
  nextRun => {
    if (nextRun && runs.value.some(r => r.id === nextRun)) {
      activeRunId.value = nextRun
      activeSubView.value = 'runs'
    } else if (nextRun) {
      void refresh()
    }
  },
)

watch(
  [selectedDatasetId, previewOffset, previewLimit],
  ([dsid]) => {
    if (!dsid) {
      preview.value = null
      return
    }
    void loadPreview()
  },
  { immediate: true },
)

function chooseDataset(id: string) {
  selectedDatasetId.value = id
  previewOffset.value = 0
  activeSubView.value = 'preview'
  emit('select-dataset', id)
}

async function askDeleteDataset(ds: AnalysisDataset) {
  deleteTarget.value = ds
  await nextTick()
  deleteDialog.value?.showModal()
}

async function confirmDeleteDataset() {
  if (!props.projectId || !deleteTarget.value || busy.value) return
  busy.value = true
  error.value = ''
  try {
    await tablesApi.remove(props.projectId, deleteTarget.value.id)
    const deletedName = deleteTarget.value.name
    deleteDialog.value?.close()
    deleteTarget.value = null
    toastMessage.value = `已删除数据表「${deletedName}」`
    await refresh()
  } catch (e) {
    error.value = e instanceof Error ? e.message : '删除数据表失败。'
  } finally {
    busy.value = false
  }
}

async function openDirectPlot() {
  if (!props.projectId || busy.value) return
  const target = selectedDataset.value
  if (!target) return
  await directPlotDialog.value?.open(props.projectId, target)
}

function onDirectPlotSubmitted(job: DirectPlotJob) {
  toastMessage.value = `已提交绘图「${job.title}」，完成后将自动显示在结果栏`
}

async function exportTable(fmt: 'csv' | 'ecsv' | 'fits', targetId?: string) {
  const dsid = targetId || selectedDatasetId.value
  if (!props.projectId || !dsid || busy.value) return
  busy.value = true
  error.value = ''
  try {
    await tablesApi.exportTable(props.projectId, dsid, fmt)
  } catch (e) {
    error.value = e instanceof Error ? e.message : `导出 ${fmt.toUpperCase()} 失败。`
  } finally {
    busy.value = false
  }
}

async function downloadBundle(runId: string) {
  if (!props.projectId || busy.value) return
  busy.value = true
  error.value = ''
  try {
    await tablesApi.exportBundle(props.projectId, runId)
  } catch (e) {
    error.value = e instanceof Error ? e.message : '下载 ZIP 分析包失败。'
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div class="table-result-panel">
    <StatusNotice v-if="error" title="数据表操作未完成" :message="error" @dismiss="error = ''" />
    <SuccessToast v-model:message="toastMessage" />

    <p v-if="loading && !datasets.length && !runs.length" class="small muted" role="status">
      正在读取当前空间数据表与分析记录…
    </p>

    <div v-else-if="!datasets.length && !runs.length" class="ui-empty-inline">
      <div class="ui-empty-icon" aria-hidden="true">
        <svg viewBox="0 0 24 24"><rect x="3" y="4" width="18" height="16" rx="2" /><path d="M3 10h18M9 4v16" /></svg>
      </div>
      <h3>当前空间尚无数据表记录</h3>
      <p>在对话中上传 FITS / VOTable / ECSV / CSV / TSV 表格，或让助手检索 Gaia / VizieR 星表后，数据预览与分析产物会自动同步到这里。</p>
    </div>

    <template v-else>
      <header v-if="selectedDataset" class="table-header-card">
        <div class="table-selector-row">
          <UiSelect
            v-if="datasets.length > 1"
            class="table-dataset-select"
            variant="compact"
            :model-value="selectedDatasetId"
            aria-label="切换本项目数据表"
            :options="datasets.map(ds => ({ value: ds.id, label: `${ds.name} (${ds.row_count}×${ds.column_count})` }))"
            @update:model-value="chooseDataset(String($event))"
          />
          <h3 v-else class="table-single-title">{{ selectedDataset.name }}</h3>
          <button
            type="button"
            class="table-icon-danger"
            aria-label="删除当前数据表"
            title="删除当前数据表"
            :disabled="busy"
            @click="askDeleteDataset(selectedDataset)"
          >
            <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 6h18M8 6V4h8v2m-9 0v13a1 1 0 0 0 1 1h8a1 1 0 0 0 1-1V6" /></svg>
          </button>
        </div>

        <div class="table-meta-strip">
          <span class="ui-pill" :class="sourcePillClass[selectedDataset.source] || 'ui-pill-neutral'">
            {{ sourceLabels[selectedDataset.source] || selectedDataset.source }}
          </span>
          <span class="table-meta-text">
            {{ selectedDataset.row_count }} 行 × {{ selectedDataset.column_count }} 列
            <template v-if="selectedDataset.coordinate_frame"> · {{ selectedDataset.coordinate_frame }}</template>
            <template v-if="selectedDataset.ref_epoch"> · {{ selectedDataset.ref_epoch }}</template>
          </span>
        </div>
      </header>

      <div class="table-segmented" role="tablist" aria-label="数据表视图切换">
        <button
          type="button"
          role="tab"
          :class="{ 'is-active': activeSubView === 'preview' }"
          :aria-selected="activeSubView === 'preview'"
          @click="activeSubView = 'preview'"
        >
          数据预览
        </button>
        <button
          type="button"
          role="tab"
          :class="{ 'is-active': activeSubView === 'runs' }"
          :aria-selected="activeSubView === 'runs'"
          @click="activeSubView = 'runs'"
        >
          分析记录
          <em v-if="runs.length">{{ runs.length }}</em>
        </button>
      </div>

      <!-- SUB-VIEW 1: DATA PREVIEW -->
      <section v-if="activeSubView === 'preview'" class="table-section-stack">
        <template v-if="selectedDataset">
          <div class="table-data-card">
            <div class="table-data-head">
              <span class="table-data-range">
                第 {{ previewOffset + 1 }}–{{ Math.min(previewOffset + previewLimit, selectedDataset.row_count) }} / {{ selectedDataset.row_count }} 行
              </span>
              <UiSelect
                v-model="previewLimit"
                variant="compact"
                aria-label="每页显示行数"
                :options="pageSizeOptions"
                @update:model-value="previewOffset = 0"
              />
            </div>

            <div v-if="preview" class="table-data-scroll" tabindex="0" aria-label="数据表分页预览">
              <table class="table-compact">
                <thead>
                  <tr>
                    <th v-for="col in preview.columns" :key="col.name">
                      <span>{{ col.name }}</span>
                      <small v-if="col.unit">{{ col.unit }}</small>
                    </th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="(row, rIdx) in preview.rows" :key="rIdx">
                    <td v-for="(cell, cIdx) in row" :key="cIdx" class="num">
                      {{ cell === null || cell === '' ? '—' : cell }}
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
            <p v-else class="table-data-loading">正在加载数据表内容…</p>

            <div v-if="selectedDataset.row_count > previewLimit" class="table-pagination">
              <button
                type="button"
                class="table-page-btn"
                :disabled="previewOffset === 0"
                @click="previewOffset = Math.max(0, previewOffset - previewLimit)"
              >
                上一页
              </button>
              <span class="table-page-info">
                {{ Math.floor(previewOffset / previewLimit) + 1 }} / {{ Math.max(1, Math.ceil(selectedDataset.row_count / previewLimit)) }}
              </span>
              <button
                type="button"
                class="table-page-btn"
                :disabled="previewOffset + previewLimit >= selectedDataset.row_count"
                @click="previewOffset += previewLimit"
              >
                下一页
              </button>
            </div>
          </div>

          <div class="table-disclosure-group">
            <details class="table-disclosure">
              <summary>
                <span>列结构与单位</span>
                <span class="table-disclosure-meta">{{ selectedDataset.columns.length }} 列</span>
              </summary>
              <div class="table-disclosure-body">
                <div class="table-col-grid">
                  <div
                    v-for="col in selectedDataset.columns"
                    :key="col.name"
                    class="table-col-item"
                    :title="col.description || col.dtype"
                  >
                    <strong>{{ col.name }}</strong>
                    <span>
                      <template v-if="col.unit">{{ col.unit }} · </template>
                      {{ col.kind }}
                      <template v-if="col.missing"> · 缺 {{ col.missing }}</template>
                    </span>
                  </div>
                </div>
              </div>
            </details>
          </div>

          <div class="table-export-card">
            <span class="table-export-title">导出数据表</span>
            <div class="table-export-pills">
              <button type="button" :disabled="busy" @click="exportTable('csv')">CSV</button>
              <button type="button" :disabled="busy" @click="exportTable('ecsv')">ECSV</button>
              <button type="button" :disabled="busy" @click="exportTable('fits')">FITS</button>
            </div>
          </div>

          <footer v-if="selectedDataset.warnings?.length" class="table-footer-card">
            <details class="table-caveats">
              <summary>
                <span>未自动校正消光、零点或系统误差</span>
                <em>{{ selectedDataset.warnings.length }} 条口径说明</em>
              </summary>
              <ul class="table-caveat-list">
                <li v-for="w in selectedDataset.warnings" :key="w">{{ w }}</li>
              </ul>
            </details>
          </footer>
        </template>
        <div v-else class="ui-empty-inline">
          <h3>暂无可预览的数据表</h3>
          <p>请切换至「分析记录」查看历史摘要，或在对话中上传新数据表。</p>
        </div>
      </section>

      <!-- SUB-VIEW 2: ANALYSIS RUNS & RESULTS -->
      <section v-else class="table-section-stack">
        <div v-if="!runs.length" class="ui-empty-inline">
          <h3>暂无分析运行记录</h3>
          <p>在对话中提出统计、筛选、坐标变换、交叉匹配或曲线拟合需求，确认执行后结果与可复现包会保存在这里。</p>
        </div>
        <template v-else>
          <UiSelect
            v-if="runs.length > 1"
            variant="compact"
            :model-value="activeRun?.id || ''"
            aria-label="切换分析运行记录"
            :options="runs.map(r => ({ value: r.id, label: `${operatorLabels[r.operator] || r.operator} · ${formatShortTime(r.created_at)}` }))"
            @update:model-value="activeRunId = String($event); emit('select-run', String($event))"
          />

          <article v-if="activeRun" class="table-run-card">
            <header class="table-run-head">
              <div class="ui-pill-list">
                <span class="ui-pill ui-pill-gaia">{{ operatorLabels[activeRun.operator] || activeRun.operator }}</span>
                <span class="ui-pill" :class="isRunSuccess(activeRun.state) ? 'ui-pill-success' : 'ui-pill-danger'">
                  {{ isRunSuccess(activeRun.state) ? '已完成' : '失败' }}
                </span>
              </div>
              <small class="table-run-time">{{ formatShortTime(activeRun.created_at) }}</small>
            </header>

            <div v-if="activeRun.operator === 'fit' && activeRun.summary" class="table-run-kpis">
              <div class="table-run-kpi">
                <span>决定系数 R²</span>
                <strong>{{ formatNum(activeRun.summary.r2, 5) }}</strong>
                <small>RMSE {{ formatNum(activeRun.summary.rmse, 4) }} · dof {{ activeRun.summary.dof }}</small>
              </div>
              <div
                v-for="p in ((activeRun.summary.parameters as Array<{ name: string; value: number; err: number }>) || [])"
                :key="p.name"
                class="table-run-kpi"
              >
                <span>{{ p.name }}</span>
                <strong>{{ formatNum(p.value, 5) }}</strong>
                <small>± {{ formatNum(p.err, 5) }}</small>
              </div>
            </div>

            <div v-else-if="activeRun.operator === 'crossmatch' && activeRun.summary" class="table-run-kpis">
              <div class="table-run-kpi">
                <span>匹配源数</span>
                <strong>{{ activeRun.summary.matched_left_rows }}</strong>
                <small>匹配率 {{ formatNum(Number(activeRun.summary.match_rate) * 100, 1) }}% · 输出 {{ activeRun.summary.output_rows }} 行</small>
              </div>
              <div class="table-run-kpi">
                <span>角距中位 / P90</span>
                <strong>{{ formatNum(activeRun.summary.sep_median_arcsec, 3) }}"</strong>
                <small>P90 {{ formatNum(activeRun.summary.sep_p90_arcsec, 3) }}" · 半径 {{ activeRun.summary.radius_arcsec }}"</small>
              </div>
            </div>

            <div class="table-disclosure-group">
              <details class="table-disclosure" :open="!['fit', 'crossmatch'].includes(activeRun.operator)">
                <summary>
                  <span>完整摘要与参数 JSON</span>
                  <span class="table-disclosure-meta">结果</span>
                </summary>
                <div class="table-disclosure-body">
                  <pre class="table-json-pre">{{ JSON.stringify(activeRun.summary, null, 2) }}</pre>
                </div>
              </details>

              <details v-if="activeRun.software && Object.keys(activeRun.software).length" class="table-disclosure">
                <summary>
                  <span>科学计算版本与哈希</span>
                  <span class="table-disclosure-meta">溯源</span>
                </summary>
                <div class="table-disclosure-body">
                  <pre class="table-json-pre">{{ JSON.stringify({ request_sha256: activeRun.request_sha256, software: activeRun.software }, null, 2) }}</pre>
                </div>
              </details>
            </div>

            <details v-if="activeRun.warnings?.length" class="table-footer-card table-run-caveats">
              <summary class="table-run-caveats-summary">
                <span>边界与口径说明</span>
                <em>{{ activeRun.warnings.length }} 条</em>
              </summary>
              <ul class="table-caveat-list">
                <li v-for="w in activeRun.warnings" :key="w">{{ w }}</li>
              </ul>
            </details>

            <div class="table-run-actions">
              <button
                v-if="runOutputDataset"
                type="button"
                class="table-run-btn is-accent"
                :disabled="busy"
                @click="chooseDataset(runOutputDataset.id)"
              >
                查看派生表
              </button>
              <button
                type="button"
                class="table-run-btn"
                :disabled="busy"
                @click="downloadBundle(activeRun.id)"
              >
                ↓ ZIP 复现包
              </button>
            </div>
          </article>
        </template>

        <button
          v-if="selectedDataset"
          type="button"
          class="table-action-card"
          :disabled="busy"
          @click="openDirectPlot"
        >
          <span class="table-action-icon" aria-hidden="true">
            <svg viewBox="0 0 24 24"><path d="M4 19h16M7 15l3.5-4.5 3.5 2.5 4.5-6" /></svg>
          </span>
          <span class="table-action-copy">
            <strong>科研绘图</strong>
            <small>使用当前选中的数据表</small>
          </span>
        </button>
      </section>
    </template>

    <DirectPlotDialog ref="directPlotDialog" @submitted="onDirectPlotSubmitted" />

    <Teleport to="body">
      <dialog ref="deleteDialog" class="project-dialog" aria-label="删除数据表">
        <div class="dialog-header">
          <div class="dialog-header-copy"><h2>删除数据表「{{ deleteTarget?.name }}」？</h2></div>
          <button type="button" class="dialog-close" aria-label="关闭" :disabled="busy" @click="deleteDialog?.close()">
            <svg viewBox="0 0 24 24" aria-hidden="true"><path d="m6 6 12 12M6 18 18 6" /></svg>
          </button>
        </div>
        <p class="small">将从当前项目中移除该数据表，历史分析运行记录摘要与原对话快照不受影响。</p>
        <div class="project-actions">
          <button type="button" :disabled="busy" @click="deleteDialog?.close()">取消</button>
          <button type="button" class="button-danger" :disabled="busy" @click="confirmDeleteDataset">
            {{ busy ? '删除中…' : '确认删除' }}
          </button>
        </div>
      </dialog>
    </Teleport>
  </div>
</template>

<style scoped>
.table-result-panel {
  display: grid;
  gap: 12px;
  padding-top: 4px;
}

.table-header-card {
  display: grid;
  gap: 8px;
  padding: 11px 12px;
  border-radius: var(--radius-card);
  border: 1px solid var(--line);
  background: var(--surface-card);
  box-shadow: var(--shadow-card);
}

.table-selector-row {
  display: flex;
  align-items: center;
  gap: 6px;
}

.table-dataset-select {
  flex: 1 1 auto;
  min-width: 0;
}

.table-single-title {
  flex: 1 1 auto;
  margin: 0;
  font-size: 13.5px;
  font-weight: 620;
  color: var(--ink);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.table-icon-danger {
  width: 30px;
  height: 30px;
  min-height: 30px;
  padding: 0;
  flex: 0 0 30px;
  display: grid;
  place-items: center;
  border-radius: 8px;
  border: 1px solid transparent;
  background: transparent;
  color: var(--muted);
  cursor: pointer;
  transition: color 140ms ease, background-color 140ms ease, border-color 140ms ease;
}

.table-icon-danger svg {
  width: 14px;
  height: 14px;
  fill: none;
  stroke: currentColor;
  stroke-width: 1.8;
  stroke-linecap: round;
  stroke-linejoin: round;
}

.table-icon-danger:hover:not(:disabled) {
  color: var(--danger);
  background: color-mix(in srgb, var(--danger) 8%, transparent);
  border-color: color-mix(in srgb, var(--danger) 24%, transparent);
}

.table-meta-strip {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 7px;
}

.table-meta-text {
  font-size: 11.5px;
  color: var(--muted);
  font-variant-numeric: tabular-nums;
}

.table-segmented {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 4px;
  padding: 3px;
  border-radius: 10px;
  border: 1px solid var(--line);
  background: var(--surface-subtle);
}

.table-segmented button {
  min-height: 30px;
  padding: 0 10px;
  border: 1px solid transparent;
  border-radius: 8px;
  background: transparent;
  color: var(--muted);
  font-size: 12.5px;
  font-weight: 560;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  box-shadow: none;
  transition: background-color 140ms ease, color 140ms ease, border-color 140ms ease;
}

.table-segmented button.is-active {
  background: var(--surface-card);
  border-color: var(--line);
  color: var(--ink);
  box-shadow: var(--shadow-card);
}

.table-segmented button em {
  font-style: normal;
  font-size: 10.5px;
  padding: 1px 6px;
  border-radius: 999px;
  background: color-mix(in srgb, var(--accent) 12%, transparent);
  color: var(--accent);
  font-variant-numeric: tabular-nums;
}

.table-section-stack {
  display: grid;
  gap: 12px;
}

.table-data-card {
  display: grid;
  gap: 8px;
  padding: 11px 12px;
  border-radius: var(--radius-card);
  border: 1px solid var(--line);
  background: var(--surface-card);
  box-shadow: var(--shadow-card);
  min-width: 0;
}

.table-data-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.table-data-range {
  font-size: 11.5px;
  color: var(--muted);
  font-variant-numeric: tabular-nums;
}

.table-data-scroll {
  width: 100%;
  overflow: auto;
  max-height: 340px;
  border-radius: 9px;
  border: 1px solid var(--line);
}

.table-data-loading {
  margin: 0;
  padding: 20px 12px;
  text-align: center;
  font-size: 12px;
  color: var(--muted);
}

.table-compact {
  width: 100%;
  border-collapse: collapse;
  font-size: 11px;
  white-space: nowrap;
}

.table-compact th {
  position: sticky;
  top: 0;
  padding: 7px 9px;
  background: var(--surface-subtle);
  color: var(--ink);
  font-weight: 600;
  text-align: left;
  border-bottom: 1px solid var(--line);
  border-right: 1px solid color-mix(in srgb, var(--line) 75%, transparent);
}

.table-compact th small {
  display: block;
  font-weight: 400;
  font-size: 10px;
  color: var(--muted);
}

.table-compact td {
  padding: 6px 9px;
  color: var(--ink);
  border-bottom: 1px solid color-mix(in srgb, var(--line) 70%, transparent);
  border-right: 1px solid color-mix(in srgb, var(--line) 55%, transparent);
  font-family: var(--font-mono);
}

.table-compact td.num {
  font-variant-numeric: tabular-nums;
}

.table-pagination {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding-top: 2px;
}

.table-page-btn {
  min-height: 28px;
  padding: 0 10px;
  border-radius: 8px;
  font-size: 11.5px;
}

.table-page-info {
  font-size: 11.5px;
  color: var(--muted);
  font-variant-numeric: tabular-nums;
}

.table-disclosure-group {
  display: grid;
  border-radius: var(--radius-card);
  border: 1px solid var(--line);
  background: var(--surface-card);
  box-shadow: var(--shadow-card);
  overflow: hidden;
}

.table-disclosure {
  padding: 0;
  border-top: 0;
}

.table-disclosure + .table-disclosure {
  border-top: 1px solid var(--line);
}

.table-disclosure > summary {
  list-style: none;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 10px 13px;
  font-size: 12.5px;
  font-weight: 560;
  color: var(--ink);
  cursor: pointer;
  user-select: none;
  transition: background-color 140ms ease;
}

.table-disclosure > summary::-webkit-details-marker {
  display: none;
}

.table-disclosure > summary::before {
  content: '';
  width: 6px;
  height: 6px;
  border-right: 1.6px solid var(--muted);
  border-bottom: 1.6px solid var(--muted);
  transform: rotate(-45deg);
  transition: transform 160ms ease;
  flex: none;
  margin-right: 2px;
}

.table-disclosure[open] > summary::before {
  transform: rotate(45deg);
}

.table-disclosure > summary > span:first-child {
  flex: 1 1 auto;
}

.table-disclosure > summary:hover {
  background: color-mix(in srgb, var(--accent) 5%, transparent);
}

.table-disclosure-meta {
  font-size: 11px;
  font-weight: 500;
  color: var(--muted);
  font-variant-numeric: tabular-nums;
}

.table-disclosure-body {
  padding: 0 12px 12px;
}

.table-col-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));
  gap: 6px;
}

.table-col-item {
  display: grid;
  gap: 2px;
  padding: 6px 9px;
  border-radius: 8px;
  border: 1px solid var(--line);
  background: var(--surface-subtle);
  min-width: 0;
}

.table-col-item strong {
  font-size: 11.5px;
  font-family: var(--font-mono);
  color: var(--ink);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.table-col-item span {
  font-size: 10.5px;
  color: var(--muted);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.table-action-card {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 12px;
  border-radius: var(--radius-card);
  border: 1px solid var(--line);
  background: var(--surface-card);
  color: var(--ink);
  text-align: left;
  box-shadow: var(--shadow-card);
  cursor: pointer;
  min-width: 0;
  transition: border-color 150ms ease, background-color 150ms ease, transform 120ms ease;
}

.table-action-card:hover:not(:disabled) {
  border-color: color-mix(in srgb, var(--accent) 42%, var(--line));
  background: color-mix(in srgb, var(--accent) 5%, var(--surface-card));
}

.table-action-card:active:not(:disabled) {
  transform: scale(0.985);
}

.table-action-icon {
  width: 30px;
  height: 30px;
  flex: none;
  border-radius: 9px;
  display: grid;
  place-items: center;
  border: 1px solid color-mix(in srgb, var(--accent) 26%, transparent);
  background: color-mix(in srgb, var(--accent) 11%, var(--surface-card));
  color: var(--accent);
}

.table-action-icon svg {
  width: 15px;
  height: 15px;
  fill: none;
  stroke: currentColor;
  stroke-width: 1.85;
  stroke-linecap: round;
  stroke-linejoin: round;
}

.table-action-copy {
  display: grid;
  gap: 2px;
  min-width: 0;
}

.table-action-copy strong {
  font-size: 12.5px;
  font-weight: 600;
  color: var(--ink);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.table-action-copy small {
  font-size: 10.5px;
  color: var(--muted);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.table-export-card {
  display: grid;
  gap: 6px;
  padding: 9px 11px;
  border-radius: var(--radius-card);
  border: 1px solid var(--line);
  background: var(--surface-card);
  box-shadow: var(--shadow-card);
  min-width: 0;
}

.table-export-title {
  font-size: 11px;
  font-weight: 560;
  color: var(--muted);
}

.table-export-pills {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 4px;
}

.table-export-pills button {
  min-height: 26px;
  padding: 0 4px;
  border-radius: 7px;
  border: 1px solid var(--line);
  background: var(--surface-subtle);
  color: var(--ink);
  font-size: 11px;
  font-weight: 600;
  font-family: var(--font-mono);
  cursor: pointer;
  transition: border-color 140ms ease, color 140ms ease, background-color 140ms ease;
}

.table-export-pills button:hover:not(:disabled) {
  border-color: color-mix(in srgb, var(--accent) 45%, var(--line));
  color: var(--accent);
  background: color-mix(in srgb, var(--accent) 7%, var(--surface-card));
}

.table-footer-card {
  padding: 10px 12px;
  border-radius: var(--radius-card);
  border: 1px solid var(--line);
  background: var(--surface-subtle);
}

.table-caveats {
  padding: 0;
  border-top: 0;
}

.table-caveats > summary,
.table-run-caveats-summary {
  list-style: none;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  font-size: 11.5px;
  color: var(--muted);
  cursor: pointer;
  user-select: none;
}

.table-caveats > summary::-webkit-details-marker,
.table-run-caveats-summary::-webkit-details-marker {
  display: none;
}

.table-caveats > summary em,
.table-run-caveats-summary em {
  font-style: normal;
  font-size: 11px;
  color: var(--accent);
  white-space: nowrap;
}

.table-caveat-list {
  margin: 8px 0 0;
  padding-left: 16px;
  display: grid;
  gap: 5px;
  font-size: 11.5px;
  line-height: 1.55;
  color: var(--muted);
}

.table-run-card {
  display: grid;
  gap: 12px;
  padding: 12px;
  border-radius: var(--radius-card);
  border: 1px solid var(--line);
  background: var(--surface-card);
  box-shadow: var(--shadow-card);
}

.table-run-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.table-run-time {
  font-size: 11px;
  color: var(--muted);
  font-variant-numeric: tabular-nums;
}

.table-run-kpis {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
}

.table-run-kpi {
  display: grid;
  gap: 3px;
  padding: 9px 11px;
  border-radius: 10px;
  border: 1px solid var(--line);
  background: var(--surface-subtle);
}

.table-run-kpi span {
  font-size: 11px;
  color: var(--muted);
}

.table-run-kpi strong {
  font-size: 16px;
  font-weight: 660;
  color: var(--ink);
  font-variant-numeric: tabular-nums;
}

.table-run-kpi small {
  font-size: 10.5px;
  color: var(--muted);
  font-variant-numeric: tabular-nums;
}

.table-json-pre {
  margin: 0;
  max-height: 220px;
  overflow: auto;
  font-size: 11px;
  border-radius: 8px;
  border: 1px solid var(--line);
}

.table-run-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.table-run-btn {
  min-height: 32px;
  padding: 0 12px;
  border-radius: 9px;
  border: 1px solid var(--line);
  background: var(--surface-card);
  color: var(--ink);
  font-size: 12px;
  font-weight: 560;
  cursor: pointer;
}

.table-run-btn:hover:not(:disabled) {
  border-color: color-mix(in srgb, var(--accent) 42%, var(--line));
  color: var(--accent);
}

.table-run-btn.is-accent {
  border-color: color-mix(in srgb, var(--accent) 36%, var(--line));
  background: color-mix(in srgb, var(--accent) 10%, var(--surface-card));
  color: var(--accent);
}
</style>
