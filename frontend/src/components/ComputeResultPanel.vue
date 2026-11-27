<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { ApiError, apiUrl } from '../api'
import {
  computeApi,
  type ComputeList,
  type ComputeParameters,
  type ComputeResult,
  type ComputeTask,
  type PlotKind,
} from '../api/compute'
import { sessionFetch } from '../session-http'
import ArtifactFileViewer, { type ArtifactPreviewItem } from './ArtifactFileViewer.vue'
import NBodyProgressVisual from './NBodyProgressVisual.vue'
import StatusNotice from './StatusNotice.vue'
import UiSelect from './UiSelect.vue'

const props = defineProps<{
  projectId: string
  taskId?: string
  allowedTaskIds?: string[]
}>()

const emit = defineEmits<{
  'select-task': [taskId: string]
}>()

const listing = ref<ComputeList | null>(null)
const task = ref<ComputeTask | null>(null)
const result = ref<ComputeResult | null>(null)
const loading = ref(false)
const busy = ref(false)
const error = ref('')
const resultError = ref('')
const unavailable = ref(false)
const activeSubView = ref<'plots' | 'compare' | 'files'>('plots')

const selectedPlot = ref<PlotKind>('trajectory')
const selectedSample = ref(0)
const plotFailed = ref(false)
const zoomDialog = ref<HTMLDialogElement | null>(null)
const downloadPlots = ref<PlotKind[]>(['trajectory', 'snapshot', 'energy'])
const compareId = ref('')
const compared = ref<{ task: ComputeTask; result: ComputeResult } | null>(null)
const compareError = ref('')
const deleteArmed = ref(false)

const labels: Record<ComputeTask['state'], string> = {
  draft: '待确认',
  queued: '排队中',
  running: '运行中',
  cancelling: '正在取消',
  succeeded: '已完成',
  failed: '失败',
  cancelled: '已取消',
  interrupted: '已中断',
}
const sourceLabels: Record<ComputeTask['source'], string> = {
  manual: '手动录入',
  template: '双体模板',
  conversation: '对话参数草稿',
}
const plotOptions = [
  { kind: 'trajectory' as const, label: '轨道轨迹' },
  { kind: 'snapshot' as const, label: '位置快照' },
  { kind: 'energy' as const, label: '能量偏差' },
]

const selectedTaskId = ref('')
let generation = 0
let pollTimer: ReturnType<typeof setTimeout> | undefined

const isActiveState = (state: ComputeTask['state']) => ['queued', 'running', 'cancelling'].includes(state)
const formatSci = (value: number | null | undefined) => (value == null ? '不适用' : value.toExponential(4))
const formatSeconds = (value: number | null | undefined) => (value == null ? '未采集' : `${value.toFixed(3)} s`)
const formatTime = (value: string) => new Date(value).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })

function statePillClass(state: ComputeTask['state']) {
  if (state === 'succeeded') return 'ui-pill-success'
  if (state === 'failed' || state === 'interrupted') return 'ui-pill-danger'
  if (isActiveState(state)) return 'ui-pill-compute'
  if (state === 'draft') return 'ui-pill-warning'
  return 'ui-pill-neutral'
}

function programVersion(run: ComputeResult) {
  return run.engine === 'petar' ? `PeTar ${run.petar_version}` : `REBOUND ${run.rebound_version}`
}

function maxima(run: ComputeResult) {
  const relative = run.samples[0]?.energy_relative != null
  return {
    energy: Math.max(...run.samples.map(sample => Math.abs(sample.energy_delta))),
    relative: relative ? Math.max(...run.samples.map(sample => Math.abs(sample.energy_relative || 0))) : null,
    angular: Math.max(...run.samples.map(sample => sample.angular_delta)),
  }
}

const visibleTasks = computed(() => {
  const all = listing.value?.tasks || []
  if (!props.allowedTaskIds) return all
  const allowed = new Set(props.allowedTaskIds)
  if (props.taskId) allowed.add(props.taskId)
  return all.filter(item => allowed.has(item.id))
})

const metrics = computed(() => (result.value ? maxima(result.value) : null))
const succeededOthers = computed(() =>
  visibleTasks.value.filter(item => item.state === 'succeeded' && item.id !== task.value?.id),
)

const plotUrl = computed(() =>
  task.value && result.value && props.projectId
    ? computeApi.plot(
        props.projectId,
        task.value.id,
        selectedPlot.value,
        selectedPlot.value === 'snapshot' ? selectedSample.value : undefined,
      )
    : '',
)

