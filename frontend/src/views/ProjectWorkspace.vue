<script setup lang="ts">
import WorkspaceHeader from '../components/WorkspaceHeader.vue'
import PanelSwitcher from '../components/PanelSwitcher.vue'
import CreateProjectDialog from '../components/CreateProjectDialog.vue'
import ResultPanel from '../components/ResultPanel.vue'
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api, ApiError } from '../api'
import { knowledgeApi, uploadDocument } from '../api/knowledge'
import { exportProject, importProject, projectsApi } from '../api/projects'
import { useProjects } from '../stores/projects'
import type { Comparison, Conversation, ConversationDetail, KnowledgeDocument, Project, ProjectDetail, RerunRequest, Snapshot, Turn } from '../types'

const MAX_SOURCE_BYTES = 20 * 1024 * 1024
const route = useRoute(), router = useRouter(), projectsStore = useProjects()
const projects = ref<Project[]>([]), conversations = ref<Conversation[]>([]), memberships = ref<Record<string, string>>({})
const current = ref<ProjectDetail | null>(null), snapshot = ref<Snapshot | null>(null)
const documents = ref<KnowledgeDocument[]>([])
const busy = ref(false), uploadingSources = ref(false), sourceProgress = ref(''), sourceDragging = ref(false)
const error = ref(''), errorCode = ref(''), message = ref('')
const editingInfo = ref(false), editName = ref(''), editDescription = ref('')
const moveId = ref(''), saveConversation = ref(''), saveTurn = ref(''), snapshotName = ref(''), renameName = ref('')
const conversationDetail = ref<ConversationDetail | null>(null)
const leftId = ref(''), rightId = ref(''), matchIds = ref(false), comparison = ref<Comparison | null>(null)
const tool = ref(''), dialog = ref<HTMLDialogElement | null>(null), action = ref<'project-delete' | 'snapshot-delete' | 'rerun' | 'archive' | ''>('')
const createDialog = ref<InstanceType<typeof CreateProjectDialog> | null>(null)
const sourceFileInput = ref<HTMLInputElement | null>(null)
const archiveFormat = ref<1 | 2 | 3 | 4 | 5 | 6>(6), knowledgeMode = ref<'full' | 'metadata'>('metadata')
const mobilePanel = ref('project'), resultsOpen = ref(false), pending = ref<{ project: string; snapshot: string; payload: RerunRequest } | null>(null)
const sidebarCollapsed = ref(false)
const compactLayout = ref(false)
const projectsVisible = computed(() => compactLayout.value ? mobilePanel.value === 'projects' : !sidebarCollapsed.value)
const resultsVisible = computed(() => compactLayout.value ? mobilePanel.value === 'results' : resultsOpen.value)
const resultsToggle = ref<HTMLButtonElement | null>(null)
let navigation = 0, selection = 0, conversationSelection = 0
let layoutQuery: MediaQueryList | undefined

const docStateLabels: Record<string, string> = {
  ready: '已就绪',
  partial: '部分可用',
  parsing: '解析中',
  failed: '未完成',
  interrupted: '已中断',
  unavailable: '原文不可用',
}

function updateLayout() { compactLayout.value = layoutQuery?.matches || false }
onMounted(() => {
  layoutQuery = window.matchMedia('(max-width: 980px)')
  updateLayout()
  layoutQuery.addEventListener('change', updateLayout)
})
onBeforeUnmount(() => layoutQuery?.removeEventListener('change', updateLayout))

function toggleProjects() {
  if (compactLayout.value) mobilePanel.value = mobilePanel.value === 'projects' ? 'project' : 'projects'
  else sidebarCollapsed.value = !sidebarCollapsed.value
}

async function closeResults() {
  resultsOpen.value = false
  if (compactLayout.value) mobilePanel.value = 'project'
  await nextTick()
  resultsToggle.value?.focus({ preventScroll: true })
}

async function toggleResults() {
  if (resultsVisible.value) {
    await closeResults()
    return
  }
  resultsOpen.value = true
  if (compactLayout.value) mobilePanel.value = 'results'
  await nextTick()
  document.getElementById('archive-results')?.querySelector<HTMLButtonElement>('.result-close')?.focus({ preventScroll: true })
}

watch(mobilePanel, value => {
  if (compactLayout.value) resultsOpen.value = value === 'results'
})

const isDefaultCurrent = computed(() => !!current.value && current.value.id === projectsStore.defaultProjectId)
const unassigned = computed(() => conversations.value.filter(c => !memberships.value[c.id]))
const defaultWorkspace = computed(() => projects.value.find(p => p.id === projectsStore.defaultProjectId) || null)
const customProjects = computed(() => projects.value.filter(p => p.id !== projectsStore.defaultProjectId))
const members = computed(() => conversations.value.filter(c => memberships.value[c.id] === current.value?.id))
const movable = computed(() => conversations.value.filter(c => memberships.value[c.id] !== current.value?.id))
const deliverable = computed(() => conversationDetail.value?.turns.filter(t => t.response_status) || [])
const readySourceCount = computed(() => documents.value.filter(d => d.state === 'ready' || d.state === 'partial').length)
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
function docKind(filename: string) {
  return filename.toLowerCase().endsWith('.pdf') ? 'PDF' : 'MD'
}
function report(e: unknown) { error.value = e instanceof Error ? e.message : '操作失败，请核对当前状态。'; errorCode.value = e instanceof ApiError ? e.code : 'project_operation_failed' }

