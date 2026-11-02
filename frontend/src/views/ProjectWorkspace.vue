<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api, ApiError } from '../api'
import { exportProject, importProject, projectsApi } from '../api/projects'
import type { Comparison, Conversation, ConversationDetail, Project, ProjectDetail, RerunRequest, Snapshot, Turn } from '../types'
import ResultPanel from '../components/ResultPanel.vue'

const route = useRoute(), router = useRouter()
const projects = ref<Project[]>([]), conversations = ref<Conversation[]>([]), memberships = ref<Record<string, string>>({})
const current = ref<ProjectDetail | null>(null), snapshot = ref<Snapshot | null>(null)
const busy = ref(false), error = ref(''), errorCode = ref(''), message = ref('')
const newName = ref(''), newDescription = ref(''), editName = ref(''), editDescription = ref('')
const moveId = ref(''), saveConversation = ref(''), saveTurn = ref(''), snapshotName = ref(''), renameName = ref('')
const conversationDetail = ref<ConversationDetail | null>(null)
const leftId = ref(''), rightId = ref(''), matchIds = ref(false), comparison = ref<Comparison | null>(null)
const tool = ref(''), dialog = ref<HTMLDialogElement | null>(null), action = ref<'project-delete' | 'snapshot-delete' | 'rerun' | 'archive' | ''>('')
const archiveFormat = ref<1 | 2 | 3 | 4 | 5>(5), knowledgeMode = ref<'full' | 'metadata'>('metadata')
const mobilePanel = ref('project'), pending = ref<{ project: string; snapshot: string; payload: RerunRequest } | null>(null)
let navigation = 0, selection = 0, conversationSelection = 0
const unassigned = computed(() => conversations.value.filter(c => !memberships.value[c.id]))
const members = computed(() => conversations.value.filter(c => memberships.value[c.id] === current.value?.id))
const movable = computed(() => conversations.value.filter(c => memberships.value[c.id] !== current.value?.id))
const deliverable = computed(() => conversationDetail.value?.turns.filter(t => t.response_status) || [])
const tools = computed(() => {
  const response = snapshot.value?.response
  if (!response) return []
  return [
    ...(response.results || []).map((r, i) => ({ value: `simbad:${i}`, label: `SIMBAD ${r.object_name}`, parameters: { object_name: r.object_name }, source: r.source })),
    ...(response.literature_results || []).map((r, i) => ({ value: `ads:${i}`, label: `ADS 第${i + 1}次检索`, parameters: { query: r.query, rows: r.rows, start: r.start, sort: r.sort }, source: r.source })),
    ...(response.gaia_results || []).map((r, i) => ({ value: `gaia:${i}`, label: `Gaia DR3 第${i + 1}次查询`, parameters: r.query, source: r.source })),
  ]
})
const selectedTool = computed(() => tools.value.find(t => t.value === tool.value))
const snapshotTurn = computed<Turn | null>(() => snapshot.value ? {
  conversation_id: snapshot.value.project_id, turn_id: snapshot.value.id, client_request_id: snapshot.value.id,
  revision: 1, message: snapshot.value.name, received_at: snapshot.value.created_at,
  execution_status: 'completed', response: snapshot.value.response,
} : null)
const format = (value: unknown) => JSON.stringify(value, null, 2)
function report(e: unknown) { error.value = e instanceof Error ? e.message : '操作失败，请刷新核对状态。'; errorCode.value = e instanceof ApiError ? e.code : 'project_operation_failed' }
async function refresh() {
  const token = ++navigation, id = typeof route.params.projectId === 'string' ? route.params.projectId : ''
  const [list, all, mapping, detail] = await Promise.all([projectsApi.list(), api.list(), projectsApi.memberships(), id ? projectsApi.detail(id) : Promise.resolve(null)])
  if (token !== navigation) return
  projects.value = list; conversations.value = all; memberships.value = mapping; current.value = detail
  editName.value = detail?.name || ''; editDescription.value = detail?.description || ''
  if (detail && typeof route.query.snapshot === 'string' && detail.snapshots.some(s => s.id === route.query.snapshot)) await viewSnapshot(route.query.snapshot, false)
}
async function act(task: () => Promise<unknown>) {
  if (busy.value) return
  busy.value = true; error.value = ''; errorCode.value = ''; message.value = ''
  try { await task(); await refresh() } catch (e) { report(e) } finally { busy.value = false }
}
async function downloadArchive() { const p = current.value; if (!p) return; if (archiveFormat.value>=3 && knowledgeMode.value==='full') await openConfirm('archive'); else await act(() => exportProject(p, archiveFormat.value, knowledgeMode.value)) }
async function updateProject() { const p = current.value; if (p) await act(() => projectsApi.update(p, editName.value.trim(), editDescription.value)) }
async function renameSnapshot() { const p = current.value, s = snapshot.value; if (p && s) await act(() => projectsApi.renameSnapshot(p, s.id, renameName.value.trim())) }
async function create() { await act(async () => { const p = await projectsApi.create(newName.value.trim(), newDescription.value); newName.value = ''; newDescription.value = ''; await router.push(`/projects/${p.id}`) }) }
async function move(id: string, remove = false) {
  const p = current.value, c = conversations.value.find(c => c.id === id)
  if (!p || !c) return
  const sourceId = memberships.value[id] || null
  await act(async () => {
    const source = sourceId && sourceId !== p.id ? await projectsApi.detail(sourceId) : null
    await projectsApi.move(p.id, id, { expected_revision: p.revision, expected_conversation_revision: c.revision, expected_metadata_revision: c.metadata_revision,
      expected_source_project_id: sourceId, expected_source_revision: source?.revision ?? null }, remove)
    moveId.value = ''; conversationDetail.value = null; saveConversation.value = ''; saveTurn.value = ''
  })
}
watch(saveConversation, async id => {
  const token = ++conversationSelection; conversationDetail.value = null; saveTurn.value = ''
  if (!id) return
  try { const c = await api.detail(id); if (token === conversationSelection) { conversationDetail.value = c; saveTurn.value = c.turns.find(t => t.response_status)?.turn_id || '' } } catch (e) { if (token === conversationSelection) report(e) }
})
async function save() {
  const p = current.value
  if (!p) return
  await act(async () => { const s = await projectsApi.save(p, saveConversation.value, saveTurn.value, snapshotName.value.trim()); snapshotName.value = ''; await router.replace({ query: { snapshot: s.id } }); message.value = '已保存完整快照，原响应不会随重跑改变。' })
}
async function viewSnapshot(id: string, changeUrl = true) {
  const p = current.value, token = ++selection
  if (!p) return
  try {
    if (changeUrl) await router.replace({ query: { snapshot: id } })
    const value = await projectsApi.snapshot(p.id, id)
    if (token !== selection || current.value?.id !== p.id) return
    snapshot.value = value; renameName.value = value.name; tool.value = ''; mobilePanel.value = 'results'
  } catch (e) { if (token === selection) report(e) }
}
async function openConfirm(kind: typeof action.value) { action.value = kind; await nextTick(); dialog.value?.showModal() }
async function confirm() {
  const kind = action.value, p = current.value, s = snapshot.value
  if (!p) return
  dialog.value?.close(); action.value = ''
  if (kind === 'archive') await act(() => exportProject(p, archiveFormat.value, 'full', true))
  else if (kind === 'project-delete') await act(async () => { await projectsApi.delete(p); snapshot.value = null; await router.push('/projects') })
  else if (kind === 'snapshot-delete' && s) await act(async () => { await projectsApi.deleteSnapshot(p, s.id); snapshot.value = null; await router.replace({ query: {} }) })
  else if (kind === 'rerun' && s && selectedTool.value) {
    const [family, index] = tool.value.split(':')
    pending.value = { project: p.id, snapshot: s.id, payload: { family: family as RerunRequest['family'], result_index: Number(index), expected_revision: p.revision, client_request_id: crypto.randomUUID(), confirmed: true } }
    await executePending()
  }
}
async function executePending() {
  const item = pending.value
  if (!item) return
  await act(async () => {
    try {
      const result = await projectsApi.rerun(item.project, item.snapshot, item.payload)
      pending.value = null
      message.value = `重跑执行状态：${result.state}；数据状态：${result.response_status || "尚无响应"}。${result.snapshot_id ? "结果已独立保存，未调用模型。" : "本次没有可交付快照，请核对记录。"}`
      if (current.value?.id === item.project && result.snapshot_id) await router.replace({ query: { snapshot: result.snapshot_id } })
    } catch (e) { if (!(e instanceof ApiError) || e.status !== 0) pending.value = null; throw e }
  })
}
async function compare() {
  const p = current.value
  if (!p) return
  await act(async () => { const result = await projectsApi.compare(p.id, leftId.value, rightId.value, matchIds.value); if (current.value?.id === p.id) comparison.value = result })
}
async function upload(event: Event) {
  const input = event.target as HTMLInputElement, file = input.files?.[0]
  if (!file) return
  await act(async () => { const result = await importProject(file); await router.push(`/projects/${result.project.id}`); message.value = '已恢复为独立项目；归档哈希只证明包内一致性，来源未经认证。' })
  input.value = ''
}
watch(() => route.params.projectId, () => {
  dialog.value?.close(); action.value = ''
  selection++; conversationSelection++; snapshot.value = null; comparison.value = null; current.value = null
  leftId.value = ''; rightId.value = ''; saveConversation.value = ''; conversationDetail.value = null
  mobilePanel.value = 'project'; error.value = ''; void refresh().catch(report)
}, { immediate: true })
</script>

