<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api } from '../api'
import { projectsApi } from '../api/projects'
import { conversationExport, orderedConversations, readPinnedConversations, saveConversationExport, savePinnedConversations } from '../conversation-tools'
import { identityUser, logout } from '../identity-state'
import { useProjects } from '../stores/projects'
import { useWorkbench } from '../stores/workbench'
import type { Conversation, Project } from '../types'
import CreateProjectDialog from './CreateProjectDialog.vue'
import SuccessToast from './SuccessToast.vue'

const props = defineProps<{ activeProjectId?: string }>()
const emit = defineEmits<{
  create: []
  removed: [ids: string[]]
  'select-project': [projectId: string]
  'manage-project': [projectId: string, tab: 'context' | 'snapshots' | 'manage', promptDelete?: boolean]
}>()
const store = useWorkbench(), projectsStore = useProjects(), router = useRouter(), route = useRoute()
const projectsOpen = ref(true), recentOpen = ref(true)
const expandedProjects = ref<Record<string, boolean>>({})
const expandedAllProjects = ref<Record<string, boolean>>({})
const startingProjectId = ref('')
const userMenuOpen = ref(false)
const userMenuTrigger = ref<HTMLButtonElement | null>(null)
const userMenuRef = ref<HTMLElement | null>(null)
const displayName = computed(() => identityUser.value?.username?.trim() || identityUser.value?.email?.split('@')[0] || '科研用户')
const avatarText = computed(() => {
  const name = displayName.value.trim()
  return (name.slice(0, 2) || 'AA').toUpperCase()
})
const failedAvatarUrl = ref('')
const rawAvatarUrl = computed(() => identityUser.value?.avatar_url || '')
const avatarUrl = computed(() => (
  rawAvatarUrl.value && rawAvatarUrl.value !== failedAvatarUrl.value ? rawAvatarUrl.value : ''
))
const userRoleLabel = computed(() => identityUser.value?.admin ? '管理员' : '科研工作台')
const pins = ref<string[]>(readPinnedConversations()), selecting = ref(false), selected = ref<string[]>([])
const recentVisible = computed(() => recentOpen.value || selecting.value)
const selectionToggle = ref<HTMLButtonElement | null>(null), selectionExit = ref<HTMLButtonElement | null>(null)
const busy = ref(false), message = ref(''), error = ref('')
const deletionMessage = ref('')
const scrolling = ref(false)
const listScroller = ref<HTMLElement | null>(null), listContent = ref<HTMLElement | null>(null)
const scrollMetrics = ref({ height: 0, content: 0, offset: 0 }), draggingScrollbar = ref(false)
const listScrollable = computed(() => scrollMetrics.value.content > scrollMetrics.value.height + 1)
const thumbHeight = computed(() => {
  const { height, content } = scrollMetrics.value
  return Math.min(height, Math.max(32, Math.min(96, height * height / Math.max(1, content))))
})
const thumbTop = computed(() => {
  const { height, content, offset } = scrollMetrics.value
  return Math.max(0, Math.min(height - thumbHeight.value, offset / Math.max(1, content - height) * (height - thumbHeight.value)))
})
let listObserver: ResizeObserver | undefined
let scrollDrag: { pointer: number; y: number; offset: number } | null = null
let scrollTimer: ReturnType<typeof setTimeout> | undefined
function measureList() {
  const element = listScroller.value
  if (element) scrollMetrics.value = { height: element.clientHeight, content: element.scrollHeight, offset: element.scrollTop }
}
function revealScrollbar() {
  measureList()
  scrolling.value = true
  clearTimeout(scrollTimer)
  scrollTimer = setTimeout(() => { scrolling.value = false }, 900)
}
function beginScrollDrag(event: PointerEvent) {
  const element = listScroller.value
  if (event.button !== 0 || !element) return
  event.preventDefault()
  const rail = event.currentTarget as HTMLElement
  measureList()
  if (!(event.target instanceof Element && event.target.closest('.history-scroll-thumb'))) {
    const travel = scrollMetrics.value.height - thumbHeight.value
    element.scrollTop = Math.max(0, event.clientY - rail.getBoundingClientRect().top - thumbHeight.value / 2) / Math.max(1, travel) * (element.scrollHeight - element.clientHeight)
  }
  scrollDrag = { pointer: event.pointerId, y: event.clientY, offset: element.scrollTop }
  draggingScrollbar.value = true
  rail.setPointerCapture(event.pointerId)
  revealScrollbar()
}
function moveScrollDrag(event: PointerEvent) {
  if (!scrollDrag || scrollDrag.pointer !== event.pointerId || !listScroller.value) return
  const { height, content } = scrollMetrics.value
  listScroller.value.scrollTop = scrollDrag.offset + (event.clientY - scrollDrag.y) / Math.max(1, height - thumbHeight.value) * (content - height)
  revealScrollbar()
}
function endScrollDrag(event: PointerEvent) {
  if (!scrollDrag || scrollDrag.pointer !== event.pointerId) return
  scrollDrag = null; draggingScrollbar.value = false
  const rail = event.currentTarget as HTMLElement
  if (rail.hasPointerCapture(event.pointerId)) rail.releasePointerCapture(event.pointerId)
  revealScrollbar()
}
const menuId = ref(''), menu = ref<HTMLElement | null>(null), menuPosition = ref({ left: '0px', top: '0px' })
const projectMenuId = ref(''), projectMenu = ref<HTMLElement | null>(null), projectMenuPosition = ref({ left: '0px', top: '0px' })
const dialog = ref<HTMLDialogElement | null>(null), action = ref<'' | 'rename' | 'delete' | 'export' | 'assign-project'>('')
const createProjectDialog = ref<InstanceType<typeof CreateProjectDialog> | null>(null)
const targets = ref<Conversation[]>([]), title = ref('')
const assignProjectId = ref('')
let menuTrigger: HTMLButtonElement | null = null
let projectMenuTrigger: HTMLButtonElement | null = null
const conversations = computed(() => orderedConversations(store.conversations, pins.value))
const menuTarget = computed(() => store.conversations.find(item => item.id === menuId.value))
const projectMenuTarget = computed(() => projectsStore.customProjects.find(item => item.id === projectMenuId.value))
const locked = computed(() => busy.value || store.creating)

