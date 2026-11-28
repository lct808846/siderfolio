<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { plottingApi } from '../api/plotting'
import { useDirectPlots, type DirectPlotJob } from '../stores/directPlots'
import type { AnalysisDataset, TableColumnMeta } from '../types'
import StatusNotice from './StatusNotice.vue'
import UiSelect, { type UiSelectOption } from './UiSelect.vue'

export interface DirectPlotCompletedPayload {
  projectId: string
  runId: string
  title: string
  files: string[]
}

const emit = defineEmits<{
  submitted: [job: DirectPlotJob]
}>()

const route = useRoute()
const directPlots = useDirectPlots()

const dialogEl = ref<HTMLDialogElement | null>(null)
const projectId = ref('')
const dataset = ref<AnalysisDataset | null>(null)

const chart = ref<'scatter' | 'line' | 'histogram' | 'errorbar'>('scatter')
const xCol = ref('')
const yCol = ref('')
const colorCol = ref('')
const yErrCol = ref('')
const bins = ref(20)
const invertY = ref(false)
const title = ref('')

const initializing = ref(false)
const needsStorageInit = ref(false)
const error = ref('')

const chartOptions: UiSelectOption<'scatter' | 'line' | 'histogram' | 'errorbar'>[] = [
  { value: 'scatter', label: '散点图（Scatter / CMD）' },
  { value: 'histogram', label: '直方图（Histogram）' },
  { value: 'line', label: '折线图（Line）' },
  { value: 'errorbar', label: '误差棒图（Errorbar）' },
]

const numericColumns = computed<TableColumnMeta[]>(() =>
  (dataset.value?.columns || []).filter(c => c.kind === 'number' || c.kind === 'integer'),
)

const columnOptions = computed<UiSelectOption<string>[]>(() =>
  numericColumns.value.map(c => ({
    value: c.name,
    label: c.unit ? `${c.name} [${c.unit}]` : c.name,
  })),
)

const optionalColumnOptions = computed<UiSelectOption<string>[]>(() => [
  { value: '', label: '不使用' },
  ...columnOptions.value,
])

function colMeta(name: string): TableColumnMeta | undefined {
  return dataset.value?.columns.find(c => c.name === name)
}

function isMagnitudeCol(name: string): boolean {
  const lower = name.toLowerCase()
  const unit = (colMeta(name)?.unit || '').toLowerCase()
  return unit === 'mag' || /(?:^|_)mag$|g_mean_mag|jmag|hmag|kmag|w[1-4]mag/i.test(lower)
}

function axisLabel(name: string): string {
  const unit = colMeta(name)?.unit
  return unit ? `${name} (${unit})` : name
}

function pickSmartDefaults(ds: AnalysisDataset) {
  const nums = ds.columns.filter(c => c.kind === 'number' || c.kind === 'integer').map(c => c.name)
  const has = (name: string) => nums.includes(name)
  const findLike = (re: RegExp) => nums.find(n => re.test(n))

  chart.value = 'scatter'
  colorCol.value = ''
  yErrCol.value = ''
  bins.value = 20

  if (has('bp_rp') && has('phot_g_mean_mag')) {
    xCol.value = 'bp_rp'
    yCol.value = 'phot_g_mean_mag'
    invertY.value = true
    title.value = `${ds.name} · 观测色星等图`
    return
  }
  const jCol = findLike(/(?:^|_)Jmag$/i)
  const kCol = findLike(/(?:^|_)Kmag$/i)
  if (has('phot_g_mean_mag') && jCol) {
    xCol.value = jCol
    yCol.value = 'phot_g_mean_mag'
    invertY.value = true
    title.value = `${ds.name} · 光学-近红外星等对比`
    return
  }
  if (jCol && kCol) {
    xCol.value = jCol
    yCol.value = kCol
    invertY.value = true
    title.value = `${ds.name} · 近红外星等图`
    return
  }
  if (has('pmra') && has('pmdec')) {
    xCol.value = 'pmra'
    yCol.value = 'pmdec'
    invertY.value = false
    title.value = `${ds.name} · 自行分布`
    return
  }
  const raCol = findLike(/^(?:ra|raj2000|ra_icrs)$/i)
  const decCol = findLike(/^(?:dec|dej2000|de_icrs)$/i)
  if (raCol && decCol) {
    xCol.value = raCol
    yCol.value = decCol
    invertY.value = false
    title.value = `${ds.name} · 天球位置分布`
    return
  }
  xCol.value = nums[0] || ''
  yCol.value = nums[1] || nums[0] || ''
  if (nums.length === 1) {
    chart.value = 'histogram'
  }
  invertY.value = isMagnitudeCol(yCol.value)
  title.value = `${ds.name} · 科研图形`
}

