<script lang="ts">
import { reactive } from 'vue'

interface OpenToast {
  id: number
  height: number
}

let nextToastId = 1
const openToasts = reactive<OpenToast[]>([])

function allocateToastId(): number {
  return nextToastId++
}

function registerToast(id: number, height: number) {
  const existing = openToasts.find(item => item.id === id)
  if (existing) existing.height = height
  else openToasts.push({ id, height })
}

function unregisterToast(id: number) {
  const index = openToasts.findIndex(item => item.id === id)
  if (index >= 0) openToasts.splice(index, 1)
}
</script>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, useSlots, watch } from 'vue'

const props = withDefaults(defineProps<{
  title?: string
  message: string
  code?: string
  actionLabel?: string
  busy?: boolean
  tone?: 'danger' | 'warning'
  announce?: boolean
  inline?: boolean
  persistent?: boolean
  duration?: number
}>(), {
  title: '',
  code: '',
  actionLabel: '',
  busy: false,
  tone: 'danger',
  announce: true,
  inline: false,
  persistent: false,
  duration: 5200,
})

const emit = defineEmits<{
  action: []
  dismiss: []
  'update:message': [value: string]
}>()

const slots = useSlots()
const toast = ref<HTMLElement | null>(null)
const visible = ref(false)
const dismissed = ref(false)
const hovered = ref(false)
const toastId = allocateToastId()
const fadeDuration = 220
let revision = 0
let dismissTimer: ReturnType<typeof setTimeout> | undefined
let fadeTimer: ReturnType<typeof setTimeout> | undefined
let boundDialog: HTMLDialogElement | null = null

const isPersistent = computed(() =>
  props.persistent || Boolean(props.actionLabel) || Boolean(slots.actions) || Boolean(slots.default),
)

const topOffset = computed(() => {
  let offset = 0
  for (const item of openToasts) {
    if (item.id === toastId) break
    offset += item.height + 10
  }
  return offset
})

function clearTimers() {
  clearTimeout(dismissTimer)
  clearTimeout(fadeTimer)
  dismissTimer = undefined
  fadeTimer = undefined
}

function isPopoverOpen(el: HTMLElement | null): boolean {
  if (!el) return false
  try {
    return el.matches(':popover-open')
  } catch {
    return false
  }
}

function closeTopLayer(el: HTMLElement | null) {
  if (!el || typeof el.hidePopover !== 'function') return
  try {
    if (isPopoverOpen(el)) el.hidePopover()
  } catch { /* fallback for environments without Popover API */ }
}

function openTopLayer(el: HTMLElement | null) {
  if (!el || typeof el.showPopover !== 'function') return
  try {
    if (isPopoverOpen(el)) el.hidePopover()
    el.showPopover()
  } catch { /* fallback for environments without Popover API */ }
}

function detachDialogListener() {
  if (boundDialog) {
    boundDialog.removeEventListener('close', handleAncestorDialogClose)
    boundDialog = null
  }
}

function handleAncestorDialogClose() {
  revision++
  clearTimers()
  visible.value = false
  closeTopLayer(toast.value)
  unregisterToast(toastId)
  detachDialogListener()
}

function scheduleAutoDismiss(current: number) {
  clearTimeout(dismissTimer)
  dismissTimer = undefined
  if (props.inline || isPersistent.value || props.duration <= 0 || hovered.value) return
  dismissTimer = setTimeout(() => {
    if (current !== revision) return
    dismissPopup()
  }, Math.max(800, props.duration - fadeDuration))
}

function dismissPopup() {
  const current = ++revision
  clearTimers()
  visible.value = false
  fadeTimer = setTimeout(() => {
    if (current !== revision) return
    closeTopLayer(toast.value)
    unregisterToast(toastId)
    dismissed.value = true
    emit('dismiss')
    emit('update:message', '')
  }, fadeDuration)
}

function onPointerEnter() {
  hovered.value = true
  clearTimeout(dismissTimer)
  dismissTimer = undefined
}

function onPointerLeave() {
  hovered.value = false
  if (visible.value && !dismissed.value) scheduleAutoDismiss(revision)
}

