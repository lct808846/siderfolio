<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { computeApi, type ComputeParameters, type ComputeResult, type ComputeStatus, type ComputeTask, type PlotKind } from '../api/compute'
import { centerOfMassReset, systemDiagnostics } from '../compute-presets'
import { useProjects } from '../stores/projects'
import type { NBodyProposalResult } from '../types'
import NBodyProgressVisual from './NBodyProgressVisual.vue'

export interface ComputeResultPayload {
  kind: 'compute'
  projectId: string
  taskId: string
  title: string
}

const props = defineProps<{
  proposal: NBodyProposalResult
  turnId: string
  proposalIndex: number
  projectId?: string
  computeStatus?: ComputeStatus | null
}>()
const emit = defineEmits<{
  refine: [prompt: string]
  'open-result': [payload: ComputeResultPayload]
}>()

const projectsStore = useProjects()
const storageKey = computed(() => `astroagent.chat_nbody.${props.turnId}.${props.proposalIndex}`)

function cloneParams(source: NBodyProposalResult): ComputeParameters {
  return {
    engine: source.engine || 'rebound',
    duration: Number(source.duration),
    samples: Math.max(2, Math.min(512, Math.round(Number(source.samples || 129)))),
    particles: source.particles.map(p => ({
      id: p.id,
      mass: Number(p.mass),
      position: [Number(p.position[0]), Number(p.position[1]), Number(p.position[2])],
      velocity: [Number(p.velocity[0]), Number(p.velocity[1]), Number(p.velocity[2])],
    })),
  }
}

const editing = ref(false)
const draftName = ref(props.proposal.name)
const draftParams = ref<ComputeParameters>(cloneParams(props.proposal))
const busy = ref(false)
const error = ref('')
const task = ref<ComputeTask | null>(null)
const taskProjectId = ref('')
const result = ref<ComputeResult | null>(null)
const resultError = ref('')
const selectedPlot = ref<PlotKind>('trajectory')
const selectedSample = ref(0)
const plotFailed = ref(false)

let pollTimer: ReturnType<typeof setTimeout> | undefined
let alive = true

const plotTabs: ReadonlyArray<{ kind: PlotKind; label: string }> = [
  { kind: 'trajectory', label: '轨道轨迹' },
  { kind: 'snapshot', label: '位置快照' },
  { kind: 'energy', label: '能量偏差' },
]

const stateLabels: Record<ComputeTask['state'], string> = {
  draft: '待确认',
  queued: '排队中',
  running: '运行中',
  cancelling: '正在取消',
  succeeded: '已完成',
  failed: '运行失败',
  cancelled: '已取消',
  interrupted: '已中断',
}

const isActive = computed(() => !!task.value && ['queued', 'running', 'cancelling'].includes(task.value.state))
const diagnostics = computed(() => systemDiagnostics(draftParams.value.particles))
const spaceLabel = computed(() => {
  const id = taskProjectId.value || props.projectId || ''
  if (!id || id === projectsStore.defaultProjectId) return '个人空间（默认）'
  return projectsStore.labelFor(id)
})
const computeDisabled = computed(() => props.computeStatus !== null && props.computeStatus !== undefined && !props.computeStatus.enabled)
const engineAvailable = computed(() => {
  if (!props.computeStatus) return true
  if (!props.computeStatus.enabled) return false
  const engine = draftParams.value.engine || 'rebound'
  return props.computeStatus.engines.includes(engine)
})
const proposalNotes = computed(() => (props.proposal.warnings || []).filter(item => item && item.trim()))