const artifactItems = computed<ArtifactPreviewItem[]>(() => {
  if (!task.value || !props.projectId) return []
  const current = task.value
  const items: ArtifactPreviewItem[] = []
  if (current.state === 'succeeded' && result.value) {
    items.push(
      {
        id: 'trajectory.svg',
        name: 'trajectory.svg',
        subtitle: 'N 体轨道轨迹图（矢量）',
        category: 'image',
        mediaType: 'image/svg+xml',
        url: computeApi.plot(props.projectId, current.id, 'trajectory'),
      },
      {
        id: 'snapshot.svg',
        name: `snapshot-frame-${selectedSample.value}.svg`,
        subtitle: `第 ${selectedSample.value + 1} 帧空间位置快照`,
        category: 'image',
        mediaType: 'image/svg+xml',
        url: computeApi.plot(props.projectId, current.id, 'snapshot', selectedSample.value),
      },
      {
        id: 'energy.svg',
        name: 'energy.svg',
        subtitle: '能量守恒偏差曲线',
        category: 'image',
        mediaType: 'image/svg+xml',
        url: computeApi.plot(props.projectId, current.id, 'energy'),
      },
      {
        id: 'snapshots.csv',
        name: `astroagent-snapshots-${current.id.slice(0, 8)}.csv`,
        subtitle: `${result.value.samples.length} 时刻粒子坐标与守恒量表`,
        category: 'table',
        mediaType: 'text/csv',
        loadBlob: async () => {
          const resp = await sessionFetch(
            apiUrl(`/api/v1/projects/${encodeURIComponent(props.projectId)}/compute-tasks/${encodeURIComponent(current.id)}/snapshots`),
            { cache: 'no-store' },
          )
          if (!resp.ok) throw new Error('无法读取快照 CSV 数据。')
          return resp.blob()
        },
        onDownload: () => computeApi.snapshots(props.projectId, current.id),
      },
    )
  }
  items.push({
    id: 'parameters.json',
    name: 'parameters.json',
    subtitle: `SHA-256: ${current.parameter_sha256.slice(0, 12)}…`,
    category: 'json',
    mediaType: 'application/json',
    text: JSON.stringify(current.parameters, null, 2),
  })
  return items
})

const comparisonRows = computed(() => {
  if (!task.value || !result.value || !compared.value) return []
  return [
    { task: task.value, result: result.value },
    compared.value,
  ].map(item => ({ ...item, metrics: maxima(item.result) }))
})

const overlay = computed(() => {
  if (comparisonRows.value.length !== 2) return null
  const first = comparisonRows.value[0]!.result
  const second = comparisonRows.value[1]!.result
  if (
    first.zero_threshold !== second.zero_threshold ||
    first.samples.length !== second.samples.length ||
    first.samples.some((sample, idx) => sample.time !== second.samples[idx]?.time)
  ) {
    return null
  }
  const series = [first, second].map(item => item.samples.map(sample => sample.energy_relative))
  if (series.some(line => line.some(value => value === null))) return null
  const scale = Math.max(...series.flat().map(value => Math.abs(value ?? 0)))
  return {
    scale,
    lines: series.map(line =>
      line
        .map(
          (value, idx) =>
            `${44 + (idx / Math.max(1, line.length - 1)) * 516},${100 - (scale ? ((value ?? 0) / scale) * 62 : 0)}`,
        )
        .join(' '),
    ),
  }
})

function schedulePoll(token: number) {
  clearTimeout(pollTimer)
  const needsPoll =
    (task.value && isActiveState(task.value.state)) ||
    !!listing.value?.tasks.some(item => isActiveState(item.state))
  if (!needsPoll) return
  pollTimer = setTimeout(() => void refresh(token, false), 1400)
}

async function loadResult(project: string, id: string, token: number) {
  resultError.value = ''
  try {
    const data = await computeApi.result(project, id)
    if (token !== generation) return
    result.value = data
    selectedSample.value = Math.max(0, data.samples.length - 1)
  } catch (reason) {
    if (token === generation) {
      resultError.value = reason instanceof Error ? reason.message : '无法加载模拟结果。'
    }
  }
}