watch(yCol, nextY => {
  if (nextY) {
    invertY.value = isMagnitudeCol(nextY)
  }
})

function buildPythonScript(): { script: string; columns: string[]; axes: Record<string, string>; explanation: string } {
  const py = (v: unknown) => JSON.stringify(v)
  const plotTitle = title.value.trim() || `${dataset.value?.name || '数据表'} · 科研图形`
  const xLabel = axisLabel(xCol.value)
  const yLabel = chart.value === 'histogram' ? '源数量 (Count)' : axisLabel(yCol.value)
  const usedCols = [xCol.value]
  if (chart.value !== 'histogram' && yCol.value && !usedCols.includes(yCol.value)) usedCols.push(yCol.value)
  if (chart.value === 'scatter' && colorCol.value && !usedCols.includes(colorCol.value)) usedCols.push(colorCol.value)
  if (chart.value === 'errorbar' && yErrCol.value && !usedCols.includes(yErrCol.value)) usedCols.push(yErrCol.value)

  const axes: Record<string, string> = { x: xLabel, y: yLabel }
  if (chart.value === 'scatter' && colorCol.value) {
    axes.color = axisLabel(colorCol.value)
  }

  let body: string
  if (chart.value === 'histogram') {
    const safeBins = Math.max(5, Math.min(80, Math.round(Number(bins.value) || 20)))
    body = `
xs = []
total = 0
with open('/input/data.csv', 'r', encoding='utf-8-sig', newline='') as f:
    for row in csv.DictReader(f):
        total += 1
        xv = to_float(row.get(${py(xCol.value)}))
        if xv is not None:
            xs.append(xv)

if not xs:
    raise RuntimeError('所选列无有效数值可供绘制。')

arr = np.asarray(xs, dtype=float)
ax.hist(arr, bins=${safeBins}, color='#2563eb', alpha=0.82, edgecolor='#ffffff', linewidth=0.8)
ax.set_xlabel(${py(xLabel)}, fontsize=12, labelpad=8)
ax.set_ylabel('源数量 (Count)', fontsize=12)
ax.set_title(${py(plotTitle)}, fontsize=13.5, pad=12)
footnote = f'输入 {total} 行 · 有效 {len(arr)} 行 · 缺失/无效 {total - len(arr)} 行 · 分箱 {${safeBins}}；仅描述当前数据表样本。'
`
  } else if (chart.value === 'errorbar') {
    body = `
xs, ys, yerrs = [], [], []
total = 0
err_col = ${py(yErrCol.value)}
with open('/input/data.csv', 'r', encoding='utf-8-sig', newline='') as f:
    for row in csv.DictReader(f):
        total += 1
        xv = to_float(row.get(${py(xCol.value)}))
        yv = to_float(row.get(${py(yCol.value)}))
        if xv is None or yv is None:
            continue
        if err_col:
            ev = to_float(row.get(err_col))
            if ev is None or ev < 0:
                continue
            yerrs.append(ev)
        xs.append(xv)
        ys.append(yv)

if not xs:
    raise RuntimeError('所选列无有效配对数值可供绘制。')

ax.errorbar(
    xs, ys,
    yerr=(yerrs if err_col else None),
    fmt='o', markersize=5.2, color='#2563eb', ecolor='#64748b',
    elinewidth=1.0, capsize=2.5, alpha=0.88
)
if ${invertY.value ? 'True' : 'False'}:
    ax.invert_yaxis()
ax.set_xlabel(${py(xLabel)}, fontsize=12, labelpad=8)
ax.set_ylabel(${py(yLabel)}, fontsize=12)
ax.set_title(${py(plotTitle)}, fontsize=13.5, pad=12)
footnote = f'输入 {total} 行 · 有效 {len(xs)} 点 · 排除缺失 {total - len(xs)} 行；未自动校正消光或零点。'
`
  } else if (chart.value === 'line') {
    body = `
pts = []
total = 0
with open('/input/data.csv', 'r', encoding='utf-8-sig', newline='') as f:
    for row in csv.DictReader(f):
        total += 1
        xv = to_float(row.get(${py(xCol.value)}))
        yv = to_float(row.get(${py(yCol.value)}))
        if xv is not None and yv is not None:
            pts.append((xv, yv))

if not pts:
    raise RuntimeError('所选列无有效配对数值可供绘制。')

pts.sort(key=lambda item: item[0])
xs = [p[0] for p in pts]
ys = [p[1] for p in pts]
ax.plot(xs, ys, '-o', color='#2563eb', linewidth=1.6, markersize=4.5, alpha=0.9)
if ${invertY.value ? 'True' : 'False'}:
    ax.invert_yaxis()
ax.set_xlabel(${py(xLabel)}, fontsize=12, labelpad=8)
ax.set_ylabel(${py(yLabel)}, fontsize=12)
ax.set_title(${py(plotTitle)}, fontsize=13.5, pad=12)
footnote = f'输入 {total} 行 · 有效 {len(xs)} 点（按 X 升序连线）· 排除缺失 {total - len(xs)} 行。'
`
  } else {
    body = `
xs, ys, cs = [], [], []
total = 0
c_col = ${py(colorCol.value)}
with open('/input/data.csv', 'r', encoding='utf-8-sig', newline='') as f:
    for row in csv.DictReader(f):
        total += 1
        xv = to_float(row.get(${py(xCol.value)}))
        yv = to_float(row.get(${py(yCol.value)}))
        if xv is None or yv is None:
            continue
        if c_col:
            cv = to_float(row.get(c_col))
            if cv is None:
                continue
            cs.append(cv)
        xs.append(xv)
        ys.append(yv)

if not xs:
    raise RuntimeError('所选列无有效配对数值可供绘制。')

if c_col:
    sc = ax.scatter(xs, ys, c=cs, cmap='viridis', s=32, alpha=0.88, edgecolors='#1e293b', linewidths=0.35)
    cbar = fig.colorbar(sc, ax=ax, pad=0.02)
    cbar.set_label(${py(colorCol.value ? axisLabel(colorCol.value) : '')}, fontsize=11)
else:
    ax.scatter(xs, ys, color='#2563eb', s=32, alpha=0.85, edgecolors='#1e3a8a', linewidths=0.35)
if ${invertY.value ? 'True' : 'False'}:
    ax.invert_yaxis()
ax.set_xlabel(${py(xLabel)}, fontsize=12, labelpad=8)
ax.set_ylabel(${py(yLabel)}, fontsize=12)
ax.set_title(${py(plotTitle)}, fontsize=13.5, pad=12)
footnote = f'输入 {total} 行 · 有效 {len(xs)} 点 · 排除缺失 {total - len(xs)} 行；未自动校正消光、零点或成员判定。'
`
  }

  const script = `import csv
import math
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

plt.rcParams['font.sans-serif'] = ['WenQuanYi Zen Hei', 'DejaVu Sans']
plt.rcParams['axes.unicode_minus'] = False

def to_float(raw):
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    try:
        v = float(s)
        return v if math.isfinite(v) else None
    except ValueError:
        return None

fig, ax = plt.subplots(figsize=(8.0, 6.0), dpi=200)
fig.patch.set_facecolor('white')
ax.set_facecolor('white')
${body}
ax.grid(True, linestyle='--', linewidth=0.6, alpha=0.35)
ax.tick_params(labelsize=10.5)
fig.subplots_adjust(left=0.12, right=0.94, top=0.90, bottom=0.20)
fig.text(0.5, 0.025, footnote, ha='center', va='bottom', fontsize=10, color='#475569')
fig.savefig('/output/figure.png', dpi=200)
fig.savefig('/output/figure.pdf')
`
  const explanation = `基于数据表「${dataset.value?.name || ''}」在隔离容器中直接绘制 ${chart.value} 图形（使用列：${usedCols.join('、')}）。`
  return { script, columns: usedCols, axes, explanation }
}