async function refresh() {
  const token = ++navigation, id = typeof route.params.projectId === 'string' ? route.params.projectId : ''
  const [list, all, mapping, detail, docs] = await Promise.all([
    projectsApi.list(),
    api.list(),
    projectsApi.memberships(),
    id ? projectsApi.detail(id) : Promise.resolve(null),
    id ? knowledgeApi.list(id).catch(() => [] as KnowledgeDocument[]) : Promise.resolve([] as KnowledgeDocument[]),
    projectsStore.load(true),
  ])
  if (token !== navigation) return
  projects.value = list; conversations.value = all; memberships.value = mapping; current.value = detail; documents.value = docs
  if (detail) {
    projectsStore.setSourceCount(detail.id, docs.filter(d => d.state === 'ready' || d.state === 'partial').length)
  }
  editName.value = detail?.name || ''; editDescription.value = detail?.description || ''
  if (detail && typeof route.query.snapshot === 'string' && detail.snapshots.some(s => s.id === route.query.snapshot)) await viewSnapshot(route.query.snapshot, false)
}

async function act(task: () => Promise<unknown>) {
  if (busy.value) return
  busy.value = true; error.value = ''; errorCode.value = ''; message.value = ''
  try { await task(); await refresh() } catch (e) { report(e) } finally { busy.value = false }
}

async function openCreateProject() {
  await createDialog.value?.open()
}

async function onProjectCreated(payload: { project: Project; uploadedCount: number; startChat: boolean }) {
  const note = payload.uploadedCount ? `，已解析 ${payload.uploadedCount} 份参考来源` : ''
  message.value = `已创建科研项目「${payload.project.name}」${note}。`
  if (payload.startChat) {
    await startChatInProject(payload.project.id)
    return
  }
  await router.push(`/projects/${payload.project.id}`)
}

async function startChatInProject(projectId = current.value?.id) {
  if (!projectId || busy.value) return
  busy.value = true; error.value = ''; errorCode.value = ''
  try {
    const conversationId = await projectsStore.startConversation(projectId)
    await router.push(`/conversations/${conversationId}`)
  } catch (e) {
    report(e)
  } finally {
    busy.value = false
  }
}

async function addSources(fileList: FileList | File[]) {
  const project = current.value
  if (!project || busy.value || uploadingSources.value) return
  const valid: File[] = []
  const rejected: string[] = []
  for (const file of Array.from(fileList)) {
    const lower = file.name.toLowerCase()
    if (!lower.endsWith('.pdf') && !lower.endsWith('.md') && !lower.endsWith('.markdown')) {
      rejected.push(`${file.name}（仅支持 PDF / Markdown）`)
      continue
    }
    if (!file.size || file.size > MAX_SOURCE_BYTES) {
      rejected.push(`${file.name}（需非空且 ≤ 20 MiB）`)
      continue
    }
    valid.push(file)
  }
  if (!valid.length) {
    if (rejected.length) error.value = `未能添加来源：${rejected.join('；')}`
    return
  }
  uploadingSources.value = true
  busy.value = true
  error.value = ''
  errorCode.value = ''
  message.value = ''
  let revision = project.revision
  let readyAdded = 0
  const failures: string[] = [...rejected]
  try {
    for (let index = 0; index < valid.length; index++) {
      const file = valid[index]!
      sourceProgress.value = `正在上传并本地解析来源 (${index + 1}/${valid.length})：${file.name}…`
      try {
        if (index > 0) {
          const latest = await projectsApi.detail(project.id)
          revision = latest.revision
        }
        const result = await uploadDocument(project.id, file, {
          expected_revision: revision,
          client_request_id: crypto.randomUUID(),
          allow_duplicate: false,
          metadata: { title: null, authors: [], year: null, doi: null },
          restore_version_id: null,
        })
        if (result.document.state === 'ready' || result.document.state === 'partial') readyAdded++
        else failures.push(`${file.name}（${result.operation.message || '未能提取文本'}）`)
      } catch (reason) {
        failures.push(`${file.name}（${reason instanceof Error ? reason.message : '上传失败'}）`)
      }
    }
    await refresh()
    if (readyAdded) message.value = `已添加并解析 ${readyAdded} 份参考来源，项目内对话将自动参考这些文献。`
    if (failures.length) error.value = `部分来源未成功添加：${failures.join('；')}`
  } finally {
    sourceProgress.value = ''
    uploadingSources.value = false
    busy.value = false
  }
}

function onSourceFilesSelected(event: Event) {
  const input = event.target as HTMLInputElement
  if (input.files?.length) void addSources(input.files)
  input.value = ''
}

function onSourceDrop(event: DragEvent) {
  sourceDragging.value = false
  if (event.dataTransfer?.files?.length) void addSources(event.dataTransfer.files)
}

