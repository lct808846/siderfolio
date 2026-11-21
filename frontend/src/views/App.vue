<script setup lang="ts">
import WorkspaceHeader from '../components/WorkspaceHeader.vue'
import InteractionHints from '../components/InteractionHints.vue'
import ModelSelector from '../components/ModelSelector.vue'
import ModelChangeNotice from '../components/ModelChangeNotice.vue'
import ConversationErrorNotice from '../components/ConversationErrorNotice.vue'
import ContextNotice from '../components/ContextNotice.vue'
import AttachmentButton from '../components/AttachmentButton.vue'
import AttachmentTray from '../components/AttachmentTray.vue'
import ConversationSidebar from '../components/ConversationSidebar.vue'
import { onMounted, onBeforeUnmount, provide, ref, watch, computed, nextTick } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useWorkbench } from '../stores/workbench'
import { useModels } from '../stores/models'
import { useAttachments } from '../stores/attachments'
import { useProjects } from '../stores/projects'
import ResultPanel from '../components/ResultPanel.vue'
import MarkdownAnswer from '../components/MarkdownAnswer'
import UserMessage from '../components/UserMessage.vue'
import ProjectWorkspace from './ProjectWorkspace.vue'
import WorkflowWorkspace from './WorkflowWorkspace.vue'
import ComputeWorkspace from './ComputeWorkspace.vue'
import KnowledgeWorkspace from './KnowledgeWorkspace.vue'
import ProjectOverview from './ProjectOverview.vue'
import RagWorkspace from './RagWorkspace.vue'
import WorkbenchPlot from '../components/WorkbenchPlot.vue'
import LocalAssistantWorkspace from './LocalAssistantWorkspace.vue'
import ProfileWorkspace from './ProfileWorkspace.vue'
import LocalTitleStatus from '../components/LocalTitleStatus.vue'
import { safeLink } from '../api'
import { computeApi, setComputeHandoff, type ComputeStatus } from '../api/compute'
import { takeWorkbenchDraft } from '../research-handoff'
import { readResultsPanelStates, saveResultsPanelStates } from '../conversation-panel-state'