const validationError = computed(() => {
  if (!draftName.value.trim()) return '请填写实验名称。'
  const d = Number(draftParams.value.duration)
  if (!Number.isFinite(d) || d < 1e-6 || d > 1e4) return '模拟时长须在 1e-6 至 1e4 yr 之间。'
  const s = Number(draftParams.value.samples)
  if (!Number.isInteger(s) || s < 2 || s > 512) return '采样帧数须为 2 至 512 的整数。'
  const list = draftParams.value.particles
  if (list.length < 2 || list.length > 128) return '粒子数须在 2 至 128 之间。'
  const seen = new Set<string>()
  for (let i = 0; i < list.length; i++) {
    const p = list[i]!
    if (!/^[A-Za-z0-9][A-Za-z0-9_-]{0,31}$/.test(p.id.trim())) {
      return `第 ${i + 1} 个粒子 ID「${p.id}」须以字母或数字开头，仅含字母/数字/_/-。`
    }
    if (seen.has(p.id.trim())) return `粒子 ID「${p.id}」重复。`
    seen.add(p.id.trim())
    if (!Number.isFinite(Number(p.mass)) || Number(p.mass) < 1e-9 || Number(p.mass) > 1e6) {
      return `粒子「${p.id}」的质量须在 1e-9 至 1e6 M_sun 之间。`
    }
    const coords = [...p.position, ...p.velocity]
    if (coords.some(v => !Number.isFinite(Number(v)) || Math.abs(Number(v)) > 1e6)) {
      return `粒子「${p.id}」存在超出范围或非有限坐标/速度。`
    }
    for (let j = 0; j < i; j++) {
      const other = list[j]!
      const dist = Math.hypot(
        Number(p.position[0]) - Number(other.position[0]),
        Number(p.position[1]) - Number(other.position[1]),
        Number(p.position[2]) - Number(other.position[2]),
      )
      if (dist <= 1e-5) return `粒子「${p.id}」与「${other.id}」初始间距过小（需 > 1e-5 AU）。`
    }
  }
  return ''
})

const maxEnergyRel = computed(() => {
  const samples = result.value?.samples || []
  let maxVal: number | null = null
  for (const s of samples) {
    if (s.energy_relative != null && Number.isFinite(s.energy_relative)) {
      maxVal = maxVal === null ? Math.abs(s.energy_relative) : Math.max(maxVal, Math.abs(s.energy_relative))
    }
  }
  return maxVal
})
const maxAngularRel = computed(() => {
  const samples = result.value?.samples || []
  let maxVal: number | null = null
  for (const s of samples) {
    if (s.angular_relative != null && Number.isFinite(s.angular_relative)) {
      maxVal = maxVal === null ? Math.abs(s.angular_relative) : Math.max(maxVal, Math.abs(s.angular_relative))
    }
  }
  return maxVal
})
const plotSrc = computed(() => {
  if (!task.value || !taskProjectId.value || task.value.state !== 'succeeded') return ''
  return computeApi.plot(
    taskProjectId.value,
    task.value.id,
    selectedPlot.value,
    selectedPlot.value === 'snapshot' ? selectedSample.value : undefined,
  )
})

function fmtNum(v: number, digits = 4) {
  if (!Number.isFinite(v)) return '—'
  if (v === 0) return '0'
  if (Math.abs(v) < 1e-3 || Math.abs(v) >= 1e4) return v.toExponential(3)
  return Number(v.toFixed(digits)).toString()
}
function fmtSci(v: number | null | undefined) {
  return v == null || !Number.isFinite(v) ? '不适用' : v.toExponential(3)
}

function resetProposal() {
  draftName.value = props.proposal.name
  draftParams.value = cloneParams(props.proposal)
  error.value = ''
}

function addParticle() {
  let idx = draftParams.value.particles.length + 1
  while (draftParams.value.particles.some(p => p.id === `P${idx}`)) idx++
  draftParams.value.particles.push({ id: `P${idx}`, mass: 0.001, position: [idx, 0, 0], velocity: [0, 1, 0] })
}

function removeParticle(index: number) {
  if (draftParams.value.particles.length <= 2) return
  draftParams.value.particles.splice(index, 1)
}

function applyComReset() {
  draftParams.value.particles = centerOfMassReset(draftParams.value.particles)
}

function normalizedParams(): ComputeParameters {
  return {
    engine: draftParams.value.engine || 'rebound',
    duration: Number(draftParams.value.duration),
    samples: Math.round(Number(draftParams.value.samples)),
    particles: draftParams.value.particles.map(p => ({
      id: p.id.trim(),
      mass: Number(p.mass),
      position: [Number(p.position[0]), Number(p.position[1]), Number(p.position[2])],
      velocity: [Number(p.velocity[0]), Number(p.velocity[1]), Number(p.velocity[2])],
    })),
  }
}

function persistTask(projectId: string, taskId: string) {
  try {
    sessionStorage.setItem(storageKey.value, JSON.stringify({ projectId, taskId }))
  } catch { /* Ignore storage quota restrictions. */ }
}

