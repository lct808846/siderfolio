<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, useId, watch } from 'vue'
import { useRoute } from 'vue-router'
import { useModels } from '../stores/models'

const props = defineProps<{ modelValue: string; disabled?: boolean }>()
const emit = defineEmits<{ 'update:modelValue': [value: string] }>()
const models = useModels()
const route = useRoute(), listId = `model-picker-${useId()}`
const trigger = ref<HTMLButtonElement | null>(null), popup = ref<HTMLElement | null>(null)
const menuRow = ref<HTMLButtonElement | null>(null), choices = ref<HTMLElement | null>(null)
const choicesOpen = ref(false), query = ref(''), searchInput = ref<HTMLInputElement | null>(null)
const open = ref(false), active = ref(0), left = ref(12), top = ref(12), maxHeight = ref(420), placement = ref('above')
const locked = computed(() => props.disabled || models.loading || !models.configured || !models.options.length)
const currentLabel = computed(() => models.loading && !models.options.length ? '读取模型…' : props.modelValue || '选择模型')
const groups = computed(() => {
  const result = new Map<string, typeof models.options>()
  const term = query.value.trim().toLowerCase()
  for (const model of models.options) {
    if (term && !`${model.id} ${model.label}`.toLowerCase().includes(term)) continue
    const name = model.id.toLowerCase().includes('qwen') ? 'Qwen' : model.id.toLowerCase().includes('deepseek') ? 'DeepSeek' : '其他模型'
    result.set(name, [...(result.get(name) || []), model])
  }
  return [...result].map(([name, items]) => ({ name, items }))
})
const filtered = computed(() => groups.value.flatMap(group => group.items))
let revision = 0, search = '', searchedAt = 0, movingFocus = false
async function position() {
  if (!trigger.value || !popup.value) return
  const rect = trigger.value.getBoundingClientRect(), width = popup.value.offsetWidth
  left.value = Math.max(12, Math.min(rect.right - width, window.innerWidth - width - 12))
  const above = rect.top - 22, below = window.innerHeight - rect.bottom - 22
  placement.value = above >= popup.value.scrollHeight || above >= below ? 'above' : 'below'
  maxHeight.value = Math.max(48, Math.min(420, placement.value === 'above' ? above : below))
  await nextTick()
  if (!popup.value || !open.value) return
  const height = popup.value.offsetHeight
  top.value = Math.max(12, Math.min(placement.value === 'above' ? rect.top - height - 10 : rect.bottom + 10, window.innerHeight - height - 12))
}
function focusOption(index: number) {
  const options = choices.value?.querySelectorAll<HTMLButtonElement>('[role="option"]')
  const option = options?.[index]
  if (!option || !choices.value) return
  active.value = index
  option.focus({ preventScroll: true })
  const container = choices.value.getBoundingClientRect(), rect = option.getBoundingClientRect()
  if (rect.top < container.top) choices.value.scrollTop -= container.top - rect.top + 8
  else if (rect.bottom > container.bottom) choices.value.scrollTop += rect.bottom - container.bottom + 8
}
async function showChoices(focus = false) {
  if (!open.value || locked.value) return
  const token = revision
  movingFocus = true
  query.value = ''
  choicesOpen.value = true
  await nextTick()
  await position()
  if (token === revision && open.value && choicesOpen.value) {
    if (focus) focusOption(active.value)
    else searchInput.value?.focus({ preventScroll: true })
  }
  if (token === revision) movingFocus = false
}
async function hideChoices() {
  const token = revision
  movingFocus = true
  choicesOpen.value = false
  await nextTick()
  if (open.value) { await position(); menuRow.value?.focus({ preventScroll: true }) }
  if (token === revision) movingFocus = false
}
async function show(index?: number, direct = false) {
  if (locked.value || open.value) return
  const token = ++revision
  query.value = ''
  active.value = index ?? Math.max(0, filtered.value.findIndex(model => model.id === props.modelValue))
  search = ''; movingFocus = false; choicesOpen.value = false; open.value = true
  await nextTick()
  if (token !== revision || !open.value || !popup.value) return
  if (typeof popup.value.showPopover === 'function' && !popup.value.matches(':popover-open')) popup.value.showPopover()
  await position()
  if (token === revision && open.value) {
    if (direct) await showChoices(true)
    else menuRow.value?.focus({ preventScroll: true })
  }
}
async function close(restoreFocus = false) {
  if (!open.value) return
  const token = ++revision
  open.value = false
  // The leaving node stays in the top layer until Vue removes it after the transition.
  if (restoreFocus) { await nextTick(); if (token === revision && !locked.value) trigger.value?.focus({ preventScroll: true }) }
}
function choose(id: string) { if (locked.value || !open.value) return; void close(true); emit('update:modelValue', id) }
function triggerKey(event: KeyboardEvent) {
  if (!['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) return
  event.preventDefault()
  void show(event.key === 'Home' ? 0 : event.key === 'End' ? models.options.length - 1 : undefined, true)
}
function menuKey(event: KeyboardEvent) {
  if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); void close(true) }
  else if (['ArrowRight', 'ArrowDown', 'ArrowUp'].includes(event.key)) { event.preventDefault(); void showChoices(true) }
  else if (event.key === 'Tab') { trigger.value?.focus({ preventScroll: true }); void close(false) }
}
function listKey(event: KeyboardEvent) {
  const count = filtered.value.length
  if (!count) return
  if (event.key === 'Escape' || event.key === 'ArrowLeft') { event.preventDefault(); event.stopPropagation(); void hideChoices(); return }
  if (event.key === 'Tab') { trigger.value?.focus({ preventScroll: true }); void close(false); return }
  if (['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) {
    event.preventDefault()
    focusOption(event.key === 'Home' ? 0 : event.key === 'End' ? count - 1 : (active.value + (event.key === 'ArrowDown' ? 1 : -1) + count) % count)
  } else if (event.key === 'Enter' || event.key === ' ') {
    event.preventDefault()
    const item = filtered.value[active.value]
    if (item) choose(item.id)
  } else if (event.key.length === 1 && !event.ctrlKey && !event.metaKey && !event.altKey) {
    event.preventDefault()
    search = Date.now() - searchedAt > 650 ? event.key.toLowerCase() : search + event.key.toLowerCase()
    searchedAt = Date.now()
    const index = filtered.value.findIndex(model => models.labelFor(model.id).toLowerCase().startsWith(search) || model.id.toLowerCase().startsWith(search))
    if (index >= 0) focusOption(index)
  }
}
function searchKey(event: KeyboardEvent) {
  if (event.isComposing) return
  if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); void hideChoices() }
  else if (event.key === 'ArrowDown' || event.key === 'ArrowUp') { event.preventDefault(); focusOption(event.key === 'ArrowDown' ? 0 : filtered.value.length - 1) }
  else if (event.key === 'Enter') { event.preventDefault(); if (filtered.value[0]) choose(filtered.value[0].id) }
  else if (event.key === 'Tab') { trigger.value?.focus({ preventScroll: true }); void close(false) }
}
function outside(event: PointerEvent) {
  if (event.target instanceof Node && !trigger.value?.contains(event.target) && !popup.value?.contains(event.target)) void close(false)
}
function scroll(event: Event) { if (!(event.target instanceof Node) || !popup.value?.contains(event.target)) void close(false) }
function blur(event: FocusEvent) { if (!movingFocus && (!(event.relatedTarget instanceof Node) || (!popup.value?.contains(event.relatedTarget) && !trigger.value?.contains(event.relatedTarget)))) void close(false) }
function resize() { if (open.value) void position() }
watch(locked, value => { if (value) void close(false) })
watch(() => props.modelValue, () => { void close(false) })
watch(() => route.fullPath, () => { void close(false) })
watch(query, async () => { if (searchInput.value === document.activeElement) active.value = 0; await nextTick(); if (open.value) await position() })
onMounted(() => {
  document.addEventListener('pointerdown', outside)
  window.addEventListener('scroll', scroll, { capture: true, passive: true })
  window.addEventListener('resize', resize)
})
onBeforeUnmount(() => {
  revision++
  document.removeEventListener('pointerdown', outside)
  window.removeEventListener('scroll', scroll, true)
  window.removeEventListener('resize', resize)
})
</script>

