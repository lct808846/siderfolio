<script setup lang="ts">
import WorkspaceHeader from '../components/WorkspaceHeader.vue'
import WorkspacePaneHeader from '../components/WorkspacePaneHeader.vue'
import PanelSwitcher from '../components/PanelSwitcher.vue'
import StatusNotice from '../components/StatusNotice.vue'
import UiSelect from '../components/UiSelect.vue'
import { computed, nextTick, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ApiError, safeLink } from '../api'
import { knowledgeApi } from '../api/knowledge'
import { linksApi } from '../api/links'
import type { EvidenceRecord, EvidenceView, LinkCreate, LinkDetail, LinkPage, LinkTarget, ProjectOverview as Overview } from '../types'

const route = useRoute(), router = useRouter()
const overview = ref<Overview | null>(null), page = ref<LinkPage | null>(null), selected = ref<LinkDetail | null>(null)
const references = ref<EvidenceRecord[]>([]), evidence = ref<EvidenceView | null>(null)
const targetKey = ref(''), evidenceId = ref(''), note = ref(''), editNote = ref(''), filter = ref('')
const busy = ref(false), error = ref(''), message = ref(''), panel = ref('results')
const dialog = ref<HTMLDialogElement | null>(null), action = ref<'create' | 'unlink' | ''>('')
const pending = ref<{ project: string; request: LinkCreate } | null>(null)
const confirmationRequest = ref<LinkCreate | null>(null), confirmationLink = ref<LinkDetail | null>(null)
const confirmationTarget = ref(''), confirmationEvidence = ref<EvidenceView | null>(null), confirmationRevision = ref(0)
let navigation = 0, evidenceSelection = 0, linkSelection = 0
const targetKinds: Record<string, string> = { conversation_turn: '会话结果', snapshot: '命名快照', workflow_run: '科研流程' }
const states: Record<string, string> = { active: '当前可核对', target_unavailable: '结果不可用', evidence_unavailable: '证据不可用' }
const categories: Record<string, string> = { database_measurement: '数据库测量', ads_abstract: 'ADS书目/摘要', user_document: '用户文档原文', saved_answer: '原回答或程序说明', program_output: '程序输出', user_note: '用户备注' }
function categoryPill(category: string) {
  if (category === 'database_measurement') return 'ui-pill-gaia'
  if (category === 'ads_abstract') return 'ui-pill-ads'
  if (category === 'user_document') return 'ui-pill-simbad'
  if (category === 'program_output') return 'ui-pill-compute'
  return 'ui-pill-neutral'
}
const key = (target: LinkTarget) => `${target.type}:${target.id}`
const allTargets = computed(() => overview.value ? [...overview.value.conversations.flatMap(c => c.turns), ...overview.value.snapshots, ...overview.value.workflows] : [])
const chosen = computed(() => allTargets.value.find(t => key(t) === targetKey.value))
const canCreate = computed(() => chosen.value?.available && evidence.value?.evidence.validity === 'available' && evidence.value.evidence.id === evidenceId.value && !pending.value)
const pretty = (v: unknown) => JSON.stringify(v, null, 2)
function report(e: unknown) { error.value = e instanceof Error ? e.message : '操作未确认，请稍后重试或重新进入页面核对。' }
function storageKey(project: string) { return `astroagent.project-link.request.${project}` }
function remember(value: typeof pending.value, project = String(route.params.projectId)) {
  if (route.params.projectId === project) pending.value = value
  try { if (value) sessionStorage.setItem(storageKey(project), JSON.stringify(value)); else sessionStorage.removeItem(storageKey(project)) } catch { message.value = '浏览器无法保留请求编号，请保留本页核对。' }
}
function restore(project: string): typeof pending.value {
  try { const value = JSON.parse(sessionStorage.getItem(storageKey(project)) || 'null'); return value?.project === project && typeof value.request?.client_request_id === 'string' ? value : null } catch { return null }
}
function resultPath(target: LinkTarget): string {
  if (target.type === 'conversation_turn') return `/conversations/${target.conversation_id}?turn=${target.id}`
  if (target.type === 'snapshot') return `/?project=${encodeURIComponent(String(route.params.projectId || ''))}&snapshot=${encodeURIComponent(target.id)}`
  return `/projects/${route.params.projectId}/workflows/${target.id}`
}
async function refresh() {
  const token = ++navigation, project = String(route.params.projectId)
  const [value, refs] = await Promise.all([linksApi.overview(project), knowledgeApi.references(project)])
  if (token !== navigation) return
  const firstPage = filter.value ? await linksApi.list(project, { target_type: filter.value as LinkTarget['type'] }) : value.first_links
  if (token !== navigation) return
  overview.value = value; page.value = firstPage; references.value = refs; pending.value = restore(project)
  const requested = `${String(route.query.target_type || '')}:${String(route.query.target_id || '')}`
  if (!allTargets.value.some(t => key(t) === targetKey.value)) targetKey.value = allTargets.value.some(t => key(t) === requested) ? requested : ''
  if (typeof route.query.evidence_id === 'string' && evidenceId.value !== route.query.evidence_id) evidenceId.value = route.query.evidence_id
  if (typeof route.query.link_id === 'string') await inspect(route.query.link_id, false)
}
async function act(task: () => Promise<unknown>) {
  if (busy.value) return
  busy.value = true; error.value = ''; message.value = ''
  try { await task() } catch (e) { report(e) } finally { busy.value = false }
}
async function inspect(id: string, navigate = true) {
  const project = String(route.params.projectId), token = ++linkSelection
  try {
    const value = await linksApi.detail(project, id)
    if (token !== linkSelection || route.params.projectId !== project) return
    selected.value = value; editNote.value = value.link.note; panel.value = 'evidence'
    if (navigate) await router.replace({ query: { ...route.query, link_id: id } })
  } catch (e) { if (token === linkSelection) report(e) }
}
async function loadPage(after?: string) {
  const project = String(route.params.projectId)
  await act(async () => {
    const value = await linksApi.list(project, { ...(after ? { after } : {}), ...(filter.value ? { target_type: filter.value as LinkTarget['type'] } : {}) })
    if (route.params.projectId !== project) return
    page.value = value
    if (value.project_revision !== overview.value?.project.revision) message.value = '项目已更新；编辑前请重新进入页面核对最新修订号。分页按不可变关联ID排序。'
    panel.value = 'results'
  })
}
async function confirm(kind: 'create' | 'unlink') {
  const project = overview.value?.project, target = chosen.value
  if (!project) return
  confirmationRevision.value = project.revision; confirmationLink.value = selected.value; confirmationEvidence.value = evidence.value
  confirmationTarget.value = target?.label || ''; confirmationRequest.value = null
  if (kind === 'create') {
    if (!target || !canCreate.value) return
    confirmationRequest.value = { expected_revision: project.revision, client_request_id: crypto.randomUUID(), target_type: target.type, target_id: target.id, evidence_id: evidenceId.value, note: note.value, confirmed: true }
  }
  action.value = kind; await nextTick(); dialog.value?.showModal()
}
async function confirmed() {
  const kind = action.value, project = overview.value?.project, link = confirmationLink.value?.link, request = confirmationRequest.value
  dialog.value?.close(); action.value = ''
  if (!project) return
  if (kind === 'unlink' && link) await act(async () => {
    await linksApi.delete(project.id, link.id, { expected_revision: confirmationRevision.value, expected_link_revision: link.revision, confirmed: true })
    selected.value = null; await router.replace({ query: { ...route.query, link_id: undefined } }); await refresh(); panel.value = 'results'
    message.value = '已解除关联。结果、证据、文档和原回答保留。原创建请求的历史不会再次建立此关联。'
  })
  else if (kind === 'create' && request) {
    remember({ project: project.id, request }, project.id)
    await submitPending()
  }
}
async function submitPending() {
  const item = pending.value
  if (!item) return
  await act(async () => {
    try {
      const value = await linksApi.create(item.project, item.request)
      remember(null, item.project)
      if (route.params.projectId !== item.project) return
      await refresh()
      if (value.detail.present) await inspect(value.detail.link.id)
      else { selected.value = value.detail; panel.value = 'evidence' }
      message.value = value.replayed ? '已返回原请求记录；没有再次创建关联。' : value.duplicate ? '该结果与证据已有此关联，返回原记录；新备注未覆盖旧备注，可单独修改。' : '已建立用户引用关系。原回答、sources和科研统计未改变。'
    } catch (e) {
      if (e instanceof ApiError && e.status >= 400 && e.status < 500) remember(null, item.project)
      throw e
    }
  })
}
async function updateNote() {
  const p = overview.value?.project, link = selected.value?.link
  if (!p || !link) return
  await act(async () => {
    const value = await linksApi.update(p.id, link.id, { expected_revision: p.revision, expected_link_revision: link.revision, note: editNote.value })
    if (route.params.projectId === p.id) { await refresh(); selected.value = value; editNote.value = value.link.note; message.value = '已更新用户备注，关联两端保持原ID。' }
  })
}
function knowledgePath() {
  const query = new URLSearchParams()
  if (chosen.value) { query.set('link_target_type', chosen.value.type); query.set('link_target_id', chosen.value.id) }
  return `/projects/${route.params.projectId}/knowledge?${query}`
}
watch(evidenceId, async id => {
  const project = String(route.params.projectId), token = ++evidenceSelection
  evidence.value = null
  if (!id || !overview.value || !/^[0-9a-f-]{36}$/i.test(id)) return
  try { const value = await knowledgeApi.evidence(project, id); if (token === evidenceSelection && route.params.projectId === project) { evidence.value = value; error.value = '' } }
  catch (e) { if (token === evidenceSelection) report(e) }
})
watch(targetKey, () => { selected.value = null })
watch(() => route.params.projectId, () => {
  navigation++; evidenceSelection++; linkSelection++; overview.value = null; page.value = null; selected.value = null; evidence.value = null
  targetKey.value = ''; evidenceId.value = ''; filter.value = ''; note.value = ''; editNote.value = ''; error.value = ''
  dialog.value?.close(); action.value = ''; panel.value = 'results'
  void refresh().catch(report)
}, { immediate: true })
</script>

