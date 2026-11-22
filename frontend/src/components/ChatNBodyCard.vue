<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { computeApi, type ComputeParameters, type ComputeResult, type ComputeStatus, type ComputeTask, type PlotKind } from '../api/compute'
import { centerOfMassReset, systemDiagnostics } from '../compute-presets'
import { useProjects } from '../stores/projects'
import type { NBodyProposalResult } from '../types'

const props = defineProps<{
  proposal: NBodyProposalResult
  turnId: string
  proposalIndex: number
  projectId?: string
  computeStatus?: ComputeStatus | null
}>()
const emit = defineEmits<{ refine: [prompt: string] }>()

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
const computeDetailPath = computed(() => {
  if (!task.value || !taskProjectId.value) return '/compute'
  if (taskProjectId.value === projectsStore.defaultProjectId) return `/compute/${task.value.id}`
  return `/projects/${taskProjectId.value}/compute/${task.value.id}`
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

async function pollTask(projectId: string, taskId: string) {
  clearTimeout(pollTimer)
  try {
    const latest = await computeApi.detail(projectId, taskId)
    if (!alive) return
    task.value = latest
    if (latest.state === 'succeeded') {
      await fetchResult(projectId, taskId)
      return
    }
    if (['queued', 'running', 'cancelling'].includes(latest.state)) {
      pollTimer = setTimeout(() => void pollTask(projectId, taskId), 1500)
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
    if (confirmed.state === 'succeeded') {
      await fetchResult(targetProject, confirmed.id)
    } else if (['queued', 'running', 'cancelling'].includes(confirmed.state)) {
      pollTimer = setTimeout(() => void pollTask(targetProject, confirmed.id), 1200)
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
        void pollTask(parsed.projectId, parsed.taskId)
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
          {{ editing ? '收起编辑' : '手动修改参数' }}
        </button>
        <button type="button" class="tool-card-ghost" @click="askModelToAdjust">让模型调整</button>
      </div>
    </header>

    <div class="tool-metrics-strip">
      <span><small>粒子数</small><b>{{ draftParams.particles.length }} 个</b></span>
      <span><small>总时长</small><b>{{ fmtNum(draftParams.duration) }} yr</b></span>
      <span><small>采样帧数</small><b>{{ draftParams.samples }} 帧</b></span>
      <span><small>总质量</small><b>{{ fmtNum(diagnostics.totalMass) }} M☉</b></span>
      <span><small>体系总能量</small><b>{{ fmtNum(diagnostics.totalEnergy, 3) }}</b></span>
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
        <span>粒子初始条件（单位：M_sun、AU、AU/yr）</span>
        <div class="tool-table-actions">
          <button type="button" class="tool-card-ghost" :disabled="busy || isActive" @click="applyComReset">归零质心系</button>
          <button type="button" class="tool-card-ghost" :disabled="busy || isActive || draftParams.particles.length >= 128" @click="addParticle">＋ 添加粒子</button>
          <button type="button" class="tool-card-ghost" :disabled="busy || isActive" @click="resetProposal">恢复模型建议</button>
        </div>
      </div>

      <div class="table-scroll compute-table">
        <table>
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
              <td><input v-model="p.id" maxlength="32" :disabled="busy || isActive" aria-label="粒子 ID"></td>
              <td><input v-model.number="p.mass" type="number" step="any" :disabled="busy || isActive" aria-label="质量"></td>
              <td><input v-model.number="p.position[0]" type="number" step="any" :disabled="busy || isActive" aria-label="x"></td>
              <td><input v-model.number="p.position[1]" type="number" step="any" :disabled="busy || isActive" aria-label="y"></td>
              <td><input v-model.number="p.position[2]" type="number" step="any" :disabled="busy || isActive" aria-label="z"></td>
              <td><input v-model.number="p.velocity[0]" type="number" step="any" :disabled="busy || isActive" aria-label="vx"></td>
              <td><input v-model.number="p.velocity[1]" type="number" step="any" :disabled="busy || isActive" aria-label="vy"></td>
              <td><input v-model.number="p.velocity[2]" type="number" step="any" :disabled="busy || isActive" aria-label="vz"></td>
              <td>
                <button type="button" class="tool-row-del" :disabled="busy || isActive || draftParams.particles.length <= 2" aria-label="删除粒子" @click="removeParticle(idx)">×</button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- Compact Read-Only Summary Table -->
    <div v-else class="table-scroll tool-summary-table">
      <table>
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
            <td>{{ fmtNum(p.mass) }}</td>
            <td>({{ fmtNum(p.position[0]) }}, {{ fmtNum(p.position[1]) }}, {{ fmtNum(p.position[2]) }})</td>
            <td>({{ fmtNum(p.velocity[0]) }}, {{ fmtNum(p.velocity[1]) }}, {{ fmtNum(p.velocity[2]) }})</td>
          </tr>
        </tbody>
      </table>
      <p v-if="draftParams.particles.length > 12" class="small muted tool-more-note">
        共 {{ draftParams.particles.length }} 个粒子，点击上方「手动修改参数」可查看或编辑全部粒子。
      </p>
    </div>

    <p v-if="validationError" class="notice danger" role="alert">{{ validationError }}</p>
    <p v-if="computeDisabled" class="notice warning" role="status">当前服务端暂未启用 N 体计算执行器；仍可审阅并调整参数。</p>
    <p v-else-if="!engineAvailable" class="notice warning" role="status">当前计算服务暂未就绪所选引擎「{{ draftParams.engine }}」，请切换引擎或检查 compute-worker 容器。</p>
    <p v-for="w in proposal.warnings || []" :key="w" class="notice warning">{{ w }}</p>
    <p v-if="error" class="notice danger" role="alert">{{ error }}</p>
    <p v-if="task?.error" class="notice danger" role="alert">{{ task.error }}</p>

    <!-- Live Progress -->
    <div v-if="isActive && task" class="tool-progress-box" role="status">
      <div class="tool-progress-row">
        <span>正在隔离计算容器中积分：{{ task.samples_completed }} / {{ task.sample_count }} 帧…</span>
        <button type="button" class="button-danger tool-mini-btn" :disabled="busy || task.state === 'cancelling'" @click="cancelRun">取消运行</button>
      </div>
      <div class="ui-progress">
        <div class="ui-progress-fill" :style="{ width: `${Math.min(100, Math.round((task.samples_completed / Math.max(1, task.sample_count)) * 100))}%` }" />
      </div>
    </div>

    <!-- Action Bar -->
    <footer class="tool-card-footer">
      <span class="small muted">保存空间：<b>{{ spaceLabel }}</b> · 单位 AU / yr / M☉</span>
      <div class="tool-card-actions">
        <RouterLink v-if="task" :to="computeDetailPath" class="tool-subtle-link">查看实验详情 →</RouterLink>
        <button
          type="button"
          class="button-primary"
          :disabled="busy || isActive || !!validationError || computeDisabled || !engineAvailable"
          @click="confirmAndRun"
        >
          {{ busy ? '正在提交…' : task?.state === 'succeeded' ? '按当前参数再跑一次' : '确认按此参数运行模拟' }}
        </button>
      </div>
    </footer>

    <!-- Inline Simulation Results Viewer -->
    <div v-if="task?.state === 'succeeded'" class="tool-result-section">
      <div class="tool-result-header">
        <div class="ui-segmented" role="tablist" aria-label="N 体模拟图表">
          <button v-for="tab in plotTabs" :key="tab.kind" type="button" role="tab" :aria-selected="selectedPlot === tab.kind" @click="selectedPlot = tab.kind">
            {{ tab.label }}
          </button>
        </div>
        <div class="tool-result-downloads">
          <button type="button" class="tool-card-ghost" @click="downloadCsv">下载快照 CSV</button>
          <button type="button" class="tool-card-ghost" @click="downloadZip">下载实验 ZIP</button>
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
      <p v-else-if="plotFailed" class="notice warning">图像暂未能加载，可点击上方下载实验 ZIP 或进入实验详情查看。</p>

      <div v-if="result" class="tool-conservation-strip">
        <span><small>积分器</small><b>{{ result.integrator }}</b></span>
        <span><small>计算耗时</small><b>{{ result.wall_seconds.toFixed(2) }} s</b></span>
        <span><small>最大相对能量漂移</small><b>{{ fmtSci(maxEnergyRel) }}</b></span>
        <span><small>最大相对角动量漂移</small><b>{{ fmtSci(maxAngularRel) }}</b></span>
      </div>
      <p v-if="resultError" class="notice warning">{{ resultError }}</p>
    </div>
  </section>
</template>

<style scoped>
.chat-tool-card {
  margin-top: 14px;
  padding: 16px 18px;
  gap: 12px;
  border-color: color-mix(in srgb, var(--accent) 24%, var(--line));
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
  font-weight: 600;
  color: var(--ink);
  overflow-wrap: anywhere;
}

.tool-card-head-actions {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}

.tool-card-ghost {
  min-height: 30px;
  padding: 4px 10px;
  font-size: 12px;
}

.tool-metrics-strip,
.tool-conservation-strip {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(110px, 1fr));
  gap: 8px;
}

.tool-metrics-strip > span,
.tool-conservation-strip > span {
  display: grid;
  gap: 2px;
  padding: 8px 10px;
  border: 1px solid var(--line);
  border-radius: 9px;
  background: var(--surface-subtle);
}

.tool-metrics-strip small,
.tool-conservation-strip small {
  color: var(--muted);
  font-size: 11px;
}

.tool-metrics-strip b,
.tool-conservation-strip b {
  color: var(--ink);
  font-size: 13px;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}

.tool-edit-panel {
  display: grid;
  gap: 12px;
  padding: 12px;
  border: 1px solid var(--line);
  border-radius: 10px;
  background: var(--surface-subtle);
}

.tool-edit-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
  gap: 10px;
}

.tool-edit-grid label {
  display: grid;
  gap: 4px;
  font-size: 12px;
  color: var(--muted);
}

.tool-edit-grid input,
.tool-edit-grid select {
  min-height: 34px;
  padding: 5px 9px;
  font-size: 12.5px;
}

.tool-table-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  flex-wrap: wrap;
  font-size: 12px;
  color: var(--muted);
}

.tool-table-actions {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}

.tool-row-del {
  min-height: 28px;
  width: 28px;
  padding: 0;
  border: 0;
  background: transparent;
  box-shadow: none;
  color: var(--danger);
  font-size: 16px;
}

.tool-summary-table {
  margin-top: 0;
  max-height: 240px;
}

.tool-more-note {
  padding: 8px 12px;
}

.tool-progress-box {
  display: grid;
  gap: 8px;
  padding: 10px 12px;
  border: 1px solid var(--line);
  border-radius: 9px;
  background: var(--surface-subtle);
  font-size: 12.5px;
}

.tool-progress-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  flex-wrap: wrap;
}

.tool-mini-btn {
  min-height: 28px;
  padding: 3px 10px;
  font-size: 12px;
}

.tool-card-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  padding-top: 10px;
  border-top: 1px solid var(--line);
}

.tool-card-actions {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.tool-subtle-link {
  font-size: 12.5px;
  font-weight: 550;
  color: var(--accent);
}

.tool-result-section {
  display: grid;
  gap: 12px;
  padding-top: 12px;
  border-top: 1px solid var(--line);
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
  color: var(--muted);
}

.tool-frame-slider input[type="range"] {
  width: 100%;
  accent-color: var(--accent);
}

.tool-figure {
  margin: 0;
  padding: 10px;
  border: 1px solid var(--line);
  border-radius: 10px;
  background: #fff;
}

.tool-figure img {
  display: block;
  width: 100%;
  height: auto;
  max-height: 460px;
  object-fit: contain;
}
</style>
