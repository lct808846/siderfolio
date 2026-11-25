<script setup lang="ts">
import WorkspaceHeader from '../components/WorkspaceHeader.vue'
import WorkspacePaneHeader from '../components/WorkspacePaneHeader.vue'
import WorkspaceSpaceBar from '../components/WorkspaceSpaceBar.vue'
import PanelSwitcher from '../components/PanelSwitcher.vue'
import StatusNotice from '../components/StatusNotice.vue'
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { fileHash, knowledgeApi, originalContent, uploadDocument } from '../api/knowledge'
import { projectsApi } from '../api/projects'
import { useProjects } from '../stores/projects'
import type { DocumentAction, DocumentDetail, DocumentUpload, DocumentVersion, EvidenceRecord, EvidenceView, KnowledgeDocument, KnowledgeResult, ProjectDetail, TextPreview } from '../types'

type Pending = { project: string; document?: string; kind: 'upload' | 'reindex'; options: DocumentUpload | DocumentAction; fileSha?: string; filename?: string }
const route = useRoute(), router = useRouter(), projectsStore = useProjects()
const resolvedProjectId = ref('')
const activeProjectId = computed(() => (typeof route.params.projectId === 'string' && route.params.projectId) ? route.params.projectId : resolvedProjectId.value)
const knowledgeBase = computed(() => (typeof route.params.projectId === 'string' && route.params.projectId) ? `/projects/${activeProjectId.value}/knowledge` : '/knowledge')
const project = ref<ProjectDetail | null>(null), documents = ref<KnowledgeDocument[]>([]), document = ref<DocumentDetail | null>(null)
const references = ref<EvidenceRecord[]>([]), result = ref<KnowledgeResult | null>(null), evidence = ref<EvidenceView | null>(null)
const busy = ref(false), error = ref(''), message = ref(''), panel = ref('documents')
const file = ref<File | null>(null), target = ref<'new' | 'version' | 'restore'>('new'), restoreVersion = ref('')
const title = ref(''), authors = ref(''), year = ref(''), doi = ref(''), allowDuplicate = ref(false)
const query = ref(''), filterDocument = ref(''), answer = ref(true), pending = ref<Pending | null>(null)
const dialog = ref<HTMLDialogElement | null>(null), action = ref<'delete' | 'reindex' | ''>(''), actionVersion = ref('')
const extracted = ref<TextPreview | null>(null), textPage = ref('1')
const previewUrl = ref(''), previewText = ref(''), previewLabel = ref(''), previewPage = ref(1)
const previewVersion = ref<DocumentVersion | null>(null), previewDocument = ref('')
let navigation = 0, previewToken = 0
const names: Record<string, string> = { parsing: '解析中', ready: '已提取并索引', partial: '部分可用', failed: '未完成', interrupted: '已中断', unavailable: '原文不可用' }
const state = (value: string) => names[value] || value
function docExt(filename: string) { return filename.toLowerCase().endsWith('.pdf') ? 'PDF' : 'MD' }
function statePillClass(value: string) {
  if (value === 'ready') return 'ui-pill-success'
  if (value === 'partial' || value === 'parsing') return 'ui-pill-warning'
  if (value === 'failed' || value === 'unavailable' || value === 'interrupted') return 'ui-pill-danger'
  return 'ui-pill-neutral'
}
function formatBytes(value: number) {
  if (value < 1024) return `${value} B`
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KiB`
  return `${(value / (1024 * 1024)).toFixed(2)} MiB`
}
const pretty = (value: unknown) => JSON.stringify(value, null, 2)
const activeVersion = computed(() => document.value?.versions.find(v => v.id === document.value?.current_version_id))
const pendingKey = (projectId: string) => `astroagent.knowledge.request.${projectId}`
function report(e: unknown) { error.value = e instanceof Error ? e.message : '操作未确认，请读取服务端记录。'; panel.value = 'search' }
function remember(value: Pending | null, projectId = activeProjectId.value) {
  if (projectId === activeProjectId.value) pending.value = value
  try { if (value) sessionStorage.setItem(pendingKey(projectId), JSON.stringify(value)); else sessionStorage.removeItem(pendingKey(projectId)) } catch { message.value = '浏览器无法保存请求编号，请保留当前页面核对。' }
}
function restorePending(projectId: string) {
  try { const value = JSON.parse(sessionStorage.getItem(pendingKey(projectId)) || 'null'); return value?.project === projectId && ['upload', 'reindex'].includes(value.kind) && typeof value.options?.client_request_id === 'string' ? value as Pending : null } catch { return null }
}
function resetPreview() { previewToken++; if (previewUrl.value) URL.revokeObjectURL(previewUrl.value); previewUrl.value = ''; previewText.value = ''; previewVersion.value = null; extracted.value = null }
async function refresh() {
  const token = ++navigation, routePid = typeof route.params.projectId === 'string' ? route.params.projectId : ''
  await projectsStore.load()
  const projectId = routePid || (await projectsStore.ensureDefault()).id
  if (token !== navigation) return
  resolvedProjectId.value = projectId
  const documentId = String(route.params.documentId || '')
  const [p, docs, refs, detail] = await Promise.all([projectsApi.detail(projectId), knowledgeApi.list(projectId), knowledgeApi.references(projectId), documentId ? knowledgeApi.detail(projectId, documentId) : Promise.resolve(null)])
  if (token !== navigation) return
  project.value = p; documents.value = docs; references.value = refs; document.value = detail
  projectsStore.setSourceCount(projectId, docs.filter(doc => doc.state === 'ready' || doc.state === 'partial').length)
  if (filterDocument.value && !docs.some(doc => doc.id === filterDocument.value)) filterDocument.value = ''
  if (detail && !detail.versions.some(v => v.id === restoreVersion.value)) restoreVersion.value = detail.current_version_id
  pending.value = restorePending(projectId)
  const requestedEvidence = typeof route.query.evidence_id === 'string' ? route.query.evidence_id : ''
  if (requestedEvidence && evidence.value?.evidence.id !== requestedEvidence) {
    const found = await knowledgeApi.evidence(projectId, requestedEvidence)
    if (token === navigation) { evidence.value = found; panel.value = 'evidence' }
  }
}
async function act(task: () => Promise<unknown>) {
  if (busy.value) return
  busy.value = true; error.value = ''; message.value = ''
  try { await task() } catch (e) { report(e) } finally { busy.value = false }
}
function pick(event: Event) { file.value = (event.target as HTMLInputElement).files?.[0] || null }
async function upload() {
  const p = project.value, chosen = file.value, doc = document.value
  if (!p || !chosen || (target.value !== 'new' && !doc)) return
  await act(async () => {
    if (!chosen.size || chosen.size > 20 * 1024 ** 2) throw new Error('文件必须非空且不超过20 MiB。')
    if (year.value.trim() && (!Number.isInteger(Number(year.value)) || Number(year.value) < 1 || Number(year.value) > 9999)) throw new Error('年份必须为1—9999的整数，未知请留空。')
    const fileSha = await fileHash(await chosen.arrayBuffer())
    const options: DocumentUpload = { expected_revision: p.revision, client_request_id: crypto.randomUUID(), allow_duplicate: allowDuplicate.value,
      metadata: { title: title.value.trim() || null, authors: authors.value.split(/[;；\n]/).map(v => v.trim()).filter(Boolean), year: year.value.trim() ? Number(year.value) : null, doi: doi.value.trim() || null },
      restore_version_id: target.value === 'restore' ? restoreVersion.value : null }
    const item: Pending = { project: p.id, document: target.value === 'new' ? undefined : doc!.id, kind: 'upload', options, fileSha, filename: chosen.name }
    remember(item, p.id); await perform(item, chosen)
  })
}
async function perform(item: Pending, chosen?: File) {
  const value = item.kind === 'upload'
    ? await uploadDocument(item.project, chosen!, item.options as DocumentUpload, item.document)
    : await knowledgeApi.reindex(item.project, item.document!, item.options as DocumentAction)
  if (value.operation.state !== 'parsing') remember(null, item.project)
  if (activeProjectId.value === item.project) {
    await router.push(`${knowledgeBase.value}/${value.document.id}`); await refresh()
    message.value = `【${state(value.document.state)}】${value.duplicate ? '重复文件：' : ''}${value.operation.message || ''}`
    panel.value = 'search'
  }
}
async function retry() {
  const item = pending.value
  if (!item) return
  await act(async () => {
    const chosen = file.value
    if (item.kind === 'upload' && (!chosen || chosen.name !== item.filename || await fileHash(await chosen.arrayBuffer()) !== item.fileSha)) throw new Error('请重新选择同一文件；需名称和SHA-256均匹配，才能使用原请求编号核对上传。')
    await perform(item, chosen || undefined)
  })
}
async function checkPending() {
  const item = pending.value
  if (!item) return
  await act(async () => {
    const value = await knowledgeApi.operation(item.project, item.options.client_request_id)
    if (value.state !== 'parsing') remember(null, item.project)
    if (activeProjectId.value === item.project) {
      await router.push(`${knowledgeBase.value}/${value.document_id}`); await refresh()
      message.value = value.message || state(value.state)
    }
  })
}
async function search() {
  const p = project.value
  if (!p) return
  await act(async () => {
    const value = await knowledgeApi.search(p.id, { query: query.value, limit: 20, document_ids: filterDocument.value ? [filterDocument.value] : [] }, answer.value)
    if (activeProjectId.value === p.id) { result.value = value; evidence.value = null; await refresh(); panel.value = 'search' }
  })
}
function associationPath(id: string) {
  const query = new URLSearchParams({ evidence_id: id })
  if (typeof route.query.link_target_type === 'string' && typeof route.query.link_target_id === 'string') { query.set('target_type', route.query.link_target_type); query.set('target_id', route.query.link_target_id) }
  return `/projects/${activeProjectId.value}/overview?${query}`
}
async function inspect(id: string) {
  const p = project.value
  if (p) await act(async () => { const value = await knowledgeApi.evidence(p.id, id); if (activeProjectId.value === p.id) { evidence.value = value; panel.value = 'evidence' } })
}
async function openOriginal(documentId: string, versionId: string, page = 1, line = 1) {
  const p = project.value
  if (!p) return
  resetPreview(); const token = previewToken
  await act(async () => {
    const detail = await knowledgeApi.detail(p.id, documentId), version = detail.versions.find(v => v.id === versionId)
    if (!version) throw new Error('原文件版本不存在。')
    const blob = await originalContent(p.id, documentId, version)
    if (token !== previewToken || activeProjectId.value !== p.id) return
    previewVersion.value = version; previewDocument.value = documentId; previewPage.value = page
    previewLabel.value = `${version.filename} · ${version.media_type === 'application/pdf' ? `物理页 ${page}（未实现精确高亮）` : `原始行 ${line} 起`}`
    if (version.media_type === 'application/pdf') previewUrl.value = URL.createObjectURL(blob)
    else { const text = new TextDecoder('utf-8', { fatal: true }).decode(await blob.arrayBuffer()); const lines = text.split(/\r\n|\n|\r/); previewText.value = lines.slice(Math.max(0, line - 3), line + 197).map((v, i) => `${Math.max(1, line - 2) + i}  ${v}`).join('\n').slice(0, 24000) }
    panel.value = 'evidence'
  })
}
async function showExtraction(documentId: string, version: DocumentVersion) {
  const p = project.value
  if (!p) return
  const position = version.media_type === 'application/pdf' ? Number(textPage.value) : 1
  if (!Number.isInteger(position) || position < 1 || position > 500) { report(new Error('请选择1—500之间的物理页。')); return }
  resetPreview(); const token = previewToken
  await act(async () => { const value = await knowledgeApi.text(p.id, documentId, version.id, position); if (token === previewToken && activeProjectId.value === p.id) { extracted.value = value; panel.value = 'evidence' } })
}
async function downloadOriginal() {
  const p = project.value, v = previewVersion.value
  if (!p || !v) return
  await act(async () => { const blob = await originalContent(p.id, previewDocument.value, v); const url = URL.createObjectURL(blob); const anchor = globalThis.document.createElement('a'); anchor.href = url; anchor.download = v.filename; anchor.click(); setTimeout(() => URL.revokeObjectURL(url), 1000) })
}
async function openConfirm(kind: 'delete' | 'reindex', versionId = '') { action.value = kind; actionVersion.value = versionId; await nextTick(); dialog.value?.showModal() }
async function confirm() {
  const p = project.value, doc = document.value, kind = action.value, versionId = actionVersion.value
  dialog.value?.close(); action.value = ''
  if (!p || !doc) return
  await act(async () => {
    if (kind === 'delete') {
      await knowledgeApi.delete(p.id, doc.id, p.revision); resetPreview(); result.value = null; evidence.value = null
      await router.push(knowledgeBase.value); await refresh(); message.value = '已删除数据库中原文、全部版本及索引，历史引用标为失效；不表示安全擦除备份或已导出文件。'
    } else {
      const item: Pending = { project: p.id, document: doc.id, kind: 'reindex', options: { expected_revision: p.revision, client_request_id: crypto.randomUUID(), confirmed: true, version_id: versionId || doc.current_version_id } }
      remember(item, p.id); await perform(item)
    }
  })
}
watch(() => route.fullPath, () => {
  navigation++; resetPreview(); dialog.value?.close(); action.value = ''; document.value = null; error.value = ''
  if (project.value?.id !== activeProjectId.value) { project.value = null; result.value = null; evidence.value = null; filterDocument.value = ''; file.value = null; target.value = 'new' }
  const path = route.fullPath
  void refresh().catch(e => { if (route.fullPath === path) report(e) })
}, { immediate: true })
onBeforeUnmount(resetPreview)
</script>

<template>
  <div class="workspace-panes project-workspace knowledge-workspace" :data-panel="panel">
    <WorkspaceHeader title="本地文献与原文证据" />
    <PanelSwitcher v-model="panel" label="知识库面板" :options="[{ value: 'documents', label: '文档与上传' }, { value: 'search', label: '检索与状态' }, { value: 'evidence', label: '证据与原文' }]" />
    <aside class="project-sidebar knowledge-sidebar">
      <WorkspacePaneHeader :level="2" title="本地文献库" :subtitle="`${documents.length}/100`" />
      <div class="workspace-pane-body">
      <div class="compact-space-bar"><WorkspaceSpaceBar section="knowledge" :project-id="activeProjectId" /></div>
      <RouterLink v-for="doc in documents" :key="doc.id" class="project-item" :class="{selected:doc.id===document?.id}" :to="`${knowledgeBase}/${doc.id}`"><div class="ui-card-head" style="align-items: center; gap: 6px;"><span class="ui-file-badge">{{ docExt(doc.filename) }}</span><b style="flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">{{ doc.metadata.title || doc.filename }}</b></div><div class="ui-pill-list" style="margin-top: 6px;"><span class="ui-pill" :class="statePillClass(doc.state)">{{ state(doc.state) }}</span><span class="ui-pill ui-pill-neutral">{{ doc.provenance==='local' ? '本机' : '导入' }}</span></div></RouterLink>
      <form class="project-form knowledge-upload" @submit.prevent="upload">
<h2>上传参考来源</h2><p class="small muted">PDF / UTF-8 Markdown，单文件 ≤ 20 MiB。副本保存在本机数据库，项目内对话与文献问答可按需参考已就绪文档。</p><fieldset :disabled="busy || !project || !!pending">
        <label for="knowledge-target">上传方式</label><select id="knowledge-target" v-model="target"><option value="new">新文档</option><option value="version" :disabled="!document">为选中文档新增版本</option><option value="restore" :disabled="!document">恢复选中文档同哈希原文件</option></select>
        <template v-if="target==='restore'"><label for="knowledge-restore">原始版本</label><select id="knowledge-restore" v-model="restoreVersion"><option v-for="version in document?.versions" :key="version.id" :value="version.id">{{ version.filename }} · {{ version.id.slice(0,8) }}</option></select><p class="small muted">只接受相同SHA-256文件；不同内容请新增版本。</p></template>
        <template v-if="target==='new'"><label for="knowledge-title">标题（可选，不从文件名推断）</label><input id="knowledge-title" v-model="title" maxlength="500"><label for="knowledge-authors">作者（可选，分号分隔）</label><textarea id="knowledge-authors" v-model="authors" rows="2"></textarea><label for="knowledge-year">年份（可选）</label><input id="knowledge-year" v-model="year" inputmode="numeric" maxlength="4"><label for="knowledge-doi">DOI（可选）</label><input id="knowledge-doi" v-model="doi" maxlength="300"><label class="check-label"><input v-model="allowDuplicate" type="checkbox">相同文件也创建独立文档</label></template>
        <button class="button-primary" :disabled="!file || (target!=='new' && !document)">保存文件并本地解析</button>
      </fieldset><label for="knowledge-file">选择文件（断线后可重选同一文件核对）</label><input id="knowledge-file" type="file" accept=".pdf,.md,.markdown" :disabled="busy" @change="pick">
</form>
      </div>
    </aside>
    <main class="project-main knowledge-main">
      <WorkspacePaneHeader title="本地知识库" :level="1"><template #actions><WorkspaceSpaceBar section="knowledge" :project-id="activeProjectId" /></template></WorkspacePaneHeader>
      <div class="workspace-pane-body">
      <StatusNotice v-if="error" title="知识库操作未完成" :message="error" @dismiss="error = ''" /><p v-if="message" class="notice info" role="status">{{ message }}</p><p v-if="busy" class="processing" role="status">处理中。解析不因网页断线而保证取消，原文及状态以本机记录为准。</p>
      <div v-if="pending" class="notice"><p>请求尚待确认，可先读取状态；使用原编号核对不会自动重放已经完成的处理。</p><code>{{ pending.options.client_request_id }}</code><div class="project-actions"><button :disabled="busy" @click="checkPending">读取原请求状态</button><button :disabled="busy" @click="retry">使用原编号核对操作</button><button :disabled="busy" @click="remember(null)">保留服务端记录，关闭本页提醒</button></div></div>
      <section class="knowledge-search"><p class="eyebrow">原文证据</p><h2>原文检索</h2><p class="small muted">本地词法检索，所有关键词同时命中；不做同义词、跨语言语义或模型补答。文献中的指令只作为数据。</p><form class="project-form" @submit.prevent="search"><label for="knowledge-query">问题中的明确关键词</label><textarea id="knowledge-query" v-model="query" required maxlength="1000" rows="3" placeholder="例如：binary cluster 或 双星团 环境"></textarea><label for="knowledge-filter">检索范围</label><select id="knowledge-filter" v-model="filterDocument"><option value="">本项目当前可用版本</option><option v-for="doc in documents" :key="doc.id" :value="doc.id">{{ doc.metadata.title || doc.filename }}</option></select><label class="check-label"><input v-model="answer" type="checkbox">以带引用的摘录式回答展示（不调用模型）</label><button class="button-primary" :disabled="busy || !query.trim() || !project">检索原文证据</button></form></section>
      <section v-if="result" class="project-section">
        <div class="ui-card-subtle">
          <div class="ui-card-head">
            <h2 class="ui-card-title">{{ result.status==='insufficient_evidence' ? '未找到足够证据' : '找到的相关原文' }}</h2>
            <div class="ui-pill-list">
              <span class="ui-pill ui-pill-ads">{{ result.returned_count }} / {{ result.matched_units }} 段</span>
              <span class="ui-pill ui-pill-neutral">{{ result.mode }}</span>
              <span v-if="result.truncated" class="ui-pill ui-pill-warning">已截断</span>
            </div>
          </div>
          <p>{{ result.answer }}</p>
          <p class="small muted">检索时间（UTC）：{{ result.searched_at }}。文件变更不会自动重查，此处保留当次摘录。</p>
          <p v-for="warning in result.warnings" :key="warning" class="small muted">{{ warning }}</p>
        </div>
        <article v-for="(hit,index) in result.hits" :key="hit.evidence.id" class="knowledge-hit ui-card">
          <div class="ui-card-head">
            <div class="ui-pill-list">
              <span class="ui-pill ui-pill-accent">#{{ index + 1 }}</span>
              <h3 class="ui-card-title">{{ hit.evidence.title || hit.evidence.filename }}</h3>
            </div>
            <span class="ui-pill ui-pill-ads">{{ hit.evidence.page ? `PDF 物理页 ${hit.evidence.page}` : `原始行 ${hit.evidence.line_start}—${hit.evidence.line_end}` }}</span>
          </div>
          <div v-if="hit.heading_path.length" class="ui-pill-list">
            <span v-for="heading in hit.heading_path" :key="heading" class="ui-pill ui-pill-neutral">{{ heading }}</span>
          </div>
          <pre>{{ hit.text }}</pre>
          <div class="project-actions"><button :disabled="busy" @click="inspect(hit.evidence.id)">核对引用与原始版本 →</button></div>
        </article>
        <details><summary>检索词、排序、版本与时间</summary><pre>{{ pretty({terms:result.terms,ranking:result.ranking,index_version:result.index_version,searched_at:result.searched_at}) }}</pre></details>
      </section>
      <section v-if="document" class="project-section">
        <div class="ui-card">
          <div class="ui-card-head">
            <div>
              <div class="ui-pill-list" style="margin-bottom: 8px;">
                <span class="ui-file-badge">{{ docExt(document.filename) }}</span>
                <span class="ui-pill" :class="statePillClass(document.state)">{{ state(document.state) }}</span>
                <span class="ui-pill ui-pill-neutral">{{ document.provenance==='local' ? '用户本机文档' : '导入 · 来源未认证' }}</span>
              </div>
              <h2 style="margin: 0;">{{ document.metadata.title || document.filename }}</h2>
            </div>
            <div class="project-actions">
              <button :disabled="busy || !!pending" @click="openConfirm('reindex')">重建索引</button>
              <button :disabled="busy || !!pending || document.state==='parsing'" class="button-danger" @click="openConfirm('delete')">删除文档</button>
            </div>
          </div>
          <p class="small muted">{{ document.provenance==='local' ? '用户本机文档，不代表科学认证。' : '导入来源未经认证，哈希只证明包内一致性。' }}</p>
          <label class="small">提取文本的 PDF 物理页（Markdown 忽略此项）<input v-model="textPage" type="number" min="1" max="500" step="1" aria-label="提取文本物理页"></label>
          <details><summary>用户元数据</summary><pre>{{ pretty(document.metadata) }}</pre></details>
        </div>
        <article v-for="version in document.versions" :key="version.id" class="knowledge-version ui-card-subtle">
          <div class="ui-card-head">
            <h3 class="ui-card-title">{{ version.filename }}</h3>
            <span class="ui-pill" :class="version.id===document.current_version_id ? 'ui-pill-accent' : 'ui-pill-neutral'">{{ version.id===document.current_version_id ? '当前版本' : '历史版本' }}</span>
          </div>
          <div class="ui-pill-list">
            <span class="ui-pill" :class="statePillClass(version.state)">{{ state(version.state) }}</span>
            <span class="ui-pill ui-pill-neutral">{{ formatBytes(version.bytes) }}</span>
            <span class="ui-pill ui-pill-neutral">{{ version.page_count == null ? `${version.line_count ?? '未知'} 行` : `${version.page_count} 物理页` }}</span>
            <span class="ui-pill ui-pill-ads">{{ version.unit_count }} 切分段</span>
            <span class="ui-pill" :class="version.indexed ? 'ui-pill-success' : 'ui-pill-warning'">{{ version.indexed ? '索引已建立' : '未建立可用索引' }}</span>
          </div>
          <div class="ui-pill-list"><span class="ui-pill ui-pill-mono">SHA256 {{ version.sha256.slice(0, 16) }}…</span></div>
          <p v-if="version.error" class="notice danger">{{ version.error.message }} <code>{{ version.error.code }}</code></p>
          <details v-if="version.warnings?.length"><summary>解析范围与限制</summary><p v-for="warning in version.warnings" :key="warning" class="small muted">{{ warning }}</p></details>
          <div class="project-actions">
            <button :disabled="busy || !version.content_available" @click="openOriginal(document.id,version.id)">核对原文件</button>
            <button :disabled="busy || !version.content_available" @click="showExtraction(document.id,version)">查看实际提取文本</button>
            <button v-if="version.id!==document.current_version_id" :disabled="busy || !!pending || !version.content_available" @click="openConfirm('reindex',version.id)">恢复此版本并重建索引</button>
          </div>
          <details><summary>版本身份与提取器</summary><pre>{{ pretty(version) }}</pre></details>
        </article>
        <p v-if="activeVersion?.state==='unavailable'" class="notice">此版本原文不可用。可在左侧选择“恢复同哈希原文件”；不会把新内容冒充旧引用。</p>
      </section>
</div>
    </main>
    <aside class="knowledge-evidence" aria-label="引用与原文件核对">
      <WorkspacePaneHeader title="证据与原文件" :level="2" />
      <div class="workspace-pane-body">
<p class="eyebrow">来源核对</p><h2>引用与原始位置</h2><p class="small muted">与ADS摘要、数据库测量和模型回答分开标识。</p><section v-if="evidence" class="project-section"><RouterLink v-if="evidence.evidence.validity==='available'" :to="associationPath(evidence.evidence.id)">关联此原文与项目结果 →</RouterLink><h3>{{ evidence.evidence.title || evidence.evidence.filename }}</h3><p class="notice" :class="{danger:evidence.evidence.validity!=='available'}">{{ evidence.warning }}</p><p v-if="evidence.historical_version" class="notice">这是保留的历史文件版本，未重定向到新文件。</p><pre v-if="evidence.text">{{ evidence.text }}</pre><p class="small">{{ evidence.evidence.page ? `物理页 ${evidence.evidence.page}` : `原始行 ${evidence.evidence.line_start}—${evidence.evidence.line_end}` }}</p><button v-if="evidence.content_url" :disabled="busy" @click="openOriginal(evidence.evidence.document_id,evidence.evidence.version_id,evidence.evidence.page || 1,evidence.evidence.line_start || 1)">打开此引用的原始版本</button><details><summary>引用ID、哈希与原文偏移</summary><pre>{{ pretty(evidence.evidence) }}</pre></details></section>
      <section v-if="extracted" class="project-section"><h3>实际提取文本 · {{ extracted.page ? `物理页${extracted.page}` : 'Markdown原文' }}</h3><p class="small muted">状态 {{ extracted.state }} · 共{{ extracted.original_characters }}字符{{ extracted.truncated ? '，此处仅预览前24000字符' : '' }}；展示原始提取副本，不是索引规范化字符串。</p><p v-if="extracted.error" class="notice danger">{{ extracted.error }}</p><pre>{{ extracted.text || '此位置未提取到文本，不执行OCR。' }}</pre><code>{{ extracted.sha256 }}</code></section><section v-if="previewVersion" class="project-section"><h3>{{ previewLabel }}</h3><p class="small muted">已核对原文件SHA-256。PDF仅按物理页定位，浏览器可能阻止受限预览，可完整下载后核对。Markdown预览最多200行/24000字符，原文件不裁剪。</p><iframe v-if="previewUrl" :src="`${previewUrl}#page=${previewPage}`" sandbox="" title="受限PDF原文件预览" class="knowledge-pdf"></iframe><pre v-if="previewText">{{ previewText }}</pre><button :disabled="busy" @click="downloadOriginal">下载完整原文件</button></section>
      <section class="project-section"><h3>最近保存的引用 · {{ references.length }}/最多显示50</h3><button v-for="item in references" :key="item.id" class="knowledge-reference" :disabled="busy" @click="inspect(item.id)">{{ item.title || item.filename }}<small>{{ item.page ? `物理页${item.page}` : `行${item.line_start}—${item.line_end}` }} · {{ item.validity==='deleted' ? '原文已删除' : '点击核对有效性' }}</small></button><p v-if="!references.length" class="small muted">检索后在此保存可回查的引用编号。</p></section>
</div>
    </aside>
    <dialog ref="dialog" class="project-dialog" @close="action=''">
      <div class="dialog-header">
        <div class="dialog-header-copy"><h2>{{ action==='delete' ? '删除文档与全部版本？' : '确认重建或恢复版本？' }}</h2></div>
        <button type="button" class="dialog-close" aria-label="关闭" :disabled="busy" @click="dialog?.close()"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="m6 6 12 12M6 18 18 6" /></svg></button>
      </div>
      <p v-if="action==='delete'">将从本机业务库删除原文件、提取文本、所有版本和索引，历史引用保留最小定位元数据并失效。旧备份和已导出归档可能仍有内容；此操作不表示安全擦除这些副本。</p>
      <p v-else>核对已有文件哈希并重建本地索引。选择历史版本将使其成为当前检索版本；原有引用仍指向各自的原始版本，不调用模型或外部服务。上次失败/中断的本地解析可能在本次明确确认后重新执行。</p>
      <div class="project-actions"><button type="button" @click="dialog?.close()">取消</button><button type="button" :class="action==='delete' ? 'button-danger' : 'button-primary'" :disabled="busy" @click="confirm">{{ action==='delete' ? '确认删除' : '确认本地重建' }}</button></div>
    </dialog>
  </div>
</template>