async function downloadArchive() { const p = current.value; if (!p) return; if (archiveFormat.value >= 3 && knowledgeMode.value === 'full') await openConfirm('archive'); else await act(() => exportProject(p, archiveFormat.value, knowledgeMode.value)) }
async function updateProject() {
  const p = current.value
  if (!p) return
  await act(async () => {
    await projectsApi.update(p, editName.value.trim(), editDescription.value)
    editingInfo.value = false
    message.value = '项目信息已更新。'
  })
}
async function renameSnapshot() { const p = current.value, s = snapshot.value; if (p && s) await act(() => projectsApi.renameSnapshot(p, s.id, renameName.value.trim())) }
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
    const openResults = changeUrl || snapshot.value?.id !== value.id
    snapshot.value = value; renameName.value = value.name; tool.value = ''
    if (openResults) {
      resultsOpen.value = true
      if (compactLayout.value) mobilePanel.value = 'results'
    }
    if (openResults && changeUrl) {
      await nextTick()
      document.getElementById('archive-results')?.querySelector<HTMLButtonElement>('.result-close')?.focus({ preventScroll: true })
    }
  } catch (e) { if (token === selection) report(e) }
}
async function openConfirm(kind: typeof action.value) { action.value = kind; await nextTick(); dialog.value?.showModal() }
async function confirm() {
  const kind = action.value, p = current.value, s = snapshot.value
  if (!p) return
  dialog.value?.close(); action.value = ''
  if (kind === 'archive') await act(() => exportProject(p, archiveFormat.value, 'full', true))
  else if (kind === 'project-delete') await act(async () => { await projectsApi.delete(p); snapshot.value = null; await router.push('/projects') })
  else if (kind === 'snapshot-delete' && s) await act(async () => {
    await projectsApi.deleteSnapshot(p, s.id)
    snapshot.value = null
    resultsOpen.value = false
    mobilePanel.value = 'project'
    await router.replace({ query: {} })
  })
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
      message.value = `重跑执行状态：${result.state}；数据状态：${result.response_status || '尚无响应'}。${result.snapshot_id ? '结果已独立保存，未调用模型。' : '本次没有可交付快照，请核对记录。'}`
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
  editingInfo.value = false
  selection++; conversationSelection++; snapshot.value = null; comparison.value = null; current.value = null; documents.value = []
  leftId.value = ''; rightId.value = ''; saveConversation.value = ''; conversationDetail.value = null
  resultsOpen.value = false
  mobilePanel.value = route.params.projectId ? 'project' : 'projects'; error.value = ''; void refresh().catch(report)
}, { immediate: true })
</script>

