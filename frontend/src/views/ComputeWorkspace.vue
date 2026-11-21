<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ApiError } from '../api'
import {
  computeApi, takeComputeHandoff, type ComputeConfirm, type ComputeDraft, type ComputeList,
  type ComputeParameters, type ComputeResult, type ComputeTask, type PlotKind,
} from '../api/compute'
import {
  centerOfMassReset, hierarchicalTriple, keplerianBinary, parseParticlesCsv, plummerCluster,
  systemDiagnostics,
} from '../compute-presets'
import { projectsApi } from '../api/projects'
import { useProjects } from '../stores/projects'
import PanelSwitcher from '../components/PanelSwitcher.vue'
import StatusNotice from '../components/StatusNotice.vue'
import WorkspaceHeader from '../components/WorkspaceHeader.vue'
import WorkspacePaneHeader from '../components/WorkspacePaneHeader.vue'
import WorkspaceSpaceBar from '../components/WorkspaceSpaceBar.vue'

const route = useRoute(), router = useRouter(), projectsStore = useProjects()
const resolvedProjectId = ref('')
const projectId = computed(() => (typeof route.params.projectId === 'string' && route.params.projectId) ? route.params.projectId : resolvedProjectId.value)
const taskId = computed(() => String(route.params.taskId || ''))
const projectPath = computed(() => (typeof route.params.projectId === 'string' && route.params.projectId) ? `/projects/${projectId.value}/compute` : '/compute')
const projectName = ref(''), listing = ref<ComputeList | null>(null)
const task = ref<ComputeTask | null>(null), result = ref<ComputeResult | null>(null)
const error = ref(''), resultError = ref(''), loading = ref(true), busy = ref(false)
const unavailable = ref(false), panel = ref('project')
const editing = ref(false), description = ref(''), modelId = ref<string>()
const clarification = ref(''), name = ref(''), source = ref<ComputeDraft['source']>('manual')
const parameters = ref<ComputeParameters>(blank())
const helperNotice = ref(''), csvText = ref(''), csvError = ref('')
const kepler = ref({
  m1: 1.0,
  m2: 0.5,
  semiMajorAu: 1.0,
  eccentricity: 0.3,
  inclinationDeg: 0,
  ascNodeDeg: 0,
  argPeriapsisDeg: 0,
  trueAnomalyDeg: 0,
  orbits: 2,
})
const keplerPeriodYr = computed(() => {
  const total = Math.max(1e-9, Number(kepler.value.m1) + Number(kepler.value.m2))
  const a = Math.max(1e-4, Number(kepler.value.semiMajorAu))
  return Math.sqrt((a * a * a) / total)
})
const liveDiagnostics = computed(() => systemDiagnostics(parameters.value.particles))
const dialog = ref<HTMLDialogElement | null>(null), action = ref<'run' | 'delete'>('run')
const selectedPlot = ref<PlotKind>('trajectory'), selectedSample = ref(0)
const plots = [{ kind: 'trajectory', label: '轨迹' }, { kind: 'snapshot', label: '位置快照' },
  { kind: 'energy', label: '能量偏差' }] as const
const downloadPlots = ref<PlotKind[]>(['trajectory', 'snapshot', 'energy'])
const plotFailed = ref(false)
const compareId = ref(''), compared = ref<{ task: ComputeTask; result: ComputeResult } | null>(null)
const compareError = ref('')
const labels: Record<ComputeTask['state'], string> = {
  draft: '待确认', queued: '排队中', running: '运行中', cancelling: '正在取消',
  succeeded: '完成', failed: '失败', cancelled: '已取消', interrupted: '已中断',
}
const sources = { manual: '手动录入', template: '圆轨道双体模板', conversation: '对话参数草稿' }
const programNames = { rebound: 'REBOUND', petar: 'PeTar' } as const
const engineCards = [
  { id: 'rebound' as const, badge: 'IAS15 · 自适应高精度', badgeClass: 'ui-pill-gaia', title: 'REBOUND', desc: '高精度 15 阶 Gauss-Radau 积分，适合双星、层级三星与精密轨道演进。' },
  { id: 'petar' as const, badge: '树算法 · 近接正则化', badgeClass: 'ui-pill-compute', title: 'PeTar', desc: 'Barnes-Hut 树算法 + Hermite 积分与 SDAR 正则化，适合星团多体演化。' },
]
function taskStatePill(state: ComputeTask['state']) {
  if (state === 'succeeded') return 'ui-pill-success'
  if (state === 'failed' || state === 'interrupted') return 'ui-pill-danger'
  if (state === 'running' || state === 'queued' || state === 'cancelling') return 'ui-pill-compute'
  if (state === 'draft') return 'ui-pill-warning'
  return 'ui-pill-neutral'
}
const programName = (engine: ComputeParameters['engine'] = 'rebound') => programNames[engine]
const canRun = computed(() => {
  const engine = task.value?.parameters.engine ?? 'rebound'
  return listing.value?.engines?.includes(engine) ?? (engine === 'rebound' && !!listing.value?.worker_ready)
})
const active = (state: ComputeTask['state']) => ['queued', 'running', 'cancelling'].includes(state)
const date = (value: string) => new Date(value).toLocaleString('zh-CN')
const quantity = (value: number | null | undefined) => value == null ? '不适用' : value.toExponential(4)
const json = (value: unknown) => JSON.stringify(value, null, 2)
let generation = 0, timer: ReturnType<typeof setTimeout> | undefined
let loadedProject = ''
let pending: { task: string; body: ComputeConfirm } | undefined

