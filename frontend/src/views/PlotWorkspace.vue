<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import WorkspaceHeader from '../components/WorkspaceHeader.vue'
import ModelSelector from '../components/ModelSelector.vue'
import { useModels } from '../stores/models'
import { projectsApi } from '../api/projects'
import { plottingApi, savePlotFile } from '../api/plotting'
import { ApiError } from '../api'
import type { DatasetPreview, PlotOperation, PlotPage, PlotPlanRequest, PlotRunRequest, PlotStatus } from '../api/plotting'
import type { ProjectDetail, Snapshot } from '../types'

const route = useRoute(), models = useModels()
const props = withDefaults(defineProps<{ embedded?: boolean; projectIdentifier?: string; datasetIdentifier?: string; snapshotIdentifier?: string; queryNumber?: number; sourceTurn?: { conversation_id: string; turn_id: string; query_index: number } | null }>(), { embedded: false, projectIdentifier: undefined, datasetIdentifier: undefined, snapshotIdentifier: undefined, queryNumber: undefined, sourceTurn: null })
const projectId = computed(() => props.projectIdentifier || String(route.params.projectId || ''))
const requestedDataset = computed(() => props.embedded ? props.datasetIdentifier : route.query.dataset)
const requestedSnapshot = computed(() => props.embedded ? props.snapshotIdentifier : route.query.snapshot)
const requestedQuery = computed(() => props.embedded ? props.queryNumber ?? 0 : Number(route.query.query ?? 0))
const project = ref<ProjectDetail | null>(null), page = ref<PlotPage>({ datasets: [], operations: [] }), status = ref<PlotStatus | null>(null)
const datasetId = ref(''), preview = ref<DatasetPreview | null>(null), selected = ref<PlotOperation | null>(null)
const question = ref(''), engine = ref<'auto' | 'python' | 'gnuplot'>('auto'), consent = ref(false), reviewed = ref(false)
const appearance = ref({ width: 1600, font_size: 12, labels: 'none' as 'none' | 'row_number', x_label: '', y_label: '' })
const axisNames: Record<string, string> = { x: '横轴', y: '纵轴', color: '颜色', legend: '图例' }
const busy = ref(false), error = ref(''), message = ref(''), image = ref(''), resultsOpen = ref(false), sidebarOpen = ref(!props.embedded)
const fileInput = ref<HTMLInputElement | null>(null), snapshot = ref<Snapshot | null>(null), snapshotId = ref(''), queryIndex = ref(0)
const exportNames = ref<string[]>([]), zoom = ref<HTMLDialogElement | null>(null), setupDialog = ref<HTMLDialogElement | null>(null)
type Pending = { id: string; kind: 'plan'; payload: PlotPlanRequest } | { id: string; kind: 'run'; payload: PlotRunRequest }
const pending = ref<Pending | null>(null)
let navigation = 0, imageNavigation = 0, previewNavigation = 0, sourceNavigation = 0
const dataset = computed(() => page.value.datasets.find(d => d.id === datasetId.value))
const currentModel = computed(() => models.modelFor(`plot:${projectId.value}`))
const active = computed(() => page.value.operations.some(op => op.state === 'running'))
const canPrepare = computed(() => !!dataset.value && preview.value?.dataset_id === dataset.value.id && consent.value && !pending.value && !busy.value && !active.value && !!currentModel.value && !!status.value?.storage_ready && models.configured)
const canUpload = computed(() => !busy.value && !!status.value?.storage_ready)
const labels = { running: '处理中', completed: '已完成', failed: '失败', interrupted: '已中断' }
const key = (id: string) => `astroagent.plot.pending.${id}`
function keep(value: Pending | null, id = projectId.value) {
  if (id === projectId.value) pending.value = value
  try { if (value) sessionStorage.setItem(key(id), JSON.stringify(value)); else sessionStorage.removeItem(key(id)) }
  catch { message.value = '浏览器无法保存请求编号；请保留本页以核对状态。' }
}
function restore() {
  try {
    const value = JSON.parse(sessionStorage.getItem(key(projectId.value)) || 'null') as Pending | null
    pending.value = value && /^[0-9a-f-]{36}$/.test(value.id) && ['plan', 'run'].includes(value.kind) ? value : null
  } catch { pending.value = null }
}
async function action(task: () => Promise<void>) {
  if (busy.value) return
  busy.value = true; error.value = ''; message.value = ''
  try { await task() } catch (e) { error.value = e instanceof Error ? e.message : '操作状态未确认，请先刷新记录。' }
  finally { busy.value = false }
}
async function refresh() {
  const id = projectId.value, token = ++navigation
  const [details, currentStatus] = await Promise.all([projectsApi.detail(id), plottingApi.status()])
  const records = currentStatus.storage_ready ? await plottingApi.page(id) : { datasets: [], operations: [] }
  if (id !== projectId.value || token !== navigation) return
  project.value = details; status.value = currentStatus; page.value = records
  if (pending.value) {
    const found = records.operations.find(op => op.id === pending.value?.id)
    if (found && found.state !== 'running') { keep(null); await selectOperation(found) }
  }
  if (selected.value) {
    const latest = records.operations.find(op => op.id === selected.value?.id)
    if (latest && latest.state !== selected.value.state) await selectOperation(latest)
  }
}
async function selectDataset(id: string) {
  datasetId.value = id; selected.value = null; reviewed.value = false; preview.value = null; consent.value = false
  imageNavigation++
  if (image.value) URL.revokeObjectURL(image.value)
  image.value = ''
  const project = projectId.value, token = ++previewNavigation
  const value = await plottingApi.preview(project, id)
  if (project === projectId.value && token === previewNavigation && id === datasetId.value) preview.value = value
}
async function selectOperation(op: PlotOperation) {
  selected.value = op; datasetId.value = op.dataset_id; reviewed.value = false; exportNames.value = [...(op.files ?? [])]
  const project = projectId.value, token = ++imageNavigation
  if (image.value) URL.revokeObjectURL(image.value)
  image.value = ''
  if (op.kind === 'run' && op.state === 'completed') {
    const raw = await plottingApi.output(project, op.id, 'figure.png')
    if (token !== imageNavigation || project !== projectId.value) return
    image.value = URL.createObjectURL(raw); resultsOpen.value = true
  }
}
async function upload(event: Event) {
  const input = event.target as HTMLInputElement, file = input.files?.[0], project = projectId.value
  input.value = ''; if (!file) return
  await action(async () => {
    const value = await plottingApi.upload(project, crypto.randomUUID(), file)
    if (project !== projectId.value) return
    await refresh(); await selectDataset(value.id)
  })
}
async function chooseSnapshot() {
  snapshot.value = null; queryIndex.value = 0
  if (!snapshotId.value) return
  const id = projectId.value, selectedId = snapshotId.value
  await action(async () => { const value = await projectsApi.snapshot(id, selectedId); if (id === projectId.value && snapshotId.value === selectedId) snapshot.value = value })
}
async function importSnapshot() {
  const project = projectId.value, source = snapshot.value
  if (!source) return
  await action(async () => {
    const key = `astroagent.plot.snapshot.${project}.${source.id}.${queryIndex.value}`
    let identifier: string = crypto.randomUUID()
    try { const saved = sessionStorage.getItem(key); if (saved && /^[0-9a-f-]{36}$/i.test(saved)) identifier = saved; else sessionStorage.setItem(key, identifier) } catch { /* Server request still has one stable ID during this submission. */ }
    const value = await plottingApi.snapshot(project, identifier, source.id, queryIndex.value)
    if (project !== projectId.value) return
    await refresh(); await selectDataset(value.id)
  })
}
async function submitPending() {
  const request = pending.value, project = projectId.value
  if (!request) return
  await action(async () => {
    let result: PlotOperation
    try { result = request.kind === 'plan' ? await plottingApi.plan(project, request.id, request.payload) : await plottingApi.run(project, request.id, request.payload) }
    catch (e) {
      if (e instanceof ApiError && ((e.status >= 400 && e.status < 500) || e.code === 'plot_sandbox_unavailable')) keep(null, project)
      throw e
    }
    if (result.state !== 'running') keep(null, project)
    if (project !== projectId.value) return
    await refresh(); await selectOperation(result)
  })
}
async function plan() {
  if (!dataset.value || preview.value?.dataset_id !== dataset.value.id || !consent.value || !question.value.trim() || pending.value || busy.value) return
  keep({ kind: 'plan', id: crypto.randomUUID(), payload: { dataset_id: dataset.value.id, model_id: currentModel.value, engine: engine.value, question: question.value, appearance: { ...appearance.value }, confirm_external_data: true } })
  await submitPending()
}
async function submitQuestion(value: string) {
  if (!canPrepare.value || !value.trim()) return false
  question.value = value
  await plan()
  return !error.value && selected.value?.kind === 'plan' && selected.value.state === 'completed'
}
defineExpose({ submitQuestion, canPrepare, busy, canUpload, chooseFile: () => fileInput.value?.click() })
async function execute() {
  if (!selected.value?.proposal || selected.value.kind !== 'plan' || !reviewed.value || pending.value || busy.value) return
  keep({ kind: 'run', id: crypto.randomUUID(), payload: { plan_id: selected.value.id, confirm_execute: true } })
  await submitPending()
}
async function download(name: string) {
  const op = selected.value, project = projectId.value
  if (!op) return
  await action(async () => savePlotFile(await plottingApi.output(project, op.id, name), name))
}
async function bundle() {
  const op = selected.value, project = projectId.value
  if (!op || !exportNames.value.length) return
  await action(async () => savePlotFile(await plottingApi.bundle(project, op.id, [...exportNames.value]), 'astroagent-plot.zip'))
}
function scriptDownload() {
  if (!selected.value?.proposal) return
  savePlotFile(new Blob([selected.value.proposal.script], { type: 'text/plain;charset=utf-8' }), `script.${selected.value.proposal.engine === 'python' ? 'py' : 'plt'}`)
}
async function initialize() {
  setupDialog.value?.close()
  await action(async () => { status.value = await plottingApi.initialize(); await refresh() })
}
async function downloadData() {
  const source = dataset.value, project = projectId.value
  if (!source) return
  await action(async () => savePlotFile(await plottingApi.data(project, source.id), 'data.csv'))
}
watch([projectId, requestedDataset, requestedSnapshot, requestedQuery, () => props.sourceTurn], () => {
  const sourceToken = ++sourceNavigation
  navigation++; imageNavigation++; previewNavigation++; datasetId.value = ''; selected.value = null; preview.value = null; snapshot.value = null; project.value = null
  page.value = { datasets: [], operations: [] }; resultsOpen.value = false; question.value = ''; consent.value = false; reviewed.value = false
  snapshotId.value = ''; status.value = null
  if (image.value) URL.revokeObjectURL(image.value)
  image.value = ''; restore()
  const path = route.fullPath
  void (async () => {
    await refresh()
    if (sourceToken !== sourceNavigation || (!props.embedded && route.fullPath !== path)) return
    if (props.sourceTurn && props.embedded) {
      const source = { ...props.sourceTurn }, project = projectId.value
      if (!status.value?.storage_ready) { message.value = '请先准备绘图记录存储，再载入本轮数据。'; return }
      await action(async () => {
        const key = `astroagent.plot.transfer.${project}.${source.conversation_id}.${source.turn_id}.${source.query_index}`
        let identifier: string = crypto.randomUUID()
        try { const saved = sessionStorage.getItem(key); if (saved && /^[0-9a-f-]{36}$/i.test(saved)) identifier = saved; else sessionStorage.setItem(key, identifier) } catch { /* Keep the identifier for this submission. */ }
        const value = await plottingApi.turn(project, identifier, source)
        if (project !== projectId.value || sourceToken !== sourceNavigation) return
        await refresh(); await selectDataset(value.id)
        message.value = '已载入本轮完整数据；请在下方聊天框描述图形，并核对列、单位和排版设置。'
      })
    } else if (typeof requestedDataset.value === 'string') {
      if (!page.value.datasets.some(item => item.id === requestedDataset.value)) throw new Error('此项目中未找到来源数据集，请刷新后核对。')
      await selectDataset(requestedDataset.value)
      message.value = '已载入本轮完整数据副本，来源和单位已保留。请描述图形并核对下方排版设置。'
    } else if (typeof requestedSnapshot.value === 'string') {
      snapshotId.value = requestedSnapshot.value
      await chooseSnapshot()
      const index = requestedQuery.value
      if (!Number.isInteger(index) || index < 0 || index > 11) throw new Error('查询序号无效。')
      queryIndex.value = index
      if (snapshot.value && status.value?.storage_ready) await importSnapshot()
    }
  })().catch(e => { if (sourceToken === sourceNavigation && (props.embedded || route.fullPath === path)) error.value = e instanceof Error ? e.message : '读取绘图记录失败。' })
}, { immediate: true })
onBeforeUnmount(() => { navigation++; imageNavigation++; previewNavigation++; sourceNavigation++; if (image.value) URL.revokeObjectURL(image.value) })
</script>