<template>
  <div class="workspace-panes primary-workspace project-workspace archive-layout" :data-panel="mobilePanel" :data-sidebar-collapsed="sidebarCollapsed" :data-results-open="resultsVisible">
    <WorkspaceHeader title="科研项目" />
    <PanelSwitcher v-model="mobilePanel" label="项目面板" :options="[{ value: 'projects', label: '项目列表' }, { value: 'project', label: '项目空间' }, { value: 'results', label: '快照结果' }]" />
    <aside id="archive-projects" class="project-sidebar" aria-label="项目列表" :inert="!projectsVisible" :aria-hidden="!projectsVisible">
      <div class="project-sidebar-top">
        <button
          type="button"
          class="new-conversation project-create-trigger"
          :disabled="busy || customProjects.length >= 20"
          @click="openCreateProject"
        >
          <span aria-hidden="true">＋</span>新建科研项目
        </button>
      </div>
      <div class="history-title project-sidebar-heading">
        <span class="eyebrow">科研项目</span>
        <span class="small muted">{{ customProjects.length }}/20</span>
      </div>
      <div v-if="error && mobilePanel === 'projects'" class="notice danger" role="alert"><p>{{ error }}</p><code>{{ errorCode }}</code></div>
      <nav class="project-sidebar-list" aria-label="科研项目列表">
        <RouterLink v-if="defaultWorkspace" :to="`/projects/${defaultWorkspace.id}`" class="project-item" :class="{ selected: defaultWorkspace.id === current?.id }">
          <span class="project-item-row"><b>个人空间</b><span class="tag">默认</span></span>
          <small>默认工作区 · r{{ defaultWorkspace.revision }}</small>
        </RouterLink>
        <RouterLink v-for="p in customProjects" :key="p.id" :to="`/projects/${p.id}`" class="project-item" :class="{ selected: p.id === current?.id }">
          <b>{{ p.name }}</b>
          <small>{{ p.provenance === 'imported_unverified' ? '导入 · 未认证' : '科研项目' }} · r{{ p.revision }}</small>
        </RouterLink>
        <p v-if="!customProjects.length" class="small muted project-sidebar-empty">暂无课题项目，点击上方按钮按课题整理会话与文献来源。</p>
      </nav>
      <div class="project-sidebar-utilities">
        <label class="sidebar-import-button">
          <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 15V4m-4 4 4-4 4 4M4 15v3a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-3" /></svg>
          <span>导入备份包 (ZIP)</span>
          <input type="file" accept=".zip,application/zip" aria-label="导入项目备份包" class="sr-only" :disabled="busy" @change="upload">
        </label>
        <p class="small muted">上限 32 MiB，恢复为独立项目。</p>
        <details v-if="unassigned.length" class="unassigned">
          <summary>未归属项目的会话 · {{ unassigned.length }}</summary>
          <div class="unassigned-list">
            <RouterLink v-for="c in unassigned" :key="c.id" :to="`/conversations/${c.id}`">{{ c.title }}</RouterLink>
          </div>
        </details>
      </div>
    </aside>

    <main class="project-main">
      <header class="chat-heading">
        <button class="chat-toolbar-button history-toggle" type="button" :aria-expanded="projectsVisible" aria-controls="archive-projects" :aria-label="projectsVisible ? '收起项目列表' : '展开项目列表'" :title="projectsVisible ? '收起项目列表' : '展开项目列表'" @click="toggleProjects">
          <svg viewBox="0 0 24 24" aria-hidden="true">
            <rect x="3" y="4" width="18" height="16" rx="3" />
            <path d="M9 4v16" />
            <path class="history-toggle-chevron" d="m16 10-2 2 2 2" />
          </svg>
        </button>
        <h1 :title="current?.name || '科研项目'">{{ current ? (isDefaultCurrent ? '个人空间（默认）' : current.name) : '科研项目' }}</h1>
        <button v-show="!resultsVisible" ref="resultsToggle" class="chat-toolbar-button results-toggle" type="button" :aria-expanded="resultsVisible" aria-controls="archive-results" aria-label="打开快照结果" @click="toggleResults">
          <svg viewBox="0 0 24 24" aria-hidden="true">
            <rect x="3" y="4" width="18" height="16" rx="3" />
            <path d="M15 4v16m-8-7 3-2-3-2" />
          </svg>
        </button>
      </header>

      <div class="archive-content" :class="{ 'archive-content-empty': !current && !error && !busy }">
        <div v-if="current" class="project-hub-stack">
          <div v-if="error && (mobilePanel !== 'projects' || sidebarCollapsed)" class="notice danger" role="alert"><p>{{ error }}</p><code v-if="errorCode">{{ errorCode }}</code></div>
          <p v-if="message" class="notice info" role="status">{{ message }}</p>
          <p v-if="busy" class="processing" role="status">{{ sourceProgress || '正在处理，请稍候。不会自动重复提交。' }}</p>
          <div v-if="pending" class="notice"><p>重跑请求尚未确认。先核对项目记录，断线不会取消后台查询。</p><button :disabled="busy" @click="executePending">用原请求编号核对重跑</button></div>

          <section class="project-hero-card">
            <div class="project-hero-top">
              <div class="project-hero-copy">
                <div class="project-hero-meta">
                  <span class="eyebrow">{{ isDefaultCurrent ? '默认个人空间' : '科研项目' }}</span>
                  <span class="tag">修订 r{{ current.revision }}</span>
                  <span v-if="readySourceCount" class="tag">{{ readySourceCount }} 份来源已启用</span>
                </div>
                <h2>{{ isDefaultCurrent ? '个人空间（默认）' : current.name }}</h2>
                <p class="project-hero-desc">{{ current.description || '尚未填写项目说明，可点击「编辑信息」补充课题目标与数据范围。' }}</p>
                <code class="project-hero-id">{{ current.id }}</code>
              </div>
              <div class="project-hero-actions">
                <button type="button" class="button-primary" :disabled="busy" @click="startChatInProject()">在项目中新建对话</button>
                <button type="button" :disabled="busy" @click="sourceFileInput?.click()">添加来源</button>
                <button type="button" :disabled="busy" @click="editingInfo = !editingInfo">{{ editingInfo ? '收起编辑' : '编辑信息' }}</button>
                <button v-if="!isDefaultCurrent" type="button" :disabled="busy" class="button-danger" @click="openConfirm('project-delete')">删除项目</button>
              </div>
            </div>
            <p v-if="current.provenance === 'imported_unverified'" class="notice">导入来源未经认证。哈希只验证包内完整性；历史数据不会因导入而重新查询。</p>
            <form v-if="editingInfo" class="project-form project-edit-panel" @submit.prevent="updateProject">
              <label for="edit-project-name">项目名称</label>
              <input id="edit-project-name" v-model="editName" maxlength="100" required>
              <label for="edit-project-description">项目说明（可选）</label>
              <textarea id="edit-project-description" v-model="editDescription" maxlength="2000" rows="3" />
              <div class="project-actions">
                <button type="button" :disabled="busy" @click="editingInfo = false">取消</button>
                <button type="submit" class="button-primary" :disabled="busy || !editName.trim()">保存修改</button>
              </div>
            </form>
          </section>

          <section
            class="project-card project-sources-card"
            :class="{ 'is-dragging': sourceDragging }"
            @dragenter.prevent="sourceDragging = !busy"
            @dragover.prevent="sourceDragging = !busy"
            @dragleave.prevent="sourceDragging = false"
            @drop.prevent="onSourceDrop"
          >
            <div class="project-card-header">
              <div>
                <h2>参考来源 <span class="small muted">{{ documents.length }} 份</span></h2>
                <p class="small muted">上传 PDF 或 UTF-8 Markdown 到本项目，项目内对话回答会自动参考已就绪的来源片段并注明页码或行号。</p>
              </div>
              <div class="project-card-header-actions">
                <button type="button" :disabled="busy" @click="sourceFileInput?.click()">＋ 添加来源</button>
                <RouterLink :to="`/projects/${current.id}/rag`" class="project-subtle-link">文献问答 →</RouterLink>
                <RouterLink :to="`/projects/${current.id}/knowledge`" class="project-subtle-link">管理知识库 →</RouterLink>
              </div>
              <input
                ref="sourceFileInput"
                type="file"
                multiple
                accept=".pdf,.md,.markdown"
                class="sr-only"
                :disabled="busy"
                @change="onSourceFilesSelected"
              >
            </div>
            <div v-if="documents.length" class="project-source-list">
              <RouterLink
                v-for="doc in documents"
                :key="doc.id"
                :to="`/projects/${current.id}/knowledge/${doc.id}`"
                class="project-source-item"
              >
                <span class="project-source-kind">{{ docKind(doc.filename) }}</span>
                <div class="project-source-info">
                  <b>{{ doc.metadata.title || doc.filename }}</b>
                  <small>{{ doc.filename }} · {{ doc.provenance === 'local' ? '本机来源' : '导入来源' }}</small>
                </div>
                <span class="tag" :class="{ error: doc.state === 'failed' || doc.state === 'unavailable', partial: doc.state === 'partial' }">{{ docStateLabels[doc.state] || doc.state }}</span>
              </RouterLink>
            </div>
            <button v-else type="button" class="project-source-empty" :disabled="busy" @click="sourceFileInput?.click()">
              <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 15V4m-4 4 4-4 4 4M4 15v3a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-3" /></svg>
              <span>点击选择或拖放 PDF / Markdown 文件作为项目参考来源（单文件 ≤ 20 MiB）</span>
            </button>
          </section>

          <section class="project-modules-section" aria-label="科研模块">
            <h2 class="project-block-title">研究工具</h2>
            <div class="project-modules-grid">
              <RouterLink :to="`/projects/${current.id}/knowledge`" class="project-module-card">
                <span class="project-module-top"><b>本地知识库</b><span class="tag">{{ current.document_count }} 份</span></span>
                <small>原文检索、多版本留存与原文定位核对</small>
              </RouterLink>
              <RouterLink :to="`/projects/${current.id}/rag`" class="project-module-card">
                <span class="project-module-top"><b>文献知识问答</b><span class="tag">{{ current.rag_answer_count }} 条</span></span>
                <small>本地混合检索、发送前片段预览与引用回查</small>
              </RouterLink>
              <RouterLink :to="`/projects/${current.id}/plotting`" class="project-module-card">
                <span class="project-module-top"><b>数据绘图</b><span class="tag">交互工作台</span></span>
                <small>审阅脚本、调节样式并导出科研图表</small>
              </RouterLink>
              <RouterLink :to="`/projects/${current.id}/workflows`" class="project-module-card">
                <span class="project-module-top"><b>科研流程</b><span class="tag">{{ current.workflow_count }} 次</span></span>
                <small>固定步骤模板、断点检查与产物下载</small>
              </RouterLink>
              <RouterLink :to="`/projects/${current.id}/compute`" class="project-module-card">
                <span class="project-module-top"><b>N 体模拟</b><span class="tag">数值实验</span></span>
                <small>REBOUND / PeTar 动力学积分与诊断对比</small>
              </RouterLink>
              <RouterLink :to="`/projects/${current.id}/overview`" class="project-module-card">
                <span class="project-module-top"><b>来源关联</b><span class="tag">{{ current.link_count }} 条</span></span>
                <small>建立对话轮次、快照与原文证据的显式映射</small>
              </RouterLink>
            </div>
          </section>

          <section class="project-card">
            <div class="project-card-header">
              <div>
                <h2>项目会话 <span class="small muted">{{ members.length }} 个</span></h2>
                <p class="small muted">项目内的会话在模型回答时会自动参考上方的项目来源。</p>
              </div>
              <button type="button" :disabled="busy" @click="startChatInProject()">＋ 新建对话</button>
            </div>
            <div v-for="c in members" :key="c.id" class="project-row">
              <RouterLink :to="`/conversations/${c.id}`">{{ c.title }} <small class="muted">· {{ c.revision }} 轮</small></RouterLink>
              <button type="button" :disabled="busy" class="button-danger" @click="move(c.id, true)">移出项目</button>
            </div>
            <p v-if="!members.length" class="small muted">尚无关联会话，可点击上方「新建对话」或将已有会话加入本项目。</p>
            <form v-if="movable.length" class="inline-form" @submit.prevent="move(moveId)">
              <label class="sr-only" for="move-conversation">选择要加入的会话</label>
              <select id="move-conversation" v-model="moveId">
                <option value="">选择已有会话加入 / 移动</option>
                <option v-for="c in movable" :key="c.id" :value="c.id">{{ c.title }}{{ memberships[c.id] ? '（从其他项目移动）' : '（未归属项目）' }}</option>
              </select>
              <button type="submit" :disabled="busy || !moveId">加入项目</button>
            </form>
          </section>

          <section class="project-card">
            <h2>命名快照 <span class="small muted">{{ current.snapshots.length }}/100</span></h2>
            <p class="small muted">保存完整交付响应，比较与重跑均保留旧结果。</p>
            <div v-for="s in current.snapshots" :key="s.id" class="snapshot-row" :class="{ selected: snapshot?.id === s.id }">
              <button type="button" :aria-label="`查看快照 ${s.name}`" @click="viewSnapshot(s.id)">
                <b>{{ s.name }}</b>
                <span class="tag">{{ s.status }}</span>
                <small>{{ s.created_at }} · {{ s.id.slice(0, 8) }}</small>
                <small v-if="s.provenance === 'imported_unverified'">导入 · 未认证</small>
              </button>
            </div>
            <p v-if="!current.snapshots.length" class="small muted">尚无快照。</p>
            <details class="project-sub-disclosure">
              <summary>从项目会话保存新快照</summary>
              <form class="project-form" @submit.prevent="save">
                <label for="save-conversation">项目内会话</label>
                <select id="save-conversation" v-model="saveConversation">
                  <option value="">选择会话</option>
                  <option v-for="c in members" :key="c.id" :value="c.id">{{ c.title }}</option>
                </select>
                <label for="save-turn">完整响应轮次</label>
                <select id="save-turn" v-model="saveTurn">
                  <option value="">选择可交付轮次</option>
                  <option v-for="t in deliverable" :key="t.turn_id" :value="t.turn_id">第{{ t.revision }}轮 · {{ t.response_status }} · {{ t.message.slice(0, 50) }}</option>
                </select>
                <label for="snapshot-name">快照名称</label>
                <input id="snapshot-name" v-model="snapshotName" maxlength="100">
                <button type="submit" class="button-primary" :disabled="busy || !saveTurn || !snapshotName.trim()">保存完整快照</button>
              </form>
            </details>
          </section>

          <section v-if="snapshot" class="project-card">
            <h2>当前快照：{{ snapshot.name }}</h2>
            <p class="small"><RouterLink :to="{ path: `/projects/${snapshot.project_id}/overview`, query: { target_type: 'snapshot', target_id: snapshot.id } }">为此快照关联本地原文证据 →</RouterLink></p>
            <code>SHA-256 {{ snapshot.sha256 }}</code>
            <p v-if="!snapshot.conversation_id" class="small muted">原会话已移出项目或删除；完整响应副本仍保留。</p>
            <form class="inline-form" @submit.prevent="renameSnapshot">
              <label class="sr-only" for="rename-snapshot">修改快照名称</label>
              <input id="rename-snapshot" v-model="renameName" maxlength="100">
              <button type="submit" :disabled="busy || !renameName.trim()">快照改名</button>
              <button type="button" :disabled="busy" class="button-danger" @click="openConfirm('snapshot-delete')">删除快照</button>
            </form>
            <details>
              <summary>原始来源与软件版本</summary>
              <pre>{{ format({ origin: snapshot.origin, software: snapshot.software, provenance: snapshot.provenance }) }}</pre>
            </details>
            <div class="project-form">
              <label for="rerun-tool">选择单条工具查询重跑</label>
              <select id="rerun-tool" v-model="tool">
                <option value="">选择查询，先核对参数</option>
                <option v-for="t in tools" :key="t.value" :value="t.value">{{ t.label }}</option>
              </select>
              <template v-if="selectedTool">
                <pre>{{ format({ parameters: selectedTool.parameters, source: selectedTool.source }) }}</pre>
                <p v-if="tool.startsWith('gaia:')" class="notice">Gaia 重跑沿用已记录的实际坐标与参数，不重新解析天体名称。历史来源时间见上方；需要重新解析时请返回对话独立查询 SIMBAD。</p>
                <button type="button" class="button-primary" :disabled="busy || !!pending" @click="openConfirm('rerun')">核对并重跑单条查询</button>
              </template>
            </div>
          </section>

          <details v-if="current.snapshots.length >= 2" class="project-card project-disclosure-card">
            <summary>比较两份快照</summary>
            <div class="project-form">
              <div class="compare-selectors">
                <label>左侧快照<select v-model="leftId"><option value="">选择快照</option><option v-for="s in current.snapshots" :key="s.id" :value="s.id">{{ s.name }} · {{ s.id.slice(0, 8) }}</option></select></label>
                <label>右侧快照<select v-model="rightId"><option value="">选择快照</option><option v-for="s in current.snapshots" :key="s.id" :value="s.id">{{ s.name }} · {{ s.id.slice(0, 8) }}</option></select></label>
              </div>
              <label class="match-identifiers"><input v-model="matchIds" type="checkbox">按精确 source_id / bibcode 比较交付编号</label>
              <button type="button" :disabled="busy || !leftId || !rightId" @click="compare">比较已存快照</button>
              <div v-if="comparison" class="comparison">
                <p v-for="warning in comparison.warnings" :key="warning" class="notice">{{ warning }}</p>
                <div class="comparison-columns">
                  <details open><summary>左侧条件、状态与来源</summary><pre>{{ format(comparison.left) }}</pre></details>
                  <details open><summary>右侧条件、状态与来源</summary><pre>{{ format(comparison.right) }}</pre></details>
                </div>
                <details open><summary>结构化字段差异（{{ comparison.differences.length }}）</summary><pre>{{ format(comparison.differences) }}</pre></details>
                <details><summary>交集与独有编号</summary><pre>{{ format(comparison.identifiers) }}</pre></details>
              </div>
            </div>
          </details>

          <details v-if="current.reruns.length" class="project-card project-disclosure-card">
            <summary>直接重跑记录 · {{ current.reruns.length }} 条</summary>
            <div class="project-form">
              <article v-for="r in current.reruns" :key="r.id" class="rerun-row">
                <span class="tag">{{ r.state }}</span> {{ r.family }} · 数据状态 {{ r.response_status || '尚无响应' }} · <time>{{ r.created_at }}</time>
                <p v-if="r.error" class="notice danger">{{ r.error.message }} · {{ r.error.code }}</p>
                <button v-if="r.snapshot_id" type="button" @click="viewSnapshot(r.snapshot_id)">查看重跑新快照</button>
                <details><summary>实际参数与记录编号</summary><pre>{{ format(r) }}</pre></details>
              </article>
            </div>
          </details>

          <details class="project-card project-disclosure-card project-export-panel">
            <summary>导出项目备份包（ZIP 迁移格式）</summary>
            <div class="project-form">
              <p class="small muted">将本项目的会话、快照、知识库与实验记录打包为 ZIP，便于离线备份或迁移恢复。</p>
              <div class="project-actions">
                <label class="small">备份格式<select v-model="archiveFormat" aria-label="项目备份格式"><option :value="6">格式 6（含数据绘图与文献问答）</option><option :value="5">格式 5（含文献问答，不含绘图）</option><option :value="4" :disabled="!!current?.rag_answer_count || !!current?.rag_request_count">V0.9 格式 4（含显式关联）</option><option :value="3" :disabled="current.link_count > 0 || current.link_request_count > 0 || current.rag_request_count > 0">V0.8 格式 3（无关联历史）</option><option :value="2" :disabled="current.document_count > 0 || current.knowledge_evidence_count > 0 || current.link_count > 0 || current.link_request_count > 0 || current.rag_request_count > 0">V0.7 格式 2（无知识库）</option><option :value="1" :disabled="current.workflow_count > 0 || current.document_count > 0 || current.knowledge_evidence_count > 0 || current.link_count > 0 || current.link_request_count > 0 || current.rag_request_count > 0">V0.6 格式 1（仅无流程项目）</option></select></label>
                <label v-if="archiveFormat >= 3" class="small">文献原文<select v-model="knowledgeMode"><option value="metadata">仅元数据（保留标题、检索词及项目记录）</option><option value="full">完整备份（含全部原文）</option></select></label>
                <button type="button" :disabled="busy" @click="downloadArchive">导出项目备份 ZIP</button>
              </div>
            </div>
          </details>
        </div>

        <div v-else class="project-empty">
          <div v-if="error && (mobilePanel !== 'projects' || sidebarCollapsed)" class="notice danger" role="alert"><p>{{ error }}</p><code v-if="errorCode">{{ errorCode }}</code></div>
          <p v-if="message" class="notice info" role="status">{{ message }}</p>
          <p class="eyebrow">科研项目 · 参考来源 · 课题空间</p>
          <h2>按课题整理你的科研工作</h2>
          <p>为每个研究课题建立独立项目，添加 PDF / Markdown 参考来源；项目内对话会自动参考来源知识，并与绘图、流程、N 体模拟及快照联动。</p>
          <div class="project-empty-actions">
            <button type="button" class="button-primary" :disabled="busy || customProjects.length >= 20" @click="openCreateProject">新建科研项目</button>
            <RouterLink v-if="defaultWorkspace" :to="`/projects/${defaultWorkspace.id}`" class="project-empty-secondary">打开个人空间</RouterLink>
            <button v-if="sidebarCollapsed" class="chat-toolbar-button archive-sidebar-toggle" type="button" @click="sidebarCollapsed = false">展开项目列表</button>
          </div>
        </div>
      </div>
    </main>

    <ResultPanel
      id="archive-results"
      :inert="!resultsVisible"
      :aria-hidden="!resultsVisible"
      :turn="snapshotTurn"
      :historical="!!snapshot"
      :heading="snapshot?.name || '快照结果'"
      :artifact-path="snapshot ? `/api/v1/projects/${snapshot.project_id}/snapshots/${snapshot.id}/artifacts` : undefined"
      dismissible
      @close="closeResults"
    >
      <template #empty>
        <h3>尚未选择快照</h3>
        <p>在项目记录中选择一份命名快照，即可查看保存的数据、来源、图表与导出选项。</p>
      </template>
    </ResultPanel>

    <CreateProjectDialog ref="createDialog" :default-start-chat="false" @created="onProjectCreated" />

    <dialog ref="dialog" class="project-dialog" @close="action = ''" @cancel="action = ''">
      <div class="dialog-header">
        <div class="dialog-header-copy">
          <h2>{{ action === 'archive' ? '导出含文献原文的完整备份？' : action === 'rerun' ? '确认执行这条工具查询？' : action === 'project-delete' ? '删除这个科研项目？' : '删除这份命名快照？' }}</h2>
        </div>
        <button type="button" class="dialog-close" aria-label="关闭" :disabled="busy" @click="dialog?.close()">
          <svg viewBox="0 0 24 24" aria-hidden="true"><path d="m6 6 12 12M6 18 18 6" /></svg>
        </button>
      </div>
      <form class="project-form" @submit.prevent="confirm">
        <template v-if="action === 'archive'">
          <p>将复制 {{ current?.document_count || 0 }} 份文档、{{ current?.document_version_count || 0 }} 个版本，原文件合计 {{ current?.document_bytes || 0 }} 字节，连同项目记录写入 ZIP。文件将包含你的文献原文，请自行管理下载副本。</p>
        </template>
        <template v-else-if="action === 'rerun'">
          <p>将按下列参数访问真实数据源，保存独立轮次和快照。旧响应不覆盖；本操作不调用语言模型，断线不代表取消。</p>
          <pre>{{ format(selectedTool) }}</pre>
        </template>
        <p v-else-if="action === 'project-delete'">将删除此项目、{{ current?.rag_answer_count || 0 }} 条文献问答、命名快照、重跑记录、{{ current?.workflow_count || 0 }} 次科研流程、{{ current?.link_count || 0 }} 条关联以及知识库原文与索引；会话及历史轮次保留并恢复为未归属项目。</p>
        <p v-else>只删除这份快照，原会话和轮次保留。</p>
        <div class="project-actions">
          <button type="button" :disabled="busy" @click="dialog?.close()">取消</button>
          <button :disabled="busy" :class="action === 'project-delete' || action === 'snapshot-delete' ? 'button-danger' : 'button-primary'" type="submit">
            {{ action === 'archive' ? '确认导出全部原文' : action === 'rerun' ? '确认访问数据源并重跑' : '确认删除' }}
          </button>
        </div>
      </form>
    </dialog>
  </div>
