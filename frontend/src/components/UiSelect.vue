<script setup lang="ts" generic="T extends string | number">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, useId, watch } from 'vue'
import { useRoute } from 'vue-router'

export interface UiSelectOption<V extends string | number = string | number> {
  value: V
  label: string
  disabled?: boolean
}

const props = withDefaults(
  defineProps<{
    modelValue: T | null | undefined
    options: readonly UiSelectOption<T>[]
    id?: string
    ariaLabel?: string
    placeholder?: string
    prefix?: string
    disabled?: boolean
    variant?: 'default' | 'compact' | 'pill'
    fullWidth?: boolean
  }>(),
  {
    id: undefined,
    ariaLabel: undefined,
    placeholder: '请选择…',
    prefix: '',
    disabled: false,
    variant: 'default',
    fullWidth: undefined,
  },
)

const emit = defineEmits<{
  'update:modelValue': [value: T]
  change: [value: T]
}>()

const route = useRoute()
const generatedId = useId()
const listId = `ui-select-list-${generatedId}`
const trigger = ref<HTMLButtonElement | null>(null)
const popup = ref<HTMLElement | null>(null)
const open = ref(false)
const left = ref(12)
const top = ref(12)
const minWidth = ref(140)
const maxWidth = ref(360)
const placement = ref<'below' | 'above'>('below')

const isFullWidth = computed(() =>
  props.fullWidth !== undefined ? props.fullWidth : props.variant === 'default',
)

const selectedOption = computed(() =>
  props.options.find(opt => opt.value === props.modelValue) || null,
)

const displayLabel = computed(() =>
  selectedOption.value ? selectedOption.value.label : props.placeholder,
)

function position() {
  if (!trigger.value || !popup.value) return
  const rect = trigger.value.getBoundingClientRect()
  const vw = window.innerWidth
  const vh = window.innerHeight
  const desiredMin = Math.max(Math.round(rect.width), props.variant === 'pill' ? 124 : 168)
  const capWidth = Math.min(Math.max(desiredMin, 340), vw - 24)
  minWidth.value = Math.min(desiredMin, vw - 24)
  maxWidth.value = capWidth

  const actualWidth = Math.min(Math.max(popup.value.offsetWidth || desiredMin, minWidth.value), capWidth)
  left.value = Math.max(12, Math.min(rect.left, vw - actualWidth - 12))

  const below = vh - rect.bottom - 14
  const above = rect.top - 14
  const height = Math.min(popup.value.scrollHeight || 220, 300)
  placement.value = below >= height || below >= above ? 'below' : 'above'
  const rawTop = placement.value === 'below' ? rect.bottom + 6 : rect.top - height - 6
  top.value = Math.max(12, Math.min(rawTop, vh - height - 12))
}

async function openMenu() {
  if (props.disabled || open.value) return
  open.value = true
  await nextTick()
  if (!open.value || !popup.value) return
  if (typeof popup.value.showPopover === 'function' && !popup.value.matches(':popover-open')) {
    try {
      popup.value.showPopover()
    } catch { /* ignore */ }
  }
  position()
  await nextTick()
  position()
  const activeEl = popup.value.querySelector<HTMLButtonElement>('[aria-selected="true"]:not(:disabled)')
    || popup.value.querySelector<HTMLButtonElement>('button:not(:disabled)')
  activeEl?.focus({ preventScroll: true })
}

function closeMenu(restoreFocus = false) {
  if (!open.value) return
  if (popup.value && typeof popup.value.hidePopover === 'function') {
    try {
      if (popup.value.matches(':popover-open')) popup.value.hidePopover()
    } catch { /* ignore */ }
  }
  open.value = false
  if (restoreFocus) {
    void nextTick(() => trigger.value?.focus({ preventScroll: true }))
  }
}

function toggleMenu() {
  if (open.value) closeMenu(true)
  else void openMenu()
}

function choose(option: UiSelectOption<T>) {
  if (option.disabled) return
  const changed = option.value !== props.modelValue
  closeMenu(true)
  if (changed) {
    emit('update:modelValue', option.value)
    emit('change', option.value)
  }
}

function onTriggerKeydown(event: KeyboardEvent) {
  if (props.disabled) return
  if (event.key === 'ArrowDown' || event.key === 'ArrowUp' || event.key === 'Enter' || event.key === ' ') {
    if (!open.value) {
      event.preventDefault()
      void openMenu()
    }
  }
}