function particle(id: string): ComputeParameters['particles'][number] {
  return { id, mass: 1, position: [0, 0, 0], velocity: [0, 0, 0] }
}
function blank(): ComputeParameters {
  return { engine: 'rebound', duration: 1, samples: 129, particles: [particle('A'), particle('B')] }
}
function addParticle() {
  let index = parameters.value.particles.length + 1
  while (parameters.value.particles.some(row => row.id === `P${index}`)) index++
  parameters.value.particles.push(particle(`P${index}`))
}
function showEditor(value?: ComputeTask) {
  editing.value = true
  panel.value = 'steps'
  name.value = value?.name || ''
  parameters.value = value ? JSON.parse(json(value.parameters)) as ComputeParameters : blank()
  parameters.value.engine ??= 'rebound'
  source.value = value?.source || 'manual'
}
function message(reason: unknown) {
  return reason instanceof Error ? reason.message : '操作未确认，请刷新后核对。'
}
function schedule(token: number) {
  clearTimeout(timer)
  if (!listing.value?.tasks.some(item => active(item.state))) return
  timer = setTimeout(() => void refresh(token), 1800)
}
async function loadResult(project: string, id: string, token: number) {
  resultError.value = ''
  try {
    const value = await computeApi.result(project, id)
    if (token !== generation) return
    result.value = value
    selectedSample.value = value.samples.length - 1
  } catch (reason) {
    if (token === generation) resultError.value = message(reason)
  }
}
async function refresh(token = generation, initial = false) {
  if (token !== generation) return
  clearTimeout(timer)
  const project = projectId.value, id = taskId.value
  try {
    const list = await computeApi.list(project)
    if (token !== generation) return
    listing.value = list
    unavailable.value = false
    if (!id || (!initial && editing.value)) return
    const selected = await computeApi.detail(project, id)
    if (token !== generation) return
    task.value = selected
    if (selected.state === 'succeeded' && !result.value && !resultError.value) {
      await loadResult(project, id, token)
    }
  } catch (reason) {
    if (token !== generation) return
    error.value = message(reason)
    unavailable.value = reason instanceof ApiError && ['compute_disabled', 'compute_schema_missing'].includes(reason.code)
  } finally {
    if (token === generation) {
      loading.value = false
      schedule(token)
    }
  }
}
watch([() => route.params.projectId, taskId], async ([routeProject, id]) => {
  const token = ++generation
  clearTimeout(timer)
  task.value = null; result.value = null; compareId.value = ''; compared.value = null
  error.value = ''; resultError.value = ''; compareError.value = ''; clarification.value = ''; plotFailed.value = false
  editing.value = false; loading.value = true; unavailable.value = false
  let project = typeof routeProject === 'string' ? routeProject : ''
  try {
    await projectsStore.load()
    if (!project) project = (await projectsStore.ensureDefault()).id
  } catch (reason) {
    if (token === generation) { error.value = message(reason); loading.value = false }
    return
  }
  if (token !== generation) return
  resolvedProjectId.value = project
  if (project !== loadedProject) {
    listing.value = null
    projectName.value = ''
    loadedProject = project
  }
  const incoming = takeComputeHandoff(project)
  description.value = incoming?.description || ''
  modelId.value = incoming?.model
  if (!id) showEditor()
  panel.value = id || incoming ? 'steps' : 'project'
  const title = projectsApi.detail(project).then(value => {
    if (token === generation) projectName.value = projectsStore.labelFor(project) || value.name
  }).catch(() => undefined)
  await Promise.all([title, refresh(token, true)])
}, { immediate: true })
onBeforeUnmount(() => { generation++; clearTimeout(timer) })

