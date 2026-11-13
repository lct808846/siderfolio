<script setup lang="ts">
import WorkspaceHeader from '../components/WorkspaceHeader.vue'
import WorkspacePaneHeader from '../components/WorkspacePaneHeader.vue'
import PanelSwitcher from '../components/PanelSwitcher.vue'
import { computed, nextTick, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ApiError, apiUrl } from '../api'
import { projectsApi } from '../api/projects'
import { downloadWorkflowOutput, outputPath, workflowsApi } from '../api/workflows'
import ResultPanel from '../components/ResultPanel.vue'
import type { AdsEvidenceParameters, ChatResponse, GaiaFieldParameters, ProjectDetail, Turn, WorkflowCreate, WorkflowDetail, WorkflowExecute, WorkflowOutput, WorkflowSummary, WorkflowTemplate } from '../types'

const route = useRoute(), router = useRouter()
const project = ref<ProjectDetail | null>(null), catalog = ref<WorkflowTemplate[]>([]), runs = ref<WorkflowSummary[]>([])
const run = ref<WorkflowDetail | null>(null), busy = ref(false), error = ref(''), message = ref(''), mobilePanel = ref('project')
const editing = ref(!route.params.runId)
const templateId = ref<'gaia_field' | 'ads_evidence'>('gaia_field'), name = ref('')
const mode = ref<'name' | 'coordinates'>('coordinates'), objectName = ref(''), ra = ref(''), dec = ref('')
const radius = ref(''), limit = ref(''), ruwe = ref(''), snr = ref(''), distance = ref(false)
const plots = ref<NonNullable<GaiaFieldParameters['plots']>>([])
const query = ref(''), rows = ref('10'), start = ref('0'), sort = ref<AdsEvidenceParameters['sort']>('date_desc')
const dialog = ref<HTMLDialogElement | null>(null), action = ref<'execute' | 'delete' | ''>('')
const pending = ref<WorkflowExecute | null>(null)
const refreshing = ref(false)
let navigation = 0
const template = computed(() => catalog.value.find(t => t.id === templateId.value))
const labels: Record<string, string> = { pending: '待执行', running: '运行中', succeeded: '完成', failed: '失败', skipped: '跳过', interrupted: '已中断' }
const plotNames = { proper_motion: '自行散点图', parallax_histogram: '视差直方图', observed_cmd: '观测颜色—星等图' }
const print = (value: unknown) => JSON.stringify(value, null, 2)
const state = (value: string) => labels[value] || value
const parameterNames: Record<string, string> = { input_mode: '坐标来源', object_name: '天体名称', ra_deg: 'ICRS 赤经（度）', dec_deg: 'ICRS 赤纬（度）', radius_arcmin: '半径（角分）', limit: '交付行上限', ruwe_max: 'RUWE 上限', parallax_snr_min: '视差信噪比下限', estimate_distance: '近似距离估算', plots: '所选图表', query: 'ADS 检索式', rows: '本页篇数', start: '起始偏移', sort: '排序' }
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
  execution_status: 'completed', response: response.value,
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
  const token = ++navigation, projectId = String(route.params.projectId || ''), runId = String(route.params.runId || '')
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
async function refreshStatus() {
  if (refreshing.value) return
  refreshing.value = true; error.value = ''
  try { await refresh() } catch (e) { report(e) } finally { refreshing.value = false }
}
function number(text: string, label: string, optional = false): number | null {
  if (!String(text).trim()) { if (optional) return null; throw new Error(`请填写${label}。`) }
  const value = Number(text)
  if (!Number.isFinite(value)) throw new Error(`${label}必须是有限数值。`)
  return value
}
function parameters(): WorkflowCreate['parameters'] {
  if (templateId.value === 'ads_evidence') return { query: query.value, rows: number(rows.value, '每页篇数')!, start: number(start.value, '起始偏移')!, sort: sort.value }
  return { input_mode: mode.value, object_name: mode.value === 'name' ? objectName.value : null,
    ra_deg: mode.value === 'coordinates' ? number(ra.value, 'ICRS赤经') : null,
    dec_deg: mode.value === 'coordinates' ? number(dec.value, 'ICRS赤纬') : null,
    radius_arcmin: number(radius.value, '半径')!, limit: number(limit.value, '交付行上限')!,
    ruwe_max: number(ruwe.value, 'RUWE上限', true), parallax_snr_min: number(snr.value, '视差信噪比下限', true),
    estimate_distance: distance.value, plots: plots.value }
}
async function create() {
  const p = project.value
  if (!p) return
  await act(async () => {
    const value = await workflowsApi.create(p.id, { expected_revision: p.revision, template_id: templateId.value, name: name.value.trim(), parameters: parameters() })
    await router.push(`/projects/${p.id}/workflows/${value.id}`); await refresh()
    message.value = '已建立待执行记录。请核对保存的参数，再确认启动。'; mobilePanel.value = 'steps'
  })
}
async function confirm(kind: 'execute' | 'delete') { action.value = kind; await nextTick(); dialog.value?.showModal() }
async function confirmed() {
  const p = project.value, r = run.value, kind = action.value
  dialog.value?.close(); action.value = ''
  if (!p || !r) return
  if (kind === 'delete') await act(async () => { await workflowsApi.delete(p.id, r.id, r.revision); persist(p.id, r.id, null); await router.push(`/projects/${p.id}/workflows`); await refresh(); message.value = '已删除流程及专属文件；项目快照与会话保留。' })
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
      if (route.params.projectId === p.id && route.params.runId === r.id) {
        await refresh(); message.value = `本次请求：${state(value.operation.state)}。科学查询和导出状态请分别查看步骤记录。`
      }
    } catch (e) {
      if (e instanceof ApiError && e.status >= 400 && e.status < 500) { persist(p.id, r.id, null); if (run.value?.id === r.id) pending.value = null }
      throw e
    }
  })
}
async function download(output: WorkflowOutput) { await act(() => downloadWorkflowOutput(output)) }
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
    plots.value = (p.plots || []) as typeof plots.value
  } else { query.value = String(p.query); rows.value = String(p.rows); start.value = String(p.start); sort.value = p.sort as typeof sort.value }
  await router.push(`/projects/${r.project_id}/workflows`); editing.value = true; mobilePanel.value = 'steps'
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
      <RouterLink :to="`/projects/${route.params.projectId}/workflows`"><p class="eyebrow">WORKFLOWS · {{ runs.length }}/50</p><h2>{{ project?.name || '正在读取项目' }}</h2></RouterLink>
      <RouterLink v-for="item in runs" :key="item.id" class="project-item" :class="{selected:item.id===run?.id}" :to="`/projects/${item.project_id}/workflows/${item.id}`"><b>{{ item.name }}</b><small>{{ state(item.state) }} · r{{ item.revision }} · {{ item.provenance==='local' ? '本机' : '导入只读' }}</small></RouterLink>
      <button type="button" class="plot-primary" :disabled="busy" @click="router.push(`/projects/${route.params.projectId}/workflows`); editing = true; mobilePanel = 'steps'">新建科研流程</button>
    </aside>
    <main class="project-main workflow-main">
      <WorkspacePaneHeader :title="editing ? '新建科研流程' : run?.name || '科研流程'" :level="1" :subtitle="project?.name" />
      <div class="workspace-pane-body">
      <div class="workflow-notices"><p v-if="error" class="notice danger" role="alert">{{ error }}</p><p v-if="message" class="notice" role="status">{{ message }}</p><p v-if="busy" class="processing" role="status">正在处理。断线不会取消已提交的执行，可刷新读取当前步骤。</p><button :disabled="refreshing" @click="refreshStatus">{{ refreshing ? '正在读取…' : '刷新记录' }}</button></div>
      <form v-if="editing" class="project-form workflow-form" @submit.prevent="create">
        <h2>参数设置</h2><p class="small muted">创建只保存参数。执行需另行确认。</p>
        <fieldset :disabled="busy || !project">