const canSubmit = computed(() => {
  if (!dataset.value || !xCol.value || initializing.value) return false
  if (chart.value !== 'histogram' && !yCol.value) return false
  return true
})

async function open(pid: string, ds: AnalysisDataset) {
  projectId.value = pid
  dataset.value = ds
  error.value = ''
  needsStorageInit.value = false
  pickSmartDefaults(ds)
  await nextTick()
  if (dialogEl.value && !dialogEl.value.open) {
    dialogEl.value.showModal()
  }
  // Quietly check plot storage readiness without blocking dialog open.
  void plottingApi.status().then(st => {
    needsStorageInit.value = !st.storage_ready
  }).catch(() => { /* Ignore non-blocking probe. */ })
}

function close() {
  if (initializing.value) return
  if (dialogEl.value?.open) dialogEl.value.close()
}

function onBackdropClick(event: MouseEvent) {
  if (event.target === dialogEl.value) close()
}

async function initializePlotStorage() {
  if (initializing.value) return
  initializing.value = true
  error.value = ''
  try {
    await plottingApi.initialize()
    needsStorageInit.value = false
    submitBackgroundPlot()
  } catch (e) {
    error.value = e instanceof Error ? e.message : '初始化绘图存储失败。'
  } finally {
    initializing.value = false
  }
}