async function refresh(token = generation, showLoader = false) {
  if (!props.projectId || token !== generation) return
  clearTimeout(pollTimer)
  if (showLoader) loading.value = true
  try {
    const list = await computeApi.list(props.projectId)
    if (token !== generation) return
    listing.value = list
    unavailable.value = false
    error.value = ''
    const pool = visibleTasks.value
    let targetId = selectedTaskId.value || props.taskId || ''
    if (!targetId || !pool.some(item => item.id === targetId)) {
      targetId = pool[0]?.id || ''
      selectedTaskId.value = targetId
    }
    if (!targetId) {
      task.value = null
      result.value = null
      return
    }
    const detail = await computeApi.detail(props.projectId, targetId)
    if (token !== generation) return
    const changedTask = task.value?.id !== detail.id
    task.value = detail
    if (detail.state === 'succeeded' && (changedTask || !result.value)) {
      await loadResult(props.projectId, detail.id, token)
    } else if (detail.state !== 'succeeded') {
      result.value = null
    }
  } catch (reason) {
    if (token !== generation) return
    error.value = reason instanceof Error ? reason.message : '读取计算任务失败。'
    unavailable.value = reason instanceof ApiError && ['compute_disabled', 'compute_schema_missing'].includes(reason.code)
  } finally {
    if (token === generation) {
      loading.value = false
      schedulePoll(token)
    }
  }
}

function chooseTask(id: string) {
  if (selectedTaskId.value === id) return
  selectedTaskId.value = id
  deleteArmed.value = false
  compareId.value = ''
  compared.value = null
  result.value = null
  emit('select-task', id)
  void refresh(++generation, true)
}

async function runAction(fn: () => Promise<void>) {
  if (busy.value) return
  busy.value = true
  error.value = ''
  try {
    await fn()
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : '操作未确认，请稍后重试或重新进入页面核对。'
  } finally {
    busy.value = false
  }
}

async function cancelRun() {
  if (!task.value) return
  const id = task.value.id
  await runAction(async () => {
    task.value = await computeApi.cancel(props.projectId, id)
    await refresh(generation, false)
  })
}

async function confirmDraft() {
  if (!task.value) return
  const current = task.value
  await runAction(async () => {
    task.value = await computeApi.confirm(props.projectId, current.id, {
      request_id: crypto.randomUUID(),
      expected_revision: current.revision,
      parameter_sha256: current.parameter_sha256,
      confirmed: true,
    })
    await refresh(generation, false)
  })
}

async function duplicateTask() {
  if (!task.value) return
  const id = task.value.id
  await runAction(async () => {
    const copy = await computeApi.copy(props.projectId, id)
    selectedTaskId.value = copy.id
    emit('select-task', copy.id)
    await refresh(++generation, true)
  })
}

async function deleteTask() {
  if (!task.value) return
  if (!deleteArmed.value) {
    deleteArmed.value = true
    return
  }
  const id = task.value.id
  deleteArmed.value = false
  await runAction(async () => {
    await computeApi.remove(props.projectId, id)
    selectedTaskId.value = ''
    task.value = null
    result.value = null
    await refresh(++generation, true)
  })
}

async function downloadArchive() {
  if (!task.value) return
  const id = task.value.id
  await runAction(() => computeApi.download(props.projectId, id, downloadPlots.value, selectedSample.value))
}

async function downloadCsv() {
  if (!task.value) return
  const id = task.value.id
  await runAction(() => computeApi.snapshots(props.projectId, id))
}

watch(plotUrl, () => {
  plotFailed.value = false
})

watch(compareId, async id => {
  compared.value = null
  compareError.value = ''
  if (!id || !props.projectId) return
  const token = generation
  try {
    const [other, data] = await Promise.all([
      computeApi.detail(props.projectId, id),
      computeApi.result(props.projectId, id),
    ])
    if (token === generation && id === compareId.value) {
      compared.value = { task: other, result: data }
    }
  } catch (reason) {
    if (token === generation && id === compareId.value) {
      compareError.value = reason instanceof Error ? reason.message : '无法加载对照实验。'
    }
  }
})

watch(
  [() => props.projectId, () => props.taskId],
  ([project, incomingTaskId]) => {
    clearTimeout(pollTimer)
    const token = ++generation
    error.value = ''
    resultError.value = ''
    compareId.value = ''
    compared.value = null
    deleteArmed.value = false
    if (incomingTaskId) selectedTaskId.value = incomingTaskId
    if (!project) {
      listing.value = null
      task.value = null
      result.value = null
      return
    }
    void refresh(token, true)
  },
  { immediate: true },
)

onBeforeUnmount(() => {
  generation++
  clearTimeout(pollTimer)
})