<label for="workflow-template">固定模板</label><select id="workflow-template" v-model="templateId"><option v-for="item in catalog" :key="item.id" :value="item.id">{{ item.title }} · v{{ item.version }}</option></select>
          <label for="workflow-name">运行名称</label><input id="workflow-name" v-model="name" required maxlength="100">
          <template v-if="templateId==='gaia_field'">
            <label for="workflow-mode">坐标来源（互斥）</label><select id="workflow-mode" v-model="mode"><option value="coordinates">明确的ICRS坐标</option><option value="name">SIMBAD名称解析</option></select>
            <template v-if="mode==='name'"><label for="workflow-object">天体名称</label><input id="workflow-object" v-model="objectName" required maxlength="200"><p class="small muted">必须从实际SIMBAD结果取得坐标。主站失败时使用哈佛镜像。</p></template>
            <template v-else><label for="workflow-ra">ICRS赤经 / 度 [0,360)</label><input id="workflow-ra" v-model="ra" type="number" step="any" min="0" max="359.99999999999994" required><label for="workflow-dec">ICRS赤纬 / 度 [-90,90]</label><input id="workflow-dec" v-model="dec" type="number" step="any" min="-90" max="90" required></template>
            <label for="workflow-radius">圆锥半径 / 角分 (0,30]</label><input id="workflow-radius" v-model="radius" type="number" step="any" min="0.000000001" max="30" required>
            <label for="workflow-limit">交付行上限 / 1—100</label><input id="workflow-limit" v-model="limit" type="number" min="1" max="100" step="1" required>
            <label for="workflow-ruwe">RUWE上限（可选）</label><input id="workflow-ruwe" v-model="ruwe" type="number" step="any" min="0.000000001" max="10">
            <label for="workflow-snr">视差信噪比下限（可选）</label><input id="workflow-snr" v-model="snr" type="number" step="any" min="0.000000001" max="1000">
            <label class="check-label"><input v-model="distance" type="checkbox">估算高信噪比正视差的近似距离</label>
            <label v-for="(title, kind) in plotNames" :key="kind" class="check-label"><input v-model="plots" type="checkbox" :value="kind">{{ title }}</label>
          </template>
          <template v-else><label for="workflow-query">实际ADS检索式</label><textarea id="workflow-query" v-model="query" required maxlength="1000" rows="4" placeholder="例如：title:&quot;binary cluster&quot; year:2020-2026"></textarea><p class="small muted">年份写入检索式；确认后原样提交，不翻译或扩展检索词。</p><label for="workflow-rows">本页篇数 / 1—10</label><input id="workflow-rows" v-model="rows" type="number" min="1" max="10" step="1" required><label for="workflow-start">起始偏移 / 0—90，偏移+篇数≤100</label><input id="workflow-start" v-model="start" type="number" min="0" max="90" step="1" required><label for="workflow-sort">排序</label><select id="workflow-sort" v-model="sort"><option value="date_desc">发表日期降序</option><option value="citation_count_desc">被引次数降序</option><option value="relevance">相关度降序</option></select></template>
          <details><summary>创建后的固定步骤</summary><ol><li v-for="step in template?.steps" :key="step.id">{{ step.title }}</li></ol></details>
          <p v-for="warning in template?.warnings" :key="warning" class="small muted">{{ warning }}</p>
          <button class="button-primary" :disabled="!name.trim() || runs.length>=50">创建待执行记录</button>
        </fieldset>
      </form>
      <template v-if="run && !editing">
        <header class="project-heading">