async function fetchResult(projectId: string, taskId: string) {
  resultError.value = ''
  try {
    const data = await computeApi.result(projectId, taskId)
    if (!alive) return
    result.value = data
    selectedSample.value = Math.max(0, data.samples.length - 1)
  } catch (e) {
    if (alive) resultError.value = e instanceof Error ? e.message : '读取模拟结果失败。'
  }
}

async function pollTask(projectId: string, taskId: string, notifyOnComplete = false) {
  clearTimeout(pollTimer)
  try {
    const latest = await computeApi.detail(projectId, taskId)
    if (!alive) return
    task.value = latest
    if (latest.state === 'succeeded') {
      await fetchResult(projectId, taskId)
      if (notifyOnComplete) {
        emit('open-result', { kind: 'compute', projectId, taskId, title: latest.name || draftName.value })
      }
      return
    }
    if (['queued', 'running', 'cancelling'].includes(latest.state)) {
      pollTimer = setTimeout(() => void pollTask(projectId, taskId, notifyOnComplete), 1100)
    }
  } catch (e) {
    if (alive) error.value = e instanceof Error ? e.message : '查询模拟状态失败。'
  }
}

async function confirmAndRun() {
  if (busy.value || isActive.value || validationError.value) return
  busy.value = true
  error.value = ''
  result.value = null
  resultError.value = ''
  plotFailed.value = false
  try {
    let targetProject = props.projectId || ''
    if (!targetProject) {
      const fallback = await projectsStore.ensureDefault()
      targetProject = fallback.id
    }
    const created = await computeApi.create(targetProject, {
      name: draftName.value.trim(),
      source: 'conversation',
      parameters: normalizedParams(),
    })
    const confirmed = await computeApi.confirm(targetProject, created.id, {
      request_id: crypto.randomUUID(),
      expected_revision: created.revision,
      parameter_sha256: created.parameter_sha256,
      confirmed: true,
    })
    editing.value = false
    taskProjectId.value = targetProject
    task.value = confirmed
    persistTask(targetProject, confirmed.id)
    emit('open-result', {
      kind: 'compute',
      projectId: targetProject,
      taskId: confirmed.id,
      title: confirmed.name || draftName.value,
    })
    if (confirmed.state === 'succeeded') {
      await fetchResult(targetProject, confirmed.id)
    } else if (['queued', 'running', 'cancelling'].includes(confirmed.state)) {
      pollTimer = setTimeout(() => void pollTask(targetProject, confirmed.id, true), 900)
    }
  } catch (e) {
    error.value = e instanceof Error ? e.message : '提交模拟任务失败，请稍后重试。'
  } finally {
    busy.value = false
  }
}

async function cancelRun() {
  if (!task.value || !taskProjectId.value || busy.value) return
  busy.value = true
  error.value = ''
  try {
    task.value = await computeApi.cancel(taskProjectId.value, task.value.id)
    void pollTask(taskProjectId.value, task.value.id)
  } catch (e) {
    error.value = e instanceof Error ? e.message : '取消运行失败。'
  } finally {
    busy.value = false
  }
}

async function downloadCsv() {
  if (!task.value || !taskProjectId.value) return
  try { await computeApi.snapshots(taskProjectId.value, task.value.id) }
  catch (e) { error.value = e instanceof Error ? e.message : '下载 CSV 失败。' }
}

async function downloadZip() {
  if (!task.value || !taskProjectId.value) return
  try { await computeApi.download(taskProjectId.value, task.value.id, ['trajectory', 'snapshot', 'energy'], selectedSample.value) }
  catch (e) { error.value = e instanceof Error ? e.message : '下载实验 ZIP 失败。' }
}

function askModelToAdjust() {
  emit('refine', `针对刚才「${draftName.value}」的 N 体模拟方案，请帮我调整以下参数：`)
}

watch(selectedPlot, () => { plotFailed.value = false })
watch(selectedSample, () => { if (selectedPlot.value === 'snapshot') plotFailed.value = false })

onMounted(() => {
  try {
    const saved = sessionStorage.getItem(storageKey.value)
    if (saved) {
      const parsed = JSON.parse(saved) as { projectId?: string; taskId?: string }
      if (parsed.projectId && parsed.taskId) {
        taskProjectId.value = parsed.projectId
        void pollTask(parsed.projectId, parsed.taskId, false)
      }
    }
  } catch { /* Ignore invalid session cache. */ }
})

onBeforeUnmount(() => {
  alive = false
  clearTimeout(pollTimer)
})
</script>