async function syncPopup() {
  if (props.inline) {
    clearTimers()
    closeTopLayer(toast.value)
    unregisterToast(toastId)
    detachDialogListener()
    return
  }
  const current = ++revision
  clearTimers()
  visible.value = false
  dismissed.value = false
  if (!props.message) {
    closeTopLayer(toast.value)
    unregisterToast(toastId)
    detachDialogListener()
    return
  }
  await nextTick()
  if (current !== revision || !toast.value) return
  const ancestorDialog = toast.value.closest('dialog')
  if (ancestorDialog && !ancestorDialog.open) {
    closeTopLayer(toast.value)
    unregisterToast(toastId)
    return
  }
  detachDialogListener()
  if (ancestorDialog) {
    boundDialog = ancestorDialog
    boundDialog.addEventListener('close', handleAncestorDialogClose)
  }
  openTopLayer(toast.value)
  const measuredHeight = toast.value.offsetHeight || 60
  registerToast(toastId, measuredHeight)
  // Start from the hidden frame so the top-layer popup fades and slides in cleanly.
  toast.value.getBoundingClientRect()
  visible.value = true
  scheduleAutoDismiss(current)
}

watch(
  () => [props.message, props.title, props.tone, props.inline, props.persistent, props.code] as const,
  () => { void syncPopup() },
)

onMounted(() => {
  if (!props.inline && props.message) void syncPopup()
})

onBeforeUnmount(() => {
  revision++
  clearTimers()
  closeTopLayer(toast.value)
  unregisterToast(toastId)
  detachDialogListener()
})
</script>

<template>
  <div
    v-if="inline"
    class="status-notice"
    :data-tone="tone"
    :role="announce ? 'alert' : 'note'"
  >
    <span class="status-notice-icon" aria-hidden="true">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6">
        <circle cx="12" cy="12" r="9" />
        <path stroke-linecap="round" d="M12 7v6m0 4h.01" />
      </svg>
    </span>
    <div class="status-notice-copy">
      <p v-if="title" class="status-notice-title">{{ title }}</p>
      <p class="status-notice-message">{{ message }}</p>
      <code v-if="code" class="status-notice-code">{{ code }}</code>
      <div v-if="$slots.actions" class="status-notice-actions"><slot name="actions" /></div>
      <div v-if="$slots.default" class="status-notice-extra"><slot /></div>
    </div>
    <button
      v-if="actionLabel"
      type="button"
      class="status-notice-action"
      :disabled="busy"
      @click="$emit('action')"
    >
      <svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.6">
        <path stroke-linecap="round" stroke-linejoin="round" d="M20 7v5h-5M4 17v-5h5M6 7a7 7 0 0 1 12-1l2 3M4 15l2 3a7 7 0 0 0 12-1" />
      </svg>
      {{ busy ? '正在重试…' : actionLabel }}
    </button>
  </div>

  <div
    v-else-if="message && !dismissed"
    ref="toast"
    class="status-notice-toast"
    :class="{ 'is-visible': visible }"
    :style="{ top: `${20 + topOffset}px` }"
    :data-tone="tone"
    popover="manual"
    :role="announce ? 'alert' : 'note'"
    :aria-live="announce ? 'assertive' : 'polite'"
    aria-atomic="true"
    @pointerenter="onPointerEnter"
    @pointerleave="onPointerLeave"
    @focusin="onPointerEnter"
    @focusout="onPointerLeave"
  >
    <span class="status-notice-icon" aria-hidden="true">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75">
        <circle cx="12" cy="12" r="9" />
        <path stroke-linecap="round" d="M12 7.5v5.5m0 3.5h.01" />
      </svg>
    </span>
    <div class="status-notice-copy">
      <p v-if="title" class="status-notice-title">{{ title }}</p>
      <p class="status-notice-message">{{ message }}</p>
      <code v-if="code" class="status-notice-code">{{ code }}</code>
      <div v-if="$slots.actions" class="status-notice-actions"><slot name="actions" /></div>
      <div v-if="$slots.default" class="status-notice-extra"><slot /></div>
    </div>
    <button
      v-if="actionLabel"
      type="button"
      class="status-notice-action"
      :disabled="busy"
      @click="$emit('action')"
    >
      {{ busy ? '正在处理…' : actionLabel }}
    </button>
    <button
      type="button"
      class="status-notice-close"
      aria-label="关闭提示"
      @click="dismissPopup"
    >
      ×
    </button>
  </div>
</template>
