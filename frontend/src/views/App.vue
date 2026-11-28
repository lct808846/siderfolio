<script setup lang="ts">
import WorkspaceHeader from '../components/WorkspaceHeader.vue'
import InteractionHints from '../components/InteractionHints.vue'
import ModelSelector from '../components/ModelSelector.vue'
import ModelChangeNotice from '../components/ModelChangeNotice.vue'
import ConversationErrorNotice from '../components/ConversationErrorNotice.vue'
import AttachmentButton from '../components/AttachmentButton.vue'
import AttachmentTray from '../components/AttachmentTray.vue'
import ConversationSidebar from '../components/ConversationSidebar.vue'
import ComposerProjectPicker from '../components/ComposerProjectPicker.vue'
import CreateProjectDialog from '../components/CreateProjectDialog.vue'
import ChatNBodyCard, { type ComputeResultPayload } from '../components/ChatNBodyCard.vue'
import ChatPlotCard, { type PlotResultPayload } from '../components/ChatPlotCard.vue'
import ChatTableAnalysisCard, { type TableResultPayload } from '../components/ChatTableAnalysisCard.vue'
import ChatExternalMcpCard from '../components/ChatExternalMcpCard.vue'
import LiteratureReceiptCard from '../components/LiteratureReceiptCard.vue'
import MemoryReceiptCard from '../components/MemoryReceiptCard.vue'
import TurnTracePanel from '../components/TurnTracePanel.vue'
import ProjectManageDrawer, { type DrawerTab } from '../components/ProjectManageDrawer.vue'
import { defineAsyncComponent, onMounted, onBeforeUnmount, provide, ref, watch, computed, nextTick } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useWorkbench } from '../stores/workbench'
import { useModels } from '../stores/models'
import { useAttachments } from '../stores/attachments'
import { useProjects } from '../stores/projects'
import ResultPanel from '../components/ResultPanel.vue'
import MarkdownAnswer from '../components/MarkdownAnswer'
import UserMessage from '../components/UserMessage.vue'
const WorkflowWorkspace = defineAsyncComponent(() => import('./WorkflowWorkspace.vue'))
const KnowledgeWorkspace = defineAsyncComponent(() => import('./KnowledgeWorkspace.vue'))
const LiteratureWorkspace = defineAsyncComponent(() => import('./LiteratureWorkspace.vue'))
const ProjectOverview = defineAsyncComponent(() => import('./ProjectOverview.vue'))
const RagWorkspace = defineAsyncComponent(() => import('./RagWorkspace.vue'))
const ProfileWorkspace = defineAsyncComponent(() => import('./ProfileWorkspace.vue'))
import LocalTitleStatus from '../components/LocalTitleStatus.vue'
import { api, safeLink } from '../api'
import { computeApi, type ComputeStatus } from '../api/compute'
import { projectsApi } from '../api/projects'
import { tablesApi } from '../api/tables'
import { readResultsPanelStates, saveResultsPanelStates } from '../conversation-panel-state'
import type { ChatAttachment, ChatToolMode, ExternalMcpResult, LiteratureSaveReceipt, MemorySaveReceipt, Project, SkillResolution, Snapshot, Turn } from '../types'

type Submission = {
  message: string
  files: ChatAttachment[]
  toolMode: ChatToolMode
  projectId: string
}

const store = useWorkbench(), route = useRoute(), router = useRouter()
const models = useModels()
const attachments = useAttachments()
const projectsStore = useProjects()
const unarchiving = ref(false)
const dragDepth = ref(0)
const draft = ref(''), composing = ref(false)
const chatScroll = ref<HTMLElement | null>(null)
const toolMode = ref<ChatToolMode>('auto')
const draftProjectId = ref('')
const switchingProject = ref(false)
const composerCreateProjectDialog = ref<InstanceType<typeof CreateProjectDialog> | null>(null)
const projectManageDrawer = ref<InstanceType<typeof ProjectManageDrawer> | null>(null)
const inspectedSnapshot = ref<Snapshot | null>(null)
const inspectedSnapshotTurn = computed<Turn | null>(() => inspectedSnapshot.value ? {
  conversation_id: inspectedSnapshot.value.project_id,
  turn_id: inspectedSnapshot.value.id,
  client_request_id: inspectedSnapshot.value.id,
  revision: 1,
  message: inspectedSnapshot.value.name,
  received_at: inspectedSnapshot.value.created_at,
  execution_status: 'completed',
  trace_status: 'not_recorded',
  response: inspectedSnapshot.value.response,
} : null)
let pendingDrawerRequest: { projectId: string; tab: DrawerTab; snapshotId?: string; promptDelete?: boolean } | null = null
const profileMode = computed(() => route.path === '/profile')
const computeStatus = ref<ComputeStatus | null>(null)
function handleInlineRefine(mode: 'auto' | 'plot' | 'compute', promptText: string) {
  toolMode.value = mode
  draft.value = promptText
  void nextTick(() => {
    resizeComposer()
    input.value?.focus()
    input.value?.setSelectionRange(promptText.length, promptText.length)
  })
}
const composerPlaceholder = computed(() => {
  if (toolMode.value === 'plot') return '描述想绘制的科研图形（可直接基于项目数据表、上文 Gaia/VizieR 数据、附带 FITS/CSV/TSV，或先查天体再出图）…'
  if (toolMode.value === 'compute') return '描述 N 体模拟需求，例如：太阳-地球-木星三体演化 12 年，模型将自动填写初始参数…'
  return '输入一个天文问题，或拖入 FITS / VOTable / CSV 数据表继续分析…'
})
const composerHint = computed(() => {
  if (toolMode.value === 'plot') return '模型将自动编写绘图配置与脚本供你核对或修改，确认后在无网容器中隔离出图。'
  if (toolMode.value === 'compute') return '模型将根据需求自动计算并填写初始条件（AU / yr / M☉），核对或修改后再确认运行。'
  return '模型回答需对照原始数据核查；位置候选源不等于星团成员。'
})
const editingTurn = ref<number | null>(null), draftBeforeEdit = ref('')
const sending = ref(false)
const failedSubmission = ref<Submission | null>(null)
const input = ref<HTMLTextAreaElement | null>(null)
const compactLayout = ref(false), sidebarCollapsed = ref(false)
const historyToggle = ref<HTMLButtonElement | null>(null)
const resultsToggle = ref<HTMLButtonElement | null>(null)
const resultsPanelStates = readResultsPanelStates()
const restoringResults = ref(true)
const conversationId = computed(() => typeof route.params.id === 'string' ? route.params.id : '')
const currentProject = computed(() => conversationId.value ? projectsStore.projectFor(conversationId.value) : null)
const effectiveProject = computed(() => {
  if (currentProject.value) return currentProject.value
  if (!conversationId.value && draftProjectId.value) {
    return projectsStore.customProjects.find(item => item.id === draftProjectId.value) || null
  }
  return null
})
const activeSpaceProjectId = computed(() => effectiveProject.value?.id || '')
const resultFocusKind = ref<'turn' | 'compute' | 'plot' | 'tables' | 'files' | 'gaia' | 'vizier' | 'ads' | 'simbad'>('turn')
const resultFocusNonce = ref(0)
const resultFocusBatchIndex = ref<number | null>(null)
const resultProjectId = ref('')
const resultProjectScoped = ref(false)
const resultComputeTaskId = ref('')
const resultPlotRunId = ref('')
const resultPlotTitle = ref('')
const resultPlotFiles = ref<string[]>([])
const resultTableDatasetId = ref('')
const resultTableRunId = ref('')
const SIDEBAR_WIDTHS_KEY = 'astroagent.workbench.sidebar_widths.v1'
const MIN_LEFT_SIDEBAR = 188
const MAX_LEFT_SIDEBAR = 440
const DEFAULT_LEFT_SIDEBAR = 248
const MIN_RIGHT_SIDEBAR = 280
const MAX_RIGHT_SIDEBAR = 920
const MIN_CENTER_CHAT = 360

function readSavedSidebarWidths(): { left: number | null; right: number | null } {
  try {
    const raw = localStorage.getItem(SIDEBAR_WIDTHS_KEY)
    if (!raw) return { left: null, right: null }
    const parsed = JSON.parse(raw) as { left?: unknown; right?: unknown }
    const left = typeof parsed.left === 'number' && Number.isFinite(parsed.left) ? Math.round(parsed.left) : null
    const right = typeof parsed.right === 'number' && Number.isFinite(parsed.right) ? Math.round(parsed.right) : null
    return { left, right }
  } catch {
    return { left: null, right: null }
  }
}