function onListKeydown(event: KeyboardEvent) {
  if (!open.value || !popup.value) return
  if (event.key === 'Escape') {
    event.preventDefault()
    event.stopPropagation()
    closeMenu(true)
    return
  }
  if (event.key === 'Tab') {
    closeMenu(false)
    return
  }
  const items = Array.from(
    popup.value.querySelectorAll<HTMLButtonElement>('button[role="option"]:not(:disabled)'),
  )
  if (!items.length) return
  const currentIdx = items.indexOf(document.activeElement as HTMLButtonElement)
  if (event.key === 'ArrowDown') {
    event.preventDefault()
    items[(currentIdx + 1) % items.length]?.focus({ preventScroll: true })
  } else if (event.key === 'ArrowUp') {
    event.preventDefault()
    items[(currentIdx - 1 + items.length) % items.length]?.focus({ preventScroll: true })
  } else if (event.key === 'Home') {
    event.preventDefault()
    items[0]?.focus({ preventScroll: true })
  } else if (event.key === 'End') {
    event.preventDefault()
    items[items.length - 1]?.focus({ preventScroll: true })
  }
}

function onOutsidePointer(event: PointerEvent) {
  if (!open.value) return
  if (
    event.target instanceof Node
    && !trigger.value?.contains(event.target)
    && !popup.value?.contains(event.target)
  ) {
    closeMenu(false)
  }
}

function onViewportChange() {
  if (open.value) position()
}

watch(() => route.fullPath, () => closeMenu(false))
watch(() => props.disabled, value => { if (value) closeMenu(false) })
watch(() => props.options.length, () => { if (open.value) void nextTick(position) })

onMounted(() => {
  document.addEventListener('pointerdown', onOutsidePointer, true)
  window.addEventListener('resize', onViewportChange, { passive: true })
  window.addEventListener('scroll', onViewportChange, { capture: true, passive: true })
})

onBeforeUnmount(() => {
  closeMenu(false)
  document.removeEventListener('pointerdown', onOutsidePointer, true)
  window.removeEventListener('resize', onViewportChange)
  window.removeEventListener('scroll', onViewportChange, true)
})
</script>

<template>
  <div
    class="ui-select"
    :class="[`is-${variant}`, { 'is-full': isFullWidth, 'is-open': open, 'is-disabled': disabled }]"
  >
    <button
      :id="id"
      ref="trigger"
      type="button"
      class="ui-select-trigger"
      :disabled="disabled"
      :aria-label="ariaLabel"
      :aria-expanded="open"
      :aria-controls="listId"
      aria-haspopup="listbox"
      :title="displayLabel"
      @click.stop="toggleMenu"
      @keydown="onTriggerKeydown"
    >
      <span v-if="$slots.prefix" class="ui-select-prefix-icon" aria-hidden="true">
        <slot name="prefix" />
      </span>
      <span v-if="prefix" class="ui-select-prefix-text">{{ prefix }}</span>
      <span class="ui-select-value" :class="{ 'is-placeholder': !selectedOption }">{{ displayLabel }}</span>
      <svg class="ui-select-caret" viewBox="0 0 24 24" aria-hidden="true">
        <path d="m7 10 5 5 5-5" />
      </svg>
    </button>

    <Teleport to="body">
      <div
        v-if="open"
        :id="listId"
        ref="popup"
        class="ui-select-popup"
        :data-placement="placement"
        popover="manual"
        role="listbox"
        :aria-label="ariaLabel || prefix || '选择选项'"
        :style="{
          left: `${left}px`,
          top: `${top}px`,
          minWidth: `${minWidth}px`,
          maxWidth: `${maxWidth}px`,
        }"
        @keydown="onListKeydown"
      >
        <button
          v-for="opt in options"
          :key="String(opt.value)"
          type="button"
          role="option"
          class="ui-select-option"
          :disabled="opt.disabled"
          :aria-selected="opt.value === modelValue"
          :title="opt.label"
          @click.stop="choose(opt)"
        >
          <span class="ui-select-option-label">{{ opt.label }}</span>
          <span v-if="opt.value === modelValue" class="ui-select-check" aria-hidden="true">✓</span>
        </button>
        <p v-if="!options.length" class="ui-select-empty">暂无可选项</p>
      </div>
    </Teleport>
  </div>
</template>

<style scoped>
.ui-select {
  position: relative;
  display: inline-flex;
  min-width: 0;
  max-width: 100%;
}

.ui-select.is-full {
  display: flex;
  width: 100%;
}