</template>

<style scoped>
.project-sidebar-top {
  flex: none;
  margin-bottom: 14px;
}

.project-create-trigger {
  width: 100%;
  height: 40px;
  min-height: 40px;
  margin: 0;
  padding: 8px 12px;
  font-size: 13px;
}

.project-sidebar-heading {
  margin: 0 6px 8px;
}

.project-sidebar-list {
  display: grid;
  gap: 3px;
}

.project-item-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.project-sidebar-empty {
  padding: 10px 8px;
  line-height: 1.65;
}

.project-sidebar-utilities {
  margin-top: auto;
  padding-top: 16px;
  border-top: 1px solid var(--line);
  display: grid;
  gap: 8px;
}

.sidebar-import-button {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  min-height: 36px;
  padding: 7px 12px;
  border: 1px solid var(--line-strong);
  border-radius: var(--radius-control);
  background: var(--paper);
  color: var(--ink);
  font-size: 12.5px;
  font-weight: 500;
  cursor: pointer;
  transition: background-color var(--duration-fast) var(--ease-out), border-color var(--duration-fast) var(--ease-out);
}

.sidebar-import-button:hover {
  background: var(--soft);
  border-color: var(--accent);
}

.sidebar-import-button svg {
  width: 15px;
  height: 15px;
  fill: none;
  stroke: var(--accent);
  stroke-width: 1.7;
  stroke-linecap: round;
  stroke-linejoin: round;
}

