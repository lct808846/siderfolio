<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api } from '../api'
import { conversationExport, orderedConversations, readPinnedConversations, saveConversationExport, savePinnedConversations } from '../conversation-tools'
import { useWorkbench } from '../stores/workbench'
import type { Conversation } from '../types'

const emit = defineEmits<{ create: []; removed: [ids: string[]] }>()
const store = useWorkbench(), router = useRouter(), route = useRoute()
const pins = ref<string[]>(readPinnedConversations()), selecting = ref(false), selected = ref<string[]>([])
const busy = ref(false), message = ref(''), error = ref('')
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
function startSelection() {
  selected.value = [menuId.value]; selecting.value = true; closeMenu()
}
function stopSelection() { selecting.value = false; selected.value = [] }
function selectAll() { selected.value = conversations.value.map(value => value.id) }
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
watch(() => route.fullPath, () => { closeMenu(false); if (!busy.value) dialog.value?.close() })
watch(() => store.conversations, items => {
  selected.value = selected.value.filter(id => items.some(item => item.id === id))
  const remainingPins = pins.value.filter(id => items.some(item => item.id === id))
  if (remainingPins.length !== pins.value.length) persistPins(remainingPins)
  if (menuId.value && !items.some(item => item.id === menuId.value)) closeMenu(false)
})
onMounted(() => {
  document.addEventListener('pointerdown', outside)
  window.addEventListener('resize', dismissMenu)
  window.addEventListener('scroll', dismissMenu, true)
})
onBeforeUnmount(() => {
  document.removeEventListener('pointerdown', outside)
  window.removeEventListener('resize', dismissMenu)
  window.removeEventListener('scroll', dismissMenu, true)
  dialog.value?.close()
})
</script>

<template>
  <aside class="history-panel" aria-label="会话列表">
    <div class="history-title"><span class="eyebrow">会话</span><span class="small muted">{{ store.conversations.length }}/20</span></div>
    <button class="new-conversation" :disabled="locked || store.loading || store.running || !!store.disconnectedRequest" @click="emit('create')"><span aria-hidden="true">＋</span>{{ store.creating ? '正在准备…' : '新建会话' }}</button>
    <div class="history-list-heading"><p class="history-label">本地会话</p><button v-if="store.conversations.length && !selecting" class="history-manage" :disabled="locked" @click="selecting=true">多选</button></div>
    <div v-if="selecting" class="conversation-selection" aria-label="批量管理会话">
      <p>已选 {{ selected.length }} 个会话</p><div><button :disabled="locked" @click="selectAll">全选</button><button :disabled="locked" @click="stopSelection">取消</button><button class="selection-delete" :disabled="locked || !selected.length || store.running" @click="deleteSelected">删除所选</button></div>
    </div>
    <p v-if="message" class="sidebar-feedback" role="status">{{ message }}</p>
    <p v-if="error && !dialog?.open" class="sidebar-feedback danger" role="alert">{{ error }}</p>
    <nav class="conversation-list" aria-label="本地会话">
      <div v-for="conversation in conversations" :key="conversation.id" class="conversation-row" :class="{selected:store.current?.id===conversation.id}">
        <input v-if="selecting" v-model="selected" type="checkbox" :value="conversation.id" :aria-label="`选择会话 ${conversation.title}`" :disabled="locked">
        <button class="conversation-item" :class="{selected:store.current?.id===conversation.id}" :aria-current="store.current?.id===conversation.id ? 'page' : undefined" :disabled="locked" @click="router.push(`/conversations/${conversation.id}`)">
          <span class="conversation-symbol" aria-hidden="true">◌</span><span><b>{{ conversation.title }}</b><small><span v-if="pins.includes(conversation.id)" class="conversation-pinned">置顶 · </span>{{ conversation.revision }} 轮 · {{ new Date(conversation.updated_at).toLocaleDateString('zh-CN') }}</small></span>
        </button>
        <button v-if="!selecting" class="conversation-more" data-tooltip="" :aria-label="`会话操作：${conversation.title}`" aria-haspopup="menu" :aria-expanded="menuId===conversation.id" :disabled="locked" @click="openMenu($event, conversation.id)">⋯</button>
      </div>
    </nav>
    <p v-if="!store.conversations.length" class="small muted empty-history">会话保存在本机，<br>从一个问题开始。</p>
    <footer class="history-footer"><span>SIMBAD / ADS / Gaia</span><small>测量 · 文献 · 可追溯结果</small></footer>

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