<template>
  <div class="project-workspace" :data-panel="mobilePanel">
    <header class="topbar"><RouterLink class="brand" to="/"><span class="brand-mark" aria-hidden="true">✳</span><b>AstroAgent</b><span class="version">1.0</span></RouterLink><span class="topbar-caption">项目与查询归档</span><RouterLink class="project-link" to="/">返回对话 ↗</RouterLink></header>
    <nav class="project-mobile" aria-label="项目面板"><button @click="mobilePanel='project'">项目记录</button><button @click="mobilePanel='results'">快照结果</button></nav>
    <aside class="project-sidebar" aria-label="项目列表">
      <p class="eyebrow">RESEARCH PROJECTS · {{ projects.length }}/20</p>
      <RouterLink v-for="p in projects" :key="p.id" :to="`/projects/${p.id}`" class="project-item" :class="{selected:p.id===current?.id}"><b>{{ p.name }}</b><small>{{ p.provenance === 'imported_unverified' ? '导入 · 未认证' : '本机项目' }} · r{{ p.revision }}</small></RouterLink>
      <form class="project-form" @submit.prevent="create"><h2>新建项目</h2><label for="new-project-name">项目名称</label><input id="new-project-name" v-model="newName" maxlength="100" required><label for="new-project-description">项目说明（可选）</label><textarea id="new-project-description" v-model="newDescription" maxlength="2000" rows="2"></textarea><button class="button-primary" :disabled="busy || !newName.trim()">创建项目</button></form>
      <label class="import-control">导入项目 ZIP<input type="file" accept=".zip,application/zip" aria-label="导入项目 ZIP" :disabled="busy" @change="upload"></label><p class="small muted">最多32 MiB；恢复为新副本。</p>
      <div class="unassigned"><h3>未归档会话 · {{ unassigned.length }}</h3><RouterLink v-for="c in unassigned" :key="c.id" :to="`/conversations/${c.id}`">{{ c.title }}</RouterLink></div>
    </aside>
    <main class="project-main">
      <div v-if="error" class="notice danger" role="alert"><p>{{ error }}</p><code>{{ errorCode }}</code><button :disabled="busy" @click="act(refresh)">刷新核对状态</button></div>
      <p v-if="message" class="notice" role="status">{{ message }}</p>
      <p v-if="busy" class="processing" role="status">正在处理，请稍候。不会自动重复提交。</p>
      <div v-if="pending" class="notice"><p>重跑请求尚未确认。先刷新项目核对记录，断线不会取消后台查询。</p><button :disabled="busy" @click="executePending">用原请求编号核对重跑</button></div>
      <template v-if="current">
        <header class="project-heading"><p class="eyebrow">PROJECT / r{{ current.revision }}</p><h1>{{ current.name }}</h1><p>{{ current.description || '暂无项目说明' }}</p><code>{{ current.id }}</code><p v-if="current.provenance==='imported_unverified'" class="notice">导入来源未经认证。哈希只验证包内完整性；历史数据不会因导入而重新查询。</p><div class="project-actions"><RouterLink :to="`/projects/${current.id}/overview`">项目总览与关联 · {{ current.link_count }} →</RouterLink><RouterLink :to="`/projects/${current.id}/rag`">文献知识问答 · {{ current.rag_answer_count }} →</RouterLink><RouterLink :to="`/projects/${current.id}/knowledge`">本地知识库 · {{ current.document_count }} →</RouterLink><RouterLink :to="`/projects/${current.id}/workflows`">科研流程 · {{ current.workflow_count }} →</RouterLink><label class="small">归档格式<select v-model="archiveFormat" aria-label="项目归档格式"><option :value="5">格式5（含知识问答）</option><option :value="4" :disabled="!!current?.rag_answer_count || !!current?.rag_request_count">V0.9格式4（含显式关联）</option><option :value="3" :disabled="current.link_count > 0 || current.link_request_count > 0 || current.rag_request_count > 0">V0.8格式3（无关联历史）</option><option :value="2" :disabled="current.document_count > 0 || current.knowledge_evidence_count > 0 || current.link_count > 0 || current.link_request_count > 0 || current.rag_request_count > 0">V0.7格式2（无知识库）</option><option :value="1" :disabled="current.workflow_count > 0 || current.document_count > 0 || current.knowledge_evidence_count > 0 || current.link_count > 0 || current.link_request_count > 0 || current.rag_request_count > 0">V0.6格式1（仅无流程项目）</option></select></label><label v-if="archiveFormat>=3" class="small">文献原文<select v-model="knowledgeMode"><option value="metadata">仅元数据（保留标题、检索词及项目记录）</option><option value="full">完整备份（含全部原文）</option></select></label><button :disabled="busy" @click="downloadArchive">导出项目 ZIP</button><button :disabled="busy" @click="openConfirm('project-delete')">删除项目</button><button :disabled="busy" @click="act(refresh)">刷新项目</button></div></header>
        <details class="project-section"><summary>修改项目名称与说明</summary><form class="project-form" @submit.prevent="updateProject"><label for="edit-project-name">修改项目名称</label><input id="edit-project-name" v-model="editName" maxlength="100"><label for="edit-project-description">修改项目说明</label><textarea id="edit-project-description" v-model="editDescription" maxlength="2000"></textarea><button :disabled="busy || !editName.trim()">保存项目修改</button></form></details>
        <section class="project-section"><h2>项目会话 <span class="small muted">{{ members.length }}/20</span></h2><div v-for="c in members" :key="c.id" class="project-row"><RouterLink :to="`/conversations/${c.id}`">{{ c.title }} <small>· {{ c.revision }}轮</small></RouterLink><button :disabled="busy" @click="move(c.id,true)">移出项目</button></div><p v-if="!members.length" class="small muted">选择已有会话加入项目，或先返回对话创建会话。</p><form class="inline-form" @submit.prevent="move(moveId)"><label class="sr-only" for="move-conversation">选择要加入的会话</label><select id="move-conversation" v-model="moveId"><option value="">选择会话加入 / 移动</option><option v-for="c in movable" :key="c.id" :value="c.id">{{ c.title }}{{ memberships[c.id] ? '（从其他项目移动）' : '（未归档）' }}</option></select><button :disabled="busy || !moveId">加入项目</button></form></section>
        <section class="project-section"><h2>保存命名快照</h2><form class="project-form" @submit.prevent="save"><label for="save-conversation">项目内会话</label><select id="save-conversation" v-model="saveConversation"><option value="">选择会话</option><option v-for="c in members" :key="c.id" :value="c.id">{{ c.title }}</option></select><label for="save-turn">完整响应轮次</label><select id="save-turn" v-model="saveTurn"><option value="">选择可交付轮次</option><option v-for="t in deliverable" :key="t.turn_id" :value="t.turn_id">第{{ t.revision }}轮 · {{ t.response_status }} · {{ t.message.slice(0,50) }}</option></select><label for="snapshot-name">快照名称</label><input id="snapshot-name" v-model="snapshotName" maxlength="100"><button :disabled="busy || !saveTurn || !snapshotName.trim()">保存完整快照</button></form></section>
        <section class="project-section"><h2>命名快照 <span class="small muted">{{ current.snapshots.length }}/100</span></h2><p class="small muted">保存完整交付响应，比较与重跑均保留旧结果。</p><div v-for="s in current.snapshots" :key="s.id" class="snapshot-row" :class="{selected:snapshot?.id===s.id}"><button :aria-label="`查看快照 ${s.name}`" @click="viewSnapshot(s.id)"><b>{{ s.name }}</b><span class="tag">{{ s.status }}</span><small>{{ s.created_at }} · {{ s.id.slice(0,8) }}</small><small v-if="s.provenance==='imported_unverified'">导入 · 未认证</small></button></div><p v-if="!current.snapshots.length" class="small muted">尚无快照。</p></section>
        <section v-if="snapshot" class="project-section"><h2>当前快照：{{ snapshot.name }}</h2><RouterLink :to="{path:`/projects/${snapshot.project_id}/overview`,query:{target_type:'snapshot',target_id:snapshot.id}}">为此快照关联本地原文证据 →</RouterLink><code>SHA-256 {{ snapshot.sha256 }}</code><p v-if="!snapshot.conversation_id" class="small muted">原会话已移出归档范围或删除；完整响应副本仍保留。</p><form class="inline-form" @submit.prevent="renameSnapshot"><label class="sr-only" for="rename-snapshot">修改快照名称</label><input id="rename-snapshot" v-model="renameName" maxlength="100"><button :disabled="busy || !renameName.trim()">快照改名</button><button type="button" :disabled="busy" @click="openConfirm('snapshot-delete')">删除快照</button></form><details><summary>原始来源与软件版本</summary><pre>{{ format({origin:snapshot.origin,software:snapshot.software,provenance:snapshot.provenance}) }}</pre></details><label for="rerun-tool">选择单条工具查询重跑</label><select id="rerun-tool" v-model="tool"><option value="">选择查询，先核对参数</option><option v-for="t in tools" :key="t.value" :value="t.value">{{ t.label }}</option></select><template v-if="selectedTool"><pre>{{ format({parameters:selectedTool.parameters,source:selectedTool.source}) }}</pre><p v-if="tool.startsWith('gaia:')" class="notice">Gaia 重跑沿用已记录的实际坐标与参数，不重新解析天体名称。历史来源时间见上方；需要重新解析时请返回对话独立查询 SIMBAD。</p><button class="button-primary" :disabled="busy || !!pending" @click="openConfirm('rerun')">核对并重跑单条查询</button></template></section>
        <section class="project-section"><h2>比较两份快照</h2><div class="compare-selectors"><label>左侧快照<select v-model="leftId"><option value="">选择快照</option><option v-for="s in current.snapshots" :key="s.id" :value="s.id">{{ s.name }} · {{ s.id.slice(0,8) }}</option></select></label><label>右侧快照<select v-model="rightId"><option value="">选择快照</option><option v-for="s in current.snapshots" :key="s.id" :value="s.id">{{ s.name }} · {{ s.id.slice(0,8) }}</option></select></label></div><label class="match-identifiers"><input v-model="matchIds" type="checkbox">按精确 source_id / bibcode 比较交付编号</label><button :disabled="busy || !leftId || !rightId" @click="compare">比较已存快照</button><div v-if="comparison" class="comparison"><p v-for="warning in comparison.warnings" :key="warning" class="notice">{{ warning }}</p><div class="comparison-columns"><details open><summary>左侧条件、状态与来源</summary><pre>{{ format(comparison.left) }}</pre></details><details open><summary>右侧条件、状态与来源</summary><pre>{{ format(comparison.right) }}</pre></details></div><details open><summary>结构化字段差异（{{ comparison.differences.length }}）</summary><pre>{{ format(comparison.differences) }}</pre></details><details><summary>交集与独有编号</summary><pre>{{ format(comparison.identifiers) }}</pre></details></div></section>
        <section class="project-section"><h2>直接重跑记录</h2><article v-for="r in current.reruns" :key="r.id" class="rerun-row"><span class="tag">{{ r.state }}</span> {{ r.family }} · 数据状态 {{ r.response_status || '尚无响应' }} · <time>{{ r.created_at }}</time><p v-if="r.error" class="notice danger">{{ r.error.message }} · {{ r.error.code }}</p><button v-if="r.snapshot_id" @click="viewSnapshot(r.snapshot_id)">查看重跑新快照</button><details><summary>实际参数与记录编号</summary><pre>{{ format(r) }}</pre></details></article><p v-if="!current.reruns.length" class="small muted">尚未执行直接重跑。不会自动重试或调用模型。</p></section>
      </template>
      <div v-else class="project-empty"><p class="eyebrow">PRESERVE / COMPARE / REVISIT</p><h1>把查询留成可核对的项目记录</h1><p>创建或选择项目，组织会话、保存完整快照，再比较、显式重跑或导出归档。</p><p class="small muted">旧会话保留在“未归档会话”中。</p></div>
    </main>
    <ResultPanel :turn="snapshotTurn" :historical="!!snapshot" :heading="snapshot?.name || '选择一份快照'" :artifact-path="snapshot ? `/api/v1/projects/${snapshot.project_id}/snapshots/${snapshot.id}/artifacts` : undefined" />
    <dialog ref="dialog" class="modal project-dialog" @close="action=''" @cancel="action=''"><form @submit.prevent="confirm"><h2>{{ action==='archive' ? '导出含文献原文的完整备份？' : action==='rerun' ? '确认执行这条工具查询？' : action==='project-delete' ? '删除这个项目？' : '删除这份命名快照？' }}</h2><template v-if="action==='archive'"><p>将复制 {{ current?.document_count || 0 }} 份文档、{{ current?.document_version_count || 0 }} 个版本，原文件合计 {{ current?.document_bytes || 0 }} 字节，连同项目记录写入ZIP。文件将包含你的文献原文，请自行管理下载副本；这不是仅元数据备份。</p></template><template v-else-if="action==='rerun'"><p>将按下列参数访问真实数据源，保存独立轮次和快照。旧响应不覆盖；本操作不调用语言模型，断线不代表取消。</p><pre>{{ format(selectedTool) }}</pre></template><p v-else-if="action==='project-delete'">将删除此项目、{{ current?.rag_answer_count || 0 }} 条文献问答及请求历史、命名快照、重跑关系，以及 {{ current?.workflow_count || 0 }} 次科研流程及其专属输出。以及 {{ current?.link_count || 0 }} 条用户关联；知识库原文、所有版本和索引也将删除，相关引用失效；会话及其轮次保留并移至未归档；已下载文件和旧备份保留。</p><p v-else>只删除这份快照，原会话和轮次保留。</p><div class="modal-actions"><button type="button" @click="dialog?.close()">取消</button><button :disabled="busy" class="button-primary" type="submit">{{ action==='archive' ? '确认导出全部原文' : action==='rerun' ? '确认访问数据源并重跑' : '确认删除' }}</button></div></form></dialog>
  </div>
</template>