<template>
  <section class="ui-card chat-tool-card chat-nbody-card" aria-label="N 体模拟参数方案">
    <header class="tool-card-head">
      <div class="tool-card-title-row">
        <span class="ui-pill ui-pill-compute">N 体模拟</span>
        <h3>{{ draftName }}</h3>
        <span class="ui-pill ui-pill-neutral">{{ (draftParams.engine || 'rebound') === 'petar' ? 'PeTar · 树算法+SDAR' : 'REBOUND · IAS15' }}</span>
        <span v-if="task" class="ui-pill" :class="task.state === 'succeeded' ? 'ui-pill-success' : task.state === 'failed' || task.state === 'interrupted' ? 'ui-pill-danger' : isActive ? 'ui-pill-compute' : 'ui-pill-warning'">
          {{ stateLabels[task.state] || task.state }}
        </span>
      </div>
      <div class="tool-card-head-actions">
        <button type="button" class="tool-card-ghost" :disabled="busy || isActive" @click="editing = !editing">
          {{ editing ? '收起编辑' : '编辑参数' }}
        </button>
        <button type="button" class="tool-card-ghost" @click="askModelToAdjust">让模型调整</button>
      </div>
    </header>

    <div class="tool-kpi-bar">
      <div class="tool-kpi-cell"><small>粒子数</small><b>{{ draftParams.particles.length }} 个</b></div>
      <div class="tool-kpi-cell"><small>总时长</small><b>{{ fmtNum(draftParams.duration) }} yr</b></div>
      <div class="tool-kpi-cell"><small>采样帧数</small><b>{{ draftParams.samples }} 帧</b></div>
      <div class="tool-kpi-cell"><small>总质量</small><b>{{ fmtNum(diagnostics.totalMass) }} M☉</b></div>
      <div class="tool-kpi-cell"><small>总能量</small><b>{{ fmtNum(diagnostics.totalEnergy, 3) }}</b></div>
    </div>

    <!-- Inline Editable Parameter Form -->
    <div v-if="editing" class="tool-edit-panel">
      <div class="tool-edit-grid">
        <label>
          <span>实验名称</span>
          <input v-model="draftName" maxlength="120" :disabled="busy || isActive">
        </label>
        <label>
          <span>模拟引擎</span>
          <select v-model="draftParams.engine" :disabled="busy || isActive">
            <option value="rebound">REBOUND（IAS15 高精度少体）</option>
            <option value="petar">PeTar（Tree + Hermite + SDAR）</option>
          </select>
        </label>
        <label>
          <span>总时长 (yr)</span>
          <input v-model.number="draftParams.duration" type="number" step="any" min="0.000001" max="10000" :disabled="busy || isActive">
        </label>
        <label>
          <span>采样帧数 (2–512)</span>
          <input v-model.number="draftParams.samples" type="number" step="1" min="2" max="512" :disabled="busy || isActive">
        </label>
      </div>

      <div class="tool-table-head">
        <span>粒子初始条件 <em class="unit-tag">M☉ · AU · AU/yr</em></span>
        <div class="tool-table-actions">
          <button type="button" class="tool-card-ghost" :disabled="busy || isActive" @click="applyComReset">归零质心系</button>
          <button type="button" class="tool-card-ghost" :disabled="busy || isActive || draftParams.particles.length >= 128" @click="addParticle">＋ 添加粒子</button>
          <button type="button" class="tool-card-ghost" :disabled="busy || isActive" @click="resetProposal">恢复建议</button>
        </div>
      </div>

      <div class="sheet-scroll">
        <table class="particle-sheet">
          <thead>
            <tr>
              <th>ID</th>
              <th>质量 (M☉)</th>
              <th>x (AU)</th>
              <th>y (AU)</th>
              <th>z (AU)</th>
              <th>vx (AU/yr)</th>
              <th>vy (AU/yr)</th>
              <th>vz (AU/yr)</th>
              <th aria-label="操作" />
            </tr>
          </thead>
          <tbody>
            <tr v-for="(p, idx) in draftParams.particles" :key="idx">
              <td class="cell-id"><input v-model="p.id" maxlength="32" :disabled="busy || isActive" aria-label="粒子 ID"></td>
              <td><input v-model.number="p.mass" type="number" step="any" :disabled="busy || isActive" aria-label="质量"></td>
              <td><input v-model.number="p.position[0]" type="number" step="any" :disabled="busy || isActive" aria-label="x"></td>
              <td><input v-model.number="p.position[1]" type="number" step="any" :disabled="busy || isActive" aria-label="y"></td>
              <td><input v-model.number="p.position[2]" type="number" step="any" :disabled="busy || isActive" aria-label="z"></td>
              <td><input v-model.number="p.velocity[0]" type="number" step="any" :disabled="busy || isActive" aria-label="vx"></td>
              <td><input v-model.number="p.velocity[1]" type="number" step="any" :disabled="busy || isActive" aria-label="vy"></td>
              <td><input v-model.number="p.velocity[2]" type="number" step="any" :disabled="busy || isActive" aria-label="vz"></td>
              <td class="cell-del">
                <button type="button" class="tool-row-del" :disabled="busy || isActive || draftParams.particles.length <= 2" aria-label="删除粒子" @click="removeParticle(idx)">×</button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- Compact Read-Only Summary Table -->
    <div v-else class="sheet-scroll tool-summary-sheet">
      <table class="particle-sheet readonly">
        <thead>
          <tr>
            <th>粒子 ID</th>
            <th>质量 (M☉)</th>
            <th>位置 (x, y, z) AU</th>
            <th>速度 (vx, vy, vz) AU/yr</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="p in draftParams.particles.slice(0, 12)" :key="p.id">
            <td><strong>{{ p.id }}</strong></td>
            <td class="mono">{{ fmtNum(p.mass) }}</td>
            <td class="mono">({{ fmtNum(p.position[0]) }}, {{ fmtNum(p.position[1]) }}, {{ fmtNum(p.position[2]) }})</td>
            <td class="mono">({{ fmtNum(p.velocity[0]) }}, {{ fmtNum(p.velocity[1]) }}, {{ fmtNum(p.velocity[2]) }})</td>
          </tr>
        </tbody>
      </table>
      <p v-if="draftParams.particles.length > 12" class="tool-more-note">
        共 {{ draftParams.particles.length }} 个粒子，点击上方「编辑参数」可查看或修改全部粒子。
      </p>
    </div>

    <!-- Compact Collapsible Assumptions & Notes (Replaces stacked yellow warning boxes) -->
    <details v-if="proposalNotes.length" class="tool-notes-disclosure">
      <summary>
        <span class="notes-badge">物理假设与说明 · {{ proposalNotes.length }} 条</span>
        <span class="notes-preview">{{ proposalNotes[0] }}</span>
      </summary>
      <ul class="tool-notes-list">
        <li v-for="note in proposalNotes" :key="note">{{ note }}</li>
      </ul>
    </details>

    <p v-if="validationError" class="tool-inline-alert is-danger" role="alert">{{ validationError }}</p>
    <p v-if="computeDisabled" class="tool-inline-alert is-info" role="status">当前服务端暂未启用 N 体计算执行器；仍可审阅并调整参数。</p>
    <p v-else-if="!engineAvailable" class="tool-inline-alert is-info" role="status">当前计算服务暂未就绪所选引擎「{{ draftParams.engine }}」，请切换引擎或检查 compute-worker 容器。</p>
    <p v-if="error" class="tool-inline-alert is-danger" role="alert">{{ error }}</p>
    <p v-if="task?.error" class="tool-inline-alert is-danger" role="alert">{{ task.error }}</p>

    <!-- Visual N-Body Progress -->
    <NBodyProgressVisual
      v-if="isActive && task"
      :state="task.state"
      :engine="task.parameters.engine"
      :samples-completed="task.samples_completed"
      :sample-count="task.sample_count"
      :started-at="task.started_at"
      :created-at="task.created_at"
      :particle-count="task.parameters.particles.length"
      :duration-yr="task.parameters.duration"
      compact
      can-cancel
      :cancelling="busy"
      @cancel="cancelRun"
    />

    <!-- Action Bar -->
    <footer class="tool-card-footer">
      <span class="tool-space-meta">空间 <b>{{ spaceLabel }}</b> · AU / yr / M☉</span>
      <div class="tool-card-actions">
        <button
          type="button"
          class="button-primary"
          :disabled="busy || isActive || !!validationError || computeDisabled || !engineAvailable"
          @click="confirmAndRun"
        >
          {{ busy ? '正在提交…' : task?.state === 'succeeded' ? '按当前参数再跑一次' : '确认运行模拟' }}
        </button>
      </div>
    </footer>

    <!-- Compact Inline Result Preview -->
    <div v-if="task?.state === 'succeeded'" class="tool-result-section">
      <div class="tool-result-header">
        <div class="ui-segmented" role="tablist" aria-label="N 体模拟图表">
          <button v-for="tab in plotTabs" :key="tab.kind" type="button" role="tab" :aria-selected="selectedPlot === tab.kind" @click="selectedPlot = tab.kind">
            {{ tab.label }}
          </button>
        </div>
        <div class="tool-result-downloads">
          <button type="button" class="tool-card-ghost" @click="downloadCsv">快照 CSV</button>
          <button type="button" class="tool-card-ghost" @click="downloadZip">实验 ZIP</button>
        </div>
      </div>

      <div v-if="selectedPlot === 'snapshot' && result && result.samples.length > 1" class="tool-frame-slider">
        <label>
          <span>采样帧：第 {{ selectedSample + 1 }} / {{ result.samples.length }} 帧（t = {{ fmtNum(result.samples[selectedSample]?.time ?? 0) }} yr）</span>
          <input v-model.number="selectedSample" type="range" :min="0" :max="result.samples.length - 1" step="1">
        </label>
      </div>

      <figure v-if="plotSrc && !plotFailed" class="tool-figure">
        <img :src="plotSrc" :alt="`${draftName} - ${selectedPlot}`" @error="plotFailed = true">
      </figure>
      <p v-else-if="plotFailed" class="tool-inline-alert is-info">图像暂未能加载，可打开右上角结果栏或下载实验 ZIP 查看。</p>

      <div v-if="result" class="tool-kpi-bar is-conservation">
        <div class="tool-kpi-cell"><small>积分器</small><b>{{ result.integrator }}</b></div>
        <div class="tool-kpi-cell"><small>计算耗时</small><b>{{ result.wall_seconds.toFixed(2) }} s</b></div>
        <div class="tool-kpi-cell"><small>最大能量漂移</small><b>{{ fmtSci(maxEnergyRel) }}</b></div>
        <div class="tool-kpi-cell"><small>最大角动量漂移</small><b>{{ fmtSci(maxAngularRel) }}</b></div>
      </div>
      <p v-if="resultError" class="tool-inline-alert is-info">{{ resultError }}</p>
    </div>
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