const engineDisplay = (engine: ComputeParameters['engine'] = 'rebound') => (engine === 'petar' ? 'PeTar' : 'REBOUND')
</script>

<template>
  <div class="compute-panel">
    <StatusNotice v-if="error" title="N 体模拟操作未完成" :message="error" @dismiss="error = ''" />

    <div v-if="loading && !task" class="compute-empty-card">
      <p>正在加载空间 N 体模拟记录…</p>
    </div>

    <div v-else-if="!task" class="compute-empty-card">
      <strong>当前空间尚无 N 体模拟记录</strong>
      <p>在左侧对话中直接描述 N 体模拟需求（或选用「科研绘图与 N 体实验准备」技能），模型会自动生成参数方案，确认运行后在此展示图表与守恒诊断。</p>
    </div>

    <template v-else>
      <!-- Single Compact Command Header (No nested boxes, no ugly horizontal scrollbar) -->
      <header class="compute-toolbar">
        <div class="compute-toolbar-top">
          <UiSelect
            v-if="visibleTasks.length > 1"
            class="compute-task-select"
            variant="compact"
            :model-value="task.id"
            aria-label="切换本次对话 N 体模拟记录"
            :options="visibleTasks.map(item => ({ value: item.id, label: `${item.name} · ${labels[item.state]} (${formatTime(item.updated_at)})` }))"
            @update:model-value="chooseTask(String($event))"
          />
          <h3 v-else class="compute-single-title">{{ task.name }}</h3>
          <span class="ui-pill" :class="statePillClass(task.state)">{{ labels[task.state] }}</span>
        </div>

        <div class="compute-toolbar-meta">
          <span>{{ engineDisplay(task.parameters.engine) }} · {{ task.parameters.particles.length }} 粒子 · {{ task.sample_count }} 帧 · {{ task.parameters.duration }} yr</span>
          <div class="compute-toolbar-links">
            <button
              v-if="task.state === 'draft'"
              type="button"
              class="compute-inline-link is-primary"
              :disabled="busy || !listing?.worker_ready"
              @click="confirmDraft"
            >
              确认运行
            </button>
            <button type="button" class="compute-inline-link" :disabled="busy" @click="duplicateTask">复制</button>
            <button
              v-if="!isActiveState(task.state)"
              type="button"
              class="compute-inline-link"
              :class="{ 'is-danger': deleteArmed }"
              :disabled="busy"
              @click="deleteTask"
            >
              {{ deleteArmed ? '确认移除' : '移除' }}
            </button>
          </div>
        </div>
      </header>

      <NBodyProgressVisual
        v-if="isActiveState(task.state)"
        :state="task.state"
        :engine="task.parameters.engine"
        :samples-completed="task.samples_completed"
        :sample-count="task.sample_count"
        :started-at="task.started_at"
        :created-at="task.created_at"
        :particle-count="task.parameters.particles.length"
        :duration-yr="task.parameters.duration"
        can-cancel
        :cancelling="busy"
        @cancel="cancelRun"
      />

      <div v-if="task.error" class="compute-alert" role="alert">{{ task.error }}</div>
      <StatusNotice v-if="resultError" title="模拟结果读取失败" :message="resultError" @dismiss="resultError = ''" />

      <template v-if="task.state === 'succeeded' && result && metrics">
        <!-- Clean Segmented Mode Switcher -->
        <div class="compute-subtabs" role="tablist">
          <button type="button" role="tab" :aria-selected="activeSubView === 'plots'" :class="{ active: activeSubView === 'plots' }" @click="activeSubView = 'plots'">诊断图表</button>
          <button type="button" role="tab" :aria-selected="activeSubView === 'files'" :class="{ active: activeSubView === 'files' }" @click="activeSubView = 'files'">数据表与文件</button>
          <button v-if="succeededOthers.length" type="button" role="tab" :aria-selected="activeSubView === 'compare'" :class="{ active: activeSubView === 'compare' }" @click="activeSubView = 'compare'">实验对比</button>
        </div>

        <!-- Hero Plot First (Above the Fold!) -->
        <section v-if="activeSubView === 'plots'" class="compute-stage-card">
          <div class="compute-plot-bar">
            <div class="compute-plot-chips">
              <button
                v-for="opt in plotOptions"
                :key="opt.kind"
                type="button"
                class="compute-plot-chip"
                :class="{ active: selectedPlot === opt.kind }"
                @click="selectedPlot = opt.kind"
              >
                {{ opt.label }}
              </button>
            </div>
            <button type="button" class="compute-sm-btn" :disabled="plotFailed" @click="zoomDialog?.showModal()">放大</button>
          </div>

          <div v-if="selectedPlot === 'snapshot'" class="compute-scrubber">
            <label for="compute-sample-range">
              <span>快照时刻</span>
              <strong>t = {{ result.samples[selectedSample]?.time.toFixed(4) }} yr ({{ selectedSample + 1 }}/{{ result.samples.length }})</strong>
            </label>
            <input
              id="compute-sample-range"
              v-model.number="selectedSample"
              type="range"
              min="0"
              :max="Math.max(0, result.samples.length - 1)"
            />
          </div>

          <div class="compute-plot-frame">
            <img
              v-if="plotUrl && !plotFailed"
              :src="plotUrl"
              :alt="`${task.name} ${selectedPlot}`"
              @click="zoomDialog?.showModal()"
              @error="plotFailed = true"
            />
            <p v-else class="compute-plot-fallback">图表暂无法加载，可稍后重新切换查看。</p>
          </div>

          <div class="compute-export-bar">
            <div class="compute-export-checks">
              <label v-for="opt in plotOptions" :key="opt.kind">
                <input v-model="downloadPlots" type="checkbox" :value="opt.kind" />
                <span>{{ opt.label }}</span>
              </label>
            </div>
            <div class="compute-export-actions">
              <button type="button" class="compute-sm-btn" :disabled="busy" @click="downloadCsv">快照 CSV</button>
              <button type="button" class="button-primary compute-sm-btn" :disabled="busy" @click="downloadArchive">导出 ZIP</button>
            </div>
          </div>
        </section>

        <section v-else-if="activeSubView === 'files'" class="compute-stage-card">
          <ArtifactFileViewer :items="artifactItems" compact />
        </section>

        <section v-else-if="activeSubView === 'compare'" class="compute-stage-card">
          <label class="compute-compare-select">
            <span>选择同空间已完成实验进行对比</span>
            <UiSelect
              v-model="compareId"
              aria-label="选择同空间已完成实验进行对比"
              :options="[
                { value: '', label: '请选择对照实验…' },
                ...succeededOthers.map(item => ({ value: item.id, label: `${item.name} · ${formatTime(item.updated_at)}` })),
              ]"
            />
          </label>
          <p v-if="compareError" class="compute-alert">{{ compareError }}</p>
          <template v-if="comparisonRows.length === 2">
            <div class="compute-compare-table-wrap">
              <table class="compute-compare-table">
                <thead>
                  <tr>
                    <th>实验</th>
                    <th>程序 / 积分器</th>
                    <th>最大相对能量偏差</th>
                    <th>角动量偏差</th>
                    <th>耗时</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="row in comparisonRows" :key="row.task.id">
                    <td>{{ row.task.name }}</td>
                    <td>{{ programVersion(row.result) }}</td>
                    <td class="mono">{{ formatSci(row.metrics.relative) }}</td>
                    <td class="mono">{{ formatSci(row.metrics.angular) }}</td>
                    <td class="mono">{{ row.result.wall_seconds.toFixed(3) }} s</td>
                  </tr>
                </tbody>
              </table>
            </div>
            <div v-if="overlay" class="compute-overlay-box">
              <div class="compute-overlay-legend">
                <span><i class="legend-a" />{{ comparisonRows[0]?.task.name }}</span>
                <span><i class="legend-b" />{{ comparisonRows[1]?.task.name }}</span>
                <span class="mono">尺度 ±{{ formatSci(overlay.scale) }}</span>
              </div>
              <svg viewBox="0 0 580 185" class="compute-overlay-svg" aria-label="相对能量偏差对比曲线">
                <line x1="44" y1="100" x2="560" y2="100" class="overlay-axis" />
                <polyline :points="overlay.lines[0]" class="overlay-line-a" />
                <polyline :points="overlay.lines[1]" class="overlay-line-b" />
              </svg>
            </div>
            <p v-else class="compute-compare-note">两组实验的采样时刻序列或参考能量阈值不同，仅展示指标对比表。</p>
          </template>
        </section>

        <!-- Compact Conservation Telemetry Grid -->
        <div class="compute-kpi-grid">
          <div class="compute-kpi">
            <span>模拟程序与耗时</span>
            <strong>{{ programVersion(result) }} · {{ result.integrator }}</strong>
            <small>{{ result.wall_seconds.toFixed(3) }} s · {{ sourceLabels[task.source] }}</small>
          </div>
          <div class="compute-kpi">
            <span>最大相对能量偏差</span>
            <strong>{{ formatSci(metrics.relative) }}</strong>
            <small>绝对 {{ formatSci(metrics.energy) }}</small>
          </div>
          <div class="compute-kpi">
            <span>最大角动量偏差</span>
            <strong>{{ formatSci(metrics.angular) }}</strong>
            <small>M☉·AU²/yr</small>
          </div>
          <div class="compute-kpi">
            <span>积分采样与粒子</span>
            <strong>{{ result.samples.length }} 帧 · {{ task.parameters.particles.length }} 粒子</strong>
            <small>时长 {{ task.parameters.duration }} yr</small>
          </div>
        </div>
      </template>

      <details class="compute-disclosure">
        <summary>初始条件与执行时间线（{{ task.parameters.particles.length }} 粒子 · {{ task.events.length }} 条状态）</summary>
        <div class="compute-disclosure-body">
          <div v-if="task.timing" class="compute-timing-grid">
            <span>排队等待 <b>{{ formatSeconds(task.timing.queue_wait_seconds) }}</b></span>
            <span>实际执行 <b>{{ formatSeconds(task.timing.execution_seconds) }}</b></span>
            <span>总耗时 <b>{{ formatSeconds(task.timing.total_seconds) }}</b></span>
          </div>
          <div class="compute-sha">参数哈希 <code>{{ task.parameter_sha256 }}</code></div>
          <ol v-if="task.events.length" class="compute-events">
            <li v-for="(ev, idx) in task.events" :key="idx">
              <span class="mono">{{ formatTime(ev.at) }}</span>
              <strong>{{ labels[ev.state] || ev.state }}</strong>
            </li>
          </ol>
          <pre class="compute-json">{{ JSON.stringify(task.parameters, null, 2) }}</pre>
        </div>
      </details>

      <dialog ref="zoomDialog" class="compute-zoom-dialog" @click.self="zoomDialog?.close()">
        <div class="compute-zoom-head">
          <strong>{{ task.name }} · {{ plotOptions.find(p => p.kind === selectedPlot)?.label }}</strong>
          <button type="button" class="compute-sm-btn" @click="zoomDialog?.close()">关闭</button>
        </div>
        <img v-if="plotUrl" :src="plotUrl" :alt="`${task.name} 放大图`" />
      </dialog>
    </template>
  </div>