<template>
  <div class="plot-workspace" :class="embedded ? 'plot-workspace-embedded' : 'workspace-panes primary-workspace'" :data-sidebar-open="sidebarOpen" :data-results-open="resultsOpen">
    <WorkspaceHeader v-if="!embedded" title="数据绘图" />
    <input ref="fileInput" type="file" accept=".csv,.tsv" hidden @change="upload" />
    <aside class="plot-sidebar" :inert="!sidebarOpen" :aria-hidden="!sidebarOpen">
      <div class="plot-sidebar-inner">
        <div class="plot-sidebar-title"><h2>绘图数据</h2><small>{{ page.datasets.length }}/30</small><button v-if="embedded" type="button" class="chat-toolbar-button" aria-label="收起绘图列表" @click="sidebarOpen = false">‹</button></div>
        <button type="button" class="plot-upload" :disabled="busy || !status?.storage_ready" @click="fileInput?.click()">＋ 导入 CSV / TSV</button>

        <p class="small muted">UTF-8 · 最多5 MiB / 10000行</p>
        <details class="plot-source-select">
<summary>从查询快照导入</summary>
          <label>完整查询快照<select v-model="snapshotId" :disabled="busy" @change="chooseSnapshot"><option value="">选择快照</option><option v-for="s in project?.snapshots" :key="s.id" :value="s.id">{{ s.name }}</option></select></label>
          <label v-if="snapshot">Gaia 查询<select v-model="queryIndex"><option v-for="(result, index) in snapshot.response.gaia_results" :key="index" :value="index" :disabled="result.status !== 'success' || !result.data?.length">第{{ index + 1 }}次 · {{ result.returned_count }}行 · {{ result.status }}</option></select></label>
          <button type="button" :disabled="busy || !snapshot || !status?.storage_ready" @click="importSnapshot">保存为独立数据集</button>
        </details>
        <div class="plot-datasets"><button v-for="item in page.datasets" :key="item.id" type="button" :aria-pressed="datasetId === item.id" @click="action(() => selectDataset(item.id))"><span>{{ item.name }}</span><small>{{ item.rows }}行 · {{ item.columns.length }}列</small></button></div>
        <div class="plot-sidebar-title"><h2>方案与运行</h2><small>{{ page.operations.length }}/100</small></div>
        <button v-for="op in page.operations" :key="op.id" type="button" class="plot-record" :aria-pressed="selected?.id === op.id" @click="action(() => selectOperation(op))"><span>{{ op.proposal?.title || (op.kind === 'plan' ? '生成绘图方案' : '隔离绘图') }}</span><small>{{ op.kind === 'plan' ? '方案' : '运行' }} · {{ labels[op.state] }}{{ op.imported ? ' · 导入' : '' }}</small></button>
      </div>
    </aside>
    <component :is="embedded ? 'section' : 'main'" class="plot-main">
      <header class="chat-heading">
        <button class="chat-toolbar-button history-toggle" type="button" :aria-expanded="sidebarOpen" :aria-label="sidebarOpen ? '收起绘图列表' : '展开绘图列表'" @click="sidebarOpen = !sidebarOpen"><svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="4" width="18" height="16" rx="3" /><path d="M9 4v16m7-6-2-2 2-2" /></svg></button>
        <h1>{{ project?.name || '项目' }} · 科研绘图</h1>
        <div class="plot-toolbar"><button type="button" :disabled="busy" @click="action(refresh)">刷新记录</button><button v-show="!resultsOpen" type="button" class="chat-toolbar-button" aria-label="打开绘图结果" @click="resultsOpen = true"><svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="4" width="18" height="16" rx="3" /><path d="M15 4v16m-6-6 2-2-2-2" /></svg></button></div>
      </header>
      <div class="plot-reading">
        <p v-if="error" role="alert" class="notice danger">{{ error }}</p><p v-if="message" role="status" class="notice">{{ message }}</p>
        <p v-if="busy || active" class="processing" role="status">{{ busy ? '正在处理，请稍候…' : '项目有正在处理的操作，可刷新核对。' }}</p>
        <div v-if="status && !status.storage_ready" class="plot-setup"><h2>准备绘图记录存储</h2><p>首次使用需要在当前 PostgreSQL 中新增绘图扩展表，核心数据库版本保持不变。确认后才创建。</p><button type="button" :disabled="busy" @click="setupDialog?.showModal()">准备绘图数据库</button></div>
        <p v-if="status" class="plot-environment small" :class="{ muted: !status.execution_configured }">{{ status.message }}</p>
        <div v-if="pending" class="notice"><p>保留的{{ pending.kind === 'plan' ? '方案' : '运行' }}请求：<code>{{ pending.id }}</code>。连接中断不代表取消，不会自动重放。</p><button type="button" :disabled="busy" @click="action(refresh)">先刷新记录</button> <button type="button" :disabled="busy" @click="submitPending">使用同一编号继续提交</button></div>
        <section v-if="!dataset && !selected" class="plot-empty"><span class="eyebrow">PYTHON · GNUPLOT</span><h2>从数据到可复现的图形</h2><p>导入数据，描述图形，审阅方案与脚本，再确认隔离执行。</p><p class="small muted">支持散点、折线、直方图与误差棒；先选择下方数据来源。</p><div class="plot-empty-actions"><button type="button" class="plot-primary" :disabled="busy || !status?.storage_ready" @click="fileInput?.click()">导入 CSV / TSV</button><RouterLink :to="`/projects/${projectId}`">选择项目查询快照 →</RouterLink><RouterLink to="/">查询新数据 →</RouterLink></div></section>
        <section v-if="dataset && !selected" class="plot-dataset-detail">
          <div class="plot-section-heading"><h2>{{ dataset.name }}</h2><button type="button" :disabled="busy" @click="downloadData">下载输入数据</button></div>
          <p class="small muted">{{ dataset.rows }}行 · {{ dataset.source === 'snapshot' ? dataset.provenance.origin_type === 'conversation_turn' ? '会话完整响应副本' : '完整交付快照副本' : '上传文件副本' }} · 未自动筛选</p>
          <div class="plot-table"><table><thead><tr><th>列</th><th>类型</th><th>缺失</th><th>单位</th></tr></thead><tbody><tr v-for="col in dataset.columns" :key="col.name"><td><code>{{ col.name }}</code></td><td>{{ col.kind }}</td><td>{{ col.missing }}</td><td>{{ col.unit || '未提供' }}</td></tr></tbody></table></div>
          <details v-if="preview"><summary>查看将发送给模型的数据范围</summary><p class="small">列信息、缺失数、已知单位、总行数与前{{ preview.sample_rows }}行样例，每格最多{{ preview.sample_cell_max_chars }}字符；不发送原文件。{{ preview.sample_cells_truncated ? '样例中的部分单元格已截短。' : '' }}</p><pre>{{ JSON.stringify(preview, null, 2) }}</pre></details>
          <details><summary>来源与科学限制</summary><pre>{{ JSON.stringify(dataset.provenance, null, 2) }}</pre><p v-for="warning in dataset.warnings" :key="warning" class="small">{{ warning }}</p><p class="small">输入 SHA256：<code>{{ dataset.data_sha256 }}</code></p></details>
        </section>
        <section v-if="selected" class="plot-plan-detail">
          <div class="plot-section-heading"><span class="eyebrow">{{ selected.kind === 'plan' ? '绘图方案' : '绘图运行' }} / {{ labels[selected.state] }}</span><button type="button" :disabled="busy" @click="action(() => selectDataset(selected!.dataset_id))">返回数据与新方案</button></div>
          <p v-if="selected.error" class="notice danger">{{ selected.error }}</p>
          <p v-if="selected.imported" class="notice">导入历史未经本机执行验证；不会直接执行导入脚本。</p>
          <template v-if="selected.proposal">
            <h2>{{ selected.proposal.title }}</h2><p>{{ selected.proposal.explanation }}</p>
          <dl class="plot-facts"><dt>引擎 / 图种</dt><dd>{{ selected.proposal.engine }} / {{ ({ scatter: '散点图', line: '折线图', histogram: '直方图', errorbar: '误差棒图' })[selected.proposal.chart] }}</dd><dt>数据列</dt><dd>{{ selected.proposal.columns.join(' · ') }}</dd><template v-for="(label, axis) in selected.proposal.axes" :key="axis"><dt>{{ axisNames[axis] || axis }}</dt><dd>{{ label }}</dd></template><dt>筛选与处理</dt><dd>{{ selected.proposal.filters.length ? selected.proposal.filters.join('；') : '方案未列出额外筛选' }}</dd></dl>
            <p v-for="warning in selected.proposal.warnings" :key="warning" class="notice">{{ warning }}</p>
            <details>