.unassigned {
  margin-top: 4px;
  padding-top: 10px;
  border-top: 1px solid var(--line);
}

.unassigned summary {
  font-size: 12px;
  font-weight: 550;
  color: var(--muted);
  cursor: pointer;
}

.unassigned-list {
  display: grid;
  gap: 6px;
  margin-top: 8px;
  max-height: 180px;
  overflow-y: auto;
}

.unassigned-list a {
  margin-top: 0;
  padding: 5px 8px;
  border-radius: 7px;
  font-size: 12px;
  color: var(--ink);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.unassigned-list a:hover {
  background: var(--accent-soft);
  color: var(--accent);
  text-decoration: none;
}

.project-hub-stack {
  width: 100%;
  max-width: 960px;
  margin: 0 auto;
  display: grid;
  gap: 20px;
  padding-bottom: 24px;
}

.project-hero-card,
.project-card {
  padding: 22px 24px;
  border: 1px solid var(--line);
  border-radius: var(--radius-surface);
  background: var(--paper);
  box-shadow: var(--shadow-card);
}

.project-hero-card {
  background: var(--surface-elevated);
}

.project-hero-top {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 20px;
  flex-wrap: wrap;
}

.project-hero-copy {
  flex: 1 1 320px;
  min-width: 0;
  display: grid;
  gap: 8px;
}

.project-hero-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.project-hero-copy h2 {
  font-size: 22px;
  font-weight: 600;
  letter-spacing: -0.015em;
  color: var(--ink);
  overflow-wrap: anywhere;
}

.project-hero-desc {
  color: var(--muted);
  font-size: 13.5px;
  line-height: 1.7;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}

.project-hero-id {
  color: var(--muted);
  font-size: 11px;
  opacity: 0.8;
}

.project-hero-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.project-edit-panel {
  margin-top: 18px;
  padding-top: 18px;
  border-top: 1px solid var(--line);
}

.project-card-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 14px;
  flex-wrap: wrap;
  margin-bottom: 14px;
}