.tool-kpi-bar {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  border-radius: 12px;
  border: 1px solid color-mix(in srgb, var(--border-subtle) 85%, transparent);
  background: color-mix(in srgb, var(--surface-muted) 56%, transparent);
  overflow: hidden;
}

.tool-kpi-bar.is-conservation {
  grid-template-columns: repeat(4, minmax(0, 1fr));
}

.tool-kpi-cell {
  display: grid;
  gap: 2px;
  padding: 8px 10px;
  position: relative;
  min-width: 0;
}

.tool-kpi-cell b {
  color: var(--text-primary);
  font-size: 12.5px;
  font-weight: 660;
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

@media (max-width: 640px) {
  .tool-kpi-bar,
  .tool-kpi-bar.is-conservation {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
  .tool-kpi-cell + .tool-kpi-cell::before {
    display: none;
  }
}

.tool-kpi-cell + .tool-kpi-cell::before {
  content: '';
  position: absolute;
  left: 0;
  top: 20%;
  bottom: 20%;
  width: 1px;
  background: color-mix(in srgb, var(--border-subtle) 85%, transparent);
}

.tool-kpi-cell small {
  color: var(--text-muted);
  font-size: 11px;
}

.tool-kpi-cell b {
  color: var(--text-primary);
  font-size: 13px;
  font-weight: 660;
  font-variant-numeric: tabular-nums;
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

.tool-table-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  flex-wrap: wrap;
  font-size: 12px;
  color: var(--text-secondary);
}

.unit-tag {
  font-style: normal;
  font-family: var(--font-mono);
  font-size: 11px;
  padding: 1px 6px;
  margin-left: 4px;
  border-radius: 6px;
  background: color-mix(in srgb, var(--surface-card) 85%, transparent);
  color: var(--text-muted);
}

.tool-table-actions {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}

.sheet-scroll {
  overflow-x: auto;
  border-radius: 11px;
  border: 1px solid color-mix(in srgb, var(--border-subtle) 85%, transparent);
  background: color-mix(in srgb, var(--surface-card) 74%, transparent);
}

.tool-summary-sheet {
  max-height: 240px;
  overflow-y: auto;
}

.particle-sheet {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
}

.particle-sheet th {
  position: sticky;
  top: 0;
  padding: 7px 8px;
  text-align: left;
  font-size: 11px;
  font-weight: 620;
  color: var(--text-muted);
  background: color-mix(in srgb, var(--surface-muted) 92%, var(--surface-card));
  border-bottom: 1px solid color-mix(in srgb, var(--border-subtle) 90%, transparent);
  white-space: nowrap;
}

.particle-sheet td {
  padding: 4px 5px;
  border-bottom: 1px solid color-mix(in srgb, var(--border-subtle) 55%, transparent);
  vertical-align: middle;
}

.particle-sheet.readonly td {
  padding: 7px 10px;
}

.particle-sheet tbody tr:last-child td {
  border-bottom: none;
}

.particle-sheet tbody tr:hover {
  background: color-mix(in srgb, var(--accent) 5%, transparent);
}

.particle-sheet input {
  width: 100%;
  min-width: 68px;
  min-height: 28px;
  padding: 3px 7px;
  border-radius: 7px;
  border: 1px solid transparent;
  background: transparent;
  color: var(--text-primary);
  font-family: var(--font-mono);
  font-size: 12px;
  font-variant-numeric: tabular-nums;
  box-shadow: none;
  transition: border-color 0.15s ease, background 0.15s ease;
}

.particle-sheet .cell-id input {
  min-width: 56px;
  font-family: inherit;
  font-weight: 650;
}

.particle-sheet input:hover:not(:disabled) {
  border-color: color-mix(in srgb, var(--border-strong) 75%, transparent);
  background: color-mix(in srgb, var(--surface-card) 80%, transparent);
}

.particle-sheet input:focus {
  outline: none;
  border-color: var(--accent);
  background: var(--surface-card);
  box-shadow: 0 0 0 2px color-mix(in srgb, var(--accent) 18%, transparent);
}

.cell-del {
  width: 32px;
  text-align: center;
}

.tool-row-del {
  min-height: 26px;
  width: 26px;
  padding: 0;
  border: 0;
  border-radius: 7px;
  background: transparent;
  box-shadow: none;
  color: var(--text-muted);
  font-size: 15px;
  cursor: pointer;
}

.tool-row-del:hover:not(:disabled) {
  background: color-mix(in srgb, var(--danger-bg) 70%, transparent);
  color: var(--danger-text);
}

.tool-more-note {
  margin: 0;
  padding: 8px 12px;
  font-size: 11.5px;
  color: var(--text-muted);
  border-top: 1px solid color-mix(in srgb, var(--border-subtle) 65%, transparent);
}

.tool-notes-disclosure {
  border-radius: 11px;
  border: 1px solid color-mix(in srgb, var(--border-subtle) 82%, transparent);
  background: color-mix(in srgb, var(--surface-muted) 48%, transparent);
  padding: 0;
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

.tool-notes-list li::marker {
  color: color-mix(in srgb, var(--accent) 65%, var(--text-muted));
}

.tool-inline-alert {
  margin: 0;
  padding: 8px 12px;
  border-radius: 10px;
  font-size: 12px;
  line-height: 1.5;
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

.tool-result-section {
  display: grid;
  gap: 12px;
  padding-top: 12px;
  border-top: 1px solid color-mix(in srgb, var(--border-subtle) 80%, transparent);
}

.tool-result-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  flex-wrap: wrap;
}

.tool-result-downloads {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}

.tool-frame-slider label {
  display: grid;
  gap: 6px;
  font-size: 12px;
  color: var(--text-muted);
  font-variant-numeric: tabular-nums;
}

.tool-frame-slider input[type="range"] {
  width: 100%;
  accent-color: var(--accent);
}

.tool-figure {
  margin: 0;
  padding: 10px;
  border: 1px solid color-mix(in srgb, var(--border-subtle) 85%, transparent);
  border-radius: 12px;
  background: #ffffff;
}

.tool-figure img {
  display: block;
  width: 100%;
  height: auto;
  max-height: 440px;
  object-fit: contain;
}

.mono {
  font-family: var(--font-mono);
  font-variant-numeric: tabular-nums;
}
</style>