const store = useWorkbench(), route = useRoute(), router = useRouter()
const models = useModels()
const attachments = useAttachments()
const projectsStore = useProjects()
const unarchiving = ref(false)
const dragDepth = ref(0)
const draft = ref(''), composing = ref(false)
const profileMode = computed(() => route.path === '/profile')
const plotMode = computed(() => !profileMode.value && route.query.mode === 'plot')
const openedPlot = ref(false), plotDraft = ref('')
const plotPanel = ref<InstanceType<typeof WorkbenchPlot> | null>(null)
const nbodyDialog = ref<HTMLDialogElement | null>(null)
const nbodyProject = ref('')
const nbodyLoading = ref(false)
const nbodyError = ref('')
const computeStatus = ref<ComputeStatus | null>(null)
const computeDisabled = computed(() => computeStatus.value !== null && !computeStatus.value.enabled)
const nbodySpaces = computed(() => {
  const items: Array<{ id: string; label: string }> = []
  if (projectsStore.defaultProject) items.push({ id: projectsStore.defaultProject.id, label: '个人空间（默认）' })
  for (const project of projectsStore.customProjects) items.push({ id: project.id, label: project.name })
  return items
})
async function openNbody() {
  nbodyError.value = ''
  nbodyLoading.value = true
  try {
    await projectsStore.load(true)
    const fallback = await projectsStore.ensureDefault()
    if (!projectsStore.customProjects.length) {
      setComputeHandoff(fallback.id, draft.value || store.turns.at(-1)?.message || '', currentModel.value || undefined)
      void router.push('/compute')
      return
    }
    const preferred = projectsStore.memberships[conversationId.value] || fallback.id
    nbodyProject.value = nbodySpaces.value.some(item => item.id === preferred) ? preferred : fallback.id
    nbodyDialog.value?.showModal()
  } catch (reason) {
    nbodyError.value = reason instanceof Error ? reason.message : '暂时无法准备计算空间。'
    nbodyDialog.value?.showModal()
  } finally { nbodyLoading.value = false }
}
function nbodyContinue() {
  if (!nbodyProject.value) return
  setComputeHandoff(nbodyProject.value, draft.value || store.turns.at(-1)?.message || '', currentModel.value || undefined)
  nbodyDialog.value?.close()
  if (nbodyProject.value === projectsStore.defaultProjectId) void router.push('/compute')
  else void router.push(`/projects/${nbodyProject.value}/compute`)
}
watch(() => route.fullPath, () => nbodyDialog.value?.close())
const composerDraft = computed({ get: () => plotMode.value ? plotDraft.value : draft.value, set: value => { if (plotMode.value) plotDraft.value = value; else draft.value = value } })
const plotBusy = computed(() => !!plotPanel.value?.busy)
const plotReady = computed(() => !!plotPanel.value?.canPrepare)
const plotHint = computed(() => plotPanel.value?.readinessHint || '')
watch(plotMode, value => { if (value) openedPlot.value = true }, { immediate: true })
async function togglePlot() {
  if (store.running || store.creating || store.loading || sending.value || store.disconnectedRequest) return
  const query = { ...route.query }
  if (plotMode.value) delete query.mode
  else query.mode = 'plot'
  await router.replace({ path: route.path, query })
  await nextTick(); resizeComposer(); input.value?.focus()
}
async function submitComposer() {
  if (!plotMode.value) return send()
  if (!plotReady.value || !plotDraft.value.trim()) return
  const text = plotDraft.value
  const done = await plotPanel.value?.submitQuestion(text)
  if (done && plotDraft.value === text) plotDraft.value = ''
}
const editingTurn = ref<number | null>(null), draftBeforeEdit = ref('')
const sending = ref(false)
const input = ref<HTMLTextAreaElement | null>(null)
const compactLayout = ref(false), sidebarCollapsed = ref(false)
const resultsToggle = ref<HTMLButtonElement | null>(null)
const resultsPanelStates = readResultsPanelStates()
const restoringResults = ref(true)
const conversationId = computed(() => typeof route.params.id === 'string' ? route.params.id : '')
const currentProject = computed(() => conversationId.value ? projectsStore.projectFor(conversationId.value) : null)
const currentProjectSources = computed(() => currentProject.value ? projectsStore.sourceCounts[currentProject.value.id] : undefined)
watch(() => currentProject.value?.id, projectId => {
  if (projectId) {
    projectsStore.setActiveProject(projectId)
    if (projectsStore.sourceCounts[projectId] === undefined) {
      void projectsStore.refreshSourceCount(projectId).catch(() => undefined)
    }
  }
}, { immediate: true })
const currentArchived = computed(() => !!conversationId.value && store.archived.some(item => item.id === conversationId.value))
async function restoreCurrentConversation() {
  if (!conversationId.value || unarchiving.value) return
  unarchiving.value = true
  try { await store.unarchiveConversation(conversationId.value) }
  catch (reason) { store.report(reason) }
  finally { unarchiving.value = false }
}
const conversationReady = computed(() => !conversationId.value || store.current?.id === conversationId.value)
const modelScope = computed(() => conversationId.value || 'draft')
const plotDrafts = new Map<string, string>()
watch(modelScope, (scope, previous) => { plotDrafts.set(previous, plotDraft.value); plotDraft.value = plotDrafts.get(scope) || '' })
const currentModel = computed(() => models.modelFor(modelScope.value, conversationReady.value ? store.turns.at(-1)?.model : undefined))
// Only a completed reply establishes a model change in the timeline.
const conversationTimeline = computed(() => {
  let previous: string | undefined
  return store.turns.map(turn => {
    const replied = turn.execution_status === 'completed' && !!turn.response
    const modelChange = replied && previous && turn.model && previous !== turn.model ? { from: previous, to: turn.model } : null
    if (replied) previous = turn.model || undefined
    return { turn, modelChange }
  })
})
function selectModel(id: string) {
  if (id === currentModel.value) return
  models.select(modelScope.value, id)
}
const attachedFiles = computed(() => attachments.ready(modelScope.value))
const attachmentDisabled = computed(() => plotMode.value || sending.value || store.running || store.creating || store.loading || !!store.disconnectedRequest)
function dragFiles(event: DragEvent) { return Array.from(event.dataTransfer?.types || []).includes('Files') }
function dragEnter(event: DragEvent) { if (dragFiles(event)) { event.preventDefault(); if (!attachmentDisabled.value) dragDepth.value++ } }
function dragOver(event: DragEvent) { if (dragFiles(event)) { event.preventDefault(); if (event.dataTransfer) event.dataTransfer.dropEffect = attachmentDisabled.value ? 'none' : 'copy' } }
function dropFiles(event: DragEvent) {
  if (!dragFiles(event)) return
  event.preventDefault(); dragDepth.value = 0
  if (!attachmentDisabled.value) void attachments.add(modelScope.value, Array.from(event.dataTransfer?.files || []))
}
const conversationTitle = computed(() => conversationId.value
  ? (store.current?.id === conversationId.value ? store.current.title : store.conversations.find(item => item.id === conversationId.value)?.title) || '会话'
  : '新会话')
const showWelcome = computed(() => conversationReady.value && !store.loading && !store.turns.length && !store.pending
  && (!conversationId.value || !!store.current) && !store.error)