const savedWidths = readSavedSidebarWidths()
const leftSidebarWidth = ref<number | null>(savedWidths.left)
const rightSidebarWidth = ref<number | null>(savedWidths.right)
const viewportWidth = ref(typeof window === 'undefined' ? 1440 : window.innerWidth)
const resizingSide = ref<'left' | 'right' | null>(null)
let activeResizeCleanup: (() => void) | null = null

function persistSidebarWidths() {
  try {
    localStorage.setItem(
      SIDEBAR_WIDTHS_KEY,
      JSON.stringify({ left: leftSidebarWidth.value, right: rightSidebarWidth.value }),
    )
  } catch {
    // Ignore storage unavailability.
  }
}

function clampLeftSidebarWidth(raw: number): number {
  const vw = viewportWidth.value
  const rightOpenDocked = !profileMode.value && store.panel === 'results' && vw >= 1440
  const rightReserved = rightOpenDocked ? (rightSidebarWidth.value ?? Math.min(520, Math.max(400, Math.round(vw * 0.34)))) + 10 : 0
  const maxAllowed = Math.max(MIN_LEFT_SIDEBAR, Math.min(MAX_LEFT_SIDEBAR, vw - rightReserved - MIN_CENTER_CHAT - 30))
  return Math.round(Math.min(maxAllowed, Math.max(MIN_LEFT_SIDEBAR, raw)))
}

function clampRightSidebarWidth(raw: number): number {
  const vw = viewportWidth.value
  const leftVisible = !sidebarCollapsed.value && vw >= 981
  const leftReserved = leftVisible ? (leftSidebarWidth.value ?? DEFAULT_LEFT_SIDEBAR) + 10 : 0
  const maxAllowed = vw >= 1440
    ? Math.max(MIN_RIGHT_SIDEBAR, Math.min(MAX_RIGHT_SIDEBAR, vw - leftReserved - MIN_CENTER_CHAT - 30))
    : Math.max(MIN_RIGHT_SIDEBAR, Math.min(MAX_RIGHT_SIDEBAR, vw - leftReserved - 32))
  return Math.round(Math.min(maxAllowed, Math.max(MIN_RIGHT_SIDEBAR, raw)))
}

const workbenchResizeStyle = computed<Record<string, string>>(() => {
  if (compactLayout.value) return {}
  const style: Record<string, string> = {}
  if (leftSidebarWidth.value !== null) {
    style['--sidebar-width'] = `${clampLeftSidebarWidth(leftSidebarWidth.value)}px`
  }
  if (rightSidebarWidth.value !== null) {
    style['--inspector-width'] = `${clampRightSidebarWidth(rightSidebarWidth.value)}px`
  }
  return style
})

function startResize(side: 'left' | 'right', event: PointerEvent) {
  if (event.button !== 0 || compactLayout.value) return
  event.preventDefault()
  activeResizeCleanup?.()
  viewportWidth.value = window.innerWidth
  const target = event.currentTarget as HTMLElement | null
  const panelEl = document.getElementById(side === 'left' ? 'conversation-history' : 'workbench-results')
  const startWidth = panelEl
    ? Math.round(panelEl.getBoundingClientRect().width)
    : (side === 'left' ? (leftSidebarWidth.value ?? DEFAULT_LEFT_SIDEBAR) : (rightSidebarWidth.value ?? 420))
  const startX = event.clientX
  resizingSide.value = side
  document.body.classList.add('workbench-is-resizing')
  try {
    target?.setPointerCapture(event.pointerId)
  } catch {
    // Pointer capture may not be supported on synthetic events.
  }

  const onMove = (moveEvent: PointerEvent) => {
    const delta = moveEvent.clientX - startX
    if (side === 'left') {
      leftSidebarWidth.value = clampLeftSidebarWidth(startWidth + delta)
    } else {
      rightSidebarWidth.value = clampRightSidebarWidth(startWidth - delta)
    }
  }

  const finish = () => {
    window.removeEventListener('pointermove', onMove)
    window.removeEventListener('pointerup', finish)
    window.removeEventListener('pointercancel', finish)
    document.body.classList.remove('workbench-is-resizing')
    resizingSide.value = null
    activeResizeCleanup = null
    persistSidebarWidths()
  }

  activeResizeCleanup = finish
  window.addEventListener('pointermove', onMove)
  window.addEventListener('pointerup', finish)
  window.addEventListener('pointercancel', finish)
}

function stepResize(side: 'left' | 'right', delta: number) {
  if (compactLayout.value) return
  viewportWidth.value = window.innerWidth
  const panelEl = document.getElementById(side === 'left' ? 'conversation-history' : 'workbench-results')
  const current = panelEl
    ? Math.round(panelEl.getBoundingClientRect().width)
    : (side === 'left' ? (leftSidebarWidth.value ?? DEFAULT_LEFT_SIDEBAR) : (rightSidebarWidth.value ?? 420))
  if (side === 'left') {
    leftSidebarWidth.value = clampLeftSidebarWidth(current + delta)
  } else {
    rightSidebarWidth.value = clampRightSidebarWidth(current + delta)
  }
  persistSidebarWidths()
}

function resetResize(side: 'left' | 'right') {
  if (side === 'left') leftSidebarWidth.value = null
  else rightSidebarWidth.value = null
  persistSidebarWidths()
}

function syncViewportWidth() {
  viewportWidth.value = window.innerWidth
}
const effectiveResultProjectId = computed(() => resultProjectId.value || activeSpaceProjectId.value || projectsStore.defaultProjectId || '')
const defaultSpaceSources = computed(() => projectsStore.defaultProjectId ? projectsStore.sourceCounts[projectsStore.defaultProjectId] : undefined)
const currentProjectSources = computed(() => effectiveProject.value ? projectsStore.sourceCounts[effectiveProject.value.id] : defaultSpaceSources.value)
const currentProjectHasInstructions = computed(() => !!(effectiveProject.value?.description || '').trim())
const currentProjectTooltip = computed(() => {
  const project = effectiveProject.value
  if (!project) {
    return defaultSpaceSources.value
      ? `个人空间（默认）· 已存 ${defaultSpaceSources.value} 份知识，点击管理知识库、文献问答、科研流程与快照`
      : '个人空间（默认）· 点击管理知识库、文献问答、科研流程、快照与备份'
  }
  const parts: string[] = []
  if (currentProjectHasInstructions.value) parts.push('项目指令')
  if (currentProjectSources.value) parts.push(`${currentProjectSources.value} 份参考来源`)
  return parts.length
    ? `所属项目：${project.name}（回答时自动携带${parts.join('与')}，点击管理知识库、科研流程与快照）`
    : `所属项目：${project.name}（点击管理项目指令、知识库、科研流程、快照与备份）`
})
function openProjectManager(projectId: string, tab: DrawerTab = 'context', promptDelete = false, snapshotId?: string) {
  if (!projectId) return
  if (projectManageDrawer.value) {
    void projectManageDrawer.value.open(projectId, tab, { snapshotId, promptDelete })
  } else {
    pendingDrawerRequest = { projectId, tab, snapshotId, promptDelete }
  }
}
async function openActiveSpaceManager(tab: DrawerTab = 'context') {
  if (effectiveProject.value) {
    openProjectManager(effectiveProject.value.id, tab)
    return
  }
  try {
    const fallback = await projectsStore.ensureDefault()
    openProjectManager(fallback.id, tab)
  } catch (reason) {
    store.report(reason)
  }
}
async function selectSidebarProject(projectId: string) {
  draftProjectId.value = projectId === projectsStore.defaultProjectId ? '' : projectId
  if (projectId) projectsStore.setActiveProject(projectId)
  if (compactLayout.value && store.panel === 'history') store.panel = 'chat'
  if (route.path !== '/') {
    await router.push('/')
  }
  await nextTick()
  resizeComposer()
  if (!compactLayout.value) input.value?.focus()
}
async function handleInspectSnapshot(item: Snapshot) {
  inspectedSnapshot.value = item
  store.panel = 'results'
  await nextTick()
  document.getElementById('workbench-results')?.querySelector<HTMLButtonElement>('.result-close')?.focus({ preventScroll: true })
}
function onProjectDeleted(deletedId: string) {
  if (draftProjectId.value === deletedId) draftProjectId.value = ''
  if (inspectedSnapshot.value?.project_id === deletedId) inspectedSnapshot.value = null
  void projectsStore.load(true).catch(() => undefined)
}
watch(() => effectiveProject.value?.id || projectsStore.defaultProjectId, projectId => {
  if (effectiveProject.value?.id) {
    projectsStore.setActiveProject(effectiveProject.value.id)
  }
  if (projectId && projectsStore.sourceCounts[projectId] === undefined) {
    void projectsStore.refreshSourceCount(projectId).catch(() => undefined)
  }
}, { immediate: true })
async function selectComposerProject(nextProjectId: string) {
  if (switchingProject.value) return
  if (!conversationId.value) {
    draftProjectId.value = nextProjectId
    return
  }
  const cid = conversationId.value
  const sourceId = projectsStore.memberships[cid] || null
  const destinationId = nextProjectId || null
  if (sourceId === destinationId) return
  switchingProject.value = true
  try {
    const latestConversation = await api.detail(cid)
    if (!destinationId && sourceId) {
      const sourceProject = await projectsApi.detail(sourceId)
      await projectsApi.move(sourceId, cid, {
        expected_revision: sourceProject.revision,
        expected_conversation_revision: latestConversation.revision,
        expected_metadata_revision: latestConversation.metadata_revision,
        expected_source_project_id: sourceId,
        expected_source_revision: sourceProject.revision,
      }, true)
    } else if (destinationId) {
      const [destProject, sourceProject] = await Promise.all([
        projectsApi.detail(destinationId),
        sourceId && sourceId !== destinationId ? projectsApi.detail(sourceId) : Promise.resolve(null),
      ])
      await projectsApi.move(destinationId, cid, {
        expected_revision: destProject.revision,
        expected_conversation_revision: latestConversation.revision,
        expected_metadata_revision: latestConversation.metadata_revision,
        expected_source_project_id: sourceId,
        expected_source_revision: sourceProject?.revision ?? null,
      }, false)
    }
    await projectsStore.load(true)
  } catch (reason) {
    store.report(reason)
  } finally {
    switchingProject.value = false
  }
}
async function onComposerProjectCreated(payload: { project: Project; uploadedCount: number; startChat: boolean }) {
  await selectComposerProject(payload.project.id)
}
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
const pendingModelChange = computed(() => {
  const pending = store.pendingTurn
  if (!store.pending || !pending || pending.conversationId !== store.current?.id || !pending.model) return null
  let previous: string | undefined
  for (const turn of store.turns) {
    if (turn.execution_status === 'completed' && turn.response && turn.model) {
      previous = turn.model
    }
  }
  if (!previous || previous === pending.model) return null
  return { from: previous, to: pending.model }
})
function selectModel(id: string) {
  if (id === currentModel.value) return
  models.select(modelScope.value, id)
}
const attachedFiles = computed(() => attachments.ready(modelScope.value))
const attachmentDisabled = computed(() => sending.value || store.running || store.creating || store.loading || !!store.disconnectedRequest)
const submissionReady = computed(() => conversationReady.value && !attachmentDisabled.value
  && !attachments.blocked(modelScope.value) && !!currentModel.value && models.configured && !models.loading)
