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
import ComposerProjectPicker from '../components/ComposerProjectPicker.vue'
import CreateProjectDialog from '../components/CreateProjectDialog.vue'
import ChatNBodyCard from '../components/ChatNBodyCard.vue'
import ChatPlotCard from '../components/ChatPlotCard.vue'
import ProjectManageDrawer, { type DrawerTab } from '../components/ProjectManageDrawer.vue'
import { onMounted, onBeforeUnmount, provide, ref, watch, computed, nextTick } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useWorkbench } from '../stores/workbench'
import { useModels } from '../stores/models'
import { useAttachments } from '../stores/attachments'
import { useProjects } from '../stores/projects'
import ResultPanel from '../components/ResultPanel.vue'
import MarkdownAnswer from '../components/MarkdownAnswer'
import UserMessage from '../components/UserMessage.vue'
import WorkflowWorkspace from './WorkflowWorkspace.vue'
import ComputeWorkspace from './ComputeWorkspace.vue'
import KnowledgeWorkspace from './KnowledgeWorkspace.vue'
import ProjectOverview from './ProjectOverview.vue'
import RagWorkspace from './RagWorkspace.vue'
import ProfileWorkspace from './ProfileWorkspace.vue'
import LocalTitleStatus from '../components/LocalTitleStatus.vue'
import { api, safeLink } from '../api'
import { computeApi, type ComputeStatus } from '../api/compute'
import { projectsApi } from '../api/projects'
import { readResultsPanelStates, saveResultsPanelStates } from '../conversation-panel-state'
import type { ChatAttachment, ChatToolMode, Project, Snapshot, Turn } from '../types'

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
  response: inspectedSnapshot.value.response,
} : null)
let pendingDrawerRequest: { projectId: string; tab: DrawerTab; snapshotId?: string; promptDelete?: boolean } | null = null
const profileMode = computed(() => route.path === '/profile')
const computeStatus = ref<ComputeStatus | null>(null)
const computeDisabled = computed(() => computeStatus.value !== null && !computeStatus.value.enabled)
function toggleToolMode(mode: 'plot' | 'compute') {
  if (store.running || store.creating || store.loading || sending.value || store.disconnectedRequest) return
  toolMode.value = toolMode.value === mode ? 'auto' : mode
  void nextTick(() => { resizeComposer(); input.value?.focus() })
}
function handleInlineRefine(mode: 'plot' | 'compute', promptText: string) {
  toolMode.value = mode
  draft.value = promptText
  void nextTick(() => {
    resizeComposer()
    input.value?.focus()
    input.value?.setSelectionRange(promptText.length, promptText.length)
  })
}
const composerPlaceholder = computed(() => {
  if (toolMode.value === 'plot') return '描述想绘制的科研图形（可直接基于上文 Gaia 数据、附带 CSV/TSV，或先查天体再出图）…'
  if (toolMode.value === 'compute') return '描述 N 体模拟需求，例如：太阳-地球-木星三体演化 12 年，模型将自动填写初始参数…'
  return '输入一个天文问题，或继续追问刚才的结果…'
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
  if (route.path !== '/') {
    await router.push('/')
  }
  await nextTick()
  resizeComposer()
  input.value?.focus()
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
const conversationTitle = computed(() => conversationId.value
  ? (store.current?.id === conversationId.value ? store.current.title : store.conversations.find(item => item.id === conversationId.value)?.title) || '会话'
  : '新会话')
const showWelcome = computed(() => conversationReady.value && !store.loading && !store.turns.length && !store.pending
  && (!conversationId.value || !!store.current) && !store.error)
const completedResults = computed(() => store.turns.filter(turn =>
  turn.response && turn.execution_status === 'completed'
  && (turn.response.results?.length || turn.response.literature_results?.length || turn.response.gaia_results?.length),
))
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
  inspectedSnapshot.value = null
  if (turnId) store.selectedTurnId = turnId
  rememberResults(true)
  store.panel = 'results'
  await nextTick()
  if (route.params.id === id && store.panel === 'results') document.getElementById('workbench-results')?.querySelector<HTMLButtonElement>('.result-close')?.focus({ preventScroll: true })
}
async function closeResults() {
  const id = route.params.id
  inspectedSnapshot.value = null
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
watch(draft, async () => { await nextTick(); resizeComposer() })
watch(() => store.panel, async () => { await nextTick(); resizeComposer() })
watch(() => store.pending, async active => {
  if (!active) return
  await nextTick()
  if (chatScroll.value) chatScroll.value.scrollTop = chatScroll.value.scrollHeight
})
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
function send() {
  if (!canSend.value || preparingConversation) return
  return submit({
    message: draft.value.trim() || '请阅读附件并概括要点。',
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
})
watch(() => route.params.id, async id => {
  const revision = ++restoreRevision
  cancelAnimationFrame(restoreFrame)
  restoringResults.value = true
  knownResults = new Set()
  // Apply saved geometry before fetching history; loading must not replay an open animation.
  store.panel = typeof id === 'string' && resultsPanelStates.get(id) === true ? 'results' : 'chat'
  if (typeof id === 'string') {
    if (store.preparedConversation?.id === id) {
      store.$patch({ current: store.preparedConversation, preparedConversation: null, turns: [], selectedTurnId: '', loading: false })
      store.clearError()
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
    store.$patch({ loadToken: store.loadToken + 1, current: null, preparedConversation: null, turns: [], selectedTurnId: '', loading: false })
    store.clearError()
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
  const q = route.query
  const requestedTool = q.tool === 'plot' || q.mode === 'plot' ? 'plot' : q.tool === 'compute' ? 'compute' : null
  const requestedProject = typeof q.project === 'string' ? q.project : typeof q.plot_project === 'string' ? q.plot_project : ''
  const requestedManage = q.manage === 'context' || q.manage === 'snapshots' || q.manage === 'manage' ? q.manage : null
  const requestedSnapshotId = typeof q.snapshot === 'string' ? q.snapshot : ''
  const requestedTurn = typeof q.plot_turn === 'string' ? q.plot_turn : ''
  const requestedPlotSnapshot = typeof q.plot_snapshot === 'string' ? q.plot_snapshot : ''
  const hasToolQuery = !!requestedTool || !!requestedProject || !!requestedManage || !!requestedSnapshotId || !!requestedTurn || !!requestedPlotSnapshot || typeof q.plot_query === 'string' || typeof q.plot_dataset === 'string'
  if (requestedTool) toolMode.value = requestedTool
  if (requestedProject && !conversationId.value && requestedProject !== projectsStore.defaultProjectId) {
    draftProjectId.value = requestedProject
  }
  if (requestedTurn && !draft.value.trim()) {
    const matched = store.turns.find(t => t.turn_id === requestedTurn)
    draft.value = matched
      ? `请基于记录编号 ${matched.turn_id} 对应的 Gaia 查询结果绘制科研图形：`
      : '请基于刚才的 Gaia 查询结果绘制科研图形：'
  } else if (requestedPlotSnapshot && !draft.value.trim()) {
    draft.value = '请基于当前项目快照的 Gaia 查询结果绘制科研图形：'
  }
  if (hasToolQuery) {
    const cleanQuery = { ...q }
    delete cleanQuery.mode
    delete cleanQuery.tool
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
watch(() => route.fullPath, () => { void applyWorkbenchHandoff() }, { immediate: true })
onMounted(async () => {
  layoutQuery = window.matchMedia('(max-width: 980px)')
  updateLayout(); layoutQuery.addEventListener('change', updateLayout)
  window.addEventListener('resize', resizeComposer)
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
  layoutQuery?.removeEventListener('change', updateLayout)
  window.removeEventListener('resize', resizeComposer)
})
</script>

<template>
  <InteractionHints />
  <RagWorkspace v-if="route.path.endsWith('/rag')" />
  <ProjectOverview v-else-if="route.path.endsWith('/overview')" />
  <KnowledgeWorkspace v-else-if="route.path.includes('/knowledge')" />
  <WorkflowWorkspace v-else-if="route.path.includes('/workflows')" />
  <ComputeWorkspace v-else-if="route.path.includes('/compute')" />
  <div v-else class="workbench workspace-panes primary-workspace conversation-layout" :data-panel="profileMode ? 'chat' : store.panel" :data-sidebar-collapsed="sidebarCollapsed" :data-results-open="!profileMode && store.panel==='results'" :data-results-restoring="restoringResults">
    <WorkspaceHeader title="本地科研工作台" />
    <ConversationSidebar
      id="conversation-history"
      :active-project-id="activeSpaceProjectId"
      :inert="!historyVisible"
      :aria-hidden="!historyVisible"
      @create="create"
      @removed="afterRemoval"
      @select-project="selectSidebarProject"
      @manage-project="(id, tab, del) => openProjectManager(id, tab, del)"
    />
    <main class="chat-panel">
      <header class="chat-heading">
        <button type="button" class="chat-toolbar-button history-toggle" :aria-expanded="historyVisible" aria-controls="conversation-history" :aria-label="historyVisible ? '收起会话列表' : '展开会话列表'" :title="historyVisible ? '收起会话列表' : '展开会话列表'" @click="toggleHistory"><svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="4" width="18" height="16" rx="3" /><path d="M9 4v16" /><path class="history-toggle-chevron" d="m16 10-2 2 2 2" /></svg></button>
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
                <span class="ui-pill ui-pill-ads">ADS · 学术文献</span>
                <span class="ui-pill ui-pill-compute">绘图 · N 体模拟</span>
              </div>
              <h2>天文数据、绘图与数值实验工作台</h2>
              <p>在一个对话框内完成天体与文献检索、科研绘图脚本生成与 N 体轨道模拟，自动保留数据来源与可复现产物。</p>
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
              <div class="answer-label"><span class="mini-star" aria-hidden="true">✳</span><b>AstroAgent</b><span v-if="turn.response" class="tag" :class="turn.response.status">{{ turn.response.status === 'success' ? '已完成' : turn.response.status === 'partial' ? '部分完成' : '查询未成功' }}</span></div>
              <p v-if="turn.execution_status==='running'" class="thinking-status"><span class="thinking-shimmer-text">正在处理中，可稍候重新进入会话查看最新结果，系统不会自动重发请求。</span></p>
              <ConversationErrorNotice
                v-if="turn.error"
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
              />
              <ConversationErrorNotice v-for="warning in turn.response?.warnings || []" :key="`${warning.code}:${warning.message}`" :message="warning.message" :code="warning.code" advisory />
              <ContextNotice v-if="turn.context?.warnings?.length" :messages="turn.context?.warnings || []" />
              <details v-if="turn.context?.included_turn_ids?.length" class="small"><summary>使用了历史上下文</summary><p>历史数据保留原查询时间。</p><code>{{ turn.context.included_turn_ids.join('\n') }}</code></details>
              <div v-if="turn.response?.sources?.length" class="source-links"><template v-for="source in turn.response.sources" :key="source.url"><a v-if="safeLink(source.url)" :href="safeLink(source.url)!" target="_blank" rel="noopener noreferrer">{{ source.name }} ↗</a><span v-else>{{ source.url }}</span></template></div>
              <button v-if="turn.response?.results?.length || turn.response?.literature_results?.length || turn.response?.gaia_results?.length" class="view-results" @click="openResults(turn.turn_id)">核查与导出查询结果 <span aria-hidden="true">→</span></button>
            </div>
          </article>
        </template>
        <article v-if="store.pending" class="turn pending-turn" role="status" aria-live="polite">
          <template v-if="store.pendingTurn && store.pendingTurn.conversationId === store.current?.id">
            <div class="turn-label">
              <time class="ui-pill ui-pill-mono" :datetime="store.pendingTurn.sentAt">{{ new Date(store.pendingTurn.sentAt).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }) }}</time>
            </div>
            <UserMessage :text="store.pendingTurn.message" :attachments="store.pendingTurn.attachments" disabled />
          </template>
          <div class="answer pending-answer">
            <div class="answer-label">
              <span class="mini-star is-thinking" aria-hidden="true">✳</span>
              <b>AstroAgent</b>
            </div>
            <p class="thinking-status">
              <span class="thinking-shimmer-text">正在处理，请稍候…</span>
            </p>
          </div>
        </article>
        <p v-if="store.loading && store.turns.length" class="small muted">正在读取本地记录…</p>
      </div>
      <form class="composer" :class="{ 'composer-dragging': dragDepth > 0, 'composer-plot-mode': toolMode !== 'auto' }" @submit.prevent="send" @dragenter="dragEnter" @dragover="dragOver" @dragleave="dragDepth = Math.max(0, dragDepth - 1)" @drop="dropFiles">
        <AttachmentTray :scope="modelScope" :disabled="attachmentDisabled" />
        <p v-if="dragDepth > 0" class="attachment-drop-hint">松开添加附件（支持 CSV / TSV / PDF / Markdown 等）</p>
        <div v-if="editingTurn!==null" class="composer-editing"><p>正在编辑问题，发送后将追加一条消息。{{ draftBeforeEdit ? '取消编辑可恢复原草稿。' : '' }}</p><button type="button" :disabled="sending || store.running" @click="cancelEdit">取消编辑</button></div>
        <label class="sr-only" for="question">天文问题</label>
        <textarea id="question" ref="input" v-model="draft" rows="2" maxlength="4000" :placeholder="composerPlaceholder" :disabled="store.running || store.creating || sending || !!store.disconnectedRequest" @keydown="keydown" @compositionstart="composing=true" @compositionend="composing=false"></textarea>
        <div v-if="store.disconnectedRequest || (store.error && !failedTurnId)" class="composer-notices">
          <ConversationErrorNotice v-if="store.disconnectedRequest" :message="store.error || '断线前的请求状态尚未确认，请先恢复会话。'" :code="store.errorCode || 'connection_lost'" operation announce>
            <template #actions>
              <button type="button" :disabled="store.pending || store.loading" @click="store.recover()">恢复会话</button>
              <button type="button" :disabled="store.pending || store.loading" @click="store.resendSameRequest()">用原请求编号核对</button>
            </template>
          </ConversationErrorNotice>
          <ConversationErrorNotice v-else :message="store.error" :code="store.errorCode" operation announce :can-retry="retryAvailable" :busy="!submissionReady" @retry="retry">
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
            <button type="button" class="composer-task-button composer-plot-toggle" :class="{ active: toolMode === 'plot' }" :aria-pressed="toolMode === 'plot'" :disabled="sending || store.running || store.creating || store.loading || !!store.disconnectedRequest" :data-tooltip="toolMode === 'plot' ? '已选中科研绘图工具（再次点击取消）' : '告诉模型调用科研绘图工具：根据需求自动生成并审阅绘图脚本'" @click="toggleToolMode('plot')"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 4v16h16M7 15l4-5 4 3 5-7" /><circle cx="11" cy="10" r="1" /></svg><span>科研绘图</span></button>
            <button type="button" class="composer-task-button composer-nbody-toggle" :class="{ active: toolMode === 'compute', 'is-unavailable': computeDisabled }" :aria-pressed="toolMode === 'compute'" :disabled="sending || store.running || store.creating || store.loading || !!store.disconnectedRequest" :data-tooltip="toolMode === 'compute' ? '已选中 N 体模拟工具（再次点击取消）' : computeDisabled ? '告诉模型生成 N 体模拟初始条件参数（服务端暂未启用计算执行器）' : '告诉模型调用 N 体模拟工具：根据需求自动填写初始参数并由你确认运行'" @click="toggleToolMode('compute')"><svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="3" /><circle cx="5" cy="6" r="1.5" /><circle cx="19" cy="17" r="1.5" /><path d="M6.3 7.2l3.4 2.9m4.7 3.8 3.4 2M18.5 8a8 8 0 0 0-9-3m-4 8a8 8 0 0 0 9 7" /></svg><span>N 体模拟</span><span v-if="computeDisabled" class="composer-status-pill">未启用</span></button>
          </div>
          <div class="composer-tools"><ModelSelector :model-value="currentModel" :disabled="sending || store.running || store.creating || store.loading || !!store.disconnectedRequest" @update:model-value="selectModel" /></div>
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
      :historical="inspectedSnapshot ? true : (!!store.selectedTurn && store.selectedTurn.turn_id!==newest)"
      :heading="inspectedSnapshot ? `快照：${inspectedSnapshot.name}` : undefined"
      :artifact-path="inspectedSnapshot ? `/api/v1/projects/${inspectedSnapshot.project_id}/snapshots/${inspectedSnapshot.id}/artifacts` : undefined"
      dismissible
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