<template>
  <div class="workspace-panes project-workspace overview-workspace" :data-panel="panel">
    <WorkspaceHeader title="项目来源与显式引用" />
    <PanelSwitcher v-model="panel" label="总览面板" :options="[{ value: 'sources', label: '项目来源' }, { value: 'results', label: '建立与管理关联' }, { value: 'evidence', label: '核对两端' }]" />
    <aside class="project-sidebar overview-sidebar">
      <WorkspacePaneHeader :level="2" title="课题总览" :subtitle="overview?.project.name || ''" />
      <div class="workspace-pane-body">
        <p class="small muted">r{{ overview?.project.revision }} · {{ overview?.project.provenance==='imported_unverified' ? '导入来源未经认证' : '本机项目' }}</p>
      <nav class="overview-nav"><RouterLink :to="`/projects/${route.params.projectId}/rag`">文献知识问答 →</RouterLink><RouterLink :to="`/?project=${encodeURIComponent(String(route.params.projectId || ''))}&manage=snapshots`">会话、快照与归档</RouterLink><RouterLink :to="`/projects/${route.params.projectId}/workflows`">科研流程 · {{ overview?.workflows.length || 0 }}</RouterLink><RouterLink :to="knowledgePath()">本地知识库 · {{ overview?.documents.length || 0 }}</RouterLink></nav>
      <section><h3>会话 · {{ overview?.conversations.length || 0 }}</h3><details v-for="conversation in overview?.conversations" :key="conversation.id"><summary>{{ conversation.title }}</summary><button v-for="turn in conversation.turns" :key="turn.id" class="overview-target" :disabled="!turn.available" @click="targetKey=key(turn);panel='results'">{{ turn.label }}<small>{{ turn.state }} / {{ turn.response_status || '尚无结果' }}</small></button></details></section>
      <section><h3>命名快照 · {{ overview?.snapshots.length || 0 }}</h3><button v-for="item in overview?.snapshots" :key="item.id" class="overview-target" :disabled="!item.available" @click="targetKey=key(item);panel='results'">{{ item.label }}<small>{{ item.response_status }} · {{ item.provenance==='local' ? '本机' : '导入未认证' }}</small></button></section>
      <section><h3>科研流程 · {{ overview?.workflows.length || 0 }}</h3><button v-for="item in overview?.workflows" :key="item.id" class="overview-target" :disabled="!item.available" @click="targetKey=key(item);panel='results'">{{ item.label }}<small>{{ item.state }} · {{ item.template_version }}</small></button></section>
      <section><h3>本地文档 · {{ overview?.documents.length || 0 }}</h3><RouterLink v-for="doc in overview?.documents" :key="doc.id" class="project-item" :to="`/projects/${doc.project_id}/knowledge/${doc.id}`">{{ doc.metadata.title || doc.filename }}<small>{{ doc.state }} · {{ doc.provenance==='local' ? '用户文档' : '导入未认证' }}</small></RouterLink></section>
      </div>
    </aside>
    <main class="project-main overview-main">
      <WorkspacePaneHeader title="来源关联" :level="1" :subtitle="overview?.project.name" />
      <div class="workspace-pane-body">
