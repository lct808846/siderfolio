<script setup lang="ts">
import WorkspaceHeader from '../components/WorkspaceHeader.vue'
import WorkspacePaneHeader from '../components/WorkspacePaneHeader.vue'
import WorkspaceSpaceBar from '../components/WorkspaceSpaceBar.vue'
import PanelSwitcher from '../components/PanelSwitcher.vue'
import { computed, nextTick, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ApiError, apiUrl } from '../api'
import { projectsApi } from '../api/projects'
import { useProjects } from '../stores/projects'
import { downloadWorkflowOutput, outputPath, workflowsApi } from '../api/workflows'
import ResultPanel from '../components/ResultPanel.vue'
import type { AdsEvidenceParameters, ChatResponse, GaiaFieldParameters, ProjectDetail, Turn, WorkflowCreate, WorkflowDetail, WorkflowExecute, WorkflowOutput, WorkflowSummary, WorkflowTemplate } from '../types'

const route = useRoute(), router = useRouter(), projectsStore = useProjects()
const resolvedProjectId = ref('')
const activeProjectId = computed(() => (typeof route.params.projectId === 'string' && route.params.projectId) ? route.params.projectId : resolvedProjectId.value)
const workflowBase = computed(() => (typeof route.params.projectId === 'string' && route.params.projectId) ? `/projects/${activeProjectId.value}/workflows` : '/workflows')
const project = ref<ProjectDetail | null>(null), catalog = ref<WorkflowTemplate[]>([]), runs = ref<WorkflowSummary[]>([])
const run = ref<WorkflowDetail | null>(null), busy = ref(false), error = ref(''), message = ref(''), mobilePanel = ref('project')
const editing = ref(!route.params.runId)
const templateId = ref<'gaia_field' | 'ads_evidence'>('gaia_field'), name = ref('')
const mode = ref<'name' | 'coordinates'>('coordinates'), objectName = ref(''), ra = ref(''), dec = ref('')
const radius = ref(''), limit = ref(''), ruwe = ref(''), snr = ref(''), distance = ref(false)
const parallaxMin = ref(''), parallaxMax = ref(''), pmraMin = ref(''), pmraMax = ref(''), pmdecMin = ref(''), pmdecMax = ref(''), gMagMax = ref('')
const plots = ref<NonNullable<GaiaFieldParameters['plots']>>([])
const query = ref(''), rows = ref('10'), start = ref('0'), sort = ref<AdsEvidenceParameters['sort']>('date_desc')
const dialog = ref<HTMLDialogElement | null>(null), action = ref<'execute' | 'delete' | ''>('')
const pending = ref<WorkflowExecute | null>(null)
let navigation = 0
const template = computed(() => catalog.value.find(t => t.id === templateId.value))
const labels: Record<string, string> = { pending: '待执行', running: '运行中', succeeded: '完成', failed: '失败', skipped: '跳过', interrupted: '已中断' }
const plotNames = { proper_motion: '自行散点图', parallax_histogram: '视差直方图', observed_cmd: '观测颜色—星等图' }
const print = (value: unknown) => JSON.stringify(value, null, 2)
const state = (value: string) => labels[value] || value
function statePill(value: string) {
  if (value === 'succeeded') return 'ui-pill-success'
  if (value === 'failed' || value === 'interrupted') return 'ui-pill-danger'
  if (value === 'running') return 'ui-pill-accent'
  if (value === 'pending') return 'ui-pill-warning'
  return 'ui-pill-neutral'
}
function fileExt(name: string) {
  const ext = name.split('.').pop()?.toUpperCase() || 'FILE'
  return ext.slice(0, 5)
}
function formatBytes(value: number) {
  if (value < 1024) return `${value} B`
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KiB`
  return `${(value / (1024 * 1024)).toFixed(2)} MiB`
}
const parameterNames: Record<string, string> = { input_mode: '坐标来源', object_name: '天体名称', ra_deg: 'ICRS 赤经（度）', dec_deg: 'ICRS 赤纬（度）', radius_arcmin: '半径（角分）', limit: '交付行上限', ruwe_max: 'RUWE 上限', parallax_snr_min: '视差信噪比下限', parallax_min: '视差下限（mas）', parallax_max: '视差上限（mas）', pmra_min: 'pmRA 下限（mas/yr）', pmra_max: 'pmRA 上限（mas/yr）', pmdec_min: 'pmDec 下限（mas/yr）', pmdec_max: 'pmDec 上限（mas/yr）', g_mag_max: 'G 星等上限（mag）', estimate_distance: '近似距离估算', plots: '所选图表', query: 'ADS 检索式', rows: '本页篇数', start: '起始偏移', sort: '排序' }
function parameterValue(key: string, value: unknown): string {
  if (value === null || value === undefined || value === '') return '未设置'
  if (key === 'input_mode') return value === 'coordinates' ? '明确的 ICRS 坐标' : 'SIMBAD 名称解析'
  if (Array.isArray(value)) return value.map(v => plotNames[v as keyof typeof plotNames] || String(v)).join('、') || '未选择'
  if (typeof value === 'boolean') return value ? '启用' : '不启用'
  return ({ date_desc: '发表日期降序', citation_count_desc: '被引次数降序', relevance: '相关度降序' } as Record<string, string>)[String(value)] || String(value)
}
const completed = computed(() => run.value?.steps.filter(s => ['succeeded', 'skipped'].includes(s.state)).length || 0)
const snapshotId = computed(() => run.value?.steps.flatMap(s => s.attempts ?? []).find(a => a.snapshot_id)?.snapshot_id)
const response = computed(() => {
  const step = run.value?.steps.find(s => s.id === (run.value?.template_id === 'gaia_field' ? 'query_gaia' : 'query_ads'))
  return step?.attempts?.slice().reverse().find(a => a.output?.response)?.output?.response as ChatResponse | undefined
})
const resultTurn = computed<Turn | null>(() => run.value && response.value ? {
  conversation_id: project.value!.id, turn_id: run.value.id, client_request_id: run.value.id,
  revision: run.value.revision, message: run.value.name, received_at: run.value.created_at,
  execution_status: 'completed', trace_status: 'not_recorded', response: response.value,
} : null)
const pictures = computed(() => run.value?.outputs.filter(o => o.media_type === 'image/png') || [])
const evidence = computed(() => run.value?.steps.find(s => s.id === 'evidence_table')?.attempts?.slice().reverse().find(a => a.state === 'succeeded')?.output)
const canExecute = computed(() => run.value && run.value.provenance === 'local' && !['running', 'succeeded'].includes(run.value.state) && !pending.value)
function report(e: unknown) { error.value = e instanceof Error ? e.message : '操作未确认，请刷新记录核对。' }
function key(projectId: string, runId: string) { return `astroagent.workflow.request.${projectId}.${runId}` }
function persist(projectId: string, runId: string, payload: WorkflowExecute | null) {
  try { if (payload) sessionStorage.setItem(key(projectId, runId), JSON.stringify(payload)); else sessionStorage.removeItem(key(projectId, runId)) }
  catch { message.value = '浏览器未能保存请求编号，请保留当前页面并先核对服务端记录。' }
}
function remembered(projectId: string, runId: string): WorkflowExecute | null {
  try { const v = JSON.parse(sessionStorage.getItem(key(projectId, runId)) || 'null'); return v && typeof v.client_request_id === 'string' && /^[0-9a-f-]{36}$/i.test(v.client_request_id) && Number.isInteger(v.expected_revision) && v.confirmed === true ? v : null } catch { return null }
}
async function refresh() {
  const token = ++navigation, routePid = typeof route.params.projectId === 'string' ? route.params.projectId : '', runId = String(route.params.runId || '')
  await projectsStore.load()
  const projectId = routePid || (await projectsStore.ensureDefault()).id
  if (token !== navigation) return
  resolvedProjectId.value = projectId
  const [p, templates, list, detail] = await Promise.all([projectsApi.detail(projectId), workflowsApi.templates(), workflowsApi.list(projectId), runId ? workflowsApi.detail(projectId, runId) : Promise.resolve(null)])
  if (token !== navigation) return
  project.value = p; catalog.value = templates; runs.value = list; run.value = detail
  pending.value = runId ? remembered(projectId, runId) : null
  if (pending.value && detail?.operations.some(op => op.client_request_id === pending.value!.client_request_id && op.state !== 'running')) {
    persist(projectId, runId, null); pending.value = null
  }
}
async function act(task: () => Promise<unknown>) {
  if (busy.value) return
  busy.value = true; error.value = ''; message.value = ''
  try { await task() } catch (e) { report(e); mobilePanel.value = 'steps' } finally { busy.value = false }
}
function number(text: string, label: string, optional = false): number | null {
  if (!String(text).trim()) { if (optional) return null; throw new Error(`请填写${label}。`) }
  const value = Number(text)
  if (!Number.isFinite(value)) throw new Error(`${label}必须是有限数值。`)
  return value
}
function parameters(): WorkflowCreate['parameters'] {
  if (templateId.value === 'ads_evidence') return { query: query.value, rows: number(rows.value, '每页篇数')!, start: number(start.value, '起始偏移')!, sort: sort.value }
  return {
    input_mode: mode.value,
    object_name: mode.value === 'name' ? objectName.value : null,
    ra_deg: mode.value === 'coordinates' ? number(ra.value, 'ICRS赤经') : null,
    dec_deg: mode.value === 'coordinates' ? number(dec.value, 'ICRS赤纬') : null,
    radius_arcmin: number(radius.value, '半径')!,
    limit: number(limit.value, '交付行上限')!,
    ruwe_max: number(ruwe.value, 'RUWE上限', true),
    parallax_snr_min: number(snr.value, '视差信噪比下限', true),
    parallax_min: number(parallaxMin.value, '视差下限', true),
    parallax_max: number(parallaxMax.value, '视差上限', true),
    pmra_min: number(pmraMin.value, 'pmRA下限', true),
    pmra_max: number(pmraMax.value, 'pmRA上限', true),
    pmdec_min: number(pmdecMin.value, 'pmDec下限', true),
    pmdec_max: number(pmdecMax.value, 'pmDec上限', true),
    g_mag_max: number(gMagMax.value, 'G星等上限', true),
    estimate_distance: distance.value,
    plots: plots.value,
  }
}
async function create() {
  const p = project.value
  if (!p) return
  await act(async () => {
    const value = await workflowsApi.create(p.id, { expected_revision: p.revision, template_id: templateId.value, name: name.value.trim(), parameters: parameters() })
    await router.push(`${workflowBase.value}/${value.id}`); await refresh()
    message.value = '已建立待执行记录。请核对保存的参数，再确认启动。'; mobilePanel.value = 'steps'
  })
}
async function confirm(kind: 'execute' | 'delete') { action.value = kind; await nextTick(); dialog.value?.showModal() }
async function confirmed() {
  const p = project.value, r = run.value, kind = action.value
  dialog.value?.close(); action.value = ''
  if (!p || !r) return
  if (kind === 'delete') await act(async () => { await workflowsApi.delete(p.id, r.id, r.revision); persist(p.id, r.id, null); await router.push(workflowBase.value); await refresh(); message.value = '已删除流程及专属文件；项目快照与会话保留。' })
  else {
    pending.value = { expected_revision: r.revision, client_request_id: crypto.randomUUID(), confirmed: true }
    persist(p.id, r.id, pending.value); await executePending()
  }
}
async function executePending() {
  const p = project.value, r = run.value, payload = pending.value
  if (!p || !r || !payload) return
  await act(async () => {
    try {
      const value = await workflowsApi.execute(p.id, r.id, payload)
      if (value.operation.state !== 'running') persist(p.id, r.id, null)
      if (activeProjectId.value === p.id && route.params.runId === r.id) {
        await refresh(); message.value = `本次请求：${state(value.operation.state)}。科学查询和导出状态请分别查看步骤记录。`
      }
    } catch (e) {
      if (e instanceof ApiError && e.status >= 400 && e.status < 500) { persist(p.id, r.id, null); if (run.value?.id === r.id) pending.value = null }
      throw e
    }
  })
}
async function download(output: WorkflowOutput) { await act(() => downloadWorkflowOutput(output)) }
async function startNewWorkflow() {
  await router.push(workflowBase.value)
  editing.value = true
  mobilePanel.value = 'steps'
}
async function copyParameters() {
  const r = run.value
  if (!r) return
  templateId.value = r.template_id; name.value = `${r.name.slice(0, 90)} · 新运行`
  const p = r.parameters
  if (r.template_id === 'gaia_field') {
    mode.value = p.input_mode as typeof mode.value; objectName.value = String(p.object_name || '')
    ra.value = p.ra_deg == null ? '' : String(p.ra_deg); dec.value = p.dec_deg == null ? '' : String(p.dec_deg)
    radius.value = String(p.radius_arcmin); limit.value = String(p.limit); ruwe.value = p.ruwe_max == null ? '' : String(p.ruwe_max)
    snr.value = p.parallax_snr_min == null ? '' : String(p.parallax_snr_min); distance.value = p.estimate_distance === true
    const extra = p as Record<string, unknown>
    parallaxMin.value = extra.parallax_min == null ? '' : String(extra.parallax_min)
    parallaxMax.value = extra.parallax_max == null ? '' : String(extra.parallax_max)
    pmraMin.value = extra.pmra_min == null ? '' : String(extra.pmra_min)
    pmraMax.value = extra.pmra_max == null ? '' : String(extra.pmra_max)
    pmdecMin.value = extra.pmdec_min == null ? '' : String(extra.pmdec_min)
    pmdecMax.value = extra.pmdec_max == null ? '' : String(extra.pmdec_max)
    gMagMax.value = extra.g_mag_max == null ? '' : String(extra.g_mag_max)
    plots.value = (p.plots || []) as typeof plots.value
  } else { query.value = String(p.query); rows.value = String(p.rows); start.value = String(p.start); sort.value = p.sort as typeof sort.value }
  await router.push(workflowBase.value); editing.value = true; mobilePanel.value = 'steps'
  message.value = '已复制参数到新建表单。确认参数后创建，再单独确认执行。'
}
watch(() => route.fullPath, () => {
  dialog.value?.close(); action.value = ''
  navigation++; run.value = null; project.value = null; pending.value = null; error.value = ''; message.value = ''
  editing.value = !route.params.runId
  mobilePanel.value = 'steps'
  const path = route.fullPath
  void refresh().catch(e => { if (route.fullPath === path) { report(e); mobilePanel.value = 'steps' } })
}, { immediate: true })
</script>

<template>
  <div class="workspace-panes project-workspace workflow-workspace" :data-panel="mobilePanel" :data-results-open="!!run && !editing">
    <WorkspaceHeader title="固定科研流程" />
    <PanelSwitcher v-model="mobilePanel" label="流程面板" :options="[{ value: 'project', label: '流程列表' }, { value: 'steps', label: '参数与记录' }, { value: 'results', label: '结果与下载' }]" />
    <aside class="project-sidebar workflow-sidebar" aria-label="流程列表与新建">
      <WorkspacePaneHeader :level="2" title="科研流程" :subtitle="`${runs.length}/50`" />
      <div class="workspace-pane-body">
        <div class="compact-space-bar"><WorkspaceSpaceBar section="workflows" :project-id="activeProjectId" /></div>
        <button type="button" class="plot-primary" :disabled="busy" @click="startNewWorkflow">新建科研流程</button>
        <RouterLink v-for="item in runs" :key="item.id" class="project-item" :class="{selected:item.id===run?.id}" :to="`${workflowBase}/${item.id}`"><b>{{ item.name }}</b><div class="ui-pill-list" style="margin-top: 6px;"><span class="ui-pill" :class="statePill(item.state)">{{ state(item.state) }}</span><span class="ui-pill ui-pill-neutral">r{{ item.revision }}</span><span v-if="item.provenance!=='local'" class="ui-pill ui-pill-warning">导入只读</span></div></RouterLink>
      </div>
    </aside>
    <main class="project-main workflow-main">
      <WorkspacePaneHeader :title="editing ? '新建科研流程' : run?.name || '科研流程'" :level="1"><template #actions><WorkspaceSpaceBar section="workflows" :project-id="activeProjectId" /></template></WorkspacePaneHeader>
      <div class="workspace-pane-body">
      <div class="workflow-notices"><p v-if="error" class="notice danger" role="alert">{{ error }}</p><p v-if="message" class="notice info" role="status">{{ message }}</p><p v-if="busy" class="processing" role="status">正在处理。断线不会取消已提交的执行，可重新打开页面查看当前步骤。</p></div>
      <form v-if="editing" class="project-form workflow-form" @submit.prevent="create">
        <h2>参数设置</h2><p class="small muted">创建只保存参数。执行需另行确认。</p>
        <fieldset :disabled="busy || !project">
        <div v-if="catalog.length" class="ui-choice-grid" style="grid-column: 1 / -1; margin-bottom: 6px;" role="group" aria-label="选择固定科研流程模板">
          <button
            v-for="item in catalog"
            :key="item.id"
            type="button"
            class="ui-choice-card"
            :aria-pressed="templateId === item.id"
            @click="templateId = item.id as 'gaia_field' | 'ads_evidence'"
          >
            <div class="ui-choice-card-top">
              <span class="ui-pill" :class="item.id === 'gaia_field' ? 'ui-pill-gaia' : 'ui-pill-ads'">{{ item.id === 'gaia_field' ? 'Gaia DR3' : 'ADS 文献' }}</span>
              <span class="ui-pill ui-pill-neutral">v{{ item.version }} · {{ item.steps.length }} 步</span>
            </div>
            <b>{{ item.title }}</b>
            <small>{{ item.id === 'gaia_field' ? '视场圆锥查询、质量与自行筛选、自动留存快照与诊断图。' : '固定 ADS 检索式、书目摘要与结构化证据表导出。' }}</small>
          </button>
        </div>
        <label class="sr-only" for="workflow-template">固定模板</label><select id="workflow-template" v-model="templateId" class="sr-only"><option v-for="item in catalog" :key="item.id" :value="item.id">{{ item.title }} · v{{ item.version }}</option></select>
          <label for="workflow-name">运行名称</label><input id="workflow-name" v-model="name" required maxlength="100">
          <template v-if="templateId==='gaia_field'">
            <label for="workflow-mode">坐标来源（互斥）</label><select id="workflow-mode" v-model="mode"><option value="coordinates">明确的ICRS坐标</option><option value="name">SIMBAD名称解析</option></select>
            <template v-if="mode==='name'"><label for="workflow-object">天体名称</label><input id="workflow-object" v-model="objectName" required maxlength="200"><p class="small muted">必须从实际SIMBAD结果取得坐标。主站失败时使用哈佛镜像。</p></template>
            <template v-else><label for="workflow-ra">ICRS赤经 / 度 [0,360)</label><input id="workflow-ra" v-model="ra" type="number" step="any" min="0" max="359.99999999999994" required><label for="workflow-dec">ICRS赤纬 / 度 [-90,90]</label><input id="workflow-dec" v-model="dec" type="number" step="any" min="-90" max="90" required></template>
            <label for="workflow-radius">圆锥半径 / 角分 (0,30]</label><input id="workflow-radius" v-model="radius" type="number" step="any" min="0.000000001" max="30" required>
            <label for="workflow-limit">交付行上限 / 1—500</label><input id="workflow-limit" v-model="limit" type="number" min="1" max="500" step="1" required>
            <label for="workflow-ruwe">RUWE上限（可选）</label><input id="workflow-ruwe" v-model="ruwe" type="number" step="any" min="0.000000001" max="10">
            <label for="workflow-snr">视差信噪比下限（可选）</label><input id="workflow-snr" v-model="snr" type="number" step="any" min="0.000000001" max="1000">
            <details class="workflow-advanced-filters">
              <summary>高级天体测量与测光筛选（可选：视差 / 自行 / G 星等）</summary>
              <div class="workflow-advanced-grid">
                <label for="workflow-plx-min">视差下限 (mas)<input id="workflow-plx-min" v-model="parallaxMin" type="number" step="any" placeholder="例如 6.0" /></label>
                <label for="workflow-plx-max">视差上限 (mas)<input id="workflow-plx-max" v-model="parallaxMax" type="number" step="any" placeholder="例如 9.0" /></label>
                <label for="workflow-pmra-min">pmRA 下限 (mas/yr)<input id="workflow-pmra-min" v-model="pmraMin" type="number" step="any" placeholder="例如 15" /></label>
                <label for="workflow-pmra-max">pmRA 上限 (mas/yr)<input id="workflow-pmra-max" v-model="pmraMax" type="number" step="any" placeholder="例如 25" /></label>
                <label for="workflow-pmdec-min">pmDec 下限 (mas/yr)<input id="workflow-pmdec-min" v-model="pmdecMin" type="number" step="any" placeholder="例如 -52" /></label>
                <label for="workflow-pmdec-max">pmDec 上限 (mas/yr)<input id="workflow-pmdec-max" v-model="pmdecMax" type="number" step="any" placeholder="例如 -38" /></label>
                <label for="workflow-g-max">G 波段星等上限 (mag)<input id="workflow-g-max" v-model="gMagMax" type="number" step="any" min="-5" max="25" placeholder="例如 16" /></label>
              </div>
            </details>
            <div class="ui-pill-list" style="grid-column: 1 / -1;">
              <label class="ui-chip-toggle"><input v-model="distance" type="checkbox">估算高信噪比正视差近似距离</label>
              <label v-for="(title, kind) in plotNames" :key="kind" class="ui-chip-toggle"><input v-model="plots" type="checkbox" :value="kind">{{ title }}</label>
            </div>
          </template>
          <template v-else><label for="workflow-query">实际ADS检索式</label><textarea id="workflow-query" v-model="query" required maxlength="1000" rows="4" placeholder="例如：title:&quot;binary cluster&quot; year:2020-2026"></textarea><p class="small muted">年份写入检索式；确认后原样提交，不翻译或扩展检索词。</p><label for="workflow-rows">本页篇数 / 1—10</label><input id="workflow-rows" v-model="rows" type="number" min="1" max="10" step="1" required><label for="workflow-start">起始偏移 / 0—90，偏移+篇数≤100</label><input id="workflow-start" v-model="start" type="number" min="0" max="90" step="1" required><label for="workflow-sort">排序</label><select id="workflow-sort" v-model="sort"><option value="date_desc">发表日期降序</option><option value="citation_count_desc">被引次数降序</option><option value="relevance">相关度降序</option></select></template>
          <details><summary>创建后的固定步骤</summary><ol><li v-for="step in template?.steps" :key="step.id">{{ step.title }}</li></ol></details>
          <p v-for="warning in template?.warnings" :key="warning" class="small muted">{{ warning }}</p>
          <button class="button-primary" :disabled="!name.trim() || runs.length>=50">创建待执行记录</button>
        </fieldset>
      </form>
      <template v-if="run && !editing">
        <header class="project-heading ui-card">
          <div class="ui-card-head">
            <div class="ui-pill-list">
              <span class="ui-pill" :class="run.template_id === 'gaia_field' ? 'ui-pill-gaia' : 'ui-pill-ads'">{{ run.template_id === 'gaia_field' ? 'Gaia 视场流程' : 'ADS 证据表流程' }}</span>
              <span class="ui-pill" :class="statePill(run.state)"><span class="ui-dot" aria-hidden="true" />{{ state(run.state) }}</span>
              <span class="ui-pill ui-pill-neutral">v{{ run.template_version }} · r{{ run.revision }}</span>
              <span class="ui-pill ui-pill-mono">{{ run.id.slice(0, 8) }}</span>
            </div>
            <span class="ui-pill ui-pill-accent">{{ completed }} / {{ run.steps.length }} 步已完成或跳过</span>
          </div>
          <div class="ui-progress" role="progressbar" :aria-valuenow="run.steps.length ? Math.round((completed / run.steps.length) * 100) : 0" aria-valuemin="0" aria-valuemax="100"><div class="ui-progress-fill" :style="{ width: `${run.steps.length ? Math.round((completed / run.steps.length) * 100) : 0}%` }" /></div>
          <p v-if="run.provenance==='imported_unverified'" class="notice">导入只读 · 来源未经认证。包内哈希不证明来源真实性；需要重新查询时，复制参数并建立本机新运行。</p>
          <p v-if="run.error" class="notice danger">{{ run.error.message }} <code>{{ run.error.code }}</code><span v-if="run.error.code === 'gaia_timeout'"> 本次未取得数据；已完成步骤保留。等待服务恢复后，可核对并继续，不会自动重复执行。</span></p>
          <div class="project-actions"><button v-if="canExecute" class="button-primary" :disabled="busy" @click="confirm('execute')">{{ run.state==='pending' ? '核对并启动' : '核对并继续' }}</button><button :disabled="busy" @click="copyParameters">复制参数，新建运行</button><RouterLink :to="{path:`/projects/${run.project_id}/overview`,query:{target_type:'workflow_run',target_id:run.id}}">关联本地原文证据 →</RouterLink><RouterLink v-if="snapshotId" :to="`/?project=${encodeURIComponent(run.project_id)}&snapshot=${encodeURIComponent(snapshotId)}`">查看保存快照 →</RouterLink><button :disabled="busy || run.state==='running' || !!pending" class="button-danger" @click="confirm('delete')">删除流程</button></div>
          <div v-if="pending" class="notice"><p>此请求还未确认结束。刷新只读取状态；下方按钮使用原请求编号核对，不会自动重放步骤。</p><code>{{ pending.client_request_id }}</code><button :disabled="busy" @click="executePending">用原请求编号核对</button></div>
          <dl class="ui-param-grid"><div v-for="(value, parameterKey) in run.parameters" :key="parameterKey" class="ui-param-tile"><dt>{{ parameterNames[parameterKey] || parameterKey }}</dt><dd>{{ parameterValue(String(parameterKey), value) }}</dd></div></dl>
          <details><summary>原始参数 JSON · 不随继续操作改变</summary><pre>{{ print(run.parameters) }}</pre></details>
          <details><summary>创建时输入与软件版本</summary><pre>{{ print({requested_parameters:run.requested_parameters,software:run.software,created_at:run.created_at,updated_at:run.updated_at,original_id:run.original_id,archive_sha256:run.archive_sha256}) }}</pre></details>
        </header>
        <section aria-label="步骤与尝试" class="workflow-steps"><article v-for="(step, index) in run.steps" :key="step.id" class="workflow-step ui-card"><header class="ui-card-head" style="align-items: center;"><div class="ui-pill-list"><span class="ui-step-num">{{ index+1 }}</span><h2 class="ui-card-title">{{ step.title }}</h2></div><span class="ui-pill" :class="statePill(step.state)">{{ state(step.state) }}</span></header><p v-if="step.skip_reason" class="small muted">{{ step.skip_reason }}</p><p v-if="!(step.attempts?.length || 0) && step.state!=='skipped'" class="small muted">尚未执行，不存在实际结果。</p><details v-for="attempt in step.attempts" :key="attempt.id" :open="attempt.state!=='succeeded'"><summary>尝试 {{ attempt.sequence }}/5 · {{ state(attempt.state) }} · {{ attempt.started_at }}</summary><div class="ui-pill-list" style="margin: 8px 0;"><span class="ui-pill ui-pill-neutral">查询：{{ attempt.query_status || '不适用' }}</span><span class="ui-pill ui-pill-neutral">导出：{{ attempt.export_status || '不适用' }}</span><span class="ui-pill ui-pill-mono">{{ attempt.elapsed_seconds == null ? '耗时未确认' : `${attempt.elapsed_seconds.toFixed(2)} s` }}</span></div><p v-if="attempt.error" class="notice danger">{{ attempt.error.message }} <code>{{ attempt.error.code }}</code></p><p v-for="warning in attempt.warnings" :key="warning" class="small muted">{{ warning }}</p><details><summary>实际输入、依赖、软件及请求编号</summary><pre>{{ print({input:attempt.input,input_sha256:attempt.input_sha256,dependencies:attempt.dependencies,software:attempt.software,attempt_id:attempt.id,operation_id:attempt.operation_id,client_request_id:attempt.client_request_id,completed_at:attempt.completed_at}) }}</pre></details><details v-if="attempt.output"><summary>完整步骤输出及哈希</summary><code>{{ attempt.output_sha256 }}</code><pre>{{ print(attempt.output) }}</pre></details></details></article></section>
        <details><summary>执行请求历史（继续会新建请求及失败步骤的尝试）</summary><pre>{{ print(run.operations) }}</pre></details>
      </template>
      <div v-else-if="!editing" class="ui-empty-card workflow-intro">
        <div class="ui-empty-icon" aria-hidden="true"><svg viewBox="0 0 24 24"><path d="M5 7h14M5 12h10M5 17h14" /><circle cx="18" cy="12" r="2" /></svg></div>
        <span class="ui-pill ui-pill-accent">固定科研流程 · 检查点留存</span>
        <h2>参数明确，逐步可复现</h2>
        <p>选择固定模板设定参数，核对后手动确认执行。每个成功步骤独立留存检查点与 SHA-256，不调用语言模型。</p>
        <div class="ui-step-rail">
          <span class="ui-step-pill"><span class="ui-step-num">1</span>选择模板</span>
          <span class="ui-step-arrow" aria-hidden="true">→</span>
          <span class="ui-step-pill"><span class="ui-step-num">2</span>核对参数</span>
          <span class="ui-step-arrow" aria-hidden="true">→</span>
          <span class="ui-step-pill"><span class="ui-step-num">3</span>逐步检查点</span>
          <span class="ui-step-arrow" aria-hidden="true">→</span>
          <span class="ui-step-pill"><span class="ui-step-num">4</span>校验下载</span>
        </div>
      </div>
</div>
    </main>
    <section v-if="run && !editing" class="workflow-results" aria-label="流程结果与持久输出">
      <WorkspacePaneHeader title="结果与下载" :level="2" />
      <div class="workspace-pane-body">
      <section class="workflow-downloads"><p class="eyebrow">DURABLE OUTPUTS</p><h2>保存的输出文件</h2><p v-if="!run?.outputs.length" class="small muted">尚无已保存文件。导出失败时请先核对查询步骤和项目快照。</p><article v-for="output in run?.outputs" :key="output.id" class="workflow-output ui-card"><div class="ui-card-head" style="align-items: center;"><div class="ui-pill-list"><span class="ui-file-badge" :class="output.media_type === 'image/png' ? 'is-image' : 'is-data'">{{ fileExt(output.filename) }}</span><b>{{ output.filename }}</b></div><span class="ui-pill ui-pill-mono">{{ formatBytes(output.bytes) }}</span></div><div class="ui-pill-list"><span class="ui-pill" :class="output.provenance==='local' ? 'ui-pill-success' : 'ui-pill-warning'">{{ output.provenance==='local' ? '本机生成' : '导入未认证' }}</span></div><details><summary>SHA-256 与归属</summary><pre>{{ print(output) }}</pre></details><div><button :disabled="busy" @click="download(output)">核对哈希并下载</button></div></article><figure v-for="picture in pictures" :key="picture.id"><img :src="apiUrl(outputPath(picture))" :alt="picture.filename" loading="lazy" @error="error='保存的图片不可用，请刷新记录核对。'"><figcaption>{{ picture.filename }} · 只描述交付样本</figcaption></figure><details v-if="evidence"><summary>ADS证据表与CSV变更说明 · 原值保留</summary><pre>{{ print(evidence) }}</pre></details></section>
      <ResultPanel :turn="resultTurn" :historical="true" :disable-export="true" heading="本次流程的实际数据" />
</div>
    </section>
    <dialog ref="dialog" class="project-dialog" @close="action=''">
      <div class="dialog-header">
        <div class="dialog-header-copy"><h2>{{ action==='delete' ? '删除流程与专属文件' : run?.state==='pending' ? '确认启动科研流程' : '确认继续科研流程' }}</h2></div>
        <button type="button" class="dialog-close" aria-label="关闭" :disabled="busy" @click="dialog?.close()"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="m6 6 12 12M6 18 18 6" /></svg></button>
      </div>
      <template v-if="action==='delete'"><p>将删除此流程的步骤、尝试与下载文件。已保存的项目快照和原始会话保留。</p></template>
      <template v-else><p>将按下列保存参数按需访问外部科研服务。成功步骤通过完整性与版本核对后复用；失败或中断步骤新建尝试，远端可能已经执行过。</p><dl v-if="run" class="workflow-parameter-summary"><template v-for="(value, parameterKey) in run.parameters" :key="parameterKey"><dt>{{ parameterNames[parameterKey] || parameterKey }}</dt><dd>{{ parameterValue(String(parameterKey), value) }}</dd></template></dl><details><summary>原始参数 JSON</summary><pre>{{ print(run?.parameters) }}</pre></details><ol><li v-for="step in run?.steps" :key="step.id">{{ step.title }} · {{ state(step.state) }}</li></ol><p>未调用模型；查询、保存和导出状态分别记录。确认后同步执行，请保留页面。</p></template>
      <div class="project-actions"><button type="button" @click="dialog?.close()">取消</button><button type="button" :class="action==='delete' ? 'button-danger' : 'button-primary'" :disabled="busy" @click="confirmed">{{ action==='delete' ? '确认删除' : '确认执行' }}</button></div>
    </dialog>
  </div>
</template>