<p class="eyebrow">{{ run.template_id }} / v{{ run.template_version }} / r{{ run.revision }}</p><h2>运行记录</h2><p>{{ state(run.state) }} · {{ completed }}/{{ run.steps.length }} 步已完成或跳过</p><code>{{ run.id }}</code><p v-if="run.provenance==='imported_unverified'" class="notice">导入只读 · 来源未经认证。包内哈希不证明来源真实性；需要重新查询时，复制参数并建立本机新运行。</p><p v-if="run.error" class="notice danger">{{ run.error.message }} <code>{{ run.error.code }}</code><span v-if="run.error.code === 'gaia_timeout'"> 本次未取得数据；已完成步骤保留。等待服务恢复后，可核对并继续，不会自动重复执行。</span></p>
          <div class="project-actions"><RouterLink :to="{path:`/projects/${run.project_id}/overview`,query:{target_type:'workflow_run',target_id:run.id}}">关联本地原文证据 →</RouterLink><button v-if="canExecute" class="button-primary" :disabled="busy" @click="confirm('execute')">{{ run.state==='pending' ? '核对并启动' : '核对并继续' }}</button><button :disabled="busy" @click="copyParameters">复制参数，新建运行</button><button :disabled="busy || run.state==='running' || !!pending" class="button-danger" @click="confirm('delete')">删除流程</button><RouterLink v-if="snapshotId" :to="`/projects/${run.project_id}?snapshot=${snapshotId}`">查看保存快照 →</RouterLink></div>
          <div v-if="pending" class="notice"><p>此请求还未确认结束。刷新只读取状态；下方按钮使用原请求编号核对，不会自动重放步骤。</p><code>{{ pending.client_request_id }}</code><button :disabled="busy" @click="executePending">用原请求编号核对</button></div>
          <dl class="workflow-parameter-summary"><template v-for="(value, parameterKey) in run.parameters" :key="parameterKey"><dt>{{ parameterNames[parameterKey] || parameterKey }}</dt><dd>{{ parameterValue(String(parameterKey), value) }}</dd></template></dl><details><summary>原始参数 JSON · 不随继续操作改变</summary><pre>{{ print(run.parameters) }}</pre></details><details><summary>创建时输入与软件版本</summary><pre>{{ print({requested_parameters:run.requested_parameters,software:run.software,created_at:run.created_at,updated_at:run.updated_at,original_id:run.original_id,archive_sha256:run.archive_sha256}) }}</pre></details>
        </header>
        <section aria-label="步骤与尝试" class="workflow-steps"><article v-for="(step, index) in run.steps" :key="step.id" class="workflow-step"><header><span class="workflow-number">{{ index+1 }}</span><h2>{{ step.title }}</h2><span class="tag" :class="{error:['failed','interrupted'].includes(step.state)}">{{ state(step.state) }}</span></header><p v-if="step.skip_reason" class="small muted">{{ step.skip_reason }}</p><p v-if="!(step.attempts?.length || 0) && step.state!=='skipped'" class="small muted">尚未执行，不存在实际结果。</p><details v-for="attempt in step.attempts" :key="attempt.id" :open="attempt.state!=='succeeded'"><summary>尝试 {{ attempt.sequence }}/5 · {{ state(attempt.state) }} · {{ attempt.started_at }}</summary><p class="small">查询：{{ attempt.query_status || '不适用' }} · 导出：{{ attempt.export_status || '不适用' }} · {{ attempt.elapsed_seconds == null ? '耗时未确认' : `${attempt.elapsed_seconds.toFixed(2)}秒` }}</p><p v-if="attempt.error" class="notice danger">{{ attempt.error.message }} <code>{{ attempt.error.code }}</code></p><p v-for="warning in attempt.warnings" :key="warning" class="small muted">{{ warning }}</p><details><summary>实际输入、依赖、软件及请求编号</summary><pre>{{ print({input:attempt.input,input_sha256:attempt.input_sha256,dependencies:attempt.dependencies,software:attempt.software,attempt_id:attempt.id,operation_id:attempt.operation_id,client_request_id:attempt.client_request_id,completed_at:attempt.completed_at}) }}</pre></details><details v-if="attempt.output"><summary>完整步骤输出及哈希</summary><code>{{ attempt.output_sha256 }}</code><pre>{{ print(attempt.output) }}</pre></details></details></article></section>
        <details><summary>执行请求历史（继续会新建请求及失败步骤的尝试）</summary><pre>{{ print(run.operations) }}</pre></details>
      </template>
      <div v-else-if="!editing" class="workflow-intro"><p class="eyebrow">FIXED RESEARCH WORKFLOWS</p><h1>参数明确，逐步留存</h1><p>选择两个固定模板之一，创建运行后核对参数并确认执行。成功步骤作为检查点保留，失败或中断后由你确认继续。</p><p class="small muted">流程同步执行，不调用语言模型。位置候选源不等于星团成员，ADS证据表仅含实际返回的书目与摘要。</p></div>
