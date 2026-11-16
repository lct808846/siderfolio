<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api } from '../api'
import { conversationExport, orderedConversations, readPinnedConversations, saveConversationExport, savePinnedConversations } from '../conversation-tools'
import { identityUser, logout } from '../identity-state'
import { useWorkbench } from '../stores/workbench'
import type { Conversation } from '../types'

const emit = defineEmits<{ create: []; removed: [ids: string[]] }>()
const store = useWorkbench(), router = useRouter(), route = useRoute()
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
const selectionToggle = ref<HTMLButtonElement | null>(null), selectionExit = ref<HTMLButtonElement | null>(null)
const busy = ref(false), message = ref(''), error = ref('')
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
const dialog = ref<HTMLDialogElement | null>(null), action = ref<'' | 'rename' | 'delete' | 'export'>('')
const targets = ref<Conversation[]>([]), title = ref('')
let menuTrigger: HTMLButtonElement | null = null
const conversations = computed(() => orderedConversations(store.conversations, pins.value))
const menuTarget = computed(() => store.conversations.find(item => item.id === menuId.value))
const locked = computed(() => busy.value || store.creating)

function closeMenu(focus = true) {
  const trigger = menuTrigger
  menuId.value = ''
  if (focus && trigger?.isConnected) trigger.focus()
}
async function openMenu(event: MouseEvent, id: string) {
  if (menuId.value === id) { closeMenu(); return }
  menuTrigger = event.currentTarget as HTMLButtonElement
  menuId.value = id
  const rect = menuTrigger.getBoundingClientRect()
  menuPosition.value = { left: `${Math.max(8, Math.min(rect.right - 210, window.innerWidth - 218))}px`, top: `${Math.max(8, Math.min(rect.bottom + 6, window.innerHeight - 300))}px` }
  await nextTick()
  menu.value?.querySelector<HTMLElement>('button:not(:disabled), a')?.focus()
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
function outside(event: PointerEvent) {
  if (event.target instanceof Node && !menu.value?.contains(event.target) && !menuTrigger?.contains(event.target)) closeMenu(false)
  if (event.target instanceof Node && !userMenuRef.value?.contains(event.target) && !userMenuTrigger.value?.contains(event.target)) userMenuOpen.value = false
}
function dismissMenu(event: Event) {
  if (event.target instanceof Node && menu.value?.contains(event.target)) return
  closeMenu(false)
}
function menuBlur(event: FocusEvent) {
  if (!(event.relatedTarget instanceof Node) || !menu.value?.contains(event.relatedTarget)) closeMenu(false)
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
async function openDialog(kind: 'rename' | 'delete' | 'export', values?: Conversation[]) {
  if (locked.value) return
  const choices = values || (menuTarget.value ? [menuTarget.value] : [])
  if (!choices.length) return
  targets.value = choices.map(value => ({ ...value }))
  title.value = choices[0]?.title || ''
  action.value = kind; error.value = ''; message.value = ''
  closeMenu()
  await nextTick()
  dialog.value?.showModal()
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
      message.value = `已删除 ${removed.length} 个会话。`
      error.value = failures.join('\n')
      emit('removed', removed)
    }
    dialog.value?.close()
    try { await store.refreshList() } catch (e) { error.value = `${error.value ? error.value + '\n' : ''}${e instanceof Error ? e.message : '列表刷新失败，请核对状态'}` }
  } catch (e) { error.value = e instanceof Error ? e.message : '操作未确认，请刷新核对。' }
  finally { busy.value = false }
}
watch(() => route.fullPath, () => { closeMenu(false); userMenuOpen.value = false; if (!busy.value) dialog.value?.close() })
watch(() => store.conversations, items => {
  selected.value = selected.value.filter(id => items.some(item => item.id === id))
  const remainingPins = pins.value.filter(id => items.some(item => item.id === id))
  if (remainingPins.length !== pins.value.length) persistPins(remainingPins)
  if (menuId.value && !items.some(item => item.id === menuId.value)) closeMenu(false)
})
onMounted(() => {
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
          <div class="history-list-heading">
            <p class="history-label">本地会话</p>
            <Transition name="history-control"><button v-if="store.conversations.length && !selecting" ref="selectionToggle" class="history-icon-button history-manage" :inert="selecting" :disabled="locked" aria-label="多选管理会话" data-tooltip="多选管理会话" @click="enterSelection()"><svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="5" cy="6" r="1.5" /><circle cx="5" cy="12" r="1.5" /><circle cx="5" cy="18" r="1.5" /><path d="M11 6h9M11 12h9M11 18h9" /></svg></button></Transition>
          </div>
          <p v-if="message" class="sidebar-feedback" role="status">{{ message }}</p>
          <p v-if="error && !dialog?.open" class="sidebar-feedback danger" role="alert">{{ error }}</p>
          <nav class="conversation-list" aria-label="本地会话">
            <div v-for="conversation in conversations" :key="conversation.id" class="conversation-row" :class="{selected:selecting ? selected.includes(conversation.id) : store.current?.id===conversation.id}">
              <div class="conversation-choice-slot" :inert="!selecting" :aria-hidden="!selecting"><input v-model="selected" type="checkbox" :value="conversation.id" :aria-label="`选择会话 ${conversation.title}`" :disabled="locked || !selecting"></div>
              <button class="conversation-item" :class="{selected:!selecting && store.current?.id===conversation.id}" :aria-current="!selecting && store.current?.id===conversation.id ? 'page' : undefined" :aria-pressed="selecting ? selected.includes(conversation.id) : undefined" :disabled="locked" data-tooltip-truncated @click="chooseConversation(conversation.id)">
                <span><b data-tooltip-source>{{ conversation.title }}</b><small><span v-if="pins.includes(conversation.id)" class="conversation-pinned">置顶 · </span>{{ conversation.revision }} 轮 · {{ new Date(conversation.updated_at).toLocaleDateString('zh-CN') }}</small></span>
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
      </div>
      <div v-if="listScrollable" class="history-scrollbar" aria-hidden="true" @pointerdown="beginScrollDrag" @pointermove="moveScrollDrag" @pointerup="endScrollDrag" @pointercancel="endScrollDrag" @lostpointercapture="endScrollDrag"><span class="history-scroll-thumb" :style="{ height: `${thumbHeight}px`, transform: `translateY(${thumbTop}px)` }"></span></div>
    </div>
    <div class="history-bottom">
      <Transition name="history-mode">
        <div v-if="selecting" key="actions" class="history-batch-actions" :inert="!selecting" aria-label="批量管理会话">
          <button :disabled="locked || !selected.length" @click="pinSelected"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="m14 3 7 7-4 1-4 5-2-2-6 6m6-6-3-3 5-4z" /></svg>{{ selectionPinned ? '取消置顶' : '置顶' }}</button>
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
        <button role="menuitem" @click="openDialog('export')"><span aria-hidden="true">↓</span>导出会话 JSON</button>
        <RouterLink role="menuitem" to="/projects" @click="closeMenu(false)"><span aria-hidden="true">▤</span>打开项目归档</RouterLink>
        <button role="menuitem" @click="startSelection"><span aria-hidden="true">☷</span>多选整理</button>
        <button role="menuitem" class="danger" :disabled="store.running && store.current?.id===menuId" @click="openDialog('delete')"><span aria-hidden="true">×</span>删除会话</button>
      </div>
    </Teleport>
    <dialog ref="dialog" class="project-dialog conversation-dialog" :aria-label="action==='rename' ? '重命名会话' : action==='export' ? '导出会话' : '删除会话'" @cancel="busy && $event.preventDefault()" @close="action=''">
      <form @submit.prevent="execute">
        <h2>{{ action==='rename' ? '重命名会话' : action==='export' ? '导出这份会话？' : `删除 ${targets.length} 个会话？` }}</h2>
        <template v-if="action==='rename'"><label for="sidebar-conversation-title">会话名称</label><input id="sidebar-conversation-title" v-model="title" maxlength="80" required autofocus :disabled="busy"></template>
        <template v-else-if="action==='export'"><p>{{ targets[0]?.title }}</p><p>将下载包含问题、回答、来源和保存结果的 JSON，可能含私人内容。请核对后自行分享。</p><p class="small muted">此文件是会话副本；完整项目备份请使用项目归档。运行中的会话需等待完成。</p></template>
        <template v-else><ul><li v-for="target in targets" :key="target.id">{{ target.title }} · {{ target.revision }} 轮</li></ul><p>将删除所选会话及全部轮次，无法在页面撤销。已经保存的项目快照和下载文件保留。</p></template>
        <p v-if="error" class="notice danger" role="alert">{{ error }}</p>
        <div class="project-actions"><button type="button" :disabled="busy" @click="closeDialog">取消</button><button type="submit" :class="action==='delete' ? 'button-danger' : 'button-primary'" :disabled="busy || (action==='rename' && !title.trim())">{{ busy ? '正在处理…' : action==='rename' ? '保存名称' : action==='export' ? '确认下载 JSON' : '确认删除' }}</button></div>
      </form>
    </dialog>
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
.history-list-heading .history-label { margin: 0; font-size: 11.5px; font-weight: 550; letter-spacing: 0.03em; color: #677d73; line-height: 1; }
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
.history-bottom { position: relative; display: grid; flex: none; min-height: 54px; margin-top: 8px; padding-top: 8px; border-top: 1px solid rgb(202 217 208 / 65%); }
.history-bottom > * { grid-area: 1 / 1; min-width: 0; margin-top: 0; }
.history-batch-actions { display: flex; flex: none; margin-top: 0; padding-top: 4px; }
.history-batch-actions button { display: inline-flex; flex: 1; align-items: center; justify-content: center; gap: 6px; min-width: 0; min-height: 34px; padding: 6px 4px; border: 0; border-radius: 7px; background: transparent; box-shadow: none; transform: none; font-size: 12px; color: var(--muted); }
.history-batch-actions button:hover:not(:disabled), .history-batch-actions button:active:not(:disabled) { border: 0; background: rgb(255 255 255 / 72%); box-shadow: none; transform: none; color: var(--ink); }
.history-batch-actions button + button { border-left: 1px solid var(--line); border-radius: 0; }
.history-batch-actions .selection-delete:not(:disabled) { color: #983e38; }
.sidebar-user-wrap { position: relative; display: flex; align-items: center; min-width: 0; }
.sidebar-user-card {
  display: flex;
  align-items: center;
  gap: 11px;
  width: 100%;
  min-height: 46px;
  padding: 6px 8px;
  border: 0;
  border-radius: 11px;
  background: transparent;
  box-shadow: none;
  transform: none;
  color: var(--ink);
  text-align: left;
  cursor: pointer;
  transition: background-color 150ms ease;
}
.sidebar-user-card:hover:not(:disabled),
.sidebar-user-card:active:not(:disabled),
.sidebar-user-card[aria-expanded="true"] {
  background: rgb(212 229 218 / 62%);
  border: 0;
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
  background: linear-gradient(135deg, #2d6a56, #1d4a3b);
  color: #fff;
  font-size: 12px;
  font-weight: 600;
  letter-spacing: 0.02em;
  box-shadow: 0 2px 6px rgb(24 58 45 / 16%), inset 0 1px rgb(255 255 255 / 20%);
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
  color: var(--muted);
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
  border: 1px solid #cfe0d4;
  border-radius: 14px;
  background: rgb(252 254 251 / 97%);
  backdrop-filter: blur(18px);
  box-shadow: 0 14px 36px rgb(20 48 37 / 14%), 0 2px 6px rgb(20 48 37 / 5%);
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
  color: var(--muted);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.sidebar-user-menu-divider {
  height: 1px;
  margin: 4px 6px;
  background: #e3ece6;
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
  border-radius: 9px;
  background: transparent;
  box-shadow: none;
  transform: none;
  color: var(--ink);
  font-size: 12.5px;
  font-weight: 450;
  text-align: left;
  text-decoration: none;
  transition: background-color 140ms ease;
}
.sidebar-user-menu a:hover,
.sidebar-user-menu button:hover:not(:disabled),
.sidebar-user-menu button:active:not(:disabled) {
  background: #eaf3ec;
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
  color: #486b5b;
}
.sidebar-user-menu button.danger {
  color: #a13a34;
}
.sidebar-user-menu button.danger svg {
  color: #a13a34;
}
.sidebar-user-menu button.danger:hover {
  background: #fdf0ee;
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