<div v-if="overview" class="ui-kpi-grid" style="margin-bottom: 16px;"><div class="ui-kpi-card"><span class="ui-kpi-label">关联会话</span><span class="ui-kpi-value">{{ overview.conversations.length }}</span></div><div class="ui-kpi-card"><span class="ui-kpi-label">命名快照</span><span class="ui-kpi-value">{{ overview.snapshots.length }}</span></div><div class="ui-kpi-card"><span class="ui-kpi-label">科研流程</span><span class="ui-kpi-value">{{ overview.workflows.length }}</span></div><div class="ui-kpi-card"><span class="ui-kpi-label">本地文档</span><span class="ui-kpi-value">{{ overview.documents.length }}</span></div><div class="ui-kpi-card"><span class="ui-kpi-label">显式引用关联</span><span class="ui-kpi-value">{{ overview.link_count }}</span></div></div>
<StatusNotice v-if="error" title="来源关联操作未完成" :message="error" @dismiss="error = ''" /><p v-if="message" class="notice info" role="status">{{ message }}</p><p v-if="busy" class="processing" role="status">正在保存用户操作，不调用模型或外部数据源。</p><p v-if="overview" class="small muted overview-scope">{{ overview.warning }}</p>
      <div v-if="pending" class="notice"><p>创建请求尚待确认。下方使用原编号核对；如果原请求尚未接收，仍会按已确认的同一参数创建一次。</p><code>{{ pending.request.client_request_id }}</code><button :disabled="busy" @click="submitPending">使用原编号核对</button></div>
      <section class="overview-composer"><p class="eyebrow">USER REFERENCE</p><h2>关联结果与原文</h2><p class="small muted">手动关联仅表示你选择的引用关系。用户备注与文献原文分开保存，不表示科学证明、支持或反驳。</p><form class="project-form" @submit.prevent="confirm('create')"><label for="link-target">同项目结果</label><UiSelect id="link-target" v-model="targetKey" aria-label="同项目结果" :options="[{ value: '', label: '选择会话结果、快照或流程' }, ...allTargets.map(target => ({ value: key(target), label: `${targetKinds[target.type]} · ${target.label} · ${target.state}`, disabled: !target.available }))]" /><RouterLink :to="knowledgePath()">在本项目知识库检索并选择原文证据 →</RouterLink><label for="link-evidence">已保存证据编号</label><input id="link-evidence" v-model="evidenceId" list="project-evidence-ids" placeholder="选择最近证据或粘贴同项目证据UUID" required><datalist id="project-evidence-ids"><option v-for="item in references" :key="item.id" :value="item.id">{{ item.title || item.filename }} · {{ item.page ? `物理页${item.page}` : `行${item.line_start}` }}</option></datalist><p v-if="evidence" class="notice" :class="{danger:evidence.evidence.validity!=='available'}">{{ evidence.evidence.title || evidence.evidence.filename }} · {{ evidence.evidence.page ? `物理页${evidence.evidence.page}` : `原始行${evidence.evidence.line_start}—${evidence.evidence.line_end}` }}<br>{{ evidence.warning }}</p><details v-if="evidence?.text"><summary>待关联的固定原文版本</summary><pre>{{ evidence.text }}</pre><code>{{ evidence.evidence.version_id }}</code></details><label for="link-note">用户备注（可选，最多1000字）</label><textarea id="link-note" v-model="note" maxlength="1000" rows="3"></textarea><button class="button-primary" :disabled="busy || !canCreate">核对后建立关联</button></form></section>
      <section class="project-section"><h2>项目关联 <span class="ui-pill ui-pill-neutral">{{ overview?.link_count || 0 }}/1000</span></h2><label for="link-filter">目标类型</label><UiSelect id="link-filter" v-model="filter" aria-label="目标类型" :options="[{ value: '', label: '全部类型' }, ...Object.entries(targetKinds).map(([kind, title]) => ({ value: kind, label: title }))]" /><div class="project-actions"><button :disabled="busy" @click="loadPage()">读取首页</button><button :disabled="busy || !page?.next_cursor" @click="loadPage(page?.next_cursor || undefined)">下一页</button></div><p class="small muted">每页最多25条，按不可变关联ID排序；此筛选共 {{ page?.total || 0 }} 条。</p><article v-for="item in page?.items" :key="item.link.id" class="overview-link ui-card"><header class="ui-card-head" style="align-items: center;"><div class="ui-pill-list"><span class="ui-pill" :class="item.link.state==='active' ? 'ui-pill-success' : 'ui-pill-danger'">{{ states[item.link.state] }}</span><span class="ui-pill ui-pill-accent">{{ targetKinds[item.link.target_type] }}</span><span class="ui-pill ui-pill-neutral">r{{ item.link.revision }}</span></div><span class="small muted">{{ item.link.provenance==='local' ? '本机用户关联' : '导入未认证' }}</span></header><h3 class="ui-card-title">{{ item.target.label }}</h3><p class="small">用户备注：{{ item.link.note || '未填写' }}</p><div class="ui-card-head" style="align-items: center;"><span class="small muted">UTC {{ item.link.created_at }}</span><button :disabled="busy" @click="inspect(item.link.id)">查看两端与来源 →</button></div></article><p v-if="page && !page.items.length" class="small muted">尚无符合条件的关联。</p></section>