<template>
  <div class="model-selector">
    <button ref="trigger" class="model-selector-trigger" type="button" :disabled="locked" aria-haspopup="menu" :aria-expanded="open" :aria-controls="listId" :aria-label="`回答模型：${currentLabel}`" :data-tooltip="open ? '' : '选择回答模型，当前会话的历史上下文继续保留'" @click="open ? close(true) : show()" @keydown="triggerKey">
      <span class="model-selector-name">{{ currentLabel }}</span>
      <svg class="model-selector-chevron" viewBox="0 0 24 24" aria-hidden="true"><path d="m7 14 5-5 5 5" /></svg>
    </button>
    <Teleport to="body">
      <Transition name="model-picker">
        <div v-if="open" :id="listId" ref="popup" class="model-picker" :role="choicesOpen ? 'dialog' : 'menu'" :aria-label="choicesOpen ? '选择回答模型' : '模型设置'" popover="manual" :data-placement="placement" :style="{ left: `${left}px`, top: `${top}px`, '--model-menu-room': `${maxHeight}px` }" @focusout="blur">
          <button v-if="!choicesOpen" ref="menuRow" class="model-picker-row" type="button" role="menuitem" aria-haspopup="dialog" aria-expanded="false" :aria-controls="`${listId}-choices`" data-tooltip="" @click="showChoices()" @keydown="menuKey">
            <span>模型</span><span class="model-picker-current">{{ currentLabel }}</span><svg viewBox="0 0 24 24" aria-hidden="true"><path d="m9 6 6 6-6 6" /></svg>
          </button>
          <div v-if="choicesOpen" class="model-picker-catalog">
            <input ref="searchInput" v-model="query" class="model-picker-search" type="search" placeholder="搜索模型…" aria-label="搜索模型" autocomplete="off" spellcheck="false" @keydown="searchKey">
            <div :id="`${listId}-choices`" ref="choices" class="model-picker-list" role="listbox" aria-label="可用模型" @keydown="listKey">
              <div v-for="(group, groupIndex) in groups" :key="group.name" class="model-picker-group" role="group" :aria-labelledby="`${listId}-group-${groupIndex}`">
                <div :id="`${listId}-group-${groupIndex}`" class="model-picker-group-label">{{ group.name }}</div>
                <button v-for="model in group.items" :key="model.id" class="model-picker-option" type="button" role="option" tabindex="-1" :aria-selected="model.id === modelValue" data-tooltip="" @focus="active = filtered.findIndex(item => item.id === model.id)" @click="choose(model.id)">
                  <span class="model-picker-label">{{ model.id }}</span>
                  <svg v-if="model.id === modelValue" class="model-picker-check" viewBox="0 0 24 24" aria-hidden="true"><path d="m5 12 4 4L19 6" /></svg>
                </button>
              </div>
              <p v-if="!filtered.length" class="model-picker-empty" role="status">没有匹配的模型</p>
            </div>
          </div>
        </div>
      </Transition>
    </Teleport>
  </div>
</template>