</template>

<style scoped>
.compute-panel {
  display: grid;
  gap: 10px;
}

.compute-toolbar {
  display: grid;
  gap: 6px;
  padding: 10px 12px;
  border-radius: 12px;
  border: 1px solid color-mix(in srgb, var(--border-subtle) 85%, transparent);
  background: color-mix(in srgb, var(--surface-muted) 56%, transparent);
}

.compute-timing-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 16px;
  padding: 8px 10px;
  border-radius: 8px;
  background: var(--surface-subtle);
  border: 1px solid var(--line);
  font-size: 12px;
  color: var(--muted);
}

.compute-timing-grid b {
  margin-left: 4px;
  font-family: var(--font-mono);
  color: var(--ink);
}

.compute-toolbar-top {
  display: flex;
  align-items: center;
  gap: 7px;
  min-width: 0;
}

.compute-task-select {
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

.compute-single-title {
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

.compute-toolbar-meta {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  flex-wrap: wrap;
  font-size: 11.5px;
  color: var(--text-muted);
  font-variant-numeric: tabular-nums;
}

.compute-toolbar-links {
  display: inline-flex;
  align-items: center;
  gap: 10px;
}

.compute-inline-link {
  min-height: 0;
  padding: 0;
  border: 0;
  background: transparent;
  box-shadow: none;
  color: var(--text-secondary);
  font-size: 11.5px;
  font-weight: 600;
  cursor: pointer;
}

.compute-inline-link:hover:not(:disabled) {
  color: var(--accent);
}

.compute-inline-link.is-primary {
  color: var(--accent);
}

.compute-inline-link.is-danger {
  color: var(--danger-text);
}

.compute-alert {
  padding: 9px 12px;
  border-radius: 10px;
  border: 1px solid color-mix(in srgb, var(--danger-text) 28%, transparent);
  background: color-mix(in srgb, var(--danger-bg) 70%, transparent);
  color: var(--danger-text);
  font-size: 12.5px;
  line-height: 1.5;
}

.compute-empty-card {
  padding: 28px 16px;
  border: 0;
  background: transparent;
  text-align: center;
  display: grid;
  justify-items: center;
  gap: 6px;
}

.compute-empty-card strong {
  font-size: 13.5px;
  color: var(--text-primary);
}

.compute-empty-card p {
  margin: 0;
  font-size: 12.5px;
  color: var(--text-muted);
  line-height: 1.6;
}

.compute-sm-btn {
  min-height: 27px;
  padding: 0 10px;
  border-radius: 999px;
  border: 1px solid var(--border-subtle);
  background: color-mix(in srgb, var(--surface-card) 86%, transparent);
  box-shadow: none;
  color: var(--text-secondary);
  font-size: 11.5px;
  font-weight: 600;
  cursor: pointer;
  transition: border-color 0.16s ease, color 0.16s ease, background 0.16s ease;
}

.compute-sm-btn:hover:not(:disabled) {
  border-color: var(--accent);
  color: var(--accent);
}

.compute-sm-btn.button-primary {
  background: var(--accent);
  border-color: var(--accent);
  color: #fff;
}

.compute-sm-btn.button-primary:hover:not(:disabled) {
  color: #fff;
  filter: brightness(1.06);
}

.compute-kpi-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 7px;
}

.compute-kpi {
  display: grid;
  gap: 2px;
  padding: 9px 11px;
  border-radius: 11px;
  border: 1px solid color-mix(in srgb, var(--border-subtle) 85%, transparent);
  background: color-mix(in srgb, var(--surface-muted) 50%, transparent);
}

.compute-kpi span {
  font-size: 10.5px;
  color: var(--text-muted);
}

.compute-kpi strong {
  font-size: 12px;
  font-weight: 680;
  font-variant-numeric: tabular-nums;
  color: var(--text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.compute-kpi small {
  font-size: 10.5px;
  font-variant-numeric: tabular-nums;
  color: var(--text-secondary);
}

.compute-subtabs {
  display: flex;
  gap: 3px;
  padding: 3px;
  border-radius: 10px;
  background: color-mix(in srgb, var(--surface-muted) 78%, transparent);
  border: 1px solid color-mix(in srgb, var(--border-subtle) 85%, transparent);
}

.compute-subtabs button {
  flex: 1 1 0;
  min-height: 28px;
  padding: 0 8px;
  border: 1px solid transparent;
  border-radius: 7px;
  background: transparent;
  box-shadow: none;
  color: var(--text-muted);
  font-size: 12px;
  font-weight: 560;
  cursor: pointer;
  transition: background 0.16s ease, color 0.16s ease, border-color 0.16s ease, box-shadow 0.16s ease;
}

.compute-subtabs button:hover:not(.active) {
  color: var(--text-primary);
}

.compute-subtabs button.active {
  background: var(--surface-card);
  border-color: color-mix(in srgb, var(--accent) 26%, var(--border-subtle));
  color: var(--accent);
  font-weight: 640;
  box-shadow: 0 1px 4px rgba(15, 23, 42, 0.08);
}

.compute-stage-card {
  display: grid;
  gap: 9px;
  padding: 11px;
  border-radius: 13px;
  border: 1px solid color-mix(in srgb, var(--border-subtle) 85%, transparent);
  background: color-mix(in srgb, var(--surface-card) 82%, transparent);
}

.compute-plot-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.compute-plot-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
}

.compute-plot-chip {
  min-height: 26px;
  padding: 0 10px;
  border-radius: 999px;
  border: 1px solid var(--border-subtle);
  background: transparent;
  box-shadow: none;
  color: var(--text-secondary);
  font-size: 11.5px;
  font-weight: 550;
  cursor: pointer;
}

.compute-plot-chip.active {
  border-color: color-mix(in srgb, var(--accent) 55%, var(--border-strong));
  background: color-mix(in srgb, var(--accent) 12%, transparent);
  color: var(--accent);
  font-weight: 650;
}

.compute-scrubber {
  display: grid;
  gap: 4px;
  padding: 8px 10px;
  border-radius: 10px;
  background: color-mix(in srgb, var(--surface-muted) 60%, transparent);
}

.compute-scrubber label {
  display: flex;
  justify-content: space-between;
  font-size: 11.5px;
  color: var(--text-secondary);
  font-variant-numeric: tabular-nums;
}

.compute-scrubber input[type="range"] {
  width: 100%;
  accent-color: var(--accent);
}

.compute-plot-frame {
  border-radius: 11px;
  background: #ffffff;
  border: 1px solid var(--border-subtle);
  padding: 8px;
  display: grid;
  place-items: center;
  overflow: hidden;
}

.compute-plot-frame img {
  width: 100%;
  height: auto;
  display: block;
  cursor: zoom-in;
  border-radius: 6px;
}

.compute-plot-fallback {
  margin: 20px 0;
  font-size: 12.5px;
  color: var(--text-muted);
}

.compute-export-bar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding-top: 8px;
  border-top: 1px solid color-mix(in srgb, var(--border-subtle) 75%, transparent);
}

.compute-export-checks {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  font-size: 11.5px;
  color: var(--text-secondary);
}

.compute-export-checks label {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  cursor: pointer;
}

.compute-export-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.compute-compare-select {
  display: grid;
  gap: 5px;
  font-size: 12px;
  color: var(--text-secondary);
}

.compute-compare-select select {
  min-height: 32px;
  padding: 0 10px;
  border-radius: 9px;
  border: 1px solid var(--border-strong);
  background: var(--surface-card);
  color: var(--text-primary);
  font-size: 12.5px;
}

.compute-compare-table-wrap {
  overflow-x: auto;
}

.compute-compare-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 11.5px;
}