function closeMenu(focus = true) {
  const trigger = menuTrigger
  menuId.value = ''
  if (focus && trigger?.isConnected) trigger.focus()
}
function closeProjectMenu(focus = true) {
  const trigger = projectMenuTrigger
  projectMenuId.value = ''
  if (focus && trigger?.isConnected) trigger.focus()
}
async function openMenu(event: MouseEvent, id: string) {
  closeProjectMenu(false)
  if (menuId.value === id) { closeMenu(); return }
  menuTrigger = event.currentTarget as HTMLButtonElement
  menuId.value = id
  const rect = menuTrigger.getBoundingClientRect()
  menuPosition.value = { left: `${Math.max(8, Math.min(rect.right - 210, window.innerWidth - 218))}px`, top: `${Math.max(8, Math.min(rect.bottom + 6, window.innerHeight - 300))}px` }
  await nextTick()
  menu.value?.querySelector<HTMLElement>('button:not(:disabled), a')?.focus()
}
async function openProjectMenu(event: MouseEvent, id: string) {
  closeMenu(false)
  if (projectMenuId.value === id) { closeProjectMenu(); return }
  projectMenuTrigger = event.currentTarget as HTMLButtonElement
  projectMenuId.value = id
  const rect = projectMenuTrigger.getBoundingClientRect()
  projectMenuPosition.value = { left: `${Math.max(8, Math.min(rect.right - 216, window.innerWidth - 224))}px`, top: `${Math.max(8, Math.min(rect.bottom + 6, window.innerHeight - 400))}px` }
  await nextTick()
  projectMenu.value?.querySelector<HTMLElement>('button:not(:disabled), a')?.focus()
}
function menuKey(event: KeyboardEvent) {
  if (event.key === 'Escape') { event.preventDefault(); closeMenu(); return }
  const items = Array.from(menu.value?.querySelectorAll<HTMLElement>('button:not(:disabled), a') || [])
  const index = items.indexOf(document.activeElement as HTMLElement)
  if (['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) {
    event.preventDefault()
    const position = event.key === 'Home' ? 0 : event.key === 'End' ? items.length - 1 : (index + (event.key === 'ArrowDown' ? 1 : -1) + items.length) % items.length
    items[position]?.focus()
  }
}
function projectMenuKey(event: KeyboardEvent) {
  if (event.key === 'Escape') { event.preventDefault(); closeProjectMenu(); return }
  const items = Array.from(projectMenu.value?.querySelectorAll<HTMLElement>('button:not(:disabled), a') || [])
  const index = items.indexOf(document.activeElement as HTMLElement)
  if (['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) {
    event.preventDefault()
    const position = event.key === 'Home' ? 0 : event.key === 'End' ? items.length - 1 : (index + (event.key === 'ArrowDown' ? 1 : -1) + items.length) % items.length
    items[position]?.focus()
  }
}
function outside(event: PointerEvent) {
  if (event.target instanceof Node && !menu.value?.contains(event.target) && !menuTrigger?.contains(event.target)) closeMenu(false)
  if (event.target instanceof Node && !projectMenu.value?.contains(event.target) && !projectMenuTrigger?.contains(event.target)) closeProjectMenu(false)
  if (event.target instanceof Node && !userMenuRef.value?.contains(event.target) && !userMenuTrigger.value?.contains(event.target)) userMenuOpen.value = false
}
function dismissMenu(event: Event) {
  if (event.target instanceof Node && (menu.value?.contains(event.target) || projectMenu.value?.contains(event.target))) return
  closeMenu(false)
  closeProjectMenu(false)
}
function menuBlur(event: FocusEvent) {
  if (!(event.relatedTarget instanceof Node) || !menu.value?.contains(event.relatedTarget)) closeMenu(false)
}
function projectMenuBlur(event: FocusEvent) {
  if (!(event.relatedTarget instanceof Node) || !projectMenu.value?.contains(event.relatedTarget)) closeProjectMenu(false)
}
function persistPins(value: string[]) {
  pins.value = value
  if (!savePinnedConversations(value)) message.value = '浏览器无法保存置顶偏好，本次页面内仍有效。'
}
function togglePin() {
  const id = menuId.value
  if (!id) return
  persistPins(pins.value.includes(id) ? pins.value.filter(value => value !== id) : [id, ...pins.value])
  closeMenu()
}
async function openDialog(kind: 'rename' | 'delete' | 'export' | 'assign-project', values?: Conversation[]) {
  if (locked.value) return
  const choices = values || (menuTarget.value ? [menuTarget.value] : [])
  if (!choices.length) return
  targets.value = choices.map(value => ({ ...value }))
  title.value = choices[0]?.title || ''
  if (kind === 'assign-project') {
    await projectsStore.load(true).catch(() => undefined)
    const currentProject = projectsStore.memberships[choices[0]!.id] || ''
    assignProjectId.value = currentProject === projectsStore.defaultProjectId ? '' : currentProject
  }
  action.value = kind; error.value = ''; message.value = ''
  if (kind === 'delete') deletionMessage.value = ''
  closeMenu()
  await nextTick()
  dialog.value?.showModal()
}
async function openCreateProject() {
  if (locked.value) return
  error.value = ''; message.value = ''
  closeMenu(false)
  await createProjectDialog.value?.open()
}
async function onProjectCreated(payload: { project: Project; uploadedCount: number; startChat: boolean }) {
  projectsOpen.value = true
  const sourceNote = payload.uploadedCount ? `，已解析 ${payload.uploadedCount} 份参考来源` : ''
  message.value = `已创建科研项目「${payload.project.name}」${sourceNote}。`
  if (payload.startChat) {
    try {
      const created = await projectsStore.startConversationDetail(payload.project.id)
      store.preparedConversation = { ...created, turns: [] }
      await store.refreshList().catch(() => undefined)
      await router.push(`/conversations/${created.id}`)
      return
    } catch (reason) {
      error.value = reason instanceof Error ? reason.message : '项目已创建，但开启新对话失败。'
    }
  }
  emit('select-project', payload.project.id)
}
function chooseProject(projectId: string) {
  closeProjectMenu(false)
  if (projectConversations(projectId).length) {
    expandedProjects.value = { ...expandedProjects.value, [projectId]: true }
  }
  emit('select-project', projectId)
}
function manageProjectFromMenu(tab: 'context' | 'snapshots' | 'manage', promptDelete = false) {
  const id = projectMenuId.value
  if (!id) return
  closeProjectMenu(false)
  emit('manage-project', id, tab, promptDelete)
}
function visibleProjectConversations(projectId: string) {
  const all = projectConversations(projectId)
  return expandedAllProjects.value[projectId] ? all : all.slice(0, 6)
}
function projectConversations(projectId: string) {
  return conversations.value.filter(item => projectsStore.memberships[item.id] === projectId)
}
function toggleProjects() {
  projectsOpen.value = !projectsOpen.value
  if (!projectsOpen.value) closeProjectMenu(false)
}
function toggleProjectExpand(projectId: string) {
  expandedProjects.value = { ...expandedProjects.value, [projectId]: !expandedProjects.value[projectId] }
}
async function startProjectChat(projectId: string) {
  if (locked.value || store.running || store.loading || !!store.disconnectedRequest || startingProjectId.value) return
  startingProjectId.value = projectId
  error.value = ''; message.value = ''
  try {
    const created = await projectsStore.startConversationDetail(projectId)
    store.preparedConversation = { ...created, turns: [] }
    void store.refreshList().catch(() => undefined)
    await router.push(`/conversations/${created.id}`)
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : '在项目中新建对话失败，请稍后重试。'
  } finally {
    startingProjectId.value = ''
  }
}
async function archiveOne(id = menuId.value) {
  if (locked.value || !id) return
  const item = store.conversations.find(value => value.id === id)
  if (!item) return
  busy.value = true; error.value = ''; message.value = ''
  closeMenu(false)
  try {
    const wasOpen = route.params.id === id
    await store.archiveConversation(id)
    persistPins(pins.value.filter(value => value !== id))
    message.value = '会话已归档，可在「设置 → 数据管理」中恢复。'
    if (wasOpen) await router.push('/')
  } catch (e) { error.value = e instanceof Error ? e.message : '归档会话失败，请稍后重试。' }
  finally { busy.value = false }
}
async function archiveSelected() {
  if (!selected.value.length || locked.value || store.running) return
  const ids = [...selected.value]
  busy.value = true; error.value = ''; message.value = ''
  const archivedIds: string[] = [], failures: string[] = []
  try {
    for (const id of ids) {
      const item = store.conversations.find(value => value.id === id)
      try {
        await store.archiveConversation(id)
        archivedIds.push(id)
      } catch (e) { failures.push(`${item?.title || id}：${e instanceof Error ? e.message : '归档失败'}`) }
    }
    persistPins(pins.value.filter(id => !archivedIds.includes(id)))
    selected.value = ids.filter(id => !archivedIds.includes(id))
    if (!selected.value.length) selecting.value = false
    if (archivedIds.length) message.value = `已归档 ${archivedIds.length} 个会话，可在「设置 → 数据管理」中恢复。`
    error.value = failures.join('\n')
    if (typeof route.params.id === 'string' && archivedIds.includes(route.params.id)) await router.push('/')
  } finally { busy.value = false }
}
async function enterSelection(ids: string[] = []) {
  selected.value = ids; selecting.value = true; closeMenu(false); userMenuOpen.value = false
  await nextTick()
  selectionExit.value?.focus({ preventScroll: true })
}
function startSelection() { void enterSelection(menuId.value ? [menuId.value] : []) }
function stopSelection() {
  selecting.value = false; selected.value = []
  void nextTick(() => selectionToggle.value?.focus({ preventScroll: true }))
}
function toggleRecent() {
  recentOpen.value = !recentOpen.value
  if (!recentOpen.value) closeMenu(false)
}
function chooseConversation(id: string) {
  if (selecting.value) selected.value = selected.value.includes(id) ? selected.value.filter(value => value !== id) : [...selected.value, id]
  else void router.push(`/conversations/${id}`)
}
const selectionPinned = computed(() => selected.value.length > 0 && selected.value.every(id => pins.value.includes(id)))
function pinSelected() {
  if (!selected.value.length || locked.value) return
  persistPins(selectionPinned.value ? pins.value.filter(id => !selected.value.includes(id)) : [...selected.value, ...pins.value.filter(id => !selected.value.includes(id))])
}
function deleteSelected() { void openDialog('delete', conversations.value.filter(value => selected.value.includes(value.id))) }
function closeDialog() { if (!busy.value) dialog.value?.close() }

async function execute() {
  if (locked.value || !targets.value.length) return
  busy.value = true; error.value = ''
  try {
    const target = targets.value[0]!
    if (action.value === 'rename') {
      if (!title.value.trim()) return
      const value = await api.rename(target.id, title.value.trim(), target.metadata_revision)
      store.conversations = store.conversations.map(item => item.id === value.id ? value : item)
      if (store.current?.id === value.id) { store.current.title = value.title; store.current.metadata_revision = value.metadata_revision }
      message.value = '会话已重命名。'
    } else if (action.value === 'assign-project') {
      const sourceId = projectsStore.memberships[target.id] || null
      const destinationId = assignProjectId.value || null
      if (sourceId !== destinationId) {
        const latestConversation = await api.detail(target.id)
        if (!destinationId && sourceId) {
          const sourceProject = await projectsApi.detail(sourceId)
          await projectsApi.move(sourceId, target.id, {
            expected_revision: sourceProject.revision,
            expected_conversation_revision: latestConversation.revision,
            expected_metadata_revision: latestConversation.metadata_revision,
            expected_source_project_id: sourceId,
            expected_source_revision: sourceProject.revision,
          }, true)
          message.value = '已将会话移出科研项目。'
        } else if (destinationId) {
          const [destProject, sourceProject] = await Promise.all([
            projectsApi.detail(destinationId),
            sourceId && sourceId !== destinationId ? projectsApi.detail(sourceId) : Promise.resolve(null),
          ])
          await projectsApi.move(destinationId, target.id, {
            expected_revision: destProject.revision,
            expected_conversation_revision: latestConversation.revision,
            expected_metadata_revision: latestConversation.metadata_revision,
            expected_source_project_id: sourceId,
            expected_source_revision: sourceProject?.revision ?? null,
          }, false)
          message.value = `已移入项目「${destProject.name}」。`
        }
        await projectsStore.load(true)
      }
    } else if (action.value === 'export') {
      const value = await conversationExport(target.id)
      saveConversationExport(target.id, value)
      message.value = '已导出会话 JSON，请核对内容后自行分享。'
    } else if (action.value === 'delete') {
      const removed: string[] = [], failures: string[] = []
      // Each server-confirmed deletion is reflected immediately; failed items stay selected.
      for (const item of targets.value) {
        try {
          await api.delete(item.id)
          removed.push(item.id)
          store.conversations = store.conversations.filter(value => value.id !== item.id)
          if (store.current?.id === item.id) { store.loadToken++; store.current = null; store.turns = []; store.selectedTurnId = '' }
          if (store.disconnectedRequest?.id === item.id) store.disconnectedRequest = null
        } catch (e) { failures.push(`${item.title}：${e instanceof Error ? e.message : '删除状态未确认，请刷新核对'}`) }
      }
      persistPins(pins.value.filter(id => !removed.includes(id)))
      selected.value = targets.value.filter(value => !removed.includes(value.id)).map(value => value.id)
      if (!selected.value.length) selecting.value = false
      if (removed.length) deletionMessage.value = `已删除 ${removed.length} 个会话。`
      error.value = failures.join('\n')
      emit('removed', removed)
    }
    dialog.value?.close()
    try { await store.refreshList() } catch (e) { error.value = `${error.value ? error.value + '\n' : ''}${e instanceof Error ? e.message : '列表刷新失败，请核对状态'}` }
  } catch (e) { error.value = e instanceof Error ? e.message : '操作未确认，请刷新核对。' }
  finally { busy.value = false }
}
watch(() => route.fullPath, () => { closeMenu(false); closeProjectMenu(false); userMenuOpen.value = false; if (!busy.value) dialog.value?.close() })
watch(() => store.conversations, items => {
  selected.value = selected.value.filter(id => items.some(item => item.id === id))
  const remainingPins = pins.value.filter(id => items.some(item => item.id === id))
  if (remainingPins.length !== pins.value.length) persistPins(remainingPins)
  if (menuId.value && !items.some(item => item.id === menuId.value)) closeMenu(false)
})
onMounted(() => {
  void projectsStore.load().catch(() => undefined)
  listObserver = new ResizeObserver(measureList)
  if (listScroller.value) listObserver.observe(listScroller.value)
  if (listContent.value) listObserver.observe(listContent.value)
  measureList()
  document.addEventListener('pointerdown', outside)
  window.addEventListener('resize', dismissMenu)
  window.addEventListener('scroll', dismissMenu, true)
})
onBeforeUnmount(() => {
  listObserver?.disconnect()
  scrollDrag = null
  clearTimeout(scrollTimer)
  document.removeEventListener('pointerdown', outside)
  window.removeEventListener('resize', dismissMenu)
  window.removeEventListener('scroll', dismissMenu, true)
  dialog.value?.close()
})
</script>

<template>
  <aside class="history-panel" :class="{ 'is-selecting': selecting, 'is-scrolling': scrolling, 'is-dragging-scrollbar': draggingScrollbar }" aria-label="会话列表" @keydown.esc="selecting ? stopSelection() : (userMenuOpen = false)">
    <div class="history-top">
      <Transition name="history-mode">
        <button v-if="!selecting" key="create" class="new-conversation" :inert="selecting" :disabled="locked || store.loading || store.running || !!store.disconnectedRequest" @click="emit('create')"><span aria-hidden="true">＋</span>{{ store.creating ? '正在准备…' : '新建会话' }}</button>
        <div v-else key="selection" class="history-selection-heading" :inert="!selecting"><span>选择会话 <small>{{ selected.length ? `已选 ${selected.length} 个` : '' }}</small></span><button ref="selectionExit" class="history-icon-button" :disabled="locked" aria-label="退出多选" data-tooltip="退出多选" @click="stopSelection"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="m6 6 12 12M6 18 18 6" /></svg></button></div>
      </Transition>
    </div>
    <div class="history-scroll-shell">
      <div ref="listScroller" class="history-scroll" tabindex="0" aria-label="滚动浏览会话" @scroll.passive="revealScrollbar">
        <div ref="listContent" class="history-scroll-content">
          <section v-if="!selecting" class="sidebar-projects" aria-label="科研项目">
            <div class="history-list-heading sidebar-projects-head">
              <button type="button" class="sidebar-section-toggle" :aria-expanded="projectsOpen" aria-controls="sidebar-project-list" @click="toggleProjects">
                <span class="sidebar-section-icon" aria-hidden="true">
                  <svg viewBox="0 0 24 24"><path d="M12 3 3 7.5 12 12l9-4.5L12 3Z" /><path d="m3 12 9 4.5 9-4.5" /><path d="m3 16.5 9 4.5 9-4.5" /></svg>
                </span>
                <span class="history-label">项目</span>
                <svg class="sidebar-chevron sidebar-section-chevron" :class="{ open: projectsOpen }" viewBox="0 0 24 24" aria-hidden="true"><path d="m9 6 6 6-6 6" /></svg>
              </button>
              <button type="button" class="history-icon-button sidebar-projects-add" :disabled="locked || projectsStore.customProjects.length >= 20" aria-label="新建科研项目" data-tooltip="新建科研项目" @click="openCreateProject">
                <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 5v14M5 12h14" /></svg>
              </button>
            </div>
            <div id="sidebar-project-list" class="sidebar-disclosure" :inert="!projectsOpen">
              <div class="sidebar-disclosure-body">
                <div class="sidebar-project-list">
                  <div v-for="project in projectsStore.customProjects" :key="project.id">
                    <div
                      class="sidebar-project-row"
                      :class="{
                        selected: props.activeProjectId === project.id || route.path.startsWith(`/projects/${project.id}/`),
                        'has-active-chat': !!store.current && projectsStore.memberships[store.current.id] === project.id,
                      }"
                    >
                      <button
                        v-if="projectConversations(project.id).length"
                        type="button"
                        class="sidebar-project-expand"
                        :aria-expanded="!!expandedProjects[project.id]"
                        :aria-controls="`sidebar-project-conversations-${project.id}`"
                        :aria-label="expandedProjects[project.id] ? `收起「${project.name}」的对话` : `展开「${project.name}」的对话`"
                        @click="toggleProjectExpand(project.id)"
                      >
                        <svg class="sidebar-chevron" :class="{ open: !!expandedProjects[project.id] }" viewBox="0 0 24 24" aria-hidden="true"><path d="m9 6 6 6-6 6" /></svg>
                      </button>
                      <button
                        type="button"
                        class="sidebar-project-item"
                        :class="{ 'is-unindented': !projectConversations(project.id).length }"
                        data-tooltip-truncated
                        @click="chooseProject(project.id)"
                      >
                        <span class="sidebar-project-icon" aria-hidden="true">
                          <svg viewBox="0 0 24 24"><path d="M3 7V5a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2Z" /></svg>
                        </span>
                        <span class="sidebar-project-name" data-tooltip-source>{{ project.name }}</span>
                      </button>
                      <button
                        type="button"
                        class="sidebar-project-quick-add"
                        :disabled="locked || store.running || store.loading || !!store.disconnectedRequest || !!startingProjectId"
                        :aria-label="`在「${project.name}」中新建对话`"
                        :data-tooltip="`在「${project.name}」中新建对话`"
                        @click="startProjectChat(project.id)"
                      >
                        <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 5v14M5 12h14" /></svg>
                      </button>
                      <button
                        type="button"
                        class="sidebar-project-quick-add"
                        :disabled="locked"
                        :aria-label="`项目操作：${project.name}`"
                        aria-haspopup="menu"
                        :aria-expanded="projectMenuId === project.id"
                        data-tooltip="项目指令、知识、快照与管理"
                        @click="openProjectMenu($event, project.id)"
                      >
                        <svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="5" cy="12" r="1.6" fill="currentColor" stroke="none" /><circle cx="12" cy="12" r="1.6" fill="currentColor" stroke="none" /><circle cx="19" cy="12" r="1.6" fill="currentColor" stroke="none" /></svg>
                      </button>
                    </div>
                    <div
                      :id="`sidebar-project-conversations-${project.id}`"
                      class="sidebar-disclosure"
                      :inert="!expandedProjects[project.id] || !projectConversations(project.id).length"
                    >
                      <div class="sidebar-disclosure-body">
                        <div class="sidebar-project-chats">
                          <RouterLink
                            v-for="chat in visibleProjectConversations(project.id)"
                            :key="chat.id"
                            :to="`/conversations/${chat.id}`"
                            class="sidebar-project-chat-link"
                            :class="{ selected: store.current?.id === chat.id }"
                            data-tooltip-truncated
                            @pointerenter="store.prefetch(chat.id)"
                          >
                            <span data-tooltip-source>{{ chat.title }}</span>
                          </RouterLink>
                          <button
                            v-if="projectConversations(project.id).length > 6 && !expandedAllProjects[project.id]"
                            type="button"
                            class="sidebar-project-chat-more"
                            @click="expandedAllProjects = { ...expandedAllProjects, [project.id]: true }"
                          >
                            展开全部 {{ projectConversations(project.id).length }} 个对话
                          </button>
                        </div>
                      </div>
                    </div>
                  </div>
                  <p v-if="!projectsStore.customProjects.length" class="sidebar-project-hint">按课题归类指令、知识与对话</p>
                </div>
              </div>
            </div>
          </section>
          <div class="history-list-heading">
            <button type="button" class="sidebar-section-toggle sidebar-recent-toggle" :aria-expanded="recentVisible" aria-controls="recent-conversations" :disabled="selecting" @click="toggleRecent">
              <span class="history-label">最近会话</span>
              <svg class="sidebar-chevron sidebar-section-chevron" :class="{ open: recentVisible }" viewBox="0 0 24 24" aria-hidden="true"><path d="m9 6 6 6-6 6" /></svg>
            </button>
            <Transition name="history-control"><button v-if="store.conversations.length && !selecting" ref="selectionToggle" class="history-icon-button history-manage" :inert="selecting" :disabled="locked" aria-label="多选管理会话" data-tooltip="多选管理会话" @click="enterSelection()"><svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="5" cy="6" r="1.5" /><circle cx="5" cy="12" r="1.5" /><circle cx="5" cy="18" r="1.5" /><path d="M11 6h9M11 12h9M11 18h9" /></svg></button></Transition>
          </div>
          <p v-if="message" class="sidebar-feedback" role="status">{{ message }}</p>
          <p v-if="error && !dialog?.open" class="sidebar-feedback danger" role="alert">{{ error }}</p>
          <Transition name="history-mode">
            <div v-show="recentVisible" id="recent-conversations" :inert="!recentVisible">
              <nav class="conversation-list" aria-label="本地会话">
            <div v-for="conversation in conversations" :key="conversation.id" class="conversation-row" :class="{selected:selecting ? selected.includes(conversation.id) : store.current?.id===conversation.id}">
              <div class="conversation-choice-slot" :inert="!selecting" :aria-hidden="!selecting"><input v-model="selected" type="checkbox" :value="conversation.id" :aria-label="`选择会话 ${conversation.title}`" :disabled="locked || !selecting"></div>
              <button class="conversation-item" :class="{selected:!selecting && store.current?.id===conversation.id}" :aria-current="!selecting && store.current?.id===conversation.id ? 'page' : undefined" :aria-pressed="selecting ? selected.includes(conversation.id) : undefined" :disabled="locked" data-tooltip-truncated @pointerenter="!selecting && store.prefetch(conversation.id)" @click="chooseConversation(conversation.id)">
                <span><b data-tooltip-source>{{ conversation.title }}</b><small><span v-if="pins.includes(conversation.id)" class="conversation-pinned">置顶 · </span><span v-if="projectsStore.projectNameFor(conversation.id)" class="conversation-project-tag">{{ projectsStore.projectNameFor(conversation.id) }} · </span>{{ new Date(conversation.updated_at).toLocaleDateString('zh-CN') }}</small></span>
              </button>
              <div class="conversation-more-slot" :inert="selecting" :aria-hidden="selecting">
                <button class="conversation-more" data-tooltip="" :aria-label="`会话操作：${conversation.title}`" aria-haspopup="menu" :aria-expanded="menuId===conversation.id" :disabled="locked || selecting" @click="openMenu($event, conversation.id)">
                  <svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="5" cy="12" r="1.6" /><circle cx="12" cy="12" r="1.6" /><circle cx="19" cy="12" r="1.6" /></svg>
                </button>
              </div>
            </div>
              </nav>
              <p v-if="!store.conversations.length" class="small muted empty-history">会话保存在本机，<br>从一个问题开始。</p>
            </div>
          </Transition>
        </div>
      </div>
      <div v-if="listScrollable" class="history-scrollbar" aria-hidden="true" @pointerdown="beginScrollDrag" @pointermove="moveScrollDrag" @pointerup="endScrollDrag" @pointercancel="endScrollDrag" @lostpointercapture="endScrollDrag"><span class="history-scroll-thumb" :style="{ height: `${thumbHeight}px`, transform: `translateY(${thumbTop}px)` }"></span></div>
    </div>
    <div class="history-bottom">
      <Transition name="history-mode">
        <div v-if="selecting" key="actions" class="history-batch-actions" :inert="!selecting" aria-label="批量管理会话">
          <button :disabled="locked || !selected.length" @click="pinSelected"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="m14 3 7 7-4 1-4 5-2-2-6 6m6-6-3-3 5-4z" /></svg>{{ selectionPinned ? '取消置顶' : '置顶' }}</button>
          <button :disabled="locked || !selected.length || store.running" @click="archiveSelected"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 5h18v4H3zM5 9v10h14V9M10 13h4" /></svg>归档</button>
          <button class="selection-delete" :disabled="locked || !selected.length || store.running" aria-label="删除所选会话" @click="deleteSelected"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 6h16M9 6V3h6v3M6 6l1 15h10l1-15M10 10v7m4-7v7" /></svg>删除</button>
        </div>
        <div v-else key="footer" class="sidebar-user-wrap" :inert="selecting">
          <Transition name="history-mode">
            <div v-if="userMenuOpen" ref="userMenuRef" class="sidebar-user-menu" role="menu" aria-label="账号菜单">
              <div class="sidebar-user-menu-header">
                <span class="sidebar-user-avatar is-sm" aria-hidden="true">
                  <img
                    v-if="avatarUrl"
                    :src="avatarUrl"
                    alt=""
                    class="sidebar-user-avatar-img"
                    @error="failedAvatarUrl = avatarUrl"
                  />
                  <template v-else>{{ avatarText }}</template>
                </span>
                <div class="sidebar-user-menu-meta">
                  <b>{{ displayName }}</b>
                  <small>{{ identityUser?.email }}</small>
                </div>
              </div>
              <div class="sidebar-user-menu-divider"></div>
              <RouterLink role="menuitem" to="/profile" @click="userMenuOpen = false">
                <svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="9" /><circle cx="12" cy="9.5" r="2.75" /><path d="M6.8 18.8a6 6 0 0 1 10.4 0" /></svg>
                <span>个人资料</span>
              </RouterLink>
              <RouterLink role="menuitem" to="/settings" @click="userMenuOpen = false">
                <svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="3" /><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9c.26.604.852.997 1.51 1H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1Z" /></svg>
                <span>设置</span>
              </RouterLink>
              <div class="sidebar-user-menu-divider"></div>
              <button type="button" role="menuitem" class="danger" @click="userMenuOpen = false; logout()">
                <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4M16 17l5-5-5-5M21 12H9" /></svg>
                <span>退出登录</span>
              </button>
            </div>
          </Transition>
          <button
            ref="userMenuTrigger"
            type="button"
            class="sidebar-user-card"
            :aria-expanded="userMenuOpen"
            aria-haspopup="menu"
            data-tooltip-truncated
            @click="userMenuOpen = !userMenuOpen"
          >
            <span class="sidebar-user-avatar" aria-hidden="true">
              <img
                v-if="avatarUrl"
                :src="avatarUrl"
                alt=""
                class="sidebar-user-avatar-img"
                @error="failedAvatarUrl = avatarUrl"
              />
              <template v-else>{{ avatarText }}</template>
            </span>
            <span class="sidebar-user-info">
              <b class="sidebar-user-name" data-tooltip-source>{{ displayName }}</b>
              <small class="sidebar-user-role">{{ userRoleLabel }}</small>
            </span>
          </button>
        </div>
      </Transition>
    </div>

    <Teleport to="body">
      <div v-if="menuTarget" ref="menu" class="conversation-menu" role="menu" aria-label="会话操作" :style="menuPosition" @keydown="menuKey" @focusout="menuBlur">
        <button role="menuitem" @click="openDialog('rename')"><span aria-hidden="true">✎</span>重命名</button>
        <button role="menuitem" title="置顶顺序保存在当前浏览器" @click="togglePin"><span aria-hidden="true">↟</span>{{ pins.includes(menuId) ? '取消置顶' : '置顶' }}</button>
        <button role="menuitem" :disabled="store.running && store.current?.id===menuId" @click="openDialog('assign-project')"><span aria-hidden="true">▤</span>移入科研项目</button>
        <button role="menuitem" :disabled="store.running && store.current?.id===menuId" @click="archiveOne()"><span aria-hidden="true">⌸</span>归档会话</button>
        <button role="menuitem" @click="openDialog('export')"><span aria-hidden="true">↓</span>导出会话 JSON</button>
        <button role="menuitem" @click="startSelection"><span aria-hidden="true">☷</span>多选整理</button>
        <button role="menuitem" class="danger" :disabled="store.running && store.current?.id===menuId" @click="openDialog('delete')"><span aria-hidden="true">×</span>删除会话</button>
      </div>
      <div v-if="projectMenuTarget" ref="projectMenu" class="conversation-menu" role="menu" :aria-label="`项目操作：${projectMenuTarget.name}`" :style="projectMenuPosition" @keydown="projectMenuKey" @focusout="projectMenuBlur">
        <button role="menuitem" @click="manageProjectFromMenu('context')"><span aria-hidden="true">✎</span>指令与项目知识</button>
        <button role="menuitem" @click="manageProjectFromMenu('snapshots')"><span aria-hidden="true">◈</span>快照与复核</button>
        <button role="menuitem" @click="manageProjectFromMenu('manage')"><span aria-hidden="true">▤</span>会话与备份导出</button>
        <div class="conversation-menu-divider" role="separator"></div>
        <RouterLink role="menuitem" :to="`/projects/${projectMenuTarget.id}/knowledge`" @click="closeProjectMenu(false)"><span aria-hidden="true">⊞</span>本地知识库</RouterLink>
        <RouterLink role="menuitem" :to="`/projects/${projectMenuTarget.id}/rag`" @click="closeProjectMenu(false)"><span aria-hidden="true">◎</span>文献知识问答</RouterLink>
        <RouterLink role="menuitem" :to="`/projects/${projectMenuTarget.id}/workflows`" @click="closeProjectMenu(false)"><span aria-hidden="true">▷</span>科研流程</RouterLink>
        <RouterLink role="menuitem" :to="{ path: '/', query: { project: projectMenuTarget.id, result: 'compute' } }" @click="closeProjectMenu(false)"><span aria-hidden="true">◌</span>N 体计算记录</RouterLink>
        <RouterLink role="menuitem" :to="`/projects/${projectMenuTarget.id}/overview`" @click="closeProjectMenu(false)"><span aria-hidden="true">☍</span>来源关联</RouterLink>
        <button role="menuitem" class="danger" @click="manageProjectFromMenu('manage', true)"><span aria-hidden="true">×</span>删除项目</button>
      </div>
    </Teleport>
    <CreateProjectDialog ref="createProjectDialog" :default-start-chat="false" @created="onProjectCreated" />
    <dialog ref="dialog" class="project-dialog conversation-dialog" :aria-label="action==='rename' ? '重命名会话' : action==='assign-project' ? '移入科研项目' : action==='export' ? '导出会话' : '删除会话'" @cancel="busy && $event.preventDefault()" @close="action=''">
      <div class="dialog-header">
        <div class="dialog-header-copy">
          <h2>{{ action==='rename' ? '重命名会话' : action==='assign-project' ? '移入科研项目' : action==='export' ? '导出这份会话？' : `删除 ${targets.length} 个会话？` }}</h2>
        </div>
        <button type="button" class="dialog-close" aria-label="关闭" :disabled="busy" @click="closeDialog">
          <svg viewBox="0 0 24 24" aria-hidden="true"><path d="m6 6 12 12M6 18 18 6" /></svg>
        </button>
      </div>
      <form class="project-form" @submit.prevent="execute">
        <template v-if="action==='rename'">
          <label for="sidebar-conversation-title">会话名称</label>
          <input id="sidebar-conversation-title" v-model="title" maxlength="80" required autofocus :disabled="busy">
        </template>
        <template v-else-if="action==='assign-project'">
          <p class="small muted">{{ targets[0]?.title }}</p>
          <label for="sidebar-assign-project">选择所属科研项目</label>
          <select id="sidebar-assign-project" v-model="assignProjectId" :disabled="busy">
            <option value="">不归属任何课题项目</option>
            <option v-for="project in projectsStore.customProjects" :key="project.id" :value="project.id">{{ project.name }}</option>
          </select>
          <p v-if="!projectsStore.customProjects.length" class="small muted">尚未创建科研项目，可先点击左侧「项目」旁的 ＋ 创建。</p>
        </template>
        <template v-else-if="action==='export'">
          <p><strong>{{ targets[0]?.title }}</strong></p>
          <p>将下载包含问题、回答、来源和保存结果的 JSON，可能含私人内容。请核对后自行分享。</p>
          <p class="small muted">此文件是会话副本；完整课题备份可在项目菜单或「设置 → 数据管理」导出 ZIP 备份包。运行中的会话需等待完成。</p>
        </template>
        <template v-else>
          <ul><li v-for="target in targets" :key="target.id">{{ target.title }}</li></ul>
          <p>将删除所选会话及其中的消息，无法在页面撤销。已经保存的项目快照和下载文件保留。</p>
        </template>
        <p v-if="error" class="notice danger" role="alert">{{ error }}</p>
        <div class="project-actions">
          <button type="button" :disabled="busy" @click="closeDialog">取消</button>
          <button type="submit" :class="action==='delete' ? 'button-danger' : 'button-primary'" :disabled="busy || (action==='rename' && !title.trim())">{{ busy ? '正在处理…' : action==='rename' ? '保存名称' : action==='assign-project' ? '保存归属' : action==='export' ? '确认下载 JSON' : '确认删除' }}</button>
        </div>
      </form>
    </dialog>
    <SuccessToast v-model:message="deletionMessage" />
  </aside>
</template>

<style scoped>
/* Only this middle region scrolls; fixed controls never share its scrollbar. */
aside.history-panel.history-panel { overflow: hidden; --selection-duration: 200ms; --selection-easing: cubic-bezier(.2, .7, .3, 1); }
.history-top { display: grid; flex: none; height: 40px; }
.history-top > * { grid-area: 1 / 1; min-width: 0; }
.history-top .new-conversation { width: 100%; height: 40px; min-height: 40px; margin: 0; }
.history-selection-heading { display: flex; min-height: 40px; align-items: center; justify-content: space-between; gap: 8px; color: var(--ink); font-size: 14px; }
.history-selection-heading small { margin-left: 6px; font-size: 11px; color: var(--muted); }
.history-scroll-shell { position: relative; flex: 1 1 0; min-height: 0; margin-top: 14px; }
.history-scroll { width: 100%; height: 100%; min-height: 0; overflow: auto; overscroll-behavior-y: contain; scrollbar-width: none; padding-right: 6px; }
.history-scroll::-webkit-scrollbar { display: none; width: 0; height: 0; }
.history-list-heading { min-height: 30px; margin: 2px 0 6px; padding-inline: 8px 3px; }
.history-list-heading .history-label { margin: 0; font-size: 11.5px; font-weight: 550; letter-spacing: 0.03em; color: var(--muted); line-height: 1; }
.sidebar-projects {
  margin-bottom: 14px;
  padding: 8px 7px 7px;
  border: 1px solid var(--line);
  border-radius: 13px;
  background: color-mix(in srgb, var(--surface-card) 52%, transparent);
  box-shadow: inset 0 1px 0 var(--inset-highlight);
}
.sidebar-projects .sidebar-projects-head {
  min-height: 30px;
  margin: 0;
  padding-inline: 2px;
  justify-content: space-between;
}
.sidebar-section-toggle {
  display: inline-flex;
  flex: 1;
  min-width: 0;
  align-items: center;
  justify-content: flex-start;
  gap: 7px;
  min-height: 28px;
  padding: 3px 6px 3px 3px;
  border: 0;
  border-radius: 8px;
  background: transparent;
  color: var(--ink);
  box-shadow: none;
  transform: none;
}
.sidebar-section-toggle:hover:not(:disabled),
.sidebar-section-toggle:active:not(:disabled) {
  background: color-mix(in srgb, var(--accent) 8%, transparent);
  color: var(--ink);
  border: 0;
  box-shadow: none;
  transform: none;
}
.sidebar-section-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  flex: 0 0 22px;
  border-radius: 7px;
  background: var(--accent-soft);
  color: var(--accent);
}
.sidebar-section-icon svg {
  width: 13px;
  height: 13px;
  fill: none;
  stroke: currentColor;
  stroke-width: 1.85;
  stroke-linecap: round;
  stroke-linejoin: round;
}
.sidebar-section-toggle .history-label {
  flex: 0 1 auto;
  font-size: 12.5px;
  font-weight: 650;
  letter-spacing: 0.01em;
  color: var(--ink);
}
.sidebar-recent-toggle { padding-inline-start: 0; }
.sidebar-recent-toggle .history-label { font-size: 11.5px; font-weight: 550; color: var(--muted); }
.sidebar-section-chevron {
  margin-left: 1px;
  color: var(--muted);
  opacity: 0.8;
}
.sidebar-projects-add {
  width: 26px;
  height: 26px;
  min-height: 26px;
  padding: 4px;
  border-radius: 7px;
}
.sidebar-chevron { width: 12px; height: 12px; flex: none; fill: none; stroke: currentColor; stroke-width: 2; stroke-linecap: round; stroke-linejoin: round; transition: transform 140ms ease; }
.sidebar-chevron.open { transform: rotate(90deg); }
.sidebar-disclosure {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  grid-template-rows: 0fr;
  opacity: 0;
  visibility: hidden;
  transition:
    grid-template-rows var(--selection-duration) var(--selection-easing),
    opacity var(--selection-duration) ease,
    visibility var(--selection-duration);
}
.sidebar-disclosure:not([inert]) {
  grid-template-rows: 1fr;
  opacity: 1;
  visibility: inherit;
}
.sidebar-disclosure-body {
  min-block-size: 0;
  overflow: hidden;
}
.sidebar-project-list {
  display: flex;
  flex-direction: column;
  gap: 3px;
  margin-top: 7px;
  padding-top: 7px;
  border-top: 1px solid var(--line);
}
.sidebar-project-row {
  position: relative;
  display: flex;
  align-items: center;
  gap: 2px;
  height: 36px;
  min-height: 36px;
  padding-inline: 5px 4px;
  border-radius: 9px;
  transition: background-color 140ms var(--ease-out), box-shadow 160ms var(--ease-out);
}
.sidebar-project-row:not(.selected):hover {
  background: color-mix(in srgb, var(--surface-card) 78%, transparent);
  box-shadow: inset 0 0 0 1px var(--line);
}
.sidebar-project-row.selected {
  background: linear-gradient(155deg, rgb(255 255 255 / 92%) 0%, color-mix(in srgb, var(--accent) 8%, rgb(255 255 255 / 80%)) 100%);
  box-shadow:
    0 4px 12px -4px color-mix(in srgb, var(--accent) 22%, rgb(16 32 54 / 10%)),
    0 1px 2px rgb(0 0 0 / 5%),
    inset 0 1px 0 0 #fff,
    inset 0 0 0 1px color-mix(in srgb, var(--accent) 24%, transparent);
}
.sidebar-project-row.selected:hover {
  background: linear-gradient(155deg, rgb(255 255 255 / 96%) 0%, color-mix(in srgb, var(--accent) 11%, rgb(255 255 255 / 86%)) 100%);
}
.sidebar-project-row.has-active-chat:not(.selected) {
  background: color-mix(in srgb, var(--accent-soft) 50%, transparent);
  box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--accent) 16%, transparent);
}
.sidebar-project-expand { display: inline-flex; align-items: center; justify-content: center; width: 18px; height: 24px; min-height: 24px; flex: 0 0 18px; padding: 0; margin: 0; border: 0; border-radius: 6px; background: transparent; box-shadow: none; color: var(--muted); transform: none; }
.sidebar-project-expand:hover:not(:disabled),
.sidebar-project-expand:active:not(:disabled) { background: transparent; border: 0; box-shadow: none; color: var(--accent); transform: none; }
.sidebar-project-item,
.sidebar-project-item:hover:not(:disabled),
.sidebar-project-item:active:not(:disabled) {
  display: flex;
  align-items: center;
  gap: 7px;
  flex: 1;
  min-width: 0;
  min-height: 30px;
  padding: 3px 4px;
  padding-inline-start: var(--project-item-inset, 4px);
  border: 0;
  border-radius: 7px;
  background: transparent;
  color: var(--ink);
  font-size: 12.5px;
  font-weight: 500;
  text-decoration: none;
  text-align: left;
  box-shadow: none;
  transform: none;
  transition: color 140ms ease;
}
.sidebar-project-item.is-unindented { --project-item-inset: 10px; }
.sidebar-project-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 21px;
  height: 21px;
  flex: 0 0 21px;
  border-radius: 6px;
  background: color-mix(in srgb, var(--accent) 10%, transparent);
  color: var(--accent);
  transition: background-color 150ms var(--ease-out), color 150ms var(--ease-out);
}
.sidebar-project-icon svg { width: 13px; height: 13px; flex: none; fill: none; stroke: currentColor; stroke-width: 1.7; stroke-linecap: round; stroke-linejoin: round; }
.sidebar-project-row.selected .sidebar-project-icon {
  background: linear-gradient(145deg, color-mix(in srgb, var(--accent) 76%, #fff) 0%, var(--accent) 100%);
  color: #fff;
  box-shadow: 0 2px 6px -2px color-mix(in srgb, var(--accent) 55%, transparent);
}
.sidebar-project-name { flex: 1; min-width: 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.sidebar-project-row.selected .sidebar-project-item,
.sidebar-project-row.selected .sidebar-project-item:hover:not(:disabled) { color: var(--accent); font-weight: 600; }
.sidebar-project-quick-add {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  min-height: 24px;
  flex: 0 0 24px;
  padding: 0;
  margin: 0;
  border: 0;
  border-radius: 6px;
  background: transparent;
  box-shadow: none;
  color: var(--muted);
  opacity: 0;
  pointer-events: none;
  transform: none;
  transition: opacity 140ms ease, color 140ms ease, background-color 140ms ease;
}
.sidebar-project-quick-add svg { width: 14px; height: 14px; flex: none; fill: none; stroke: currentColor; stroke-width: 1.8; stroke-linecap: round; }
.sidebar-project-row:hover .sidebar-project-quick-add,
.sidebar-project-row:focus-within .sidebar-project-quick-add,
.sidebar-project-row:has(.sidebar-project-quick-add[aria-expanded="true"]) .sidebar-project-quick-add { opacity: 1; pointer-events: auto; }
.sidebar-project-quick-add:hover:not(:disabled),
.sidebar-project-quick-add:active:not(:disabled) { background: color-mix(in srgb, var(--accent) 16%, transparent); border: 0; box-shadow: none; color: var(--accent); transform: none; }
@media (hover: none) {
  .sidebar-project-quick-add { opacity: 1; pointer-events: auto; }
}
.sidebar-project-chats { display: flex; flex-direction: column; gap: 1px; margin: 4px 0 4px 22px; padding-left: 9px; border-left: 1px solid var(--line-strong); }
.sidebar-project-chat-link { display: flex; align-items: center; height: 28px; min-height: 28px; padding: 0 8px; border-radius: 7px; color: var(--muted); font-size: 12px; text-decoration: none; transition: background-color 140ms ease, color 140ms ease; }
.sidebar-project-chat-link span { min-width: 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.sidebar-project-chat-link:hover { background: color-mix(in srgb, var(--accent) 8%, transparent); color: var(--ink); text-decoration: none; }
.sidebar-project-chat-link.selected { background: color-mix(in srgb, var(--accent) 12%, transparent); color: var(--accent); font-weight: 550; }
.sidebar-project-chat-more { width: 100%; padding: 4px 8px; border: 0; border-radius: 6px; background: transparent; color: var(--accent); font-size: 11px; text-align: left; box-shadow: none; transform: none; }
.sidebar-project-chat-more:hover:not(:disabled),
.sidebar-project-chat-more:active:not(:disabled) { background: var(--accent-soft); border: 0; box-shadow: none; transform: none; }
.sidebar-project-hint { margin: 2px 0 0; padding: 4px 8px 2px; color: var(--muted); font-size: 11.5px; line-height: 1.5; }
.conversation-project-tag { color: var(--accent); font-weight: 500; }
.history-icon-button { display: inline-flex; align-items: center; justify-content: center; width: 28px; height: 28px; min-height: 28px; padding: 5px; margin: 0; border: 0; border-radius: 7px; background: transparent; box-shadow: none; color: var(--muted); transform: none; }
.history-icon-button:hover:not(:disabled), .history-icon-button:active:not(:disabled) { color: var(--accent); background: var(--accent-soft); border: 0; box-shadow: none; transform: none; }
.history-icon-button svg, .history-batch-actions svg { width: 18px; height: 18px; flex: none; fill: none; stroke: currentColor; stroke-width: 1.5; stroke-linecap: round; stroke-linejoin: round; }
.conversation-item { padding-left: 10px; }
.conversation-row { display: grid; grid-template-columns: 0px minmax(0, 1fr) 34px; align-items: center; transition: grid-template-columns var(--selection-duration) var(--selection-easing), background-color 150ms ease, box-shadow 150ms ease; }
.is-selecting .conversation-row { grid-template-columns: 34px minmax(0, 1fr) 0px; }
.conversation-choice-slot, .conversation-more-slot { display: flex; align-items: center; justify-content: center; min-width: 0; overflow: hidden; transition: opacity var(--selection-duration) ease, transform var(--selection-duration) var(--selection-easing); }
.conversation-choice-slot { opacity: 0; transform: translateX(-6px); pointer-events: none; }
.is-selecting .conversation-choice-slot { opacity: 1; transform: translateX(0); pointer-events: auto; }
.conversation-more-slot { opacity: 1; transform: translateX(0); padding-right: 3px; }
.is-selecting .conversation-more-slot { opacity: 0; transform: translateX(6px); pointer-events: none; }
.conversation-choice-slot > input { display: block; appearance: none; width: 18px; height: 18px; margin: 0 0 0 6px; border: 1px solid var(--line-strong); border-radius: 50%; padding: 0; background: var(--paper); cursor: pointer; transition: border-color 160ms ease, background-color 160ms ease, box-shadow 160ms ease; }
.conversation-choice-slot > input:checked { border-color: var(--accent); background: var(--accent); box-shadow: inset 0 0 0 4px var(--paper); }
.history-bottom { position: relative; display: grid; flex: none; min-height: 54px; margin-top: 8px; padding-top: 8px; border-top: 1px solid var(--line); }
.history-bottom > * { grid-area: 1 / 1; min-width: 0; margin-top: 0; }
.history-batch-actions { display: flex; flex: none; margin-top: 0; padding-top: 4px; }
.history-batch-actions button { display: inline-flex; flex: 1; align-items: center; justify-content: center; gap: 6px; min-width: 0; min-height: 34px; padding: 6px 4px; border: 0; border-radius: 7px; background: transparent; box-shadow: none; transform: none; font-size: 12px; color: var(--muted); }
.history-batch-actions button:hover:not(:disabled), .history-batch-actions button:active:not(:disabled) { border: 0; background: var(--accent-soft); box-shadow: none; transform: none; color: var(--ink); }
.history-batch-actions button + button { border-left: 1px solid var(--line); border-radius: 0; }
.history-batch-actions .selection-delete:not(:disabled) { color: var(--danger); }
.sidebar-user-wrap { position: relative; display: flex; align-items: center; min-width: 0; }
.sidebar-user-card {
  display: flex;
  align-items: center;
  gap: 11px;
  width: 100%;
  min-height: 46px;
  padding: 6px 8px;
  border: 1px solid transparent;
  border-radius: 11px;
  background: transparent;
  box-shadow: none;
  transform: none;
  color: var(--ink);
  text-align: left;
  cursor: pointer;
  transition: background-color 150ms ease, border-color 150ms ease;
}
.sidebar-user-card:hover:not(:disabled),
.sidebar-user-card:active:not(:disabled),
.sidebar-user-card[aria-expanded="true"] {
  background: var(--accent-soft);
  border-color: color-mix(in srgb, var(--accent) 26%, var(--line));
  box-shadow: none;
  transform: none;
}
.sidebar-user-avatar {
  display: grid;
  place-items: center;
  width: 32px;
  height: 32px;
  flex: 0 0 32px;
  border-radius: 999px;
  overflow: hidden;
  background: linear-gradient(135deg, var(--accent), var(--accent-hover));
  color: #fff;
  font-size: 12px;
  font-weight: 600;
  letter-spacing: 0.02em;
  box-shadow: 0 2px 6px rgb(0 0 0 / 18%), inset 0 1px rgb(255 255 255 / 20%);
}
.sidebar-user-avatar.is-sm {
  width: 28px;
  height: 28px;
  flex: 0 0 28px;
  font-size: 11px;
}
.sidebar-user-avatar-img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}
.sidebar-user-info {
  display: flex;
  flex-direction: column;
  min-width: 0;
  flex: 1;
  line-height: 1.25;
}
.sidebar-user-name {
  font-size: 13px;
  font-weight: 600;
  color: var(--ink);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.sidebar-user-role {
  margin-top: 2px;
  font-size: 11px;
  color: var(--ink-tertiary, var(--muted));
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.sidebar-user-menu {
  position: absolute;
  left: 0;
  right: 0;
  bottom: calc(100% + 10px);
  z-index: 40;
  padding: 6px;
  border: 1px solid var(--line-strong);
  border-radius: calc(var(--radius-control, 8px) + 6px);
  background: var(--specular-spot, none), var(--surface-glass-float, var(--surface-float));
  -webkit-backdrop-filter: blur(28px) saturate(190%);
  backdrop-filter: blur(28px) saturate(190%);
  box-shadow: var(--shadow-float, var(--shadow-card-hover));
  color: var(--ink);
  animation: menu-pop-in 160ms var(--ease-out);
  transform-origin: bottom left;
}
.sidebar-user-menu::before {
  content: '';
  position: absolute;
  top: 0;
  left: 10%;
  right: 10%;
  height: 1.5px;
  background: var(--specular-sheen);
  pointer-events: none;
}
.sidebar-user-menu-header {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 10px;
  min-width: 0;
}
.sidebar-user-menu-meta {
  display: grid;
  min-width: 0;
  line-height: 1.3;
}
.sidebar-user-menu-meta b {
  font-size: 12.5px;
  font-weight: 600;
  color: var(--ink);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.sidebar-user-menu-meta small {
  font-size: 11px;
  color: var(--ink-tertiary, var(--muted));
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.sidebar-user-menu-divider {
  height: 1px;
  margin: 4px 6px;
  background: var(--line);
}
.sidebar-user-menu a,
.sidebar-user-menu button {
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
  min-height: 36px;
  padding: 7px 10px;
  border: 0;
  border-radius: var(--radius-control, 9px);
  background: transparent;
  box-shadow: none;
  transform: none;
  color: var(--ink);
  font-size: 12.5px;
  font-weight: 450;
  text-align: left;
  text-decoration: none;
  transition: background-color 140ms ease, color 140ms ease;
}
.sidebar-user-menu a:hover,
.sidebar-user-menu button:hover:not(:disabled),
.sidebar-user-menu button:active:not(:disabled) {
  background: var(--accent-soft);
  color: var(--accent);
  border: 0;
  box-shadow: none;
  transform: none;
}
.sidebar-user-menu svg {
  width: 16px;
  height: 16px;
  flex: none;
  fill: none;
  stroke: currentColor;
  stroke-width: 1.75;
  stroke-linecap: round;
  stroke-linejoin: round;
  color: var(--muted);
  transition: color 140ms ease;
}
.sidebar-user-menu a:hover svg,
.sidebar-user-menu button:hover:not(:disabled) svg {
  color: currentColor;
}
.sidebar-user-menu button.danger {
  color: var(--danger);
}
.sidebar-user-menu button.danger svg {
  color: var(--danger);
}
.sidebar-user-menu button.danger:hover:not(:disabled) {
  background: var(--danger-soft);
  color: var(--danger);
}
.history-mode-enter-active, .history-mode-leave-active, .history-control-enter-active, .history-control-leave-active { transition: opacity var(--selection-duration) ease, transform var(--selection-duration) var(--selection-easing); }
.history-mode-enter-from { opacity: 0; transform: translateY(6px); }
.history-mode-leave-to { opacity: 0; transform: translateY(-6px); }
.history-control-enter-from, .history-control-leave-to { opacity: 0; transform: scale(.9); }
.history-mode-leave-active, .history-control-leave-active { pointer-events: none; }
/* Overlay rail keeps the content width constant; a short thumb maps the full range. */
.history-scrollbar { position: absolute; top: 0; bottom: 0; right: 0; width: 8px; opacity: 0; pointer-events: none; transition: opacity 160ms ease; touch-action: none; user-select: none; }
.history-scroll-thumb { position: absolute; top: 0; right: 1px; width: 4px; border-radius: 999px; background: var(--scrollbar-thumb); }
.history-scroll-shell:hover .history-scrollbar,
.history-scroll-shell:focus-within .history-scrollbar,
.is-scrolling .history-scrollbar,
.is-dragging-scrollbar .history-scrollbar { opacity: 1; pointer-events: auto; }
.history-scrollbar:hover .history-scroll-thumb { background: var(--scrollbar-hover); }
.is-dragging-scrollbar .history-scroll-thumb { background: var(--scrollbar-active); }
@media (prefers-reduced-motion: reduce) {
  .sidebar-disclosure, .sidebar-chevron, .sidebar-project-quick-add,
  .history-scrollbar, .conversation-row, .conversation-choice-slot, .conversation-more-slot,
  .conversation-choice-slot > input, .history-mode-enter-active, .history-mode-leave-active,
  .history-control-enter-active, .history-control-leave-active { transition: none; }
}
@media (forced-colors: active) {
  .history-scroll { scrollbar-width: auto; }
  .history-scroll::-webkit-scrollbar { display: block; width: 8px; }
  .history-scrollbar { display: none; }
  .conversation-choice-slot > input { appearance: auto; }
}
</style>