</div>
    </main>
    <aside class="overview-evidence" aria-label="来源核对">
      <WorkspacePaneHeader title="来源核对" :level="2" />
      <div class="workspace-pane-body">
<p class="eyebrow">VERIFY / 精确来源</p><template v-if="selected"><h2>{{ states[selected.link.state] }} <span v-if="!selected.present" class="tag error">已解绑的原请求记录</span></h2><p class="notice">{{ selected.warning }}</p><h3>{{ selected.target.label }}</h3><p class="small muted">{{ selected.target.state }} · {{ selected.target.provenance==='imported_unverified' ? '导入来源未经认证' : selected.target.provenance }}</p><RouterLink v-if="selected.target.available" :to="resultPath(selected.target)">打开关联的结果 →</RouterLink><p v-else class="notice danger">结果当前不可核对（运行中、已删除或已移出项目），未用同名对象替代。{{ selected.link.invalidation_reason }}</p><section v-if="selected.evidence" class="project-section"><h3>用户文档原文</h3><p class="small">{{ selected.evidence.evidence.title || selected.evidence.evidence.filename }} · {{ selected.evidence.evidence.page ? `物理页${selected.evidence.evidence.page}` : `行${selected.evidence.evidence.line_start}—${selected.evidence.evidence.line_end}` }}</p><p class="small muted">{{ selected.evidence.warning }}</p><p v-if="selected.evidence.historical_version" class="notice">此引用属于保留的历史文件版本，未跳到当前文档。</p><p class="small muted">证据保存时间（UTC）：{{ selected.evidence.evidence.created_at }}</p><pre v-if="selected.evidence.text">{{ selected.evidence.text }}</pre><RouterLink v-if="selected.evidence.evidence.validity==='available'" :to="{path:`/projects/${route.params.projectId}/knowledge`,query:{evidence_id:selected.link.evidence_id}}">核对固定原文与文件哈希 →</RouterLink></section><p v-else class="notice danger">文献证据已失效或固定身份不符，不展示替代原文。</p><section class="project-section"><h3>用户备注（独立于原文）</h3><form v-if="selected.present" class="project-form" @submit.prevent="updateNote"><textarea v-model="editNote" aria-label="修改用户备注" maxlength="1000" rows="4"></textarea><button :disabled="busy || !!pending">保存备注</button></form><p v-else>{{ selected.link.note }}</p><button v-if="selected.present" :disabled="busy || !!pending" class="button-danger" @click="confirm('unlink')">仅解除关联</button></section><details><summary>固定版本、哈希及关联身份</summary><pre>{{ pretty(selected.link) }}</pre><p class="small">当前修订：{{ selected.latest_revision ?? '已解绑' }}</p></details></template>
      <template v-else-if="chosen"><div class="ui-card-subtle"><div class="ui-pill-list"><span class="ui-pill ui-pill-accent">{{ targetKinds[chosen.type] }}</span><span class="ui-pill ui-pill-neutral">{{ chosen.state }}</span></div><h2 class="ui-card-title">{{ chosen.label }}</h2><div><RouterLink v-if="chosen.available" :to="resultPath(chosen)" class="ui-pill ui-pill-accent">打开完整结果 →</RouterLink></div><p class="small muted">先在中间面板选择原文证据，核对后再确认建立用户引用。</p></div></template><div v-else class="ui-empty-card"><div class="ui-empty-icon" aria-hidden="true"><svg viewBox="0 0 24 24"><path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71" /><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71" /></svg></div><h3>选择结果或关联核对两端</h3><p>点击左侧或列表中的任意关联记录，可在此对照查看原始数据源、固定文献版本与用户备注。</p></div>
      <section v-if="selected || chosen" class="project-section"><details><summary>结果版本、软件与时间</summary><pre>{{ pretty(selected?.target || chosen) }}</pre></details><h3>原结果中记录的来源</h3><article v-for="(source,index) in (selected?.target.sources || chosen?.sources || [])" :key="index" class="overview-source ui-card-subtle"><div class="ui-pill-list"><span class="ui-pill" :class="categoryPill(source.category)">{{ categories[source.category] }}</span><span class="ui-pill ui-pill-neutral">{{ source.provider }}</span><span class="ui-pill" :class="source.status === 'success' ? 'ui-pill-success' : 'ui-pill-warning'">{{ source.status }}</span></div><time v-if="source.retrieved_at" class="small muted">UTC {{ source.retrieved_at }}</time><div><a v-if="source.url && safeLink(source.url)" :href="safeLink(source.url)!" class="ui-pill ui-pill-accent" target="_blank" rel="noopener noreferrer">打开原始来源 ↗</a><p v-else-if="source.url" class="small">{{ source.url }}</p></div></article></section>