function submitBackgroundPlot() {
  if (!canSubmit.value || !dataset.value || !projectId.value) return
  const built = buildPythonScript()
  const finishedTitle = title.value.trim() || `${dataset.value.name} · 科研图形`
  const conversationId = typeof route.params.id === 'string' ? route.params.id : 'draft'
  const job = directPlots.enqueue({
    conversationId,
    projectId: projectId.value,
    datasetId: dataset.value.id,
    title: finishedTitle,
    chart: chart.value,
    columns: built.columns,
    axes: built.axes,
    explanation: built.explanation,
    warnings: dataset.value.warnings?.slice(0, 4) || [],
    script: built.script,
  })
  if (dialogEl.value?.open) dialogEl.value.close()
  emit('submitted', job)
}

defineExpose({ open, close })
</script>

<template>
  <Teleport to="body">
    <dialog
      ref="dialogEl"
      class="project-dialog direct-plot-dialog"
      aria-labelledby="direct-plot-title"
      @click="onBackdropClick"
      @cancel="initializing && $event.preventDefault()"
    >
      <header class="direct-plot-head">
        <div>
          <h2 id="direct-plot-title">科研绘图</h2>
          <p v-if="dataset" class="small muted">
            使用「{{ dataset.name }}」（{{ dataset.row_count }} 行）绘图，完成后自动显示在结果栏。
          </p>
        </div>
        <button type="button" class="dialog-close" aria-label="关闭" :disabled="initializing" @click="close">
          <svg viewBox="0 0 24 24" aria-hidden="true"><path d="m6 6 12 12M6 18 18 6" /></svg>
        </button>
      </header>

      <div v-if="!numericColumns.length" class="ui-empty-inline">
        <h3>当前数据表没有可绘制的数值列</h3>
        <p>请先切换到包含数值列的数据表，或派生数值列后再绘图。</p>
      </div>

      <form v-else class="direct-plot-form" @submit.prevent="submitBackgroundPlot">
        <div class="direct-plot-grid">
          <label class="direct-plot-field">
            <span>图表类型</span>
            <UiSelect v-model="chart" :options="chartOptions" aria-label="图表类型" :disabled="initializing" />
          </label>
          <label class="direct-plot-field">
            <span>图标题</span>
            <input v-model="title" type="text" maxlength="200" placeholder="输入图形标题" :disabled="initializing">
          </label>
        </div>

        <div class="direct-plot-grid">
          <label class="direct-plot-field">
            <span>{{ chart === 'histogram' ? '统计列（X 轴）' : 'X 轴列' }}</span>
            <UiSelect v-model="xCol" :options="columnOptions" aria-label="X 轴列" :disabled="initializing" />
          </label>
          <label v-if="chart !== 'histogram'" class="direct-plot-field">
            <span>Y 轴列</span>
            <UiSelect v-model="yCol" :options="columnOptions" aria-label="Y 轴列" :disabled="initializing" />
          </label>
          <label v-else class="direct-plot-field">
            <span>分箱数（Bins）</span>
            <input v-model.number="bins" type="number" min="5" max="80" step="1" :disabled="initializing">
          </label>
        </div>

        <div v-if="chart === 'scatter' || chart === 'errorbar'" class="direct-plot-grid">
          <label v-if="chart === 'scatter'" class="direct-plot-field">
            <span>颜色映射列（可选）</span>
            <UiSelect v-model="colorCol" :options="optionalColumnOptions" aria-label="颜色映射列" :disabled="initializing" />
          </label>
          <label v-if="chart === 'errorbar'" class="direct-plot-field">
            <span>Y 轴误差列（可选）</span>
            <UiSelect v-model="yErrCol" :options="optionalColumnOptions" aria-label="Y 轴误差列" :disabled="initializing" />
          </label>
          <label class="direct-plot-check">
            <input v-model="invertY" type="checkbox" :disabled="initializing">
            <span>反转 Y 轴（星等图常用，亮星在上）</span>
          </label>
        </div>

        <label v-else-if="chart === 'line'" class="direct-plot-check">
          <input v-model="invertY" type="checkbox" :disabled="initializing">
          <span>反转 Y 轴（星等图常用，亮星在上）</span>
        </label>

        <StatusNotice v-if="error" title="绘图未完成" :message="error" @dismiss="error = ''" />

        <div v-if="needsStorageInit" class="direct-plot-init-box">
          <p class="small">当前空间需要先初始化绘图存储，完成后将自动开始绘图。</p>
          <button type="button" class="button-primary" :disabled="initializing" @click="initializePlotStorage">
            {{ initializing ? '正在初始化…' : '初始化并开始绘图' }}
          </button>
        </div>

        <footer class="direct-plot-footer">
          <button type="button" class="button-secondary" :disabled="initializing" @click="close">取消</button>
          <button v-if="!needsStorageInit" type="submit" class="button-primary" :disabled="!canSubmit">
            开始绘图
          </button>
        </footer>
      </form>
    </dialog>
  </Teleport>