</div>
    </main>
    <section v-if="run && !editing" class="workflow-results" aria-label="流程结果与持久输出">
      <WorkspacePaneHeader title="结果与下载" :level="2" />
      <div class="workspace-pane-body">
      <section class="workflow-downloads"><p class="eyebrow">DURABLE OUTPUTS</p><h2>保存的输出文件</h2><p v-if="!run?.outputs.length" class="small muted">尚无已保存文件。导出失败时请先核对查询步骤和项目快照。</p><article v-for="output in run?.outputs" :key="output.id" class="workflow-output"><b>{{ output.filename }}</b><p class="small muted">{{ output.bytes }} 字节 · {{ output.provenance==='local' ? '本机生成' : '导入未认证' }}</p><details><summary>SHA-256与归属</summary><pre>{{ print(output) }}</pre></details><button :disabled="busy" @click="download(output)">核对哈希并下载</button></article><figure v-for="picture in pictures" :key="picture.id"><img :src="apiUrl(outputPath(picture))" :alt="picture.filename" loading="lazy" @error="error='保存的图片不可用，请刷新记录核对。'"><figcaption>{{ picture.filename }} · 只描述交付样本</figcaption></figure><details v-if="evidence"><summary>ADS证据表与CSV变更说明 · 原值保留</summary><pre>{{ print(evidence) }}</pre></details></section>
      <ResultPanel :turn="resultTurn" :historical="true" :disable-export="true" heading="本次流程的实际数据" />
