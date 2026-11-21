<script setup lang="ts">
import MarkdownAnswer from '../components/MarkdownAnswer'
import ModelSelector from '../components/ModelSelector.vue'
import { useModels } from '../stores/models'
import WorkspaceHeader from '../components/WorkspaceHeader.vue'
import WorkspacePaneHeader from '../components/WorkspacePaneHeader.vue'
import WorkspaceSpaceBar from '../components/WorkspaceSpaceBar.vue'
import PanelSwitcher from '../components/PanelSwitcher.vue'
import { computed, nextTick, onUnmounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ApiError } from '../api'
import { knowledgeApi } from '../api/knowledge'
import { projectsApi } from '../api/projects'
import { useProjects } from '../stores/projects'
import { ragApi } from '../api/rag'
import type { DocumentVersion, GenerateRequest, IndexRequest, KnowledgeDocument, Preview, ProjectDetail, RagAnswerView, RagPage, RagStatus } from '../types'

const route = useRoute()
const projectsStore = useProjects()
const resolvedProjectId = ref('')
const models = useModels()
const project = ref<ProjectDetail | null>(null), documents = ref<KnowledgeDocument[]>([]), state = ref<RagStatus | null>(null), history = ref<RagPage | null>(null)
const preview = ref<Preview | null>(null), selected = ref<RagAnswerView | null>(null)
const question = ref(''), documentIds = ref<string[]>([]), versionIds = ref<string[]>([]), historyIds = ref<string[]>([])
const versions = ref<Record<string, DocumentVersion[]>>({}), error = ref(''), message = ref(''), busy = ref(false), panel = ref('question')
const retrieving = ref(false), retrievalSeconds = ref(0)
const dialog = ref<HTMLDialogElement | null>(null), action = ref<'generate' | 'index' | 'delete' | 'index-delete' | ''>('')
const frozen = ref<Preview | null>(null), frozenId = ref('')
const pending = ref<GenerateRequest | null>(null), indexPending = ref<IndexRequest | null>(null)
let navigation = 0
let statusTimer: ReturnType<typeof setInterval> | undefined
let retrievalTimer: ReturnType<typeof setInterval> | undefined
watch(busy, value => {
  if (statusTimer) clearInterval(statusTimer)
  if (value && indexPending.value) {
    const projectId = id()
    statusTimer = setInterval(() => { void ragApi.status(projectId).then(value => { if(projectId===id())state.value=value }).catch(() => { /* Keep the original pending request; no automatic mutation retry. */ }) },2000)
  }
})
onUnmounted(() => { if(statusTimer)clearInterval(statusTimer);if(retrievalTimer)clearInterval(retrievalTimer);navigation++ })
const labels: Record<string, string> = { running:'正在处理', pending:'待处理', ready:'可用', stale:'来源已变化', failed:'失败', interrupted:'已中断', completed:'已保存模型回答', insufficient_evidence:'证据不足' }
function formatBytes(value?: number | null) {
  if (value == null) return '0 B'
  if (value < 1024) return `${value} B`
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KiB`
  return `${(value / (1024 * 1024)).toFixed(2)} MiB`
}
const vectorPercent = computed(() => {
  const used = state.value?.vector_used_bytes || 0
  const budget = state.value?.vector_budget_bytes || 0
  return budget > 0 ? Math.min(100, Math.round((used / budget) * 100)) : 0
})
const id = () => resolvedProjectId.value || (typeof route.params.projectId === 'string' ? route.params.projectId : '')
const knowledgeBase = computed(() => (typeof route.params.projectId === 'string' && route.params.projectId) ? `/projects/${id()}/knowledge` : '/knowledge')
const currentModel = computed(() => models.modelFor(`rag:${id()}`))
function changeModel(model: string) {
  models.select(`rag:${id()}`, model)
  if (preview.value && preview.value.model !== model) {
    preview.value = null; panel.value = 'question'
    message.value = '回答模型已切换，请重新预览并确认；所选历史问答和文档范围已保留。'
  }
}
const storageKey = (project: string, kind: string) => `astroagent.rag.${kind}.${project}`
function store(kind: 'answer' | 'index', value: GenerateRequest | IndexRequest | null, project = id()) {
  if (project === id()) { if (kind === 'answer') pending.value = value as GenerateRequest | null; else indexPending.value = value as IndexRequest | null }
  try { if (value) sessionStorage.setItem(storageKey(project,kind),JSON.stringify(value)); else sessionStorage.removeItem(storageKey(project,kind)) } catch { message.value = '浏览器无法保留请求编号，请保留本页核对。' }
}
function restore<T>(kind: string): T | null { try { return JSON.parse(sessionStorage.getItem(storageKey(id(),kind)) || 'null') as T | null } catch { return null } }
function report(e: unknown) { error.value = e instanceof Error ? e.message : '操作状态未确认，请先刷新记录。' }
async function refresh() {
  const token = ++navigation
  const routePid = typeof route.params.projectId === 'string' ? route.params.projectId : ''
  await projectsStore.load()
  const projectId = routePid || (await projectsStore.ensureDefault()).id
  if (token !== navigation) return
  resolvedProjectId.value = projectId
  pending.value = restore<GenerateRequest>('answer')
  indexPending.value = restore<IndexRequest>('index')
  const values = await Promise.all([projectsApi.detail(projectId), knowledgeApi.list(projectId), ragApi.status(projectId), ragApi.history(projectId)])
  if (token !== navigation || projectId !== id()) return
  project.value = values[0]; documents.value = values[1]; state.value = values[2]; history.value = values[3]
}
async function act(task: () => Promise<void>) { if (busy.value) return; busy.value = true; error.value = ''; message.value = ''; try { await task() } catch(e) { report(e) } finally { busy.value = false } }
async function loadVersions(document: string) { const projectId=id(); await act(async () => { const value = await knowledgeApi.detail(projectId,document); if(projectId===id())versions.value = {...versions.value,[document]:value.versions} }) }
async function retrieve() {
  const projectId = id()
  await act(async () => {
    preview.value = null
    retrieving.value = true
    retrievalSeconds.value = 0
    const started = Date.now()
    retrievalTimer = setInterval(() => { retrievalSeconds.value = Math.floor((Date.now() - started) / 1000) }, 1000)
    try {
      const value = await ragApi.preview(projectId,{question:question.value,model:currentModel.value || undefined,document_ids:documentIds.value,version_ids:versionIds.value,history_ids:historyIds.value})
      if (projectId !== id()) return
      preview.value = value; selected.value = null; panel.value = 'evidence'
      await refresh()
    } finally {
      if (retrievalTimer) clearInterval(retrievalTimer)
      retrievalTimer = undefined
      retrieving.value = false
    }
  })
}
async function confirm(kind: typeof action.value, identifier = '') {
  if (busy.value) return
  if (kind === 'generate' && !preview.value?.evidence.length) return
  frozen.value = preview.value ? JSON.parse(JSON.stringify(preview.value)) as Preview : null; frozenId.value = identifier; action.value = kind
  await nextTick(); dialog.value?.showModal()
}
async function runPending() {
  const request = pending.value, projectId = id()
  if (!request) return
  await act(async () => {
    try { const value = await ragApi.generate(projectId,request); store('answer',null,projectId); if(projectId!==id())return; selected.value=value; preview.value=null; panel.value='answer'; message.value='已返回该编号的保存状态。模型解释需要逐条核对原文。'; await refresh() }
    catch(e) { if(e instanceof ApiError && e.status>=400 && e.status<500)store('answer',null,projectId); throw e }
  })
}
async function buildPending() {
  const request = indexPending.value, projectId = id()
  if (!request) return
  await act(async () => { try { const value=await ragApi.build(projectId,request); store('index',null,projectId); if(projectId!==id())return; message.value=`索引：${labels[value.state] || value.state}，${value.processed}/${value.total}段。${value.error || ''}`; await refresh() } catch(e) { if(e instanceof ApiError && e.status>=400 && e.status<500)store('index',null,projectId); throw e } })
}
async function confirmed() {
  const kind=action.value, value=frozen.value, identifier=frozenId.value, projectId=id()
  dialog.value?.close(); action.value=''
  if(kind==='generate' && value) { store('answer',{client_request_id:crypto.randomUUID(),preview_id:value.id,confirmation_token:value.confirmation_token,confirmed:true},projectId); await runPending() }
  else if(kind==='index' && project.value) { store('index',{client_request_id:crypto.randomUUID(),expected_revision:project.value.revision,confirmed:true},projectId); await buildPending() }
  else if(kind==='delete') await act(async()=>{await ragApi.delete(projectId,identifier);if(projectId!==id())return;selected.value=null;historyIds.value=historyIds.value.filter(v=>v!==identifier);await refresh();message.value='已删除问答，原文保留；原请求不会再次生成。'})
  else if(kind==='index-delete') await act(async()=>{await ragApi.deleteIndex(projectId,identifier);if(projectId!==id())return;await refresh();message.value='已清除此索引代，原文件与问答保留。'})
}
async function inspect(identifier: string) { const projectId=id(); await act(async()=>{const value=await ragApi.detail(projectId,identifier);if(projectId===id()){selected.value=value;panel.value='answer'}}) }
async function more() { const cursor=history.value?.next_cursor, projectId=id(); if(cursor)await act(async()=>{const value=await ragApi.history(projectId,cursor);if(projectId===id())history.value=value}) }
async function cancelPreview() { const value=preview.value, projectId=id(); if(value) await act(async()=>{await ragApi.discard(projectId,value.id);if(projectId===id()){preview.value=null;panel.value='question';message.value='已取消预览，未向回答服务发送内容；可直接修改问题重新检索。'}}) }
watch(()=>route.fullPath,()=>{navigation++;resolvedProjectId.value=typeof route.params.projectId==='string'?route.params.projectId:'';project.value=null;documents.value=[];state.value=null;history.value=null;preview.value=null;selected.value=null;frozen.value=null;question.value='';documentIds.value=[];versionIds.value=[];historyIds.value=[];versions.value={};error.value='';message.value='';dialog.value?.close();action.value='';pending.value=id()?restore<GenerateRequest>('answer'):null;indexPending.value=id()?restore<IndexRequest>('index'):null;void refresh().catch(report)},{immediate:true})
</script>

<template>
  <div class="rag-workspace workspace-panes" :data-panel="panel">
    <WorkspaceHeader title="文献知识问答" />
    <PanelSwitcher v-model="panel" label="问答面板" :options="[{ value: 'question', label: '问题与历史' }, { value: 'evidence', label: '本次发送预览' }, { value: 'answer', label: '回答与原文' }]" />
    <div v-if="error || message || busy" class="rag-notices"><p v-if="error" class="notice danger" role="alert">{{ error }}</p><p v-if="message" class="notice info" role="status">{{ message }}</p><p v-if="busy" class="notice info" role="status">{{ retrieving ? `正在本机检索，已等待 ${retrievalSeconds} 秒，请勿重复提交。` : '正在处理。断线后请使用原请求编号核对；不自动重发新请求。' }}</p></div>
    <aside class="rag-question">
      <WorkspacePaneHeader title="文献问答" :level="1" />
      <div class="workspace-pane-body">
<div class="compact-space-bar"><WorkspaceSpaceBar section="rag" :project-id="id()" /></div>
<p class="workspace-section-label">问题与文献范围</p><p class="small muted">默认只做本机检索。你确认具体片段与服务后才发送；模型解释与原文分开。</p><div v-if="state && !state.active_index_id" class="rag-index-callout" role="status"><p><strong>当前为纯词法检索模式</strong>（所有关键词须同时出现在原文中）。{{ documents.length ? '建议先构建本地语义索引，以支持自然语言提问与高召回检索。' : '上传参考文献后可构建本地语义索引以支持自然语言提问。' }}</p><div class="project-actions"><button type="button" class="button-primary" :disabled="busy || !!indexPending || !state.model_configured || !documents.length" @click="confirm('index')">构建本地语义索引</button><span v-if="!state.model_configured" class="small muted">尚未配置本地嵌入模型</span></div></div><div v-if="pending" class="notice"><p>上次生成状态待确认，保留原编号：</p><code>{{ pending.client_request_id }}</code><button :disabled="busy" @click="runPending">按原编号核对（尚未接收时会执行一次）</button></div><div v-if="indexPending" class="notice"><p>索引请求待确认：{{ indexPending.client_request_id }}</p><button :disabled="busy" @click="buildPending">核对原索引请求</button></div>
      <ModelSelector :model-value="currentModel" :disabled="busy || !!pending" @update:model-value="changeModel" /><form class="project-form" @submit.prevent="retrieve"><label for="rag-question">本次问题</label><textarea id="rag-question" v-model="question" required maxlength="1000" rows="4" placeholder="输入要依据本项目文献回答的完整问题"></textarea><p class="small muted">单个英文词或编号需要原文直接匹配；没有匹配时，请核对写法或补充完整问题。</p><fieldset><legend>文档范围（不选表示全部当前版本）</legend><label v-for="doc in documents" :key="doc.id" class="rag-checkbox"><input v-model="documentIds" type="checkbox" :value="doc.id">{{ doc.metadata.title || doc.filename }} · {{ doc.state }}</label></fieldset><details><summary>选择保留的历史文件版本（可选）</summary><p class="small muted">不选时只搜当前版本。显式选择历史版本只使用该固定版本；语义索引可能尚未覆盖它，预览会标记降级。</p><div v-for="doc in documents" :key="doc.id"><button type="button" :disabled="busy" @click="loadVersions(doc.id)">读取 {{ doc.metadata.title || doc.filename }} 的版本</button><label v-for="version in versions[doc.id] || []" :key="version.id" class="rag-checkbox"><input v-model="versionIds" type="checkbox" :value="version.id">{{ version.filename }} · {{ version.created_at }} · {{ version.state }}</label></div></details><fieldset><legend>本次包含的历史问答（最多3条）</legend><label v-for="item in history?.items.filter(v=>v.record.state==='completed') || []" :key="item.record.id" class="rag-checkbox"><input v-model="historyIds" type="checkbox" :value="item.record.id" :disabled="historyIds.length>=3 && !historyIds.includes(item.record.id)">{{ item.record.question }}</label></fieldset><button class="button-primary" :disabled="busy || !!pending || !question.trim() || documentIds.length>20 || versionIds.length>20">检索并预览，不调用回答模型</button></form>
      <section class="project-section">
        <div class="ui-card-subtle">
          <div class="ui-card-head">
            <h2 class="ui-card-title">本地语义索引</h2>
            <span class="ui-pill" :class="state?.active_index_id ? 'ui-pill-success' : 'ui-pill-warning'"><span class="ui-dot" aria-hidden="true" />{{ state?.active_index_id ? '语义索引可用' : '仅词法模式' }}</span>
          </div>
          <div style="display: grid; gap: 6px;">
            <div class="ui-card-head"><span class="small muted">向量存储占用</span><span class="small mono">{{ formatBytes(state?.vector_used_bytes) }} / {{ formatBytes(state?.vector_budget_bytes) }}</span></div>
            <div class="ui-progress" role="progressbar" :aria-valuenow="vectorPercent" aria-valuemin="0" aria-valuemax="100"><div class="ui-progress-fill" :style="{ width: `${vectorPercent}%` }" /></div>
          </div>
          <p class="small muted">新代完成前保留旧代，不混用不同嵌入模型。</p>
          <div class="project-actions"><button :disabled="busy || !!indexPending || !state?.model_configured" @click="confirm('index')">确认构建新索引代</button></div>
        </div>
        <article v-for="index in state?.indexes" :key="index.id" class="rag-index ui-card">
          <div class="ui-card-head">
            <span class="ui-pill" :class="index.state === 'ready' ? 'ui-pill-success' : index.state === 'failed' ? 'ui-pill-danger' : 'ui-pill-warning'">{{ labels[index.state] || index.state }}</span>
            <span class="ui-pill ui-pill-mono">{{ index.processed }} / {{ index.total }} 段</span>
          </div>
          <p class="small muted">{{ index.created_at }} · {{ index.error || index.model_name }}</p>
          <div><button :disabled="busy || index.state==='running'" @click="confirm('index-delete',index.id)">仅清除此索引代</button></div>
        </article>
        <div style="margin-top: 12px;"><RouterLink :to="knowledgeBase" class="ui-pill ui-pill-ads">导入文献或使用原词法摘录 →</RouterLink></div>
      </section>
      <section class="project-section"><h2>已保存问答 · {{ history?.total || 0 }}/100</h2><button v-for="item in history?.items" :key="item.record.id" class="overview-target" :disabled="busy" @click="inspect(item.record.id)">{{ item.record.question }}<small>{{ labels[item.record.state] }} · {{ item.record.created_at }}</small></button><button :disabled="busy || !history?.next_cursor" @click="more">下一页</button></section>
</div>
    </aside>
    <main class="rag-evidence">
      <WorkspacePaneHeader title="证据预览" :level="2"><template #actions><WorkspaceSpaceBar section="rag" :project-id="id()" /></template></WorkspacePaneHeader>
      <div class="workspace-pane-body">
<template v-if="preview">
  <div class="ui-card-subtle" style="margin-bottom: 14px;">
    <div class="ui-card-head">
      <h2 class="ui-card-title">{{ preview.semantic_status==='literal_query_unmatched' ? '请核对关键词、编号或补充完整问题' : preview.status==='no_results' ? '没有可用证据，不能生成' : '核对待发送片段与回答服务' }}</h2>
      <span class="ui-pill" :class="preview.evidence.length ? 'ui-pill-success' : 'ui-pill-warning'">{{ preview.evidence.length }} 条待发送片段</span>
    </div>
    <p style="margin: 0;"><strong>问题：</strong>{{ preview.question }}</p>
    <div class="ui-pill-list">
      <span class="ui-pill ui-pill-accent">{{ preview.provider }} · {{ models.labelFor(preview.model) }}</span>
      <span class="ui-pill ui-pill-ads">词法：{{ preview.lexical_status }}（{{ preview.lexical_candidates }}）</span>
      <span class="ui-pill ui-pill-compute">语义：{{ preview.semantic_status }}（{{ preview.semantic_candidates }}）</span>
      <span v-if="preview.retrieval.embedding_cache_hit" class="ui-pill ui-pill-success">复用本地向量缓存</span>
    </div>
    <p v-for="warning in preview.warnings" :key="warning" class="notice small">{{ warning }}</p>
    <p class="small muted" style="margin: 0;">确认有效至 {{ preview.expires_at }}。仅发送下列问题、原文片段及所选历史，服务端保留问答记录。</p>
    <div class="project-actions"><button :disabled="busy" @click="cancelPreview">{{ preview.evidence.length ? '取消，不发送' : '返回修改问题' }}</button><button v-if="!preview.evidence.length && state && !state.active_index_id && state.model_configured && documents.length" type="button" :disabled="busy || !!indexPending" @click="confirm('index')">构建本地语义索引</button><button class="button-primary" :disabled="busy || !!pending || !preview.evidence.length" @click="confirm('generate')">核对后确认发送与生成</button></div>
  </div>
  <article v-for="item in preview.evidence" :key="item.label" class="rag-excerpt ui-card">
    <div class="ui-card-head">
      <div class="ui-pill-list"><span class="ui-pill ui-pill-accent">[{{ item.label }}]</span><h3 class="ui-card-title">{{ item.view.evidence.title || item.view.evidence.filename }}</h3></div>
      <span class="ui-pill ui-pill-ads">{{ item.view.evidence.page ? `物理页 ${item.view.evidence.page}` : `行 ${item.view.evidence.line_start}—${item.view.evidence.line_end}` }}</span>
    </div>
    <div class="ui-pill-list"><span class="ui-pill ui-pill-mono">版本 {{ item.view.evidence.version_id.slice(0, 10) }}</span><span v-if="item.view.historical_version" class="ui-pill ui-pill-warning">保留历史版本</span></div>
    <pre>{{ item.view.text }}</pre>
    <div class="ui-card-head"><span class="small muted">{{ item.view.warning }}</span><RouterLink :to="{path:knowledgeBase,query:{evidence_id:item.view.evidence.id}}" class="ui-pill ui-pill-ads">核对原文件与定位 →</RouterLink></div>
  </article>
  <section v-if="preview.history.length" class="ui-card-subtle" style="margin-top: 14px;"><h3>本次也会发送这些历史问答</h3><article v-for="item in preview.history" :key="item.id"><b>{{ item.question }}</b><pre>{{ item.answer }}</pre></article></section>
</template>
<div v-else class="ui-empty-card">
  <div class="ui-empty-icon" aria-hidden="true"><svg viewBox="0 0 24 24"><path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20" /><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z" /><path d="M9 8h6M9 12h4" /></svg></div>
  <h3>先检索并审阅原文片段</h3>
  <p>在左侧选择文献范围并提出问题；系统会先在本机检索并展示全部待发送原文，经你确认后才会调用模型生成回答。</p>
  <div class="ui-step-rail"><span class="ui-step-pill"><span class="ui-step-num">1</span>输入问题</span><span class="ui-step-arrow" aria-hidden="true">→</span><span class="ui-step-pill"><span class="ui-step-num">2</span>预览命中片段</span><span class="ui-step-arrow" aria-hidden="true">→</span><span class="ui-step-pill"><span class="ui-step-num">3</span>确认生成与回查</span></div>
</div>
      </div>
    </main>
    <aside class="rag-answer">
      <WorkspacePaneHeader title="回答与引用" :level="2" />
      <div class="workspace-pane-body">
<template v-if="selected">
  <div class="ui-card">
    <div class="ui-pill-list">
      <span class="ui-pill" :class="selected.record.state === 'completed' ? 'ui-pill-success' : 'ui-pill-warning'">{{ labels[selected.record.state] }}</span>
      <span class="ui-pill ui-pill-accent">{{ selected.record.provider }} · {{ selected.record.model }}</span>
      <span class="ui-pill" :class="selected.record.provenance==='imported_unverified' ? 'ui-pill-warning' : 'ui-pill-neutral'">{{ selected.record.provenance==='imported_unverified' ? '导入来源未认证' : '用户已确认发送' }}</span>
    </div>
    <h2 class="ui-card-title">{{ selected.record.question }}</h2>
    <p class="notice">{{ selected.warning }}</p>
    <MarkdownAnswer v-if="selected.record.answer" class="rag-answer-text" :text="selected.record.answer" />
    <p v-else class="notice">{{ selected.record.error || '操作已保存，尚无可展示的回答。' }}</p>
    <div><button :disabled="busy || selected.record.state==='running'" class="button-danger" @click="confirm('delete',selected.record.id)">删除此问答，保留文献</button></div>
  </div>
  <section v-for="item in selected.current_evidence" :key="item.label" class="rag-excerpt ui-card-subtle">
    <div class="ui-card-head">
      <div class="ui-pill-list"><span class="ui-pill ui-pill-accent">[{{ item.label }}]</span><h3 class="ui-card-title">{{ item.view.evidence.title || item.view.evidence.filename }}</h3></div>
      <span class="ui-pill" :class="item.view.evidence.validity==='available' ? 'ui-pill-success' : 'ui-pill-danger'">{{ item.view.evidence.page ? `物理页 ${item.view.evidence.page}` : `行 ${item.view.evidence.line_start}—${item.view.evidence.line_end}` }} · {{ item.view.evidence.validity }}</span>
    </div>
    <pre v-if="item.view.text">{{ item.view.text }}</pre>
    <div><RouterLink v-if="item.view.evidence.validity==='available'" :to="{path:knowledgeBase,query:{evidence_id:item.view.evidence.id}}" class="ui-pill ui-pill-ads">回查固定原文 →</RouterLink><p v-else class="notice danger">引用已失效或原文缺失，没有改指向同名文件。</p></div>
  </section>
</template>
<div v-else class="ui-empty-card">
  <div class="ui-empty-icon" aria-hidden="true"><svg viewBox="0 0 24 24"><path d="M9 12h6M9 16h4M7 3h10a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2Z" /></svg></div>
  <h3>等待生成或打开历史问答</h3>
  <p>确认生成或选择左侧历史记录后，可在此逐条核对模型解释与固定原文定位。</p>
</div>
      </div>
    </aside>
    <dialog ref="dialog" class="project-dialog" @close="action=''">
      <div class="dialog-header">
        <div class="dialog-header-copy"><h2>{{ action==='generate' ? '确认发送这一份预览？' : action==='index' ? '只在本机构建新索引？' : '确认删除所选记录？' }}</h2></div>
        <button type="button" class="dialog-close" aria-label="关闭" :disabled="busy" @click="dialog?.close()"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="m6 6 12 12M6 18 18 6" /></svg></button>
      </div>
      <template v-if="action==='generate' && frozen"><p>服务：{{ frozen.provider }} · {{ frozen.model }}</p><p>问题：{{ frozen.question }}</p><details v-for="item in frozen.evidence" :key="item.label"><summary>[{{ item.label }}] {{ item.view.evidence.filename }} · {{ item.view.evidence.page ? `物理页${item.view.evidence.page}` : `行${item.view.evidence.line_start}` }}</summary><pre>{{ item.view.text }}</pre></details><details v-for="item in frozen.history" :key="item.id"><summary>历史：{{ item.question }}</summary><pre>{{ item.answer }}</pre></details><p>将发送上面列明的内容并保存问答，可能产生供应商费用。文献中的指令不获得工具权限，模型解释仍需人工核对。</p></template>
      <p v-else-if="action==='index'">使用已配置的固定本地模型，仅在CPU计算。不会下载模型或向回答服务发送原文。失败保留旧可用索引，来源变化时需明确重建。</p>
      <p v-else>只删除你选择的问答或索引代，原文和其他科研结果保留；生成请求历史保留，旧编号不会再次调用模型。</p>
      <div class="project-actions"><button type="button" @click="dialog?.close()">取消</button><button type="button" :class="action==='delete' || action==='index-delete' ? 'button-danger' : 'button-primary'" :disabled="busy" @click="confirmed">{{ action==='generate' ? '确认发送这份内容并生成' : action==='index' ? '确认构建索引' : '确认删除' }}</button></div>
    </dialog>
  </div>
</template>