const canSend = computed(() => submissionReady.value && (!!draft.value.trim() || !!attachedFiles.value.length))
const retryAvailable = computed(() => !!failedSubmission.value && !!store.error && !store.disconnectedRequest)
const failedTurnId = computed(() => {
  if (!store.error || !store.errorTurnId || !conversationReady.value) return ''
  return store.turns.find(turn => turn.turn_id === store.errorTurnId
    && turn.error?.code === store.errorCode && turn.error.message === store.error)?.turn_id || ''
})
function dragFiles(event: DragEvent) { return Array.from(event.dataTransfer?.types || []).includes('Files') }
function dragEnter(event: DragEvent) { if (dragFiles(event)) { event.preventDefault(); if (!attachmentDisabled.value) dragDepth.value++ } }
function dragOver(event: DragEvent) { if (dragFiles(event)) { event.preventDefault(); if (event.dataTransfer) event.dataTransfer.dropEffect = attachmentDisabled.value ? 'none' : 'copy' } }
function dropFiles(event: DragEvent) {
  if (!dragFiles(event)) return
  event.preventDefault(); dragDepth.value = 0
  if (!attachmentDisabled.value) void attachments.add(modelScope.value, Array.from(event.dataTransfer?.files || []))
}
function onComposerPaste(event: ClipboardEvent) {
  if (attachmentDisabled.value) return
  const items = Array.from(event.clipboardData?.items || [])
  const pastedImages: File[] = []
  for (const item of items) {
    if (item.kind === 'file' && item.type.startsWith('image/')) {
      const file = item.getAsFile()
      if (file) pastedImages.push(file)
    }
  }
  if (pastedImages.length) {
    event.preventDefault()
    void attachments.add(modelScope.value, pastedImages)
  }
}
const conversationTitle = computed(() => conversationId.value
  ? (store.current?.id === conversationId.value ? store.current.title : store.conversations.find(item => item.id === conversationId.value)?.title) || '会话'
  : '新会话')
const showWelcome = computed(() => conversationReady.value && !store.loading && !store.turns.length && !store.pending
  && (!conversationId.value || !!store.current) && !store.error)
