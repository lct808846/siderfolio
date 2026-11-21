<script setup lang="ts" generic="T extends string">
import { computed, nextTick, onBeforeUnmount, ref, useId, watch } from 'vue'

export interface SettingsSelectOption<V extends string = string> {
  value: V
  label: string
  description?: string
  swatch?: readonly [string, string]
}

const props = defineProps<{ modelValue: T; label: string; disabled?: boolean; options: readonly SettingsSelectOption<T>[] }>()
const emit = defineEmits<{ 'update:modelValue': [value: T] }>()
const id = `settings-select-${useId()}`
const trigger = ref<HTMLButtonElement | null>(null), popup = ref<HTMLElement | null>(null)
const open = ref(false), active = ref(0), left = ref(0), top = ref(0), width = ref(0), height = ref(300)
const positioned = ref(false)
const selected = computed(() => props.options.find(item => item.value === props.modelValue))
let typing = '', typedAt = 0

function close(focus = false) {
  if (!open.value) return
  popup.value?.hidePopover(); open.value = false
  document.removeEventListener('pointerdown', outside, true)
  window.removeEventListener('resize', resized)
  document.removeEventListener('scroll', scrolled, true)
  if (focus) trigger.value?.focus()
}
function outside(event: PointerEvent) {
  if (!trigger.value?.contains(event.target as Node) && !popup.value?.contains(event.target as Node)) close()
}
function resized() { close() }
function scrolled(event: Event) { if (!popup.value?.contains(event.target as Node)) close() }
async function focusOption() {
  await nextTick()
  popup.value?.querySelectorAll<HTMLButtonElement>('[role=option]')[active.value]?.focus()
}
async function show() {
  if (props.disabled || !trigger.value) return
  positioned.value = false; open.value = true; active.value = Math.max(0, props.options.findIndex(item => item.value === props.modelValue))
  await nextTick()
  const rect = trigger.value.getBoundingClientRect(), below = window.innerHeight - rect.bottom - 12
  const room = Math.max(below, rect.top - 12)
  width.value = Math.min(rect.width, window.innerWidth - 24)
  left.value = Math.max(12, Math.min(rect.left, window.innerWidth - width.value - 12))
  height.value = Math.max(80, Math.min(340, room - 6))
  popup.value?.showPopover()
  await nextTick()
  const size = popup.value?.getBoundingClientRect().height || 0
  top.value = below >= Math.min(size, 220) ? rect.bottom + 6 : Math.max(12, rect.top - size - 6)
  positioned.value = true
  document.addEventListener('pointerdown', outside, true)
  window.addEventListener('resize', resized)
  document.addEventListener('scroll', scrolled, true)
  await focusOption()
}
function choose(value: T) { emit('update:modelValue', value); close(true) }
function key(event: KeyboardEvent) {
  if (event.key === 'Tab') { close(); return }
  if (event.key === 'Escape') { if (open.value) { event.preventDefault(); event.stopPropagation(); close(true) }; return }
  if (!open.value) {
    if (['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) { event.preventDefault(); void show() }
    return
  }
  if (['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) {
    event.preventDefault()
    const last = props.options.length - 1
    active.value = event.key === 'Home' ? 0 : event.key === 'End' ? last : (active.value + (event.key === 'ArrowDown' ? 1 : -1) + props.options.length) % props.options.length
    void focusOption()
  } else if (event.key.length === 1 && event.key !== ' ' && !event.ctrlKey && !event.metaKey && !event.altKey) {
    event.preventDefault()
    const now = Date.now(); typing = now - typedAt < 700 ? typing + event.key : event.key; typedAt = now
    const found = props.options.findIndex(item => item.label.toLowerCase().startsWith(typing.toLowerCase()))
    if (found >= 0) { active.value = found; void focusOption() }
  }
}
watch(() => props.disabled, value => { if (value) close() })
onBeforeUnmount(() => close())
</script>

<template>
  <div class="settings-select">
    <button ref="trigger" type="button" class="settings-select-trigger" :disabled="disabled" :aria-label="`${label}：${selected?.label || ''}`" aria-haspopup="listbox" :aria-expanded="open" :aria-controls="id" data-tooltip="" @click="open ? close(true) : show()" @keydown="key">
      <span class="settings-select-trigger-main">
        <span v-if="selected?.swatch" class="settings-select-swatch" aria-hidden="true" :style="{ background: `linear-gradient(135deg, ${selected.swatch[0]} 50%, ${selected.swatch[1]} 50%)` }" />
        <span class="settings-select-trigger-label">{{ selected?.label }}</span>
        <small v-if="selected?.swatch && selected?.description" class="settings-select-trigger-meta">{{ selected.description }}</small>
      </span>
      <svg viewBox="0 0 24 24" aria-hidden="true" :class="{ 'is-open': open }"><path d="m7 10 5 5 5-5" /></svg>
    </button>
    <div :id="id" ref="popup" class="settings-select-popup" popover="manual" role="listbox" :aria-label="label" :style="{ left: `${left}px`, top: `${top}px`, width: `${width}px`, maxHeight: `${height}px`, visibility: positioned ? 'visible' : 'hidden' }" @keydown="key" @focusout="event => { const next = event.relatedTarget as Node | null; if (next && !popup?.contains(next) && !trigger?.contains(next)) close() }">
      <button v-for="(item, index) in options" :key="item.value" type="button" class="settings-select-option" role="option" :aria-selected="modelValue === item.value" tabindex="-1" data-tooltip="" @focus="active = index" @click="choose(item.value)">
        <span class="settings-select-option-main">
          <span v-if="item.swatch" class="settings-select-swatch" aria-hidden="true" :style="{ background: `linear-gradient(135deg, ${item.swatch[0]} 50%, ${item.swatch[1]} 50%)` }" />
          <span class="settings-select-option-copy">
            <strong>{{ item.label }}</strong>
            <small v-if="item.description">{{ item.description }}</small>
          </span>
        </span>
        <svg v-if="modelValue === item.value" viewBox="0 0 24 24" aria-hidden="true"><path d="m5 12 4 4 10-10" /></svg>
      </button>
    </div>
  </div>
</template>