const completedResults = computed(() => store.turns.filter(turn => turn.response && turn.execution_status === 'completed'))
let knownResults = new Set<string>()
let restoreFrame = 0, restoreRevision = 0
const historyVisible = computed(() => compactLayout.value ? store.panel === 'history' : !sidebarCollapsed.value)
let layoutQuery: MediaQueryList | undefined
function updateLayout() { compactLayout.value = layoutQuery?.matches || false }
function toggleHistory() {
  if (compactLayout.value) store.panel = store.panel === 'history' ? 'chat' : 'history'
  else sidebarCollapsed.value = !sidebarCollapsed.value
}
function rememberResults(open: boolean) {
  const id = route.params.id
  if (typeof id !== 'string') return
  resultsPanelStates.delete(id)
  resultsPanelStates.set(id, open)
  saveResultsPanelStates(resultsPanelStates)
}
async function openResults(turnId?: string) {
  const id = route.params.id
  if (turnId) store.selectedTurnId = turnId
  rememberResults(true)
  store.panel = 'results'
  await nextTick()
  if (route.params.id === id && store.panel === 'results') document.getElementById('workbench-results')?.querySelector<HTMLButtonElement>('.result-close')?.focus({ preventScroll: true })
}
async function closeResults() {
  const id = route.params.id
  rememberResults(false); store.panel = 'chat'
  await nextTick()
  if (route.params.id === id && store.panel === 'chat') resultsToggle.value?.focus({ preventScroll: true })
}
function toggleResults() { if (store.panel === 'results') void closeResults(); else void openResults() }
function resizeComposer() {
  const field = input.value
  if (!field) return
  field.style.height = 'auto'
  field.style.height = `${Math.min(144, Math.max(50, field.scrollHeight))}px`
}
watch(composerDraft, async () => { await nextTick(); resizeComposer() })
watch(() => store.panel, async () => { await nextTick(); resizeComposer() })
// Desktop reveal leaves typing focus alone; a compact panel needs an accessible return action.
function revealResultsAutomatically() {
  const id = route.params.id
  rememberResults(true)
  store.panel = 'results'
  if (compactLayout.value) void nextTick(() => {
    if (route.params.id === id && store.panel === 'results' && !document.querySelector('dialog[open]')) document.getElementById('workbench-results')?.querySelector<HTMLButtonElement>('.result-close')?.focus({ preventScroll: true })
  })
}
function revealNewResults() {
  if (restoringResults.value || !store.current || store.current.id !== route.params.id) return
  const fresh = completedResults.value.some(turn => !knownResults.has(turn.turn_id))
  for (const turn of completedResults.value) knownResults.add(turn.turn_id)
  if (fresh) revealResultsAutomatically()
}
watch(completedResults, revealNewResults)
let appliedTurnLink = '', requestedTurnLink = ''
watch([() => route.fullPath, () => store.turns], () => {
  const turnId = typeof route.query.turn === 'string' ? route.query.turn : ''
  const key = `${route.params.id || ''}:${turnId}`
  if (key !== requestedTurnLink) { appliedTurnLink = ''; requestedTurnLink = key }
  if (turnId && appliedTurnLink !== key && store.current?.id === route.params.id && store.turns.some(t => t.turn_id === turnId)) { void openResults(turnId); appliedTurnLink = key }
  if (!turnId) appliedTurnLink = ''
})
const newest = computed(() => store.turns.at(-1)?.turn_id)
const examples = [
  {
    badge: 'Gaia DR3',
    badgeClass: 'ui-pill-gaia',
    label: '坐标圆锥查询',
    summary: '以 ICRS 坐标为中心检索 5 角分内 Gaia DR3 位置候选源与基础统计。',
    text: '以 ICRS 赤经56.75度、赤纬24.12度为中心，查5角分内最近100个Gaia DR3位置候选源，不估算距离。',
  },
  {
    badge: 'DR3 编号',
    badgeClass: 'ui-pill-simbad',
    label: '指定源精确测量',
    summary: '按 Gaia DR3 source_id 精确核查天体测量与高信噪比视差距离近似。',
    text: '查询 Gaia DR3 source_id 5853498713190525696 的测量信息并估算距离，说明近似条件。',
  },
  {
    badge: 'ADS 文献',
    badgeClass: 'ui-pill-ads',
    label: '近期论文与来源检索',
    summary: '按年份与发表日期降序检索 ADS 天文文献摘要，保留可追溯 bibcode。',
    text: '检索2020—2026年双星团相关论文，取3篇，按发表日期降序，给出来源。',
  },
]
let preparingConversation = false
async function create() {
  // Share the guard across the sidebar and brand, including router navigation.
  if (preparingConversation || sending.value) return
  preparingConversation = true
  try {
    const origin = route.fullPath
    const id = await store.create(false)
    if (id !== undefined && route.fullPath === origin) {
      if (id && id === route.params.id) rememberResults(false)
      const destination = id ? `/conversations/${id}` : '/'
      if (route.fullPath !== destination) await router.push(destination)
    }
    return id ?? undefined
  } finally {
    store.preparedConversation = null
    preparingConversation = false
  }
}
provide('astroagent.create-conversation', create)
async function afterRemoval(ids: string[]) {
  for (const id of ids) attachments.clear(id)
  models.forget(ids)
  for (const id of ids) resultsPanelStates.delete(id)
  saveResultsPanelStates(resultsPanelStates)
  if (typeof route.params.id === 'string' && ids.includes(route.params.id)) await router.push('/')
}
async function send() {
  const originalDraft = draft.value
  const sourceScope = modelScope.value
  const files = attachedFiles.value
  const message = originalDraft.trim() ? originalDraft : files.length ? '请阅读附件并概括要点。' : ''
  const selectedModel = currentModel.value
  if (!message.trim() || attachments.blocked(sourceScope) || !selectedModel || !models.configured || models.loading || store.running || store.creating || store.loading || sending.value || preparingConversation) return
  sending.value = true
  try {
    let id = store.current?.id
    if (!id) {
      const origin = route.fullPath
      id = (await store.create()) ?? undefined
      if (!id || route.fullPath !== origin) return
      models.select(id, selectedModel)
      attachments.move(sourceScope, id)
      await router.push(`/conversations/${id}`)
    }
    if (!id || route.path !== `/conversations/${id}` || store.current?.id !== id) return
    draft.value = ''
    models.select(id, selectedModel)
    await store.send(message, id, selectedModel, files)
    if (store.error && !store.disconnectedRequest) draft.value = originalDraft
    else {
      if (!store.disconnectedRequest) attachments.clear(id)
      editingTurn.value = null; draftBeforeEdit.value = ''
    }
    input.value?.focus()
  } finally { sending.value = false }
}
function keydown(event: KeyboardEvent) { if (event.key === 'Enter' && !event.shiftKey && !event.isComposing && !composing.value) { event.preventDefault(); void submitComposer() } }
function useExample(text: string) { draft.value = text; input.value?.focus() }
async function editQuestion(text: string, revision: number, conversationId: string) {
  if (store.running || store.creating || store.loading || sending.value || store.disconnectedRequest) return
  if (store.current?.id !== conversationId || route.params.id !== conversationId) return
  if (editingTurn.value === null) draftBeforeEdit.value = draft.value
  editingTurn.value = revision; draft.value = text
  await nextTick(); resizeComposer(); input.value?.focus()
  input.value?.setSelectionRange(text.length, text.length)
}
async function cancelEdit() {
  draft.value = draftBeforeEdit.value; draftBeforeEdit.value = ''; editingTurn.value = null
  await nextTick(); resizeComposer(); input.value?.focus()
}
watch(() => route.params.id, () => { dragDepth.value = 0; editingTurn.value = null; draftBeforeEdit.value = '' })
watch(() => store.disconnectedRequest, (current, previous) => { if (!current && previous) attachments.clear(previous.id) })
watch(() => route.params.id, async id => {
  const revision = ++restoreRevision
  cancelAnimationFrame(restoreFrame)
  restoringResults.value = true
  knownResults = new Set()
  // Apply saved geometry before fetching history; loading must not replay an open animation.
  store.panel = typeof id === 'string' && resultsPanelStates.get(id) === true ? 'results' : 'chat'
  if (typeof id === 'string') {
    if (store.preparedConversation?.id === id) {
      store.$patch({ current: store.preparedConversation, preparedConversation: null, turns: [], selectedTurnId: '', loading: false, error: '', errorCode: '' })
    }
    if (id !== store.current?.id) await store.load(id)
    if (revision !== restoreRevision) return
    if (store.current?.id === id) {
      const open = resultsPanelStates.get(id) ?? (completedResults.value.length > 0)
      store.panel = open ? 'results' : 'chat'
      rememberResults(open)
      knownResults = new Set(completedResults.value.map(turn => turn.turn_id))
    }
  } else {
    store.$patch({ loadToken: store.loadToken + 1, current: null, preparedConversation: null, turns: [], selectedTurnId: '', loading: false, error: '', errorCode: '' })
  }
  await nextTick()
  if (revision !== restoreRevision) return
  // Paint the restored state with transitions disabled, then allow manual/new-result motion.
  restoreFrame = requestAnimationFrame(() => {
    if (revision !== restoreRevision) return
    restoreFrame = requestAnimationFrame(() => {
      if (revision !== restoreRevision) return
      restoringResults.value = false
      revealNewResults()
    })
  })
}, { immediate: true, flush: 'sync' })
async function applyWorkbenchHandoff() {
  if (route.path !== '/' && !route.path.startsWith('/conversations/')) return
  const handed = takeWorkbenchDraft()
  if (!handed) return
  draft.value = handed
  await nextTick()
  resizeComposer()
  input.value?.focus()
}
watch(() => route.fullPath, () => { void applyWorkbenchHandoff() }, { immediate: true })
onMounted(async () => {
  layoutQuery = window.matchMedia('(max-width: 980px)')
  updateLayout(); layoutQuery.addEventListener('change', updateLayout)
  window.addEventListener('resize', resizeComposer)
  resizeComposer()
  void applyWorkbenchHandoff()
  void computeApi.status().then(status => { computeStatus.value = status }).catch(() => undefined)
  try {
    await Promise.all([store.refreshList(), models.load()])
    void store.refreshArchived().catch(() => undefined)
    void projectsStore.load().catch(() => undefined)
  } catch (error) { store.report(error) }
})
onBeforeUnmount(() => {
  nbodyDialog.value?.close()
  restoreRevision++
  cancelAnimationFrame(restoreFrame)
  layoutQuery?.removeEventListener('change', updateLayout)
  window.removeEventListener('resize', resizeComposer)
})
</script>