</template>

<style scoped>
.direct-plot-dialog {
  width: min(560px, calc(100vw - 32px));
  max-height: calc(100dvh - 48px);
  overflow: auto;
  padding: var(--space-5);
  color: var(--ink);
}

.direct-plot-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 14px;
}

.direct-plot-head h2 {
  margin: 0 0 4px;
  font-size: 17px;
  font-weight: 620;
  color: var(--ink);
}

.direct-plot-head p {
  margin: 0;
}

.direct-plot-form {
  display: grid;
  gap: 12px;
}

.direct-plot-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
  align-items: end;
}

.direct-plot-field {
  display: grid;
  gap: 5px;
  min-width: 0;
}

.direct-plot-field > span {
  font-size: 12px;
  font-weight: 560;
  color: var(--muted);
}

.direct-plot-field input {
  width: 100%;
  min-height: 36px;
  padding: 6px 10px;
  border-radius: var(--radius-control);
  border: 1px solid var(--line);
  background: var(--surface-card);
  color: var(--ink);
  font-size: 13px;
}

.direct-plot-check {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  min-height: 36px;
  font-size: 12.5px;
  color: var(--ink);
  cursor: pointer;
}

.direct-plot-init-box {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 10px 12px;
  border-radius: 10px;
  border: 1px solid color-mix(in srgb, var(--accent) 28%, var(--line));
  background: color-mix(in srgb, var(--accent) 6%, var(--surface-card));
}

.direct-plot-init-box p {
  margin: 0;
}

.direct-plot-status {
  margin: 0;
}

.direct-plot-footer {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  padding-top: 4px;
}

@media (max-width: 560px) {
  .direct-plot-grid {
    grid-template-columns: 1fr;
  }
}
</style>