<summary>原始需求与模型用量</summary><pre>{{ JSON.stringify(selected.request, null, 2) }}
{{ JSON.stringify(selected.model_usage, null, 2) }}</pre><p class="small">模型返回 token 用量仅供核对；不估算价格。</p>
</details>
            <details :open="selected.kind === 'plan'" class="plot-script-review">
<summary>实际绘图脚本 · {{ selected.kind === 'plan' ? '请审阅后确认执行' : '查看已执行的原始脚本' }}</summary><div class="plot-section-heading"><h3>实际绘图脚本</h3><button type="button" @click="scriptDownload">下载 {{ selected.proposal.engine === 'python' ? '.py' : '.plt' }}</button></div>
            <pre class="plot-code"><code>{{ selected.proposal.script }}</code></pre><p class="small muted">脚本 SHA256：<code>{{ selected.script_sha256 }}</code></p>
</details>
            <template v-if="selected.kind === 'plan' && selected.state === 'completed' && !selected.imported">
              <label class="plot-check"><input v-model="reviewed" type="checkbox" :disabled="busy" />我已核对脚本、数据列、单位与筛选，确认执行此方案</label>
              <button type="button" class="plot-primary" :disabled="busy || active || !!pending || !reviewed || !status?.execution_configured" @click="execute">确认隔离执行</button>
            </template>
            <details v-if="selected.kind === 'run'"><summary>运行环境与记录</summary><pre>{{ JSON.stringify(selected.runtime, null, 2) }}</pre><p class="small">创建：{{ selected.created_at }}<br />结束：{{ selected.completed_at || '未确认' }}</p></details>
          </template>
        </section>
        <section v-if="dataset && !selected" class="plot-compose">
          <p v-if="embedded" class="small muted">在下方聊天框描述需要的图形，核对排版与发送范围后生成方案。</p>
          <template v-else><label for="plot-question">绘图需求</label><textarea id="plot-question" v-model="question" maxlength="4000" rows="4" placeholder="例如：用 bp_rp 为横轴、phot_g_mean_mag 为纵轴绘制散点图，G 星等轴反向；说明缺失值处理。" :disabled="busy" /></template>
          <div class="plot-compose-controls"><label>绘图引擎<select v-model="engine" :disabled="busy"><option value="auto">自动选择</option><option value="python">Python</option><option value="gnuplot">Gnuplot</option></select></label><ModelSelector :model-value="currentModel" :disabled="busy" @update:model-value="models.select(`plot:${projectId}`, $event)" /></div>
          <fieldset class="plot-appearance" :disabled="busy">