<template>
  <InteractionHints />
  <LocalAssistantWorkspace v-if="route.path==='/local-assistant'" />
  <RagWorkspace v-else-if="route.path.endsWith('/rag')" />
  <ProjectOverview v-else-if="route.path.endsWith('/overview')" />
  <KnowledgeWorkspace v-else-if="route.path.includes('/knowledge')" />
  <WorkflowWorkspace v-else-if="route.path.includes('/workflows')" />
  <ComputeWorkspace v-else-if="route.path.includes('/compute')" />
  <ProjectWorkspace v-else-if="route.path.startsWith('/projects')" />
  <div v-else class="workbench workspace-panes primary-workspace conversation-layout" :data-panel="profileMode || plotMode ? 'chat' : store.panel" :data-sidebar-collapsed="sidebarCollapsed" :data-results-open="!profileMode && !plotMode && store.panel==='results'" :data-results-restoring="restoringResults">
    <WorkspaceHeader title="本地科研工作台" />
    <ConversationSidebar id="conversation-history" :inert="!historyVisible" :aria-hidden="!historyVisible" @create="create" @removed="afterRemoval" />
    <main class="chat-panel">
      <header class="chat-heading">
        <button type="button" class="chat-toolbar-button history-toggle" :aria-expanded="historyVisible" aria-controls="conversation-history" :aria-label="historyVisible ? '收起会话列表' : '展开会话列表'" :title="historyVisible ? '收起会话列表' : '展开会话列表'" @click="toggleHistory"><svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="4" width="18" height="16" rx="3" /><path d="M9 4v16" /><path class="history-toggle-chevron" d="m16 10-2 2 2 2" /></svg></button>
        <h1 :title="profileMode ? '个人资料' : conversationTitle">{{ profileMode ? '个人资料' : conversationTitle }}</h1>
        <RouterLink
          v-if="!profileMode && currentProject"
          :to="`/projects/${currentProject.id}`"
          class="chat-project-pill"
          :data-tooltip="currentProjectSources ? `所属项目：${currentProject.name}（回答时自动参考 ${currentProjectSources} 份项目来源）` : `所属项目：${currentProject.name}（点击查看或添加参考来源）`"
        >
          <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 7V5a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2Z" /></svg>
          <span class="chat-project-pill-name">{{ currentProject.name }}</span>
          <span v-if="currentProjectSources" class="chat-project-pill-sources">{{ currentProjectSources }} 份来源</span>
        </RouterLink>
        <LocalTitleStatus v-if="!profileMode" silent :conversation-id="conversationId" :has-message="!!store.turns.length || store.pending" :submitting="store.pending" />
        <button
          v-show="!profileMode && !plotMode && store.panel !== 'results'"
          ref="resultsToggle"
          type="button"
          class="chat-toolbar-button results-toggle"
          :aria-expanded="store.panel === 'results'"
          aria-controls="workbench-results"
          aria-label="打开结果栏"
          @click="toggleResults">
          <svg viewBox="0 0 24 24" aria-hidden="true">
            <rect x="3" y="4" width="18" height="16" rx="3" />
            <path d="M15 4v16m-8-7 3-2-3-2" />
          </svg>
        </button>
      </header>
      <ProfileWorkspace v-if="profileMode" />
      <template v-else>
        <div v-if="currentArchived" class="archived-banner" role="status">
          <span>此会话已归档，当前处于收纳状态。继续发送消息或取消归档将恢复至左侧会话列表。</span>
          <button type="button" :disabled="unarchiving" @click="restoreCurrentConversation">{{ unarchiving ? '正在恢复…' : '取消归档' }}</button>
        </div>
        <ConversationErrorNotice v-if="store.error" class="global-error" :message="store.error" :code="store.errorCode" current :busy="store.running || store.loading" :can-retry="!!draft.trim() && !store.disconnectedRequest" @retry="send" />
      <div v-if="store.disconnectedRequest" class="notice"><p>断线前的问题尚未确认。先恢复会话；若仍未显示，可用原请求编号重新核对，避免重复执行。</p><button @click="store.resendSameRequest">用原请求编号核对</button></div>
      <div v-show="!plotMode" class="chat-scroll" :class="{'chat-scroll-empty':showWelcome}" :aria-busy="store.loading" aria-live="polite">
        <div v-if="store.loading && !store.turns.length" class="conversation-loading" role="status">
          <p class="small muted">正在读取会话…</p>
          <div class="conversation-loading-question" aria-hidden="true"></div>
          <div class="conversation-loading-answer" aria-hidden="true"><span></span><span></span><span></span></div>
        </div>
        <div v-else-if="showWelcome" class="welcome">
          <div class="welcome-intro">
            <div class="welcome-copy">
              <div class="ui-pill-list" style="justify-content: center; margin-bottom: 14px;">
                <span class="ui-pill ui-pill-simbad">SIMBAD · 天体目标</span>
                <span class="ui-pill ui-pill-gaia">Gaia DR3 · 天体测量</span>
                <span class="ui-pill ui-pill-ads">ADS · 学术文献</span>
              </div>
              <h2>天文数据与文献检索</h2>
              <p>查询天体、Gaia DR3 测量和学术论文，自动保留每轮数据来源、统计与可复现导出。</p>
            </div>
          </div>
          <div v-if="currentProject" class="welcome-project-banner">
            <span>
              <template v-if="currentProjectSources">当前会话属于科研项目「{{ currentProject.name }}」，已启用 {{ currentProjectSources }} 份参考来源，回答时将自动参考项目文献。</template>
              <template v-else>当前会话属于科研项目「{{ currentProject.name }}」，可添加 PDF / Markdown 来源供模型回答时参考。</template>
            </span>
            <RouterLink :to="`/projects/${currentProject.id}`">{{ currentProjectSources ? '管理来源 →' : '添加来源 →' }}</RouterLink>
          </div>
          <div class="welcome-launch-grid">
            <button v-for="example in examples" :key="example.label" type="button" class="welcome-launch-card" @click="useExample(example.text)">
              <div class="welcome-launch-head">
                <span class="ui-pill" :class="example.badgeClass">{{ example.badge }}</span>
                <span class="welcome-launch-arrow" aria-hidden="true">↗</span>
              </div>
              <b>{{ example.label }}</b>
              <p>{{ example.summary }}</p>
            </button>
          </div>
          <p class="welcome-hint">点击上方任务卡片仅将示例填入输入框，由你核对后确认发送。</p>
        </div>
        <template v-for="{ turn, modelChange } in conversationTimeline" :key="turn.turn_id">
          <ModelChangeNotice v-if="modelChange" :from="models.labelFor(modelChange.from)" :to="models.labelFor(modelChange.to)" />
          <article class="turn" :class="{ 'selected-turn':store.selectedTurnId===turn.turn_id }"><div class="turn-label"><span class="ui-pill ui-pill-neutral">第 {{ turn.revision }} 轮</span><time class="ui-pill ui-pill-mono">{{ new Date(turn.received_at).toLocaleTimeString('zh-CN',{hour:'2-digit',minute:'2-digit'}) }}</time><span v-if="turn.turn_id!==newest" class="ui-pill ui-pill-neutral">历史记录</span></div><UserMessage :text="turn.message" :attachments="turn.attachments" :turn-number="turn.revision" :disabled="store.running || store.creating || store.loading || sending || !!store.disconnectedRequest" @edit="editQuestion($event, turn.revision, turn.conversation_id)" /><div class="answer"><div class="answer-label"><span class="mini-star" aria-hidden="true">✳</span><b>AstroAgent</b><span v-if="turn.response" class="tag" :class="turn.response.status">{{ turn.response.status === 'success' ? '已完成' : turn.response.status === 'partial' ? '部分完成' : '查询未成功' }}</span></div><p v-if="turn.execution_status==='running'" class="processing">正在处理中，可稍候重新进入会话查看最新结果，系统不会自动重发请求。</p><ConversationErrorNotice v-if="turn.error" :message="turn.error.message" :code="turn.error.code" /><MarkdownAnswer v-if="turn.response" class="answer-text" :text="turn.response.answer" /><ContextNotice v-if="turn.context?.warnings?.length" :messages="turn.context?.warnings || []" /><details v-if="turn.context?.included_turn_ids?.length" class="small"><summary>使用了 {{ turn.context.included_turn_ids.length }} 轮历史上下文</summary><p>历史数据保持原查询时间，不代表本轮重新查询。</p><code>{{ turn.context.included_turn_ids.join('\n') }}</code></details><div v-if="turn.response?.sources?.length" class="source-links"><template v-for="source in turn.response.sources" :key="source.url"><a v-if="safeLink(source.url)" :href="safeLink(source.url)!" target="_blank" rel="noopener noreferrer">{{ source.name }} ↗</a><span v-else>{{ source.url }}</span></template></div><button class="view-results" @click="openResults(turn.turn_id)">核查本轮结果与导出 <span aria-hidden="true">→</span></button></div></article>
        </template>
        <p v-if="store.pending" class="processing pending"><span class="status-dot"></span>正在处理，请稍候…</p>
        <p v-if="store.loading && store.turns.length" class="small muted">正在读取本地记录…</p>
      </div>
      <WorkbenchPlot v-if="openedPlot" v-show="plotMode" ref="plotPanel" :turns="store.turns" :conversation-id="conversationId" :preferred-project="typeof route.query.plot_project === 'string' ? route.query.plot_project : undefined" :preferred-turn="typeof route.query.plot_turn === 'string' ? route.query.plot_turn : undefined" :preferred-query="Number(route.query.plot_query ?? 0)" :dataset-identifier="typeof route.query.plot_dataset === 'string' ? route.query.plot_dataset : undefined" :snapshot-identifier="typeof route.query.plot_snapshot === 'string' ? route.query.plot_snapshot : undefined" />
      <form class="composer" :class="{ 'composer-dragging': dragDepth > 0, 'composer-plot-mode': plotMode }" @submit.prevent="submitComposer" @dragenter="dragEnter" @dragover="dragOver" @dragleave="dragDepth = Math.max(0, dragDepth - 1)" @drop="dropFiles">
        <AttachmentTray v-show="!plotMode" :scope="modelScope" :disabled="attachmentDisabled" />
        <p v-if="dragDepth > 0" class="attachment-drop-hint">松开添加附件</p>
        <div v-if="!plotMode && editingTurn!==null" class="composer-editing"><p>编辑第 {{ editingTurn }} 轮问题 · 确认发送后作为新一轮，原记录保留。{{ draftBeforeEdit ? '取消编辑可恢复原草稿。' : '' }}</p><button type="button" :disabled="sending || store.running" @click="cancelEdit">取消编辑</button></div>
        <label class="sr-only" for="question">{{ plotMode ? '绘图需求' : '天文问题' }}</label>
        <textarea id="question" ref="input" v-model="composerDraft" rows="2" maxlength="4000" :placeholder="plotMode ? '描述需要的图形，例如：画 BP−RP 与 G 星等的散点图，星等轴反向…' : '输入一个天文问题，或继续追问刚才的结果…'" :disabled="store.running || store.creating || sending || !!store.disconnectedRequest" @keydown="keydown" @compositionstart="composing=true" @compositionend="composing=false"></textarea>
        <div v-if="!plotMode && (models.error || (models.loaded && !models.configured))" class="model-catalog-error" role="status"><span>{{ models.error || '服务端尚未配置回答模型。' }}</span></div>
        <div class="composer-bottom">
          <div class="composer-task-tools">
            <button type="button" class="composer-task-button composer-plot-toggle" :class="{ active: plotMode }" :aria-pressed="plotMode" :disabled="sending || store.running || store.creating || store.loading || !!store.disconnectedRequest" :data-tooltip="plotMode ? '返回对话，保留绘图进度和草稿' : '在当前工作台选择数据、描述图形并审阅绘图方案'" @click="togglePlot"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 4v16h16M7 15l4-5 4 3 5-7" /><circle cx="11" cy="10" r="1" /></svg><span>科研绘图</span><span v-if="plotMode" class="composer-plot-return">返回对话</span></button>
            <button type="button" class="composer-task-button composer-nbody-toggle" :class="{ 'is-unavailable': computeDisabled }" :data-tooltip="computeDisabled ? '服务端暂未启用 N 体计算执行器（仍可编辑初始条件草稿）' : '准备并运行 N 体模拟实验'" @click="openNbody"><svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="3" /><circle cx="5" cy="6" r="1.5" /><circle cx="19" cy="17" r="1.5" /><path d="M6.3 7.2l3.4 2.9m4.7 3.8 3.4 2M18.5 8a8 8 0 0 0-9-3m-4 8a8 8 0 0 0 9 7" /></svg><span>N 体模拟</span><span v-if="computeDisabled" class="composer-status-pill">未启用</span></button>
          </div>
          <div v-show="!plotMode" class="composer-tools"><ModelSelector :model-value="currentModel" :disabled="sending || store.running || store.creating || store.loading || !!store.disconnectedRequest" @update:model-value="selectModel" /></div>
          <button v-if="plotMode" type="button" class="workbench-plot-upload" :disabled="!plotPanel?.canUpload" aria-label="上传绘图 CSV 或 TSV 数据" data-tooltip="上传 CSV / TSV 绘图数据" @click="plotPanel?.chooseFile()"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 16V4m-4 4 4-4 4 4M5 14v6h14v-6" /></svg></button>
          <AttachmentButton v-else :scope="modelScope" :disabled="attachmentDisabled" />
          <button class="button-primary composer-send" :disabled="plotMode ? !plotDraft.trim() || !plotReady || plotBusy : (!draft.trim() && !attachedFiles.length) || attachments.blocked(modelScope) || !currentModel || !models.configured || models.loading || store.running || store.creating || store.loading || sending || !!store.disconnectedRequest" type="submit" :aria-label="plotMode ? plotBusy ? '正在准备绘图' : '生成绘图方案' : store.running || sending ? '正在处理问题' : '发送问题'" :data-tooltip="plotMode ? (plotHint || '生成绘图方案，审阅后再确认执行') : store.running || sending ? '正在处理，请稍候' : '发送问题及附件；Enter 发送，Shift + Enter 换行'">
            <svg v-if="store.running || sending || (plotMode && plotBusy)" class="composer-send-spinner" viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="7" /></svg>
            <svg v-else viewBox="0 0 24 24" aria-hidden="true"><path d="M12 19V5m-5.5 5.5L12 5l5.5 5.5" /></svg>
          </button>
        </div>
        <p v-if="plotMode && !plotReady && plotHint" class="composer-readiness-hint" role="status">{{ plotHint }}</p>
        <p v-else>{{ plotMode ? '生成方案后请核对数据、单位与脚本；确认执行后才会绘图。' : '模型回答需对照原始数据核查；位置候选源不等于星团成员。' }}</p>
      </form>
      </template>
    </main>
    <ResultPanel id="workbench-results" :inert="profileMode || plotMode || store.panel !== 'results'" :aria-hidden="profileMode || plotMode || store.panel !== 'results'" :pending="store.pending" :turn="store.selectedTurn" :historical="!!store.selectedTurn && store.selectedTurn.turn_id!==newest" dismissible @close="closeResults" />
    <dialog ref="nbodyDialog" class="project-dialog" aria-labelledby="nbody-title">
      <div class="dialog-header">
        <div class="dialog-header-copy">
          <h2 id="nbody-title">选择计算空间</h2>
          <p class="dialog-subtitle">指定保存 N 体模拟实验参数、轨迹图表与诊断数据的空间。</p>
        </div>
        <button type="button" class="dialog-close" aria-label="关闭" @click="nbodyDialog?.close()">
          <svg viewBox="0 0 24 24" aria-hidden="true"><path d="m6 6 12 12M6 18 18 6" /></svg>
        </button>
      </div>
      <p v-if="nbodyLoading" class="processing" role="status">正在准备计算空间…</p>
      <p v-else-if="nbodyError" class="notice danger" role="alert">{{ nbodyError }}</p>
      <div v-else class="project-form">
        <p v-if="computeDisabled" class="notice warning" role="status">当前服务端暂未启用 N 体计算执行器。你仍可进入页面准备轨道初始条件草稿；启用 compute 服务后即可执行积分。</p>
        <label for="nbody-space-select">保存计算结果的空间</label>
        <select id="nbody-space-select" v-model="nbodyProject"><option v-for="space in nbodySpaces" :key="space.id" :value="space.id">{{ space.label }}</option></select>
        <p v-if="draft || store.turns.length" class="small muted">当前输入或最近一条提问将填入实验描述，可在提交前编辑。</p>
      </div>
      <div class="project-actions">
        <button type="button" autofocus @click="nbodyDialog?.close()">取消</button>
        <button type="button" class="button-primary" :disabled="nbodyLoading || !nbodyProject || !!nbodyError" @click="nbodyContinue">打开计算任务</button>
      </div>
    </dialog>
</div>
</template>