const completedResults = computed(() => store.turns.filter(turn =>
  turn.response && turn.execution_status === 'completed'
  && (turn.response.results?.length || turn.response.literature_results?.length || turn.response.gaia_results?.length || turn.response.vizier_results?.length),
))
let knownResults = new Set<string>()
let restoreFrame = 0, restoreRevision = 0
const historyVisible = computed(() => compactLayout.value ? store.panel === 'history' : !sidebarCollapsed.value)
const mobileOverlayOpen = computed(() => compactLayout.value && (store.panel === 'history' || (!profileMode.value && store.panel === 'results')))
let layoutQuery: MediaQueryList | undefined
function updateLayout() { compactLayout.value = layoutQuery?.matches || false }
function toggleHistory() {
  if (compactLayout.value) {
    const opening = store.panel !== 'history'
    store.panel = opening ? 'history' : 'chat'
    if (opening) {
      void nextTick(() => {
        const drawer = document.getElementById('conversation-history')
        drawer?.querySelector<HTMLElement>('.mobile-drawer-close, .new-conversation, button, a[href]')?.focus({ preventScroll: true })
      })
    } else {
      void nextTick(() => { historyToggle.value?.focus({ preventScroll: true }) })
    }
  } else {
    sidebarCollapsed.value = !sidebarCollapsed.value
  }
}
function closeMobileHistory() {
  if (compactLayout.value && store.panel === 'history') {
    store.panel = 'chat'
    void nextTick(() => { historyToggle.value?.focus({ preventScroll: true }) })
  }
}
function dismissMobileOverlay() {
  if (store.panel === 'results') void closeResults()
  else if (store.panel === 'history') closeMobileHistory()
}
function onWorkbenchKeydown(event: KeyboardEvent) {
  if (event.key !== 'Escape' || !mobileOverlayOpen.value) return
  if (document.querySelector('dialog[open]')) return
  event.preventDefault()
  dismissMobileOverlay()
}
function rememberResults(open: boolean) {
  const id = route.params.id
  if (typeof id !== 'string') return
  resultsPanelStates.delete(id)
  resultsPanelStates.set(id, open)
  saveResultsPanelStates(resultsPanelStates)
}
async function openResults(
  turnId?: string,
  focusKind: 'turn' | 'gaia' | 'vizier' | 'ads' | 'simbad' = 'turn',
  batchIndex?: number,
) {
  const id = route.params.id
  inspectedSnapshot.value = null
  resultProjectId.value = ''
  resultProjectScoped.value = false
  resultFocusKind.value = focusKind
  resultFocusBatchIndex.value = typeof batchIndex === 'number' && batchIndex >= 0 ? batchIndex : null
  resultFocusNonce.value++
  if (turnId) store.selectedTurnId = turnId
  rememberResults(true)
  store.panel = 'results'
  await nextTick()
  if (route.params.id === id && store.panel === 'results') document.getElementById('workbench-results')?.querySelector<HTMLButtonElement>('.result-close')?.focus({ preventScroll: true })
}
function handleOpenToolResult(payload: ComputeResultPayload | PlotResultPayload | TableResultPayload) {
  inspectedSnapshot.value = null
  resultProjectId.value = payload.projectId
  resultProjectScoped.value = false
  if (payload.kind === 'compute') {
    resultFocusKind.value = 'compute'
    resultComputeTaskId.value = payload.taskId
  } else if (payload.kind === 'tables') {
    resultFocusKind.value = 'tables'
    resultTableDatasetId.value = payload.datasetId || ''
    resultTableRunId.value = payload.runId || ''
  } else {
    resultFocusKind.value = 'plot'
    resultPlotRunId.value = payload.runId
    resultPlotTitle.value = payload.title
    resultPlotFiles.value = payload.files
  }
  resultFocusNonce.value++
  rememberResults(true)
  store.panel = 'results'
  void nextTick(() => {
    if (store.panel === 'results') document.getElementById('workbench-results')?.querySelector<HTMLButtonElement>('.result-close')?.focus({ preventScroll: true })
  })
}
async function closeResults() {
  const id = route.params.id
  inspectedSnapshot.value = null
  rememberResults(false); store.panel = 'chat'
  await nextTick()
  if (route.params.id === id && store.panel === 'chat') resultsToggle.value?.focus({ preventScroll: true })
}
function toggleResults() { if (store.panel === 'results') void closeResults(); else void openResults() }
function turnReceipts(turn: Turn): LiteratureSaveReceipt[] {
  const merged: LiteratureSaveReceipt[] = []
  const seen = new Set<string>()
  for (const item of [...(turn.literature_receipts || []), ...(turn.response?.literature_receipts || [])]) {
    if (!seen.has(item.receipt_id)) {
      seen.add(item.receipt_id)
      merged.push(item)
    }
  }
  return merged
}
function turnMemoryReceipts(turn: Turn): MemorySaveReceipt[] {
  const merged: MemorySaveReceipt[] = []
  const seen = new Set<string>()
  for (const item of [...(turn.memory_receipts || []), ...(turn.response?.memory_receipts || [])]) {
    if (!seen.has(item.receipt_id)) {
      seen.add(item.receipt_id)
      merged.push(item)
    }
  }
  return merged
}
function turnSkillResolution(turn: Turn): SkillResolution | null {
  return turn.skill_resolution || turn.response?.skill_resolution || null
}
const needsInitialBottomScroll = ref(false)
function scrollChatToBottom() {
  const el = chatScroll.value
  if (!el) return
  const prev = el.style.scrollBehavior
  el.style.scrollBehavior = 'auto'
  el.scrollTop = el.scrollHeight
  el.style.scrollBehavior = prev
}
function externalMcpResultFor(turn: Turn, confirmationId: string): ExternalMcpResult | null {
  return turn.response?.external_mcp_results?.find(item => item.confirmation_id === confirmationId) || null
}
async function handleExternalMcpUpdated(targetConversationId: string) {
  if (!targetConversationId) return
  try {
    await store.load(targetConversationId, true)
  } catch (reason) {
    store.report(reason)
  }
}
interface TurnSourceItem {
  url: string
  safeUrl: string | null
  provider: string
  badge: string
  label: string
  title: string
  code: string
}
const expandedSourceTurns = ref<Record<string, boolean>>({})
function toggleTurnSources(turnId: string) {
  expandedSourceTurns.value = {
    ...expandedSourceTurns.value,
    [turnId]: !expandedSourceTurns.value[turnId],
  }
}
function firstAuthorSurname(authors?: string[] | null): string {
  const first = authors?.[0]?.trim() || ''
  if (!first) return ''
  if (first.includes(',')) return first.split(',', 1)[0]!.trim()
  const parts = first.split(/\s+/)
  return parts[parts.length - 1] || first
}
function turnSourceItems(turn: Turn): TurnSourceItem[] {
  const res = turn.response
  if (!res?.sources?.length) return []
  const adsMap = new Map<string, { index: number; bibcode: string; title: string; author: string; year: number | null }>()
  let paperOrder = 0
  for (const batch of res.literature_results || []) {
    for (const paper of batch.papers || []) {
      paperOrder += 1
      if (paper.source?.url && !adsMap.has(paper.source.url)) {
        adsMap.set(paper.source.url, {
          index: paperOrder,
          bibcode: paper.bibcode || '',
          title: paper.title || paper.bibcode || 'ADS 文献',
          author: firstAuthorSurname(paper.authors),
          year: paper.year ?? null,
        })
      }
    }
  }
  const simbadMap = new Map<string, string>()
  for (const item of res.results || []) {
    if (item.source?.url && !simbadMap.has(item.source.url)) {
      simbadMap.set(item.source.url, item.object_name)
    }
  }
  return res.sources.map(source => {
    const safeUrl = safeLink(source.url)
    const ads = adsMap.get(source.url)
    if (ads) {
      const citation = [ads.author, ads.year].filter(Boolean).join(' ')
      return {
        url: source.url,
        safeUrl,
        provider: 'ADS',
        badge: `#${ads.index}`,
        label: citation ? `${citation}` : (ads.bibcode || 'ADS 文献'),
        title: ads.title,
        code: ads.bibcode,
      }
    }
    const simbadObj = simbadMap.get(source.url)
    if (simbadObj) {
      return {
        url: source.url,
        safeUrl,
        provider: 'SIMBAD',
        badge: 'SIMBAD',
        label: simbadObj,
        title: `SIMBAD 天体记录：${simbadObj}`,
        code: '',
      }
    }
    return {
      url: source.url,
      safeUrl,
      provider: source.name,
      badge: source.name,
      label: source.name,
      title: source.url,
      code: '',
    }
  })
}
function turnSourceSummary(items: TurnSourceItem[]): string {
  if (!items.length) return ''
  const providers = Array.from(new Set(items.map(item => item.provider)))
  if (providers.length === 1 && providers[0] === 'ADS') return `原始来源 · ${items.length} 篇 ADS`
  if (providers.length === 1) return `原始来源 · ${items.length} 条 ${providers[0]}`
  return `原始来源 · ${items.length} 条`
}
function handleTraceJump(turnId: string, target: { type: string; batchIndex?: number; receiptId?: string; projectId?: string }) {
  if (target.type === 'literature') {
    void router.push('/literature')
    return
  }
  if (target.type === 'tables') {
    resultProjectId.value = target.projectId || activeSpaceProjectId.value || projectsStore.defaultProjectId || ''
    resultProjectScoped.value = true
    resultFocusKind.value = 'tables'
    resultFocusNonce.value++
    rememberResults(true)
    store.panel = 'results'
    return
  }
  if (target.type === 'compute') {
    if (turnId) store.selectedTurnId = turnId
    resultFocusKind.value = 'compute'
    resultFocusBatchIndex.value = null
    resultFocusNonce.value++
    rememberResults(true)
    store.panel = 'results'
    return
  }
  if (target.type === 'plot') {
    if (turnId) store.selectedTurnId = turnId
    resultFocusKind.value = 'plot'
    resultFocusBatchIndex.value = null
    resultFocusNonce.value++
    rememberResults(true)
    store.panel = 'results'
    return
  }
  if (target.type === 'gaia' || target.type === 'vizier' || target.type === 'ads' || target.type === 'simbad') {
    void openResults(turnId, target.type, target.batchIndex)
    return
  }
  void openResults(turnId)
}
function resizeComposer() {
  const field = input.value
  if (!field) return
  field.style.height = 'auto'
  field.style.height = `${Math.min(144, Math.max(50, field.scrollHeight))}px`
}
watch(draft, async () => { await nextTick(); resizeComposer() })
watch(() => store.panel, async () => { await nextTick(); resizeComposer() })
watch(() => store.pending, async active => {
  if (!active) return
  await nextTick()
  scrollChatToBottom()
})
watch(
  [() => store.current?.id, () => store.turns.length, chatScroll, () => store.panel],
  () => {
    if (!needsInitialBottomScroll.value) return
    const id = conversationId.value
    if (!id || !chatScroll.value || store.current?.id !== id || !store.turns.length) return
    scrollChatToBottom()
    needsInitialBottomScroll.value = false
  },
  { flush: 'post' },
)
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
  if (fresh && !compactLayout.value) revealResultsAutomatically()
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
    badge: 'VizieR 星表',
    badgeClass: 'ui-pill-simbad',
    label: '2MASS 近红外星表检索',
    summary: '通过 CDS VizieR TAP 检索 2MASS / AllWISE 等星表并一键转存至项目数据分析。',
    text: '以 M45 为中心，在 VizieR 2MASS 点源星表（II/246/out）检索 5 角分内前 50 颗候选源，给出 J/H/K 星等与参考历元说明。',
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
  if (compactLayout.value && store.panel === 'history') store.panel = 'chat'
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
function send() {
  if (!canSend.value || preparingConversation) return
  const defaultAttachmentPrompt =
    attachedFiles.value.length > 0 && attachedFiles.value.every(item => item.media_type.startsWith('image/'))
      ? '请查看并分析这张图片。'
      : '请阅读附件并概括要点。'
  return submit({
    message: draft.value.trim() || defaultAttachmentPrompt,
    files: attachedFiles.value,
    toolMode: toolMode.value,
    projectId: draftProjectId.value,
  }, true)
}
function retry() {
  const submission = failedSubmission.value
  if (!submission || !retryAvailable.value || !submissionReady.value || preparingConversation) return
  return submit(submission, false)
}
function clearSubmittedDraft(scope: string) {
  draft.value = ''
  attachments.clear(scope)
  toolMode.value = 'auto'
  editingTurn.value = null
  draftBeforeEdit.value = ''
}
const syncedTableAttachments = new Set<string>()
const TABLE_ATTACHMENT_RE = /\.(fits|fit|vot|xml|ecsv|csv|tsv)$/i