.project-card-header h2,
.project-card > h2 {
  font-size: 16px;
  font-weight: 600;
  color: var(--ink);
  margin: 0 0 4px;
}

.project-card-header-actions {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.project-subtle-link {
  font-size: 12.5px;
  font-weight: 500;
  color: var(--accent);
}

.project-sources-card.is-dragging {
  border-color: var(--accent);
  background: var(--accent-soft);
}

.project-source-list {
  display: grid;
  gap: 8px;
}

.project-source-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 12px;
  border: 1px solid var(--line);
  border-radius: 10px;
  background: var(--surface-evidence);
  color: var(--ink);
  text-decoration: none;
  transition: border-color var(--duration-fast) var(--ease-out), background-color var(--duration-fast) var(--ease-out);
}

.project-source-item:hover {
  border-color: var(--line-strong);
  background: var(--soft);
  text-decoration: none;
}

.project-source-kind {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 36px;
  height: 24px;
  padding: 0 7px;
  border-radius: 6px;
  background: var(--accent-soft);
  color: var(--accent);
  font-size: 10.5px;
  font-weight: 650;
  letter-spacing: 0.04em;
  flex: none;
}

.project-source-info {
  flex: 1;
  min-width: 0;
  display: grid;
  gap: 2px;
}

.project-source-info b {
  font-size: 13px;
  font-weight: 550;
  color: var(--ink);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.project-source-info small {
  font-size: 11.5px;
  color: var(--muted);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.project-source-empty {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
  width: 100%;
  min-height: 64px;
  padding: 14px 18px;
  border: 1.5px dashed var(--line-strong);
  border-radius: 10px;
  background: var(--surface-evidence);
  color: var(--muted);
  font-size: 13px;
  box-shadow: none;
}

.project-source-empty:hover:not(:disabled) {
  border-color: var(--accent);
  background: var(--accent-soft);
  color: var(--ink);
}

.project-source-empty svg {
  width: 18px;
  height: 18px;
  flex: none;
  fill: none;
  stroke: var(--accent);
  stroke-width: 1.7;
  stroke-linecap: round;
  stroke-linejoin: round;
}

.project-block-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--muted);
  margin: 0 0 10px;
}

