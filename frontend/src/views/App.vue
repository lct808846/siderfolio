<script setup lang="ts">
import WorkspaceHeader from '../components/WorkspaceHeader.vue'
import InteractionHints from '../components/InteractionHints.vue'
import ModelSelector from '../components/ModelSelector.vue'
import ModelChangeNotice from '../components/ModelChangeNotice.vue'
import AttachmentButton from '../components/AttachmentButton.vue'
import AttachmentTray from '../components/AttachmentTray.vue'
import ConversationSidebar from '../components/ConversationSidebar.vue'
import { onMounted, onBeforeUnmount, provide, ref, watch, computed, nextTick } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useWorkbench } from '../stores/workbench'
import { useModels } from '../stores/models'
import { useAttachments } from '../stores/attachments'
import ResultPanel from '../components/ResultPanel.vue'
import MarkdownAnswer from '../components/MarkdownAnswer'
import UserMessage from '../components/UserMessage.vue'
import ProjectWorkspace from './ProjectWorkspace.vue'
import WorkflowWorkspace from './WorkflowWorkspace.vue'
import KnowledgeWorkspace from './KnowledgeWorkspace.vue'
import ProjectOverview from './ProjectOverview.vue'
import SettingsWorkspace from './SettingsWorkspace.vue'
import RagWorkspace from './RagWorkspace.vue'
import WorkbenchPlot from '../components/WorkbenchPlot.vue'
import LocalAssistantWorkspace from './LocalAssistantWorkspace.vue'
import LocalTitleStatus from '../components/LocalTitleStatus.vue'
import { safeLink } from '../api'
import { readResultsPanelStates, saveResultsPanelStates } from '../conversation-panel-state'