async function syncChatTableAttachments(conversationIdValue: string, files: ChatAttachment[]) {
  const tableFiles = files.filter(f => TABLE_ATTACHMENT_RE.test(f.filename))
  if (!tableFiles.length) return
  let pid = projectsStore.memberships[conversationIdValue] || activeSpaceProjectId.value || projectsStore.defaultProjectId || ''
  if (!pid) {
    try {
      pid = (await projectsStore.ensureDefault()).id
    } catch {
      return
    }
  }
  for (const att of tableFiles) {
    const dedupeKey = `${pid}:${att.sha256}`
    if (syncedTableAttachments.has(dedupeKey)) continue
    const raw = attachments.rawFile(att.sha256)
    let fileToUpload: File | null = raw ?? null
    if (!fileToUpload && !att.truncated && /\.(csv|tsv)$/i.test(att.filename)) {
      fileToUpload = new File([att.text], att.filename, { type: att.media_type })
    }
    if (!fileToUpload) continue
    try {
      await tablesApi.upload(pid, fileToUpload, {
        name: att.filename.replace(/\.[^.]+$/, ''),
      })
      syncedTableAttachments.add(dedupeKey)
    } catch {
      // Non-blocking: chat message still proceeds with parsed attachment summary.
    }
  }
}

async function submit(submission: Submission, fromComposer: boolean) {
  const sourceScope = modelScope.value
  const selectedModel = currentModel.value
  sending.value = true
  failedSubmission.value = null
  try {
    let id = conversationId.value
    if (!id) {
      const origin = route.fullPath
      const targetProjectId = submission.projectId
      id = (await store.create()) ?? ''
      if (route.fullPath !== origin) return
      if (!id) {
        if (store.error) {
          if (fromComposer) clearSubmittedDraft(sourceScope)
          failedSubmission.value = submission
        }
        return
      }
      if (targetProjectId && targetProjectId !== projectsStore.defaultProjectId) {
        try {
          const destProject = await projectsApi.detail(targetProjectId)
          await projectsApi.move(targetProjectId, id, {
            expected_revision: destProject.revision,
            expected_conversation_revision: store.current?.revision ?? 0,
            expected_metadata_revision: store.current?.metadata_revision ?? 0,
            expected_source_project_id: null,
            expected_source_revision: null,
          }, false)
          projectsStore.memberships = { ...projectsStore.memberships, [id]: targetProjectId }
          void projectsStore.load(true).catch(() => undefined)
        } catch (reason) {
          store.report(reason)
        }
      }
      if (route.fullPath !== origin) return
      draftProjectId.value = ''
      models.select(id, selectedModel)
      attachments.move(sourceScope, id)
      await router.push(`/conversations/${id}`)
    }
    const destination = `/conversations/${id}`
    if (route.path !== destination || store.current?.id !== id) return
    if (submission.files.length) {
      await syncChatTableAttachments(id, submission.files)
    }
    if (fromComposer) clearSubmittedDraft(id)
    models.select(id, selectedModel)
    const result = await store.send(submission.message, id, selectedModel, submission.files, submission.toolMode)
    if (route.path !== destination || store.current?.id !== id) return
    if (result === 'rejected') failedSubmission.value = submission
    void nextTick(() => input.value?.focus())
  } finally { sending.value = false }
}
function keydown(event: KeyboardEvent) { if (event.key === 'Enter' && !event.shiftKey && !event.isComposing && !composing.value) { event.preventDefault(); void send() } }
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
watch(() => route.params.id, () => {
  dragDepth.value = 0; editingTurn.value = null; draftBeforeEdit.value = ''; inspectedSnapshot.value = null
  failedSubmission.value = null
  expandedSourceTurns.value = {}
  resultFocusKind.value = 'turn'
  resultComputeTaskId.value = ''
  resultPlotRunId.value = ''
  resultPlotTitle.value = ''
  resultPlotFiles.value = []
  resultTableDatasetId.value = ''
  resultTableRunId.value = ''
  resultProjectId.value = ''
  resultProjectScoped.value = false
})
watch(() => route.params.id, async id => {
  const revision = ++restoreRevision
  cancelAnimationFrame(restoreFrame)
  restoringResults.value = true
  needsInitialBottomScroll.value = typeof id === 'string' && Boolean(id)
  knownResults = new Set()
  // Apply saved geometry before fetching history; loading must not replay an open animation.
  const isCompactNow = typeof window !== 'undefined' && window.matchMedia('(max-width: 980px)').matches
  store.panel = !isCompactNow && typeof id === 'string' && resultsPanelStates.get(id) === true ? 'results' : 'chat'
  if (typeof id === 'string') {
    if (store.preparedConversation?.id === id) {
      store.$patch({ current: store.preparedConversation, preparedConversation: null, turns: [], selectedTurnId: '', loading: false })
      store.clearError()
    }
    if (id !== store.current?.id) await store.load(id)
    if (revision !== restoreRevision) return
    if (store.current?.id === id) {
      if (isCompactNow) {
        store.panel = 'chat'
      } else {
        const open = resultsPanelStates.get(id) ?? (completedResults.value.length > 0)
        store.panel = open ? 'results' : 'chat'
        rememberResults(open)
      }
      knownResults = new Set(completedResults.value.map(turn => turn.turn_id))
    }
  } else {
    store.$patch({ loadToken: store.loadToken + 1, current: null, preparedConversation: null, turns: [], selectedTurnId: '', loading: false })
    store.clearError()
  }
  await nextTick()
  if (revision !== restoreRevision) return
  if (typeof id === 'string' && store.current?.id === id) {
    scrollChatToBottom()
    needsInitialBottomScroll.value = false
  }
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
  const q = route.query
  const requestedTool = q.tool === 'plot' || q.mode === 'plot' ? 'plot' : q.tool === 'compute' ? 'compute' : null
  const requestedResult = q.result === 'compute' || q.result === 'plot' || q.result === 'tables' ? q.result : null
  const requestedComputeTask = typeof q.compute_task === 'string' ? q.compute_task : ''
  const requestedPlotRun = typeof q.plot_run === 'string' ? q.plot_run : ''
  const requestedTableDataset = typeof q.table_dataset === 'string' ? q.table_dataset : ''
  const requestedTableRun = typeof q.table_run === 'string' ? q.table_run : ''
  const requestedProject = typeof q.project === 'string' ? q.project : typeof q.plot_project === 'string' ? q.plot_project : ''
  const requestedManage = q.manage === 'context' || q.manage === 'snapshots' || q.manage === 'manage' ? q.manage : null
  const requestedSnapshotId = typeof q.snapshot === 'string' ? q.snapshot : ''
  const requestedTurn = typeof q.plot_turn === 'string' ? q.plot_turn : ''
  const requestedPlotSnapshot = typeof q.plot_snapshot === 'string' ? q.plot_snapshot : ''
  const requestedPlotDataset = typeof q.plot_dataset === 'string' ? q.plot_dataset : ''
  const hasToolQuery = !!requestedTool || !!requestedResult || !!requestedComputeTask || !!requestedPlotRun || !!requestedTableDataset || !!requestedTableRun || !!requestedProject || !!requestedManage || !!requestedSnapshotId || !!requestedTurn || !!requestedPlotSnapshot || typeof q.plot_query === 'string' || !!requestedPlotDataset
  if (requestedTool) {
    toolMode.value = requestedTool
  }
  if (requestedProject && !conversationId.value && requestedProject !== projectsStore.defaultProjectId) {
    draftProjectId.value = requestedProject
  }
  if (requestedPlotDataset && !draft.value.trim()) {
    draft.value = `请基于项目绘图数据集 ${requestedPlotDataset} 生成科研绘图脚本（data_source_kind="project_dataset", dataset_id="${requestedPlotDataset}"）：`
  } else if (requestedTurn && !draft.value.trim()) {
    const matched = store.turns.find(t => t.turn_id === requestedTurn)
    const isLatestTurn = Boolean(matched && matched.turn_id === newest.value)
    draft.value = matched && !isLatestTurn
      ? `请基于第 ${matched.revision} 轮的 Gaia DR3 查询结果绘制科研图形：`
      : '请基于刚才的 Gaia DR3 查询结果绘制科研图形：'
    void nextTick(() => input.value?.focus())
  } else if (requestedPlotSnapshot && !draft.value.trim()) {
    draft.value = '请基于当前项目快照的 Gaia DR3 查询结果绘制科研图形：'
    void nextTick(() => input.value?.focus())
  }
  if (hasToolQuery) {
    const cleanQuery = { ...q }
    delete cleanQuery.mode
    delete cleanQuery.tool
    delete cleanQuery.result
    delete cleanQuery.compute_task
    delete cleanQuery.plot_run
    delete cleanQuery.table_dataset
    delete cleanQuery.table_run
    delete cleanQuery.project
    delete cleanQuery.manage
    delete cleanQuery.snapshot
    delete cleanQuery.plot_project
    delete cleanQuery.plot_turn
    delete cleanQuery.plot_query
    delete cleanQuery.plot_dataset
    delete cleanQuery.plot_snapshot
    await router.replace({ path: route.path, query: cleanQuery })
  }
  if (requestedResult) {
    let targetProject = requestedProject || activeSpaceProjectId.value || projectsStore.defaultProjectId || ''
    if (!targetProject) {
      try {
        const def = await projectsStore.ensureDefault()
        targetProject = def.id
      } catch { /* Fallback to empty if unavailable. */ }
    }
    inspectedSnapshot.value = null
    resultProjectId.value = targetProject
    resultProjectScoped.value = true
    resultFocusKind.value = requestedResult
    if (requestedResult === 'compute') resultComputeTaskId.value = requestedComputeTask
    if (requestedResult === 'plot') resultPlotRunId.value = requestedPlotRun
    if (requestedResult === 'tables') {
      resultTableDatasetId.value = requestedTableDataset
      resultTableRunId.value = requestedTableRun
    }
    resultFocusNonce.value++
    rememberResults(true)
    store.panel = 'results'
    return
  }
  const drawerProjectId = requestedProject || effectiveProject.value?.id || ''
  if (drawerProjectId && (requestedManage || requestedSnapshotId)) {
    const tab: DrawerTab = requestedSnapshotId ? 'snapshots' : (requestedManage || 'context')
    openProjectManager(drawerProjectId, tab, false, requestedSnapshotId || undefined)
    return
  }
  if (hasToolQuery) {
    await nextTick()
    resizeComposer()
    input.value?.focus()
  }
}
let streamScrollFrame = 0
let resizeComposerFrame = 0
function scheduleResizeComposer() {
  if (resizeComposerFrame) return
  resizeComposerFrame = requestAnimationFrame(() => {
    resizeComposerFrame = 0
    resizeComposer()
  })
}
watch(() => store.pendingTurn?.streamedText, value => {
  if (!value || streamScrollFrame) return
  streamScrollFrame = requestAnimationFrame(() => {
    streamScrollFrame = 0
    const el = chatScroll.value
    if (!el) return
    if (el.scrollHeight - el.scrollTop - el.clientHeight < 140) {
      el.scrollTop = el.scrollHeight
    }
  })
})
watch(() => route.fullPath, () => {
  if (compactLayout.value && store.panel === 'history') store.panel = 'chat'
  void applyWorkbenchHandoff()
}, { immediate: true })
onMounted(async () => {
  layoutQuery = window.matchMedia('(max-width: 980px)')
  updateLayout(); layoutQuery.addEventListener('change', updateLayout)
  window.addEventListener('resize', scheduleResizeComposer, { passive: true })
  window.addEventListener('resize', syncViewportWidth, { passive: true })
  window.addEventListener('keydown', onWorkbenchKeydown)
  resizeComposer()
  void applyWorkbenchHandoff()
  if (pendingDrawerRequest && projectManageDrawer.value) {
    const req = pendingDrawerRequest
    pendingDrawerRequest = null
    void projectManageDrawer.value.open(req.projectId, req.tab, { snapshotId: req.snapshotId, promptDelete: req.promptDelete })
  }
  void computeApi.status().then(status => { computeStatus.value = status }).catch(() => undefined)
  try {
    await Promise.all([store.refreshList(), models.load()])
    void store.refreshArchived().catch(() => undefined)
    void projectsStore.load().catch(() => undefined)
  } catch (error) { store.report(error) }
})
onBeforeUnmount(() => {
  restoreRevision++
  cancelAnimationFrame(restoreFrame)
  if (streamScrollFrame) cancelAnimationFrame(streamScrollFrame)
  if (resizeComposerFrame) cancelAnimationFrame(resizeComposerFrame)
  activeResizeCleanup?.()
  layoutQuery?.removeEventListener('change', updateLayout)
  window.removeEventListener('resize', scheduleResizeComposer)
  window.removeEventListener('resize', syncViewportWidth)
  window.removeEventListener('keydown', onWorkbenchKeydown)
})
</script>

<template>
  <InteractionHints />
  <LiteratureWorkspace v-if="route.path === '/literature' || route.path.startsWith('/literature/')" />
  <RagWorkspace v-else-if="route.path.endsWith('/rag')" />
  <ProjectOverview v-else-if="route.path.endsWith('/overview')" />
  <KnowledgeWorkspace v-else-if="route.path.includes('/knowledge')" />
  <WorkflowWorkspace v-else-if="route.path.includes('/workflows')" />
  <div v-else class="workbench workspace-panes primary-workspace conversation-layout" :style="workbenchResizeStyle" :data-panel="profileMode ? (store.panel === 'history' ? 'history' : 'chat') : store.panel" :data-sidebar-collapsed="sidebarCollapsed" :data-results-open="!profileMode && store.panel==='results'" :data-results-restoring="restoringResults" :data-resizing="resizingSide || undefined">
    <WorkspaceHeader title="本地科研工作台" />
    <div
      v-if="mobileOverlayOpen"
      class="mobile-sheet-scrim"
      aria-hidden="true"
      @click="dismissMobileOverlay"
    />
    <ConversationSidebar
      id="conversation-history"
      :active-project-id="activeSpaceProjectId"
      :inert="!historyVisible"
      :aria-hidden="!historyVisible"
      @create="create"
      @close="closeMobileHistory"
      @removed="afterRemoval"
      @select-project="selectSidebarProject"
      @manage-project="(id, tab, del) => openProjectManager(id, tab, del)"
    />
    <div
      v-if="!compactLayout && !sidebarCollapsed"
      class="workbench-resizer workbench-resizer-left"
      role="separator"
      aria-orientation="vertical"
      aria-label="拖拽调整左侧边栏宽度（双击恢复默认）"
      title="拖拽调整左侧边栏宽度，双击恢复默认"
      tabindex="0"
      @pointerdown="startResize('left', $event)"
      @dblclick="resetResize('left')"
      @keydown.left.prevent="stepResize('left', -20)"
      @keydown.right.prevent="stepResize('left', 20)"
      @keydown.home.prevent="resetResize('left')"
    />
    <main class="chat-panel" :inert="mobileOverlayOpen" :aria-hidden="mobileOverlayOpen">
      <header class="chat-heading">
        <button ref="historyToggle" type="button" class="chat-toolbar-button history-toggle" :aria-expanded="historyVisible" aria-controls="conversation-history" :aria-label="historyVisible ? '收起会话列表' : '展开会话列表'" :title="historyVisible ? '收起会话列表' : '展开会话列表'" @click="toggleHistory"><svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="4" width="18" height="16" rx="3" /><path d="M9 4v16" /><path class="history-toggle-chevron" d="m16 10-2 2 2 2" /></svg></button>
        <h1 :title="profileMode ? '个人资料' : conversationTitle">{{ profileMode ? '个人资料' : conversationTitle }}</h1>
        <button
          v-if="!profileMode"
          type="button"
          class="chat-project-pill"
          :class="{ 'is-default': !effectiveProject }"
          :data-tooltip="currentProjectTooltip"
          @click="openActiveSpaceManager('context')"
        >
          <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 7V5a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2Z" /></svg>
          <span class="chat-project-pill-name">{{ effectiveProject ? effectiveProject.name : '个人空间' }}</span>
          <span v-if="currentProjectSources" class="chat-project-pill-sources">{{ currentProjectSources }} 份知识</span>
          <span v-else-if="effectiveProject && currentProjectHasInstructions" class="chat-project-pill-sources">已设指令</span>
          <span v-else-if="!effectiveProject" class="chat-project-pill-sources">知识与流程</span>
        </button>
        <LocalTitleStatus v-if="!profileMode" silent :conversation-id="conversationId" :has-message="!!store.turns.length || store.pending" :submitting="store.pending" />
        <button
          v-if="!profileMode"
          type="button"
          class="chat-toolbar-button mobile-quick-new"
          :disabled="store.creating || store.loading || store.running || !!store.disconnectedRequest"
          aria-label="新建会话"
          title="新建会话"
          @click="create"
        >
          <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 5v14M5 12h14" /></svg>
        </button>
        <button
          v-show="!profileMode && store.panel !== 'results'"
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
      <div ref="chatScroll" class="chat-scroll" :class="{'chat-scroll-empty':showWelcome}" :aria-busy="store.loading" aria-live="polite">
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
                <span class="ui-pill ui-pill-accent">VizieR · 数据分析</span>
                <span class="ui-pill ui-pill-ads">ADS · 学术文献</span>
                <span class="ui-pill ui-pill-compute">绘图 · N 体模拟</span>
              </div>
              <h2>天文数据、星表分析与数值实验工作台</h2>
              <p>在一个工作台内完成天体、VizieR 多波段星表与文献检索、FITS/VOTable 交叉匹配与拟合、科研绘图及 N 体模拟，自动保留来源与可复现产物。</p>
            </div>
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
          <article class="turn" :class="{ 'selected-turn':store.selectedTurnId===turn.turn_id }">
            <div class="turn-label"><time class="ui-pill ui-pill-mono" :datetime="turn.received_at">{{ new Date(turn.received_at).toLocaleTimeString('zh-CN',{hour:'2-digit',minute:'2-digit'}) }}</time><span v-if="turn.turn_id!==newest" class="ui-pill ui-pill-neutral">历史记录</span></div>
            <UserMessage :text="turn.message" :attachments="turn.attachments" :disabled="attachmentDisabled" @edit="editQuestion($event, turn.revision, turn.conversation_id)" />
            <div class="answer">
              <div class="answer-label">
                <span class="mini-star" aria-hidden="true">✳</span>
                <b>Siderfolio</b>
                <span v-if="turn.response && turn.response.status !== 'success'" class="tag" :class="turn.response.status">{{ turn.response.status === 'partial' ? '部分完成' : '查询未成功' }}</span>
              </div>
              <p v-if="turnSkillResolution(turn)?.clarification_note && turnSkillResolution(turn)?.selection_mode !== 'ambiguous'" class="turn-skill-note">
                {{ turnSkillResolution(turn)!.clarification_note }}
              </p>
              <p v-if="turn.execution_status==='running'" class="thinking-status"><span class="thinking-shimmer-text">正在处理中，可稍候重新进入会话查看最新结果，系统不会自动重发请求。</span></p>
              <ConversationErrorNotice
                v-if="turn.error"
                inline
                :message="turn.error.message"
                :code="turn.error.code"
                :announce="turn.turn_id === failedTurnId"
                :can-retry="turn.turn_id === failedTurnId && retryAvailable"
                :busy="!submissionReady"
                @retry="retry"
              />
              <MarkdownAnswer v-if="turn.response" class="answer-text" :text="turn.response.answer" />
              <ChatNBodyCard
                v-for="(proposal, idx) in turn.response?.nbody_proposals || []"
                :key="`${turn.turn_id}-nbody-${idx}`"
                :proposal="proposal"
                :turn-id="turn.turn_id"
                :proposal-index="idx"
                :project-id="activeSpaceProjectId"
                :compute-status="computeStatus"
                @refine="handleInlineRefine('compute', $event)"
                @open-result="handleOpenToolResult"
              />
              <ChatPlotCard
                v-for="(proposal, idx) in turn.response?.plot_proposals || []"
                :key="`${turn.turn_id}-plot-${idx}`"
                :proposal="proposal"
                :turn="turn"
                :all-turns="store.turns"
                :proposal-index="idx"
                :project-id="activeSpaceProjectId"
                @refine="handleInlineRefine('plot', $event)"
                @open-result="handleOpenToolResult"
              />
              <ChatTableAnalysisCard
                v-for="(proposal, idx) in turn.response?.table_analysis_proposals || []"
                :key="`${turn.turn_id}-table-${idx}`"
                :proposal="proposal"
                :turn-id="turn.turn_id"
                :proposal-index="idx"
                :project-id="activeSpaceProjectId"
                @refine="handleInlineRefine('auto', $event)"
                @open-result="handleOpenToolResult"
              />
              <LiteratureReceiptCard
                v-for="receipt in turnReceipts(turn)"
                :key="receipt.receipt_id"
                :receipt="receipt"
              />
              <MemoryReceiptCard
                v-for="receipt in turnMemoryReceipts(turn)"
                :key="receipt.receipt_id"
                :receipt="receipt"
              />
              <ChatExternalMcpCard
                v-for="proposal in turn.response?.external_mcp_proposals || []"
                :key="proposal.confirmation_id"
                :proposal="proposal"
                :initial-result="externalMcpResultFor(turn, proposal.confirmation_id)"
                @updated="handleExternalMcpUpdated(turn.conversation_id)"
              />
              <ConversationErrorNotice v-for="warning in turn.response?.warnings || []" :key="`${warning.code}:${warning.message}`" inline :message="warning.message" :code="warning.code" advisory />
              <div
                v-if="turn.response?.results?.length || turn.response?.literature_results?.length || turn.response?.gaia_results?.length || turn.response?.vizier_results?.length || turn.attachments?.length || turn.response?.sources?.length"
                class="turn-footer-group"
              >
                <div class="turn-footer-actions">
                  <button
                    v-if="turn.response?.results?.length || turn.response?.literature_results?.length || turn.response?.gaia_results?.length || turn.response?.vizier_results?.length || turn.attachments?.length"
                    type="button"
                    class="view-results"
                    @click="openResults(turn.turn_id)"
                  >
                    {{ (turn.response?.results?.length || turn.response?.literature_results?.length || turn.response?.gaia_results?.length || turn.response?.vizier_results?.length) ? '核查与导出查询结果' : '在右侧栏预览附件' }}
                    <span aria-hidden="true">→</span>
                  </button>
                  <template v-if="turnSourceItems(turn).length === 1">
                    <a
                      v-if="turnSourceItems(turn)[0]!.safeUrl"
                      class="turn-source-pill"
                      :href="turnSourceItems(turn)[0]!.safeUrl!"
                      :title="turnSourceItems(turn)[0]!.title"
                      target="_blank"
                      rel="noopener noreferrer"
                    >
                      <span>{{ turnSourceItems(turn)[0]!.badge }}</span>
                      <span v-if="turnSourceItems(turn)[0]!.label !== turnSourceItems(turn)[0]!.badge">· {{ turnSourceItems(turn)[0]!.label }}</span>
                      <span aria-hidden="true">↗</span>
                    </a>
                    <span v-else class="turn-source-pill">{{ turnSourceItems(turn)[0]!.url }}</span>
                  </template>
                  <button
                    v-else-if="turnSourceItems(turn).length > 1"
                    type="button"
                    class="turn-source-toggle"
                    :aria-expanded="Boolean(expandedSourceTurns[turn.turn_id])"
                    @click="toggleTurnSources(turn.turn_id)"
                  >
                    <span>{{ turnSourceSummary(turnSourceItems(turn)) }}</span>
                    <svg class="turn-source-chevron" :class="{ 'is-open': expandedSourceTurns[turn.turn_id] }" viewBox="0 0 24 24" aria-hidden="true"><path d="m6 9 6 6 6-6" /></svg>
                  </button>
                </div>
                <ul v-if="turnSourceItems(turn).length > 1 && expandedSourceTurns[turn.turn_id]" class="turn-source-list">
                  <li v-for="item in turnSourceItems(turn)" :key="item.url" class="turn-source-row">
                    <span class="ui-pill ui-pill-mono">{{ item.badge }}</span>
                    <div class="turn-source-row-copy">
                      <span class="turn-source-row-title" :title="item.title">{{ item.title }}</span>
                      <span v-if="item.code" class="turn-source-row-code">{{ item.code }}</span>
                    </div>
                    <a
                      v-if="item.safeUrl"
                      class="turn-source-row-link"
                      :href="item.safeUrl"
                      target="_blank"
                      rel="noopener noreferrer"
                    >
                      {{ item.provider }} ↗
                    </a>
                    <span v-else class="small muted">{{ item.url }}</span>
                  </li>
                </ul>
              </div>
              <TurnTracePanel
                :trace="turn.run_trace"
                :trace-status="turn.trace_status"
                @jump-result="handleTraceJump(turn.turn_id, $event)"
              />
            </div>
          </article>
        </template>
        <ModelChangeNotice v-if="pendingModelChange" :from="models.labelFor(pendingModelChange.from)" :to="models.labelFor(pendingModelChange.to)" />
        <article v-if="store.pending && store.pendingTurn" class="turn pending-turn" role="status" aria-live="polite">
          <template v-if="store.pendingTurn.conversationId === store.current?.id">
            <div class="turn-label">
              <time class="ui-pill ui-pill-mono" :datetime="store.pendingTurn.sentAt">{{ new Date(store.pendingTurn.sentAt).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }) }}</time>
            </div>
            <UserMessage :text="store.pendingTurn.message" :attachments="store.pendingTurn.attachments" disabled />
          </template>
          <div class="answer pending-answer">
            <div class="answer-label">
              <span class="mini-star is-thinking" aria-hidden="true">✳</span>
              <b>Siderfolio</b>
            </div>
            <div v-if="store.pendingTurn.streamedText" class="streaming-answer-wrap">
              <MarkdownAnswer class="answer-text" :text="store.pendingTurn.streamedText" />
              <span class="streaming-caret" aria-hidden="true" />
            </div>
            <p v-else class="thinking-status">
              <span class="thinking-shimmer-text">{{ store.pendingTurn.statusLabel || '正在处理，请稍候…' }}</span>
            </p>
          </div>
        </article>
        <p v-if="store.loading && store.turns.length" class="small muted">正在读取本地记录…</p>
      </div>
      <form class="composer" :class="{ 'composer-dragging': dragDepth > 0, 'composer-plot-mode': toolMode !== 'auto' }" @submit.prevent="send" @dragenter="dragEnter" @dragover="dragOver" @dragleave="dragDepth = Math.max(0, dragDepth - 1)" @drop="dropFiles">
        <AttachmentTray :scope="modelScope" :disabled="attachmentDisabled" />
        <p v-if="dragDepth > 0" class="attachment-drop-hint">松开添加附件（支持 FITS / VOTable / ECSV / CSV / TSV、图片及 PDF / Markdown 等）</p>
        <div v-if="editingTurn!==null" class="composer-editing"><p>正在编辑问题，发送后将追加一条消息。{{ draftBeforeEdit ? '取消编辑可恢复原草稿。' : '' }}</p><button type="button" :disabled="sending || store.running" @click="cancelEdit">取消编辑</button></div>
        <label class="sr-only" for="question">天文问题</label>
        <textarea id="question" ref="input" v-model="draft" rows="2" maxlength="4000" :placeholder="composerPlaceholder" :disabled="store.running || store.creating || sending || !!store.disconnectedRequest" @keydown="keydown" @paste="onComposerPaste" @compositionstart="composing=true" @compositionend="composing=false"></textarea>
        <div v-if="store.disconnectedRequest || (store.error && !failedTurnId)" class="composer-notices">
          <ConversationErrorNotice v-if="store.disconnectedRequest" :message="store.error || '断线前的请求状态尚未确认，请先恢复会话。'" :code="store.errorCode || 'connection_lost'" operation announce>
            <template #actions>
              <button type="button" :disabled="store.pending || store.loading" @click="store.recover()">恢复会话</button>
              <button type="button" :disabled="store.pending || store.loading" @click="store.resendSameRequest()">用原请求编号核对</button>
            </template>
          </ConversationErrorNotice>
          <ConversationErrorNotice v-else :message="store.error" :code="store.errorCode" operation announce :can-retry="retryAvailable" :busy="!submissionReady" @retry="retry" @dismiss="store.error = ''">
            <template v-if="!conversationReady && conversationId" #actions>
              <button type="button" :disabled="store.loading" @click="store.load(conversationId)">重新读取会话</button>
            </template>
          </ConversationErrorNotice>
        </div>
        <div v-if="models.error || (models.loaded && !models.configured)" class="model-catalog-error" role="status"><span>{{ models.error || '服务端尚未配置回答模型。' }}</span></div>
        <div class="composer-bottom">
          <div class="composer-task-tools">
            <ComposerProjectPicker
              :model-value="activeSpaceProjectId"
              :disabled="sending || store.running || store.creating || store.loading || !!store.disconnectedRequest"
              :busy="switchingProject"
              @update:model-value="selectComposerProject"
              @create="composerCreateProjectDialog?.open()"
            />
          </div>
          <div class="composer-tools">
            <ModelSelector
              :model-value="currentModel"
              :disabled="sending || store.running || store.creating || store.loading || !!store.disconnectedRequest"
              :searchable="false"
              @update:model-value="selectModel"
            />
          </div>
          <AttachmentButton :scope="modelScope" :disabled="attachmentDisabled" />
          <button class="button-primary composer-send" :disabled="!canSend" type="submit" :aria-label="store.running || sending ? '正在处理问题' : '发送问题'" :data-tooltip="store.running || sending ? '正在处理，请稍候' : '发送问题及附件；Enter 发送，Shift + Enter 换行'">
            <svg v-if="store.running || sending" class="composer-send-spinner" viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="7" /></svg>
            <svg v-else viewBox="0 0 24 24" aria-hidden="true"><path d="M12 19V5m-5.5 5.5L12 5l5.5 5.5" /></svg>
          </button>
        </div>
        <p>{{ composerHint }}</p>
      </form>
      </template>
    </main>
    <ResultPanel
      id="workbench-results"
      :inert="profileMode || store.panel !== 'results'"
      :aria-hidden="profileMode || store.panel !== 'results'"
      :pending="inspectedSnapshot ? false : store.pending"
      :turn="inspectedSnapshotTurn || store.selectedTurn"
      :turns="inspectedSnapshot ? [] : store.turns"
      :conversation-id="conversationId"
      :historical="inspectedSnapshot ? true : (!!store.selectedTurn && store.selectedTurn.turn_id!==newest)"
      :heading="inspectedSnapshot ? `快照：${inspectedSnapshot.name}` : undefined"
      :artifact-path="inspectedSnapshot ? `/api/v1/projects/${inspectedSnapshot.project_id}/snapshots/${inspectedSnapshot.id}/artifacts` : undefined"
      :project-id="effectiveResultProjectId"
      :project-scoped-browse="resultProjectScoped"
      :focus-kind="inspectedSnapshot ? 'turn' : resultFocusKind"
      :focus-nonce="resultFocusNonce"
      :focus-batch-index="inspectedSnapshot ? null : resultFocusBatchIndex"
      :compute-task-id="resultComputeTaskId"
      :plot-run-id="resultPlotRunId"
      :plot-title="resultPlotTitle"
      :plot-files="resultPlotFiles"
      :table-dataset-id="resultTableDatasetId"
      :table-run-id="resultTableRunId"
      :resizable="!compactLayout"
      dismissible
      @resize-start="startResize('right', $event)"
      @resize-step="stepResize('right', $event)"
      @resize-reset="resetResize('right')"
      @select-turn="store.selectedTurnId = $event"
      @select-compute-task="resultComputeTaskId = $event"
      @select-plot-run="resultPlotRunId = $event"
      @select-table-dataset="resultTableDatasetId = $event"
      @select-table-run="resultTableRunId = $event"
      @close="closeResults"
    />
    <CreateProjectDialog ref="composerCreateProjectDialog" :default-start-chat="false" @created="onComposerProjectCreated" />
    <ProjectManageDrawer
      ref="projectManageDrawer"
      can-inspect-in-workbench
      @deleted="onProjectDeleted"
      @inspect-snapshot="handleInspectSnapshot"
    />
</div>
</template>

<style scoped>
.turn-skill-note {
  margin: 0 0 10px;
  padding: 8px 11px;
  border: 1px solid var(--line);
  border-radius: var(--radius-control);
  background: var(--surface-subtle);
  color: var(--muted);
  font-size: 12px;
  line-height: 1.55;
}
</style>