.ui-select-trigger {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  width: 100%;
  min-width: 0;
  min-height: 36px;
  padding: 6px 10px 6px 12px;
  border: 1px solid var(--line-strong);
  border-radius: var(--radius-control);
  background: var(--surface-card, var(--paper));
  box-shadow: none;
  color: var(--ink);
  font: 400 13px/1.45 var(--font-ui);
  text-align: left;
  cursor: pointer;
  transition: border-color 140ms ease, background-color 140ms ease, box-shadow 140ms ease;
}

.ui-select.is-compact .ui-select-trigger {
  min-height: 32px;
  padding: 4px 8px 4px 10px;
  font-size: 12.5px;
}

.ui-select.is-pill .ui-select-trigger {
  min-height: 30px;
  padding: 4px 9px 4px 10px;
  border-color: var(--line);
  border-radius: 999px;
  background: var(--surface-subtle, var(--paper));
  font-size: 12.5px;
}

.ui-select-trigger:hover:not(:disabled) {
  border-color: color-mix(in srgb, var(--accent) 44%, var(--line-strong));
  background: var(--surface-card, var(--paper));
  transform: none;
  box-shadow: none;
}

.ui-select.is-open .ui-select-trigger,
.ui-select-trigger:focus-visible {
  border-color: var(--accent);
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--accent) 18%, transparent);
  outline: none;
}

.ui-select-trigger:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

.ui-select-prefix-icon {
  display: inline-flex;
  align-items: center;
  flex: none;
  color: var(--muted);
}

.ui-select-prefix-icon :deep(svg) {
  width: 14px;
  height: 14px;
  fill: none;
  stroke: currentColor;
  stroke-width: 1.7;
}

.ui-select-prefix-text {
  flex: none;
  color: var(--muted);
  font-size: 12px;
  font-weight: 500;
}

.ui-select-value {
  flex: 1 1 auto;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ui-select-value.is-placeholder {
  color: var(--muted);
}

.ui-select-caret {
  width: 14px;
  height: 14px;
  flex: none;
  fill: none;
  stroke: currentColor;
  stroke-width: 1.8;
  stroke-linecap: round;
  stroke-linejoin: round;
  color: var(--muted);
  transition: transform 160ms ease;
}

.ui-select.is-open .ui-select-caret {
  transform: rotate(180deg);
  color: var(--accent);
}
</style>

<style>
.ui-select-popup {
  position: fixed;
  margin: 0;
  padding: 5px;
  max-height: min(300px, calc(100vh - 28px));
  overflow-y: auto;
  display: grid;
  gap: 2px;
  border: 1px solid var(--line-strong);
  border-radius: calc(var(--radius-control, 8px) + 4px);
  background: var(--specular-spot, none), var(--surface-glass-float, var(--surface-card, #fff));
  -webkit-backdrop-filter: blur(22px) saturate(160%);
  backdrop-filter: blur(22px) saturate(160%);
  box-shadow: var(--shadow-float, 0 14px 36px rgb(15 23 42 / 16%));
  color: var(--ink);
  z-index: 9999;
}

.ui-select-popup::backdrop {
  background: transparent;
  pointer-events: none;
}

.ui-select-option {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  width: 100%;
  min-height: 32px;
  padding: 6px 10px;
  border: 1px solid transparent;
  border-radius: var(--radius-control, 8px);
  background: transparent;
  box-shadow: none;
  color: var(--ink);
  font: 400 13px/1.4 var(--font-ui);
  text-align: left;
  cursor: pointer;
  transition: background-color 120ms ease, border-color 120ms ease, color 120ms ease;
}

.ui-select-option:hover:not(:disabled),
.ui-select-option:focus-visible:not(:disabled) {
  background: var(--hover-veil, var(--surface-subtle));
  border-color: var(--line);
  outline: none;
  transform: none;
  box-shadow: none;
}

.ui-select-option[aria-selected="true"] {
  background: var(--accent-soft);
  border-color: color-mix(in srgb, var(--accent) 30%, var(--line));
  color: var(--accent);
  font-weight: 550;
}

.ui-select-option:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.ui-select-option-label {
  flex: 1 1 auto;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ui-select-check {
  flex: none;
  font-size: 12.5px;
  font-weight: 700;
  color: var(--accent);
}

.ui-select-empty {
  margin: 0;
  padding: 8px 10px;
  font-size: 12.5px;
  color: var(--muted);
  text-align: center;
}
</style>