<legend>图形排版</legend>
            <label>图片宽度<select v-model.number="appearance.width"><option :value="1200">1200 px</option><option :value="1600">1600 px</option><option :value="2000">2000 px</option><option :value="2400">2400 px</option></select></label>
            <label>基础字号<select v-model.number="appearance.font_size"><option :value="10">10 pt</option><option :value="12">12 pt</option><option :value="14">14 pt</option><option :value="16">16 pt</option><option :value="18">18 pt</option></select></label>
            <label>点标注<select v-model="appearance.labels"><option value="none">不标注编号（推荐）</option><option value="row_number">标注原始数据行号</option></select></label>
            <label>横轴名称与单位<input v-model="appearance.x_label" maxlength="80" placeholder="自动使用列名和已知单位" /></label>
            <label>纵轴名称与单位<input v-model="appearance.y_label" maxlength="80" placeholder="自动使用列名和已知单位" /></label>
            <p class="small muted">默认不逐点显示长编号；完整编号保留在数据表中。排版设置会写入方案请求，执行前仍可核对脚本和科学条件。</p>
          </fieldset>
          <label class="plot-check"><input v-model="consent" type="checkbox" :disabled="busy || preview?.dataset_id !== dataset.id" />确认将需求、列信息和上方样例发送给所选外部模型，生成方案可能产生费用</label>
          <button v-if="!embedded" type="button" class="plot-primary" :disabled="busy || active || !!pending || preview?.dataset_id !== dataset.id || !consent || !question.trim() || !currentModel || !status?.storage_ready || !models.configured" @click="plan">生成绘图方案</button>
        </section>
      </div>
    </component>
    <aside v-if="resultsOpen" class="plot-results">
      <header class="plot-section-heading workspace-pane-header"><h2>绘图结果</h2><button type="button" class="chat-toolbar-button" aria-label="收起绘图结果" @click="resultsOpen = false">×</button></header>
      <div class="workspace-pane-body">
      <template v-if="image && selected?.kind === 'run' && selected.state === 'completed'">
        <button type="button" class="plot-image" aria-label="放大绘图" @click="zoom?.showModal()"><img :src="image" :alt="selected.proposal?.title || '绘图结果'" /></button><p class="small muted">点击图像放大；模型脚本生成结果需要人工核对。</p>
        <h3>选择保存内容</h3><div v-for="name in selected.files" :key="name" class="plot-export-row"><label class="plot-check"><input v-model="exportNames" type="checkbox" :value="name" />{{ name }}</label><button type="button" :disabled="busy" :aria-label="`下载${name}`" @click="download(name)">下载</button></div>
        <button type="button" class="plot-primary" :disabled="busy || !exportNames.length" @click="bundle">保存所选文件 ZIP</button>
      </template>
      <div v-else class="plot-empty"><h3>尚无绘图结果</h3><p>完成方案审阅和隔离执行后，图像会显示在这里。</p></div>
      </div>
    </aside>
    <dialog ref="zoom" class="plot-zoom" @click="($event.target === zoom) && zoom?.close()"><button type="button" aria-label="关闭放大图" @click="zoom?.close()">关闭</button><img v-if="image" :src="image" :alt="selected?.proposal?.title || '绘图结果'" /></dialog>
    <dialog ref="setupDialog" class="plot-setup-dialog"><h2>创建绘图扩展表</h2><p>将在已配置的 PostgreSQL 中新增 plot_meta、plot_datasets、plot_operations 和 plot_outputs 表。现有会话与核心 schema 6 保留。</p><p>此操作不下载模型、不创建容器，不执行绘图脚本。</p><div class="plot-section-heading"><button type="button" @click="setupDialog?.close()">取消</button><button type="button" @click="initialize">确认创建</button></div></dialog>
  </div>
</template>