async function act(operation: (project: string, token: number) => Promise<void>) {
  if (busy.value) return
  const token = generation
  busy.value = true
  error.value = ''
  try { await operation(projectId.value, token) }
  catch (reason) { if (token === generation) error.value = message(reason) }
  finally { busy.value = false }
}
function useTemplate() {
  helperNotice.value = ''
  void act(async (project, token) => {
    const data = await computeApi.template(project)
    if (token !== generation) return
    parameters.value = { ...data, engine: parameters.value.engine }
    name.value ||= '圆轨道双体实验'
    source.value = 'template'
  })
}
function applyKeplerBinary() {
  const generated = keplerianBinary(kepler.value)
  parameters.value = {
    ...parameters.value,
    duration: generated.durationYr,
    particles: generated.particles,
  }
  name.value ||= `椭圆双星 (a=${kepler.value.semiMajorAu} AU, e=${kepler.value.eccentricity})`
  source.value = 'manual'
  helperNotice.value = `已由开普勒轨道根数生成质心系双星初始条件：轨道周期 T ≈ ${generated.periodYr.toPrecision(4)} yr，模拟时长已设为 ${generated.durationYr} yr。`
}
function applyTriplePreset() {
  const preset = hierarchicalTriple()
  parameters.value = { ...parameters.value, duration: preset.durationYr, particles: preset.particles }
  name.value ||= '层级三星动力学实验'
  source.value = 'manual'
  helperNotice.value = '已填入层级三星预设（内双星 a=1 AU + 外伴星 a=8 AU，质心系已归零）。'
}
function applyPlummerPreset() {
  const preset = plummerCluster(12, 12, 50, 45)
  parameters.value = { ...parameters.value, duration: preset.durationYr, particles: preset.particles }
  name.value ||= 'Plummer 12 体星团实验'
  source.value = 'manual'
  helperNotice.value = '已生成 12 体维里化 Plummer 模型星团（2T/|U| ≈ 1.0，质心系已归零）。'
}
function applyComReset() {
  parameters.value = {
    ...parameters.value,
    particles: centerOfMassReset(parameters.value.particles),
  }
  helperNotice.value = '已将全部粒子坐标与速度平移至质心静止参考系（R_cm = 0, V_cm = 0）。'
}
function applyCsvImport() {
  csvError.value = ''
  try {
    const rows = parseParticlesCsv(csvText.value)
    parameters.value = { ...parameters.value, particles: rows }
    source.value = 'manual'
    helperNotice.value = `已导入 ${rows.length} 个粒子的初始条件；可检查上方质心速度并按需执行「质心系归零」。`
  } catch (reason) {
    csvError.value = reason instanceof Error ? reason.message : '解析粒子表失败。'
  }
}
async function onCsvFile(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file) return
  if (file.size > 512 * 1024) {
    csvError.value = '粒子表文件需不超过 512 KiB。'
    return
  }
  csvText.value = await file.text()
  applyCsvImport()
}
function describe() {
  clarification.value = ''
  void act(async (project, token) => {
    const proposal = await computeApi.describe(project, description.value.trim(), modelId.value)
    if (token !== generation) return
    clarification.value = proposal.clarification || ''
    if (proposal.parameters) {
      parameters.value = { ...proposal.parameters, engine: parameters.value.engine }
      source.value = 'conversation'
      name.value ||= 'N 体模拟'
    }
  })
}
function save() {
  const payload: ComputeDraft = { name: name.value.trim(), source: source.value, parameters: parameters.value }
  const edited = task.value
  void act(async (project, token) => {
    const saved = edited
      ? await computeApi.update(project, edited.id, edited.revision, payload)
      : await computeApi.create(project, payload)
    if (token !== generation) return
    editing.value = false
    task.value = saved
    panel.value = 'steps'
    if (taskId.value !== saved.id) await router.push(`${projectPath.value}/${saved.id}`)
    else await refresh(token)
  })
}
function confirm(kind: 'run' | 'delete') {
  action.value = kind
  dialog.value?.showModal()
}
function applyAction() {
  const current = task.value
  if (!current) return
  dialog.value?.close()
  void act(async (project, token) => {
    if (action.value === 'delete') {
      await computeApi.remove(project, current.id)
      if (token === generation) await router.push(projectPath.value)
      return
    }
    if (pending?.task !== current.id || pending.body.expected_revision !== current.revision) {
      pending = { task: current.id, body: {
        request_id: crypto.randomUUID(), expected_revision: current.revision,
        parameter_sha256: current.parameter_sha256, confirmed: true,
      } }
    }
    const submitted = await computeApi.confirm(project, current.id, pending.body)
    pending = undefined
    if (token !== generation) return
    task.value = submitted
    await refresh(token)
  })
}
function cancel() {
  const id = taskId.value
  void act(async (project, token) => {
    const updated = await computeApi.cancel(project, id)
    if (token !== generation) return
    task.value = updated
    await refresh(token)
  })
}
function copy() {
  const id = taskId.value
  void act(async (project, token) => {
    const draft = await computeApi.copy(project, id)
    if (token === generation) await router.push(`${projectPath.value}/${draft.id}`)
  })
}
function downloadExperiment() {
  const id = taskId.value
  void act(project => computeApi.download(project, id, downloadPlots.value, selectedSample.value))
}
function downloadSnapshots() {
  const id = taskId.value
  void act(project => computeApi.snapshots(project, id))
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
const metrics = computed(() => result.value ? maxima(result.value) : null)
const plotUrl = computed(() => task.value && result.value
  ? computeApi.plot(projectId.value, task.value.id, selectedPlot.value,
    selectedPlot.value === 'snapshot' ? selectedSample.value : undefined)
  : '')
watch(plotUrl, () => { plotFailed.value = false })
watch(compareId, async id => {
  compared.value = null; compareError.value = ''
  if (!id) return
  const token = generation, project = projectId.value
  try {
    const [other, data] = await Promise.all([computeApi.detail(project, id), computeApi.result(project, id)])
    if (token === generation && id === compareId.value) compared.value = { task: other, result: data }
  } catch (reason) {
    if (token === generation && id === compareId.value) compareError.value = message(reason)
  }
})
const comparisonRows = computed(() => {
  if (!task.value || !result.value || !compared.value) return []
  return [{ task: task.value, result: result.value }, compared.value].map(value => ({ ...value, metrics: maxima(value.result) }))
})
const overlay = computed(() => {
  if (comparisonRows.value.length !== 2) return null
  const first = comparisonRows.value[0]!.result, second = comparisonRows.value[1]!.result
  if (first.zero_threshold !== second.zero_threshold || first.samples.length !== second.samples.length
      || first.samples.some((sample, index) => sample.time !== second.samples[index]?.time)) return null
  const series = [first, second].map(value => value.samples.map(sample => sample.energy_relative))
  if (series.some(line => line.some(value => value === null))) return null
  const scale = Math.max(...series.flat().map(value => Math.abs(value ?? 0)))
  return {
    scale,
    lines: series.map(line => line.map((value, index) =>
      `${44 + index / (line.length - 1) * 516},${100 - (scale ? (value ?? 0) / scale * 62 : 0)}`).join(' ')),
  }
})
</script>

<template>
  <div class="workspace-panes project-workspace workflow-workspace compute-workspace" :data-panel="panel" data-results-open="false">
    <WorkspaceHeader title="计算任务" />
    <PanelSwitcher v-model="panel" label="计算任务视图" :options="[{ value: 'project', label: '任务列表' }, { value: 'steps', label: '实验详情' }]" />
    <aside class="project-sidebar workflow-sidebar compute-sidebar" aria-label="计算任务列表">
      <WorkspacePaneHeader :level="2" title="N 体模拟" :subtitle="projectName" />
      <div class="workspace-pane-body">
        <div class="compact-space-bar"><WorkspaceSpaceBar section="compute" :project-id="projectId" /></div>
        <StatusNotice v-if="unavailable && error" title="计算任务暂不可用" :message="error" />
        <div class="project-actions">
          <button class="button-primary" type="button" :disabled="loading || unavailable || busy" @click="taskId ? router.push(projectPath) : showEditor()">新建草稿</button>
        </div>
        <RouterLink v-for="item in listing?.tasks" :key="item.id" class="project-item" :class="{ selected: item.id === taskId }" :to="`${projectPath}/${item.id}`">
          <b>{{ item.name }}</b>
          <div class="ui-pill-list" style="margin-top: 6px;">
            <span class="ui-pill" :class="taskStatePill(item.state)">{{ labels[item.state] }}</span>
            <span class="ui-pill ui-pill-neutral">{{ date(item.updated_at).split(' ')[0] }}</span>
          </div>
        </RouterLink>
        <p v-if="listing && !listing.tasks.length" class="empty">此项目还没有计算任务。</p>
      </div>
    </aside>
    <main class="project-main workflow-main compute-main">
      <WorkspacePaneHeader :title="editing ? '初始条件' : task?.name || '计算任务'" :subtitle="editing ? '孤立牛顿点质量系统 · 2–128 个粒子' : task && labels[task.state] || ''"><template #actions><WorkspaceSpaceBar section="compute" :project-id="projectId" /></template></WorkspacePaneHeader>
      <div class="workspace-pane-body compute-body">
        <StatusNotice v-if="error" :title="unavailable ? '计算任务暂不可用' : '计算任务操作提示'" :message="error" />
        <p v-if="loading" role="status">正在读取项目计算任务…</p>
        <StatusNotice v-else-if="listing && !listing.worker_ready" title="计算 Worker 未就绪" message="可以保存参数草稿，Worker 就绪后即可确认运行。" tone="warning" />
        <form v-if="editing && listing && !unavailable" class="project-form compute-form" @submit.prevent="save">
          <div class="ui-choice-grid" aria-label="天文初始条件预设">
            <button type="button" class="ui-choice-card" :disabled="busy" @click="useTemplate">
              <div class="ui-choice-card-top"><span class="ui-pill ui-pill-gaia">2 体</span><span class="small muted">快捷填入</span></div>
              <b>圆轨道双体模板</b>
              <small>标准等质量双星圆轨道，用于快速校验能量与角动量守恒。</small>
            </button>
            <button type="button" class="ui-choice-card" :disabled="busy" @click="applyTriplePreset">
              <div class="ui-choice-card-top"><span class="ui-pill ui-pill-simbad">3 体</span><span class="small muted">质心归零</span></div>
              <b>层级三星系统</b>
              <small>内双星（a=1 AU）配外伴星（a=8 AU），演示三体长期摄动。</small>
            </button>
            <button type="button" class="ui-choice-card" :disabled="busy" @click="applyPlummerPreset">
              <div class="ui-choice-card-top"><span class="ui-pill ui-pill-compute">12 体</span><span class="small muted">维里平衡</span></div>
              <b>Plummer 模型星团</b>
              <small>2T/|U| ≈ 1.0 的 12 体自引力星团，可直接对比 REBOUND 与 PeTar。</small>
            </button>
          </div>
          <div class="project-actions compute-preset-bar">
            <button type="button" :disabled="busy" @click="applyComReset">质心系归零（R_cm=0, V_cm=0）</button>
          </div>
          <p v-if="helperNotice" class="notice info" role="status">{{ helperNotice }}</p>
          <details class="compute-helper-card">
            <summary>双体开普勒轨道根数生成器（a, e, i, Ω, ω, ν → 3D 质心系笛卡尔坐标）</summary>
            <div class="compute-helper-body">
              <div class="compute-kepler-grid">
                <label>主星质量 M₁ (M_sun)<input v-model.number="kepler.m1" type="number" min="0.000001" step="any" /></label>
                <label>伴星质量 M₂ (M_sun)<input v-model.number="kepler.m2" type="number" min="0.000001" step="any" /></label>
                <label>半长轴 a (AU)<input v-model.number="kepler.semiMajorAu" type="number" min="0.001" step="any" /></label>
                <label>偏心率 e [0, 0.98]<input v-model.number="kepler.eccentricity" type="number" min="0" max="0.98" step="0.01" /></label>
                <label>轨道倾角 i (deg)<input v-model.number="kepler.inclinationDeg" type="number" min="0" max="180" step="1" /></label>
                <label>升交点黄经 Ω (deg)<input v-model.number="kepler.ascNodeDeg" type="number" min="0" max="360" step="1" /></label>
                <label>近星点幅角 ω (deg)<input v-model.number="kepler.argPeriapsisDeg" type="number" min="0" max="360" step="1" /></label>
                <label>初始真近点角 ν (deg)<input v-model.number="kepler.trueAnomalyDeg" type="number" min="0" max="360" step="1" /></label>
                <label>积分轨道圈数<input v-model.number="kepler.orbits" type="number" min="0.1" max="500" step="any" /></label>
              </div>
              <div class="compute-helper-footer">
                <span class="small muted">计算轨道周期 T ≈ {{ keplerPeriodYr.toPrecision(4) }} yr（G = 4π² AU³ / (M_sun·yr²)）</span>
                <button type="button" :disabled="busy" @click="applyKeplerBinary">生成并填入粒子表</button>
              </div>
            </div>
          </details>
          <details class="compute-helper-card">
            <summary>批量导入粒子表（CSV / TSV：id, mass, x, y, z, vx, vy, vz）</summary>
            <div class="compute-helper-body">
              <p class="small muted">单位需为 M_sun、AU、AU/yr，支持 2–128 个粒子，首行表头与 # 注释自动跳过。</p>
              <textarea v-model="csvText" rows="4" placeholder="id,mass,x,y,z,vx,vy,vz&#10;StarA,1.0,-0.5,0,0,0,-3.1416,0&#10;StarB,1.0,0.5,0,0,0,3.1416,0" />
              <p v-if="csvError" class="notice danger" role="alert">{{ csvError }}</p>
              <div class="project-actions">
                <label class="compute-csv-upload">选择 CSV/TSV 文件<input type="file" accept=".csv,.tsv,.txt" class="sr-only" @change="onCsvFile" /></label>
                <button type="button" :disabled="busy || !csvText.trim()" @click="applyCsvImport">解析并填入粒子表</button>
              </div>
            </div>
          </details>
          <details :open="!!description">
            <summary>从自然语言提取参数</summary>
            <label>实验描述
              <textarea v-model="description" rows="4" maxlength="6000" placeholder="填写各粒子的质量、三维位置和速度，以及模拟时长和采样数。" />
            </label>
            <div class="project-actions"><button type="button" :disabled="busy || !description.trim()" @click="describe">生成参数草稿</button></div>
            <p v-if="clarification" role="status">{{ clarification }}</p>
          </details>
          <label>实验名称 <input v-model="name" required maxlength="120" /></label>
          <div style="display: grid; gap: 8px;">
            <span class="small muted" style="font-weight: 550;">选择数值模拟引擎</span>
            <div class="ui-choice-grid" role="group" aria-label="选择模拟程序">
              <button
                v-for="eng in engineCards"
                :key="eng.id"
                type="button"
                class="ui-choice-card"
                :aria-pressed="parameters.engine === eng.id"
                @click="parameters.engine = eng.id"
              >
                <div class="ui-choice-card-top">
                  <b>{{ eng.title }}</b>
                  <span class="ui-pill" :class="eng.badgeClass">{{ eng.badge }}</span>
                </div>
                <small>{{ eng.desc }}</small>
              </button>
            </div>
          </div>
          <div class="compute-fields">
            <label>模拟时长（yr） <input v-model.number="parameters.duration" type="number" min="0.000001" max="10000" step="any" required /></label>
            <label>采样点数 <input v-model.number="parameters.samples" type="number" min="2" max="512" step="1" required /></label>
          </div>
          <div class="ui-kpi-grid" aria-label="实时初始条件物理诊断">
            <div class="ui-kpi-card"><span class="ui-kpi-label">总质量 M_tot</span><span class="ui-kpi-value">{{ liveDiagnostics.totalMass.toPrecision(4) }}</span><span class="ui-kpi-sub">M_sun</span></div>
            <div class="ui-kpi-card" :class="{ 'is-warn': liveDiagnostics.comSpeed > 1e-4 }"><span class="ui-kpi-label">质心速度 |V_cm|</span><span class="ui-kpi-value">{{ liveDiagnostics.comSpeed.toExponential(2) }}</span><span class="ui-kpi-sub">{{ liveDiagnostics.comSpeed > 1e-4 ? '建议执行质心系归零' : 'AU/yr · 已居中' }}</span></div>
            <div class="ui-kpi-card"><span class="ui-kpi-label">维里比 2T/|U|</span><span class="ui-kpi-value">{{ liveDiagnostics.virialRatio == null ? '—' : liveDiagnostics.virialRatio.toFixed(3) }}</span><span class="ui-kpi-sub">1.0 为维里平衡</span></div>
            <div class="ui-kpi-card"><span class="ui-kpi-label">系统束缚态</span><span class="ui-kpi-value">{{ liveDiagnostics.totalEnergy < 0 ? '束缚态' : '非束缚' }}</span><span class="ui-kpi-sub">{{ liveDiagnostics.totalEnergy < 0 ? 'E < 0' : 'E ≥ 0' }}</span></div>
          </div>
          <p class="compute-source">粒子表来源 · {{ sources[source || 'manual'] }} · 单位 AU / yr / M_sun（G = 4π²；星团尺度可用无量纲标度换算）</p>
          <div class="compute-table">
            <table>
              <thead><tr><th scope="col">粒子 ID</th><th scope="col">质量<br />M_sun</th><th v-for="axis in ['X', 'Y', 'Z']" :key="axis" scope="col">{{ axis }}<br />AU</th><th v-for="axis in ['Vx', 'Vy', 'Vz']" :key="axis" scope="col">{{ axis }}<br />AU/yr</th><th scope="col">操作</th></tr></thead>
              <tbody>
                <tr v-for="(row, index) in parameters.particles" :key="index">
                  <td><input v-model="row.id" :aria-label="`第 ${index + 1} 行粒子 ID`" required pattern="[A-Za-z0-9][A-Za-z0-9_\-]{0,31}" maxlength="32" /></td>
                  <td><input v-model.number="row.mass" :aria-label="`第 ${index + 1} 行质量`" type="number" min="0.000000001" max="1000000" step="any" required /></td>
                  <td v-for="(axis, coordinate) in ['X', 'Y', 'Z']" :key="axis"><input v-model.number="row.position[coordinate]" :aria-label="`第 ${index + 1} 行位置 ${axis}`" type="number" min="-1000000" max="1000000" step="any" required /></td>
                  <td v-for="(axis, coordinate) in ['Vx', 'Vy', 'Vz']" :key="axis"><input v-model.number="row.velocity[coordinate]" :aria-label="`第 ${index + 1} 行速度 ${axis}`" type="number" min="-1000000" max="1000000" step="any" required /></td>
                  <td><button type="button" :disabled="parameters.particles.length <= 2" :aria-label="`移除第 ${index + 1} 行粒子`" @click="parameters.particles.splice(index, 1)">移除</button></td>
                </tr>
              </tbody>
            </table>
          </div>
          <div class="project-actions">
            <button type="button" :disabled="parameters.particles.length >= 128 || busy" @click="addParticle">添加粒子</button>
            <button v-if="task" type="button" @click="editing=false">取消编辑</button>
            <button class="button-primary" :disabled="busy" type="submit">保存草稿</button>
          </div>
        </form>
        <template v-else-if="task && !unavailable">
          <dl class="compute-facts">
            <div><dt>模拟程序</dt><dd>{{ programName(task.parameters.engine) }}</dd></div>
            <div><dt>粒子与采样</dt><dd>{{ task.parameters.particles.length }} 粒子 · {{ task.sample_count }} 个时刻</dd></div>
            <div><dt>模拟时长</dt><dd>{{ task.parameters.duration }} yr</dd></div>
            <div><dt>初始条件来源</dt><dd>{{ sources[task.source] }}</dd></div>
            <div><dt>最近更新</dt><dd>{{ date(task.updated_at) }}</dd></div>
          </dl>
          <StatusNotice v-if="task.error" :title="labels[task.state]" :message="task.error" tone="warning" />
          <StatusNotice v-if="task.state === 'draft' && listing?.worker_ready && !canRun" title="所选模拟程序暂不可用" message="草稿已保存。可以等待程序就绪，或编辑条件选择可用的程序。" tone="warning" />
          <div v-if="active(task.state)" role="status">
            <p>{{ task.state === 'queued' ? '等待 Worker 认领' : `${labels[task.state]} · 已输出 ${task.samples_completed} / ${task.sample_count} 个快照` }}</p>
            <progress v-if="task.state !== 'queued'" :value="task.samples_completed" :max="task.sample_count" aria-label="快照输出进度" />
          </div>
          <div class="project-actions">
            <button v-if="task.state === 'draft'" type="button" :disabled="busy" @click="showEditor(task)">编辑条件</button>
            <button v-if="task.state === 'draft'" class="button-primary" type="button" :disabled="busy || !canRun" @click="confirm('run')">核对并运行</button>
            <button v-if="['queued', 'running'].includes(task.state)" type="button" :disabled="busy" @click="cancel">取消运行</button>
            <button v-if="task.state !== 'draft'" type="button" :disabled="busy" @click="copy">复制为新草稿</button>
            <button v-if="!active(task.state)" type="button" :disabled="busy" @click="confirm('delete')">移除记录</button>
          </div>
          <details>
            <summary>查看初始条件与状态记录</summary>
            <p>参数 SHA-256 <code>{{ task.parameter_sha256 }}</code></p>
            <p v-if="task.origin_id">来源任务 <RouterLink :to="`${projectPath}/${task.origin_id}`">{{ task.origin_id }}</RouterLink></p>
            <pre>{{ json(task.parameters) }}</pre>
            <ul><li v-for="event in task.events" :key="event.at">{{ date(event.at) }} · {{ labels[event.state] }}</li></ul>
          </details>
          <StatusNotice v-if="resultError" title="结果读取失败" :message="resultError" action-label="重试" @action="loadResult(projectId, taskId, generation)" />
          <section v-if="result && metrics" class="compute-result">
            <h2>运行结果</h2>
            <dl class="compute-facts">
              <div><dt>最大绝对能量偏差</dt><dd>{{ quantity(metrics.energy) }} M_sun AU²/yr²</dd></div>
              <div><dt>最大相对能量偏差</dt><dd>{{ quantity(metrics.relative) }}</dd></div>
              <div><dt>最大绝对角动量偏差</dt><dd>{{ quantity(metrics.angular) }} M_sun AU²/yr</dd></div>
              <div><dt>模拟程序与耗时</dt><dd>{{ programVersion(result) }} · {{ result.integrator }} · {{ result.wall_seconds.toFixed(2) }} s</dd></div>
            </dl>
            <StatusNotice v-for="warning in result.warnings" :key="warning" :announce="false" title="数值诊断" :message="warning" tone="warning" />
            <div class="ui-segmented" role="group" aria-label="预览图表">
              <button v-for="plot in plots" :key="plot.kind" type="button" :aria-pressed="selectedPlot === plot.kind" @click="selectedPlot=plot.kind">{{ plot.label }}</button>
            </div>
            <label v-if="selectedPlot === 'snapshot'">采样时刻（{{ result.samples[selectedSample]?.time.toPrecision(5) }} yr）
              <input v-model.lazy.number="selectedSample" type="range" min="0" :max="result.samples.length - 1" step="1" />
            </label>
            <img v-if="plotUrl && !plotFailed" :key="plotUrl" :src="plotUrl" :alt="plots.find(plot => plot.kind === selectedPlot)?.label" @error="plotFailed=true" />
            <StatusNotice v-if="plotFailed" title="图表暂未显示" message="可以重试绘图，或下载原始快照和诊断数据。" action-label="重试" @action="plotFailed=false" />
            <fieldset class="compute-download">
              <legend>实验归档</legend>
              <p>ZIP 含初始参数、快照与诊断 CSV，以及 SHA-256 清单。</p>
              <div class="ui-pill-list" style="margin: 10px 0 12px;">
                <label v-for="plot in plots" :key="plot.kind" class="ui-chip-toggle"><input v-model="downloadPlots" type="checkbox" :value="plot.kind" />{{ plot.label }}</label>
              </div>
              <div class="project-actions">
                <button type="button" class="button-primary" :disabled="busy" @click="downloadExperiment">下载实验 ZIP</button>
                <button type="button" :disabled="busy" @click="downloadSnapshots">下载原始快照 CSV</button>
              </div>
            </fieldset>
            <label v-if="listing?.tasks.some(item => item.state === 'succeeded' && item.id !== taskId)">比较同项目实验
              <select v-model="compareId">
                <option value="">选择一次运行</option>
                <option v-for="item in listing.tasks.filter(value => value.state === 'succeeded' && value.id !== taskId)" :key="item.id" :value="item.id">{{ item.name }} · {{ date(item.created_at) }}</option>
              </select>
            </label>
            <StatusNotice v-if="compareError" title="实验比较失败" :message="compareError" />
            <div v-if="comparisonRows.length" class="compute-compare">
              <article v-for="entry in comparisonRows" :key="entry.task.id">
                <h3>{{ entry.task.name }} · {{ date(entry.task.created_at) }}</h3>
                <p>{{ programVersion(entry.result) }} · {{ entry.task.parameters.particles.length }} 粒子 · {{ entry.task.parameters.duration }} yr · {{ entry.task.sample_count }} 个时刻</p>
                <p>最大相对能量偏差 {{ quantity(entry.metrics.relative) }}</p>
                <img :src="computeApi.plot(projectId, entry.task.id, 'trajectory')" :alt="`${entry.task.name}的轨迹`" />
                <details><summary>初始条件</summary><pre>{{ json(entry.task.parameters) }}</pre></details>
              </article>
            </div>
            <figure v-if="overlay && result" class="compute-overlay">
              <figcaption>相对能量偏差叠图 · 实线为本次运行，虚线为对照运行</figcaption>
              <svg viewBox="0 0 600 200" role="img" aria-label="两次运行的相对能量偏差，横轴为年">
                <path d="M44 25V165H560 M44 100H560" />
                <polyline :points="overlay.lines[0]" />
                <polyline :points="overlay.lines[1]" stroke-dasharray="4 3" />
                <text x="47" y="24">ΔE / |E₀| · ±{{ quantity(overlay.scale) }}</text>
                <text x="44" y="185">0</text><text x="562" y="185" text-anchor="end">{{ task.parameters.duration }} yr</text>
              </svg>
            </figure>
            <p v-else-if="compared">采样时刻或相对偏差定义无法对齐，结果按各自运行并列查看。</p>
          </section>
        </template>
      </div>
    </main>
    <dialog ref="dialog" class="project-dialog" aria-labelledby="compute-dialog-title">
      <div class="dialog-header">
        <div class="dialog-header-copy"><h2 id="compute-dialog-title">{{ action === 'run' ? '确认运行实验' : '移除计算记录' }}</h2></div>
        <button type="button" class="dialog-close" aria-label="关闭" :disabled="busy" @click="dialog?.close()"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="m6 6 12 12M6 18 18 6" /></svg></button>
      </div>
      <template v-if="action === 'run' && task">
        <p>{{ task.parameters.particles.length }} 个粒子 · {{ task.parameters.duration }} yr · {{ task.sample_count }} 个采样点，共 {{ task.parameters.particles.length * task.sample_count }} 行快照数据。</p>
        <p v-if="task.parameters.engine === 'petar'">PeTar · 树算法、Hermite 积分与近接正则化。</p>
        <p v-else>REBOUND · IAS15（ε = 10⁻⁹），粒子间距触及 10⁻⁵ AU 时停止。</p>
        <p>单位为 AU、yr、M_sun，软化为 0。资源上限 120 秒、512 MiB 内存、1 vCPU、32 MiB 产物。</p>
        <p class="compute-digest">参数 SHA-256 <code>{{ task.parameter_sha256 }}</code></p>
        <details><summary>核对保存的初始条件 · 版本 {{ task.revision }}</summary><pre>{{ json(task.parameters) }}</pre></details>
      </template>
      <p v-else>将永久移除此项实验的参数、状态与结果。</p>
      <div class="project-actions"><button type="button" autofocus @click="dialog?.close()">取消</button><button type="button" :class="action === 'run' ? 'button-primary' : 'button-danger'" :disabled="busy || (action === 'run' && !canRun)" @click="applyAction">{{ action === 'run' ? '确认并排队' : '确认移除' }}</button></div>
    </dialog>
  </div>
</template>

<style scoped>
.compute-body, .compute-form, .compute-result { display: grid; gap: 1rem; }
.compute-workspace > :is(.compute-sidebar, .compute-main) { padding: 0; }
.compute-sidebar :deep(.workspace-pane-heading h2) { flex-shrink: 0; }
.compute-body { align-content: start; min-width: 0; }
.compute-body h2, .compute-body h3, .compute-body p { margin-block: 0; }
.compute-fields, .compute-facts, .compute-compare { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: .75rem 1.25rem; }
.compute-facts dt, .compute-source { opacity: .78; }
.compute-facts dd { margin: .25rem 0 0; font-variant-numeric: tabular-nums; }
.compute-form label, .compute-result label { display: grid; gap: .35rem; }
.compute-table { overflow-x: auto; }
.compute-table table { min-width: 46rem; }
.compute-table input { width: 100%; min-width: 4.25rem; }
.compute-table th, .compute-table td { text-align: start; padding: .35rem; }
.compute-result img { display: block; width: 100%; height: auto; }
.compute-body pre, .project-dialog pre { overflow: auto; max-height: 18rem; }
.compute-body code { overflow-wrap: anywhere; }
.compute-digest code { overflow-wrap: anywhere; }
.compute-download label { display: inline-flex; align-items: center; margin: .65rem .75rem .65rem 0; }
.compute-compare article { display: grid; gap: .5rem; min-width: 0; }
.compute-overlay { margin: 0; }
.compute-overlay svg { display: block; width: 100%; max-width: 38rem; }
.compute-overlay path { fill: none; stroke: currentColor; opacity: .25; }
.compute-overlay polyline { fill: none; stroke: currentColor; stroke-width: 1.5; }
.compute-overlay text { fill: currentColor; font-size: 12px; }
.compute-preset-bar { flex-wrap: wrap; gap: 8px; }
.compute-helper-card {
  border: 1px solid var(--line); border-radius: 10px; background: var(--surface-evidence);
  padding: 10px 14px;
}
.compute-helper-card > summary { cursor: pointer; font-weight: 550; font-size: 13px; color: var(--ink); }
.compute-helper-body { display: grid; gap: 12px; margin-top: 12px; }
.compute-kepler-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 10px 12px; }
.compute-helper-footer { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 10px; }
.compute-csv-upload {
  display: inline-flex !important; align-items: center; justify-content: center;
  min-height: 36px; padding: 0 12px; border: 1px solid var(--line-strong); border-radius: 8px;
  background: var(--paper); color: var(--ink); font-size: 12.5px; cursor: pointer;
}
.compute-csv-upload:hover { border-color: var(--accent); color: var(--accent); background: var(--soft); }
@media (max-width: 820px) {
  .compute-kepler-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
@media (max-width: 680px) {
  .compute-fields, .compute-facts, .compute-compare, .compute-kepler-grid { grid-template-columns: minmax(0, 1fr); }
}
</style>