</div>
    </aside>
    <dialog ref="dialog" class="project-dialog" @close="action=''">
      <div class="dialog-header">
        <div class="dialog-header-copy"><h2>{{ action==='unlink' ? '只解除此关联？' : '确认建立用户引用？' }}</h2></div>
        <button type="button" class="dialog-close" aria-label="关闭" :disabled="busy" @click="dialog?.close()"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="m6 6 12 12M6 18 18 6" /></svg></button>
      </div>
      <p v-if="action==='unlink'">仅删除关联记录，保留原结果、文档、证据与备注之外的原始数据。原创建请求的重放不会重新建立关联。</p>
      <template v-else><p>项目结果：{{ confirmationTarget }}</p><p>文献：{{ confirmationEvidence?.evidence.title || confirmationEvidence?.evidence.filename }} · {{ confirmationEvidence?.evidence.page ? `物理页${confirmationEvidence.evidence.page}` : `行${confirmationEvidence?.evidence.line_start}—${confirmationEvidence?.evidence.line_end}` }}</p><pre>{{ confirmationEvidence?.text }}</pre><p>用户备注：{{ confirmationRequest?.note || '未填写' }}</p><p>这只表示用户选择的引用，不表示支持、反驳、因果证明或成员判定；不会发送文献给模型，也不改写原回答。</p></template>
      <div class="project-actions"><button type="button" @click="dialog?.close()">取消</button><button type="button" :class="action==='unlink' ? 'button-danger' : 'button-primary'" :disabled="busy" @click="confirmed">{{ action==='unlink' ? '确认只解除关联' : '确认关联这两项' }}</button></div>
    </dialog>
  </div>
</template>