.project-modules-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
}

.project-module-card {
  display: grid;
  gap: 6px;
  padding: 15px 16px;
  border: 1px solid var(--line);
  border-radius: 12px;
  background: var(--paper);
  color: var(--ink);
  text-decoration: none;
  transition: border-color var(--duration-fast) var(--ease-out), box-shadow var(--duration-fast) var(--ease-out), transform var(--duration-fast) var(--ease-out);
}

.project-module-card:hover {
  border-color: var(--accent);
  box-shadow: var(--shadow-card-hover);
  transform: translateY(-1px);
  text-decoration: none;
}

.project-module-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.project-module-top b {
  font-size: 14px;
  font-weight: 600;
  color: var(--ink);
}

.project-module-card small {
  font-size: 12px;
  color: var(--muted);
  line-height: 1.55;
}

.project-sub-disclosure {
  margin-top: 14px;
  padding-top: 12px;
  border-top: 1px solid var(--line);
}

.project-disclosure-card {
  padding: 16px 22px;
}

.project-disclosure-card > summary {
  font-size: 14.5px;
  font-weight: 600;
  color: var(--ink);
  cursor: pointer;
}

.project-empty-actions {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
  flex-wrap: wrap;
  margin-top: 22px;
}

.project-empty-actions > button {
  margin-top: 0;
}

.project-empty-secondary {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-height: 36px;
  padding: 8px 16px;
  border: 1px solid var(--line-strong);
  border-radius: var(--radius-control);
  background: var(--paper);
  color: var(--ink);
  font-size: 13px;
  font-weight: 500;
  text-decoration: none;
}

.project-empty-secondary:hover {
  background: var(--soft);
  text-decoration: none;
}

@media (max-width: 1120px) {
  .project-modules-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 680px) {
  .project-hero-card,
  .project-card {
    padding: 16px;
  }

  .project-modules-grid {
    grid-template-columns: minmax(0, 1fr);
  }
}
</style>