</div>
    </section>
    <dialog ref="dialog" class="project-dialog" @close="action=''"><template v-if="action==='delete'"><h2>删除流程与专属文件</h2><p>将删除此流程的步骤、尝试与下载文件。已保存的项目快照和原始会话保留。</p></template><template v-else><h2>{{ run?.state==='pending' ? '确认启动科研流程' : '确认继续科研流程' }}</h2><p>将按下列保存参数按需访问外部科研服务。成功步骤通过完整性与版本核对后复用；失败或中断步骤新建尝试，远端可能已经执行过。</p><dl v-if="run" class="workflow-parameter-summary"><template v-for="(value, parameterKey) in run.parameters" :key="parameterKey"><dt>{{ parameterNames[parameterKey] || parameterKey }}</dt><dd>{{ parameterValue(String(parameterKey), value) }}</dd></template></dl><details><summary>原始参数 JSON</summary><pre>{{ print(run?.parameters) }}</pre></details><ol><li v-for="step in run?.steps" :key="step.id">{{ step.title }} · {{ state(step.state) }}</li></ol><p>未调用模型；查询、保存和导出状态分别记录。确认后同步执行，请保留页面。</p></template><div class="project-actions"><button @click="dialog?.close()">取消</button><button class="button-primary" :disabled="busy" @click="confirmed">{{ action==='delete' ? '确认删除' : '确认执行' }}</button></div></dialog>
  </div>
</template>