.compute-compare-table th,
.compute-compare-table td {
  padding: 6px 8px;
  border-bottom: 1px solid var(--border-subtle);
  text-align: left;
  white-space: nowrap;
}

.compute-compare-table th {
  color: var(--text-muted);
  font-weight: 600;
}

.compute-overlay-box {
  display: grid;
  gap: 6px;
  padding: 10px;
  border-radius: 10px;
  background: color-mix(in srgb, var(--surface-muted) 65%, transparent);
}

.compute-overlay-legend {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  font-size: 11.5px;
  color: var(--text-secondary);
}

.compute-overlay-legend i {
  display: inline-block;
  width: 10px;
  height: 3px;
  border-radius: 99px;
  margin-right: 5px;
  vertical-align: middle;
}

.legend-a { background: #2563eb; }
.legend-b { background: #ec4899; }

.compute-overlay-svg {
  width: 100%;
  height: auto;
  border-radius: 8px;
  background: var(--surface-card);
  border: 1px solid var(--border-subtle);
}

.overlay-axis {
  stroke: var(--border-strong);
  stroke-dasharray: 4 4;
}

.overlay-line-a {
  fill: none;
  stroke: #2563eb;
  stroke-width: 2;
}

.overlay-line-b {
  fill: none;
  stroke: #ec4899;
  stroke-width: 2;
  stroke-dasharray: 5 3;
}

.compute-compare-note {
  margin: 0;
  font-size: 12px;
  color: var(--text-muted);
}

.compute-disclosure {
  border-radius: 12px;
  border: 1px solid color-mix(in srgb, var(--border-subtle) 85%, transparent);
  background: color-mix(in srgb, var(--surface-muted) 45%, transparent);
  padding: 8px 12px;
}

.compute-disclosure summary {
  cursor: pointer;
  font-size: 12px;
  font-weight: 600;
  color: var(--text-secondary);
}

.compute-disclosure-body {
  margin-top: 10px;
  display: grid;
  gap: 8px;
}

.compute-sha {
  font-size: 11.5px;
  color: var(--text-muted);
  word-break: break-all;
}

.compute-events {
  margin: 0;
  padding-left: 16px;
  display: grid;
  gap: 4px;
  font-size: 11.5px;
  color: var(--text-secondary);
}

.compute-events li {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.compute-json {
  margin: 0;
  padding: 10px;
  border-radius: 9px;
  background: var(--surface-card);
  border: 1px solid var(--border-subtle);
  font-size: 11px;
  max-height: 220px;
  overflow: auto;
  font-family: var(--font-mono);
}

.compute-zoom-dialog {
  width: min(92vw, 960px);
  max-height: 90vh;
  padding: 14px;
  border-radius: 16px;
  border: 1px solid var(--border-strong);
  background: var(--surface-card);
  color: var(--text-primary);
}

.compute-zoom-dialog::backdrop {
  background: rgba(8, 12, 24, 0.65);
  backdrop-filter: blur(6px);
}

.compute-zoom-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 10px;
}

.compute-zoom-dialog img {
  width: 100%;
  max-height: 76vh;
  object-fit: contain;
  background: #ffffff;
  border-radius: 10px;
}

.mono {
  font-family: var(--font-mono);
  font-variant-numeric: tabular-nums;
}
</style>