const store = useWorkbench(), route = useRoute(), router = useRouter()
const models = useModels()
const attachments = useAttachments()
const dragDepth = ref(0)
const draft = ref(''), composing = ref(false)
const plotMode = computed(() => route.query.mode === 'plot')
const openedPlot = ref(false), plotDraft = ref('')
const plotPanel = ref<InstanceType<typeof WorkbenchPlot> | null>(null)
const nbodyDialog = ref<HTMLDialogElement | null>(null)
watch(() => route.fullPath, () => nbodyDialog.value?.close())
const composerDraft = computed({ get: () => plotMode.value ? plotDraft.value : draft.value, set: value => { if (plotMode.value) plotDraft.value = value; else draft.value = value } })
const plotBusy = computed(() => !!plotPanel.value?.busy)
const plotReady = computed(() => !!plotPanel.value?.canPrepare)
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
  { label: '坐标圆锥查询', text: '以 ICRS 赤经56.75度、赤纬24.12度为中心，查5角分内最近100个Gaia DR3位置候选源，不估算距离。' },
  { label: '指定 DR3 编号', text: '查询 Gaia DR3 source_id 5853498713190525696 的测量信息并估算距离，说明近似条件。' },
  { label: 'ADS 文献检索', text: '检索2020—2026年双星团相关论文，取3篇，按发表日期降序，给出来源。' },
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
onMounted(async () => {
  layoutQuery = window.matchMedia('(max-width: 980px)')
  updateLayout(); layoutQuery.addEventListener('change', updateLayout)
  window.addEventListener('resize', resizeComposer)
  resizeComposer()
  try {
    await Promise.all([store.refreshList(), models.load()])
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
  <SettingsWorkspace v-if="route.path==='/settings'" />
  <LocalAssistantWorkspace v-else-if="route.path==='/local-assistant'" />
  <RagWorkspace v-else-if="route.path.endsWith('/rag')" />
  <ProjectOverview v-else-if="route.path.endsWith('/overview')" />
  <KnowledgeWorkspace v-else-if="route.path.includes('/knowledge')" />
  <WorkflowWorkspace v-else-if="route.path.includes('/workflows')" />
  <ProjectWorkspace v-else-if="route.path.startsWith('/projects')" />
  <div v-else class="workbench workspace-panes primary-workspace conversation-layout" :data-panel="plotMode ? 'chat' : store.panel" :data-sidebar-collapsed="sidebarCollapsed" :data-results-open="!plotMode && store.panel==='results'" :data-results-restoring="restoringResults">
    <WorkspaceHeader title="本地科研工作台" />
    <ConversationSidebar id="conversation-history" :inert="!historyVisible" :aria-hidden="!historyVisible" @create="create" @removed="afterRemoval" />
    <main class="chat-panel">
      <header class="chat-heading">
        <button type="button" class="chat-toolbar-button history-toggle" :aria-expanded="historyVisible" aria-controls="conversation-history" :aria-label="historyVisible ? '收起会话列表' : '展开会话列表'" :title="historyVisible ? '收起会话列表' : '展开会话列表'" @click="toggleHistory"><svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="4" width="18" height="16" rx="3" /><path d="M9 4v16" /><path class="history-toggle-chevron" d="m16 10-2 2 2 2" /></svg></button>
        <h1 :title="conversationTitle">{{ conversationTitle }}</h1>
        <LocalTitleStatus silent :conversation-id="conversationId" :has-message="!!store.turns.length || store.pending" :submitting="store.pending" />
        <button
          v-show="!plotMode && store.panel !== 'results'"
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
      <div v-if="store.error" class="global-error notice danger" role="alert"><p>{{ store.error }}</p><details><summary>错误详情</summary><code>{{ store.errorCode }}</code></details><button @click="store.recover">恢复会话 / 刷新状态</button><button v-if="draft.trim() && !store.disconnectedRequest" :disabled="store.running" title="会产生新的模型用量" @click="send">重新执行（新一轮）</button></div>
      <div v-if="store.disconnectedRequest" class="notice"><p>断线前的问题尚未确认。先恢复会话；若仍未显示，可用原请求编号重新核对，避免重复执行。</p><button @click="store.resendSameRequest">用原请求编号核对</button></div>
      <div v-show="!plotMode" class="chat-scroll" :class="{'chat-scroll-empty':showWelcome}" :aria-busy="store.loading" aria-live="polite">
        <div v-if="store.loading && !store.turns.length" class="conversation-loading" role="status">
          <p class="small muted">正在读取会话…</p>
          <div class="conversation-loading-question" aria-hidden="true"></div>
          <div class="conversation-loading-answer" aria-hidden="true"><span></span><span></span><span></span></div>
        </div>
        <div v-else-if="showWelcome" class="welcome">
          <div class="welcome-intro"><div class="welcome-copy"><p class="eyebrow">SIMBAD · ADS · Gaia DR3</p><h2>天文数据与文献检索</h2><p>查询天体、Gaia 测量和论文，保留每轮来源与结果。</p></div></div>
          <div class="example-list"><button v-for="example in examples" :key="example.label" @click="useExample(example.text)"><span>{{ example.label }}</span><span aria-hidden="true">↗</span></button></div>
          <p class="welcome-hint">示例仅填入输入框，由你确认发送。</p>
        </div>
        <template v-for="{ turn, modelChange } in conversationTimeline" :key="turn.turn_id">
          <ModelChangeNotice v-if="modelChange" :from="models.labelFor(modelChange.from)" :to="models.labelFor(modelChange.to)" />
          <article class="turn" :class="{ 'selected-turn':store.selectedTurnId===turn.turn_id }"><div class="turn-label"><span class="eyebrow">第 {{ turn.revision }} 轮</span><time>{{ new Date(turn.received_at).toLocaleTimeString('zh-CN',{hour:'2-digit',minute:'2-digit'}) }}</time><span v-if="turn.turn_id!==newest" class="tag">历史记录</span></div><UserMessage :text="turn.message" :attachments="turn.attachments" :turn-number="turn.revision" :disabled="store.running || store.creating || store.loading || sending || !!store.disconnectedRequest" @edit="editQuestion($event, turn.revision, turn.conversation_id)" /><div class="answer"><div class="answer-label"><span class="mini-star" aria-hidden="true">✳</span><b>AstroAgent</b><span v-if="turn.response" class="tag" :class="turn.response.status">{{ turn.response.status === 'success' ? '已完成' : turn.response.status === 'partial' ? '部分完成' : '查询未成功' }}</span></div><p v-if="turn.execution_status==='running'" class="processing">正在处理。刷新页面可恢复状态，不会自动重新执行。<button @click="store.recover">刷新状态</button></p><p v-if="turn.error" class="notice danger">{{ turn.error.message }}</p><MarkdownAnswer v-if="turn.response" class="answer-text" :text="turn.response.answer" /><p v-for="warning in turn.context?.warnings" :key="warning" class="notice">{{ warning }}</p><details v-if="turn.context?.included_turn_ids?.length" class="small"><summary>使用了 {{ turn.context.included_turn_ids.length }} 轮历史上下文</summary><p>历史数据保持原查询时间，不代表本轮重新查询。</p><code>{{ turn.context.included_turn_ids.join('\n') }}</code></details><div v-if="turn.response?.sources?.length" class="source-links"><template v-for="source in turn.response.sources" :key="source.url"><a v-if="safeLink(source.url)" :href="safeLink(source.url)!" target="_blank" rel="noopener noreferrer">{{ source.name }} ↗</a><span v-else>{{ source.url }}</span></template></div><button class="view-results" @click="openResults(turn.turn_id)">核查本轮结果与导出 <span aria-hidden="true">→</span></button></div></article>
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
        <div v-if="!plotMode && (models.error || (models.loaded && !models.configured))" class="model-catalog-error" role="status"><span>{{ models.error || '服务端尚未配置回答模型。' }}</span><button type="button" :disabled="models.loading" @click="models.load(true)">刷新模型</button></div>
        <div class="composer-bottom">
          <div class="composer-task-tools">
            <button type="button" class="composer-task-button composer-plot-toggle" :class="{ active: plotMode }" :aria-pressed="plotMode" :disabled="sending || store.running || store.creating || store.loading || !!store.disconnectedRequest" :data-tooltip="plotMode ? '返回对话，保留绘图进度和草稿' : '在当前工作台选择数据、描述图形并审阅绘图方案'" @click="togglePlot"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 4v16h16M7 15l4-5 4 3 5-7" /><circle cx="11" cy="10" r="1" /></svg><span>科研绘图</span><span v-if="plotMode" class="composer-plot-return">返回对话</span></button>
            <button type="button" class="composer-task-button composer-nbody-toggle" aria-haspopup="dialog" data-tooltip="N 体模拟入口已预留，后续开放" @click="nbodyDialog?.showModal()"><svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="3" /><circle cx="5" cy="6" r="1.5" /><circle cx="19" cy="17" r="1.5" /><path d="M6.3 7.2l3.4 2.9m4.7 3.8 3.4 2M18.5 8a8 8 0 0 0-9-3m-4 8a8 8 0 0 0 9 7" /></svg><span>N 体模拟</span><small>待开放</small></button>
          </div>
          <div v-show="!plotMode" class="composer-tools"><ModelSelector :model-value="currentModel" :disabled="sending || store.running || store.creating || store.loading || !!store.disconnectedRequest" @update:model-value="selectModel" /></div>
          <button v-if="plotMode" type="button" class="workbench-plot-upload" :disabled="!plotPanel?.canUpload" aria-label="上传绘图 CSV 或 TSV 数据" data-tooltip="上传 CSV / TSV 绘图数据" @click="plotPanel?.chooseFile()"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 16V4m-4 4 4-4 4 4M5 14v6h14v-6" /></svg></button>
          <AttachmentButton v-else :scope="modelScope" :disabled="attachmentDisabled" />
          <button class="button-primary composer-send" :disabled="plotMode ? !plotDraft.trim() || !plotReady || plotBusy : (!draft.trim() && !attachedFiles.length) || attachments.blocked(modelScope) || !currentModel || !models.configured || models.loading || store.running || store.creating || store.loading || sending || !!store.disconnectedRequest" type="submit" :aria-label="plotMode ? plotBusy ? '正在准备绘图' : '生成绘图方案' : store.running || sending ? '正在处理问题' : '发送问题'" :data-tooltip="plotMode ? '生成绘图方案，审阅后再确认执行' : store.running || sending ? '正在处理，请稍候' : '发送问题及附件；Enter 发送，Shift + Enter 换行'">
            <svg v-if="store.running || sending || (plotMode && plotBusy)" class="composer-send-spinner" viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="7" /></svg>
            <svg v-else viewBox="0 0 24 24" aria-hidden="true"><path d="M12 19V5m-5.5 5.5L12 5l5.5 5.5" /></svg>
          </button>
        </div>
        <p>{{ plotMode ? '生成方案后请核对数据、单位与脚本；确认执行后才会绘图。' : '模型回答需对照原始数据核查；位置候选源不等于星团成员。' }}</p>
      </form>
    </main>
    <ResultPanel id="workbench-results" :inert="plotMode || store.panel !== 'results'" :aria-hidden="plotMode || store.panel !== 'results'" :pending="store.pending" :turn="store.selectedTurn" :historical="!!store.selectedTurn && store.selectedTurn.turn_id!==newest" dismissible @close="closeResults" />
    <dialog ref="nbodyDialog" class="project-dialog nbody-placeholder" aria-labelledby="nbody-title" aria-describedby="nbody-description">
      <h2 id="nbody-title">N 体模拟 · 待开放</h2>
      <p id="nbody-description">模拟入口已预留，后续将在这里接入 N 体模拟功能。</p>
      <div class="project-actions"><button type="button" class="button-primary" autofocus @click="nbodyDialog?.close()">知道了</button></div>
    </dialog>
</div>
</template>
