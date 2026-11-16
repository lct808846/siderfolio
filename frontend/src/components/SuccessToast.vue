<script setup lang="ts">
import { nextTick, onBeforeUnmount, ref, watch } from 'vue'

const props = defineProps<{ message: string }>()
const emit = defineEmits<{ 'update:message': [value: string] }>()
const toast = ref<HTMLElement | null>(null), visible = ref(false)
const duration = 2880, fadeDuration = 220
let revision = 0
let dismissTimer: ReturnType<typeof setTimeout> | undefined
let fadeTimer: ReturnType<typeof setTimeout> | undefined
function clearTimers() { clearTimeout(dismissTimer); clearTimeout(fadeTimer) }
function hidePopover() {
  if (toast.value?.matches(':popover-open')) toast.value.hidePopover()
}
watch(() => props.message, async message => {
  const current = ++revision
  clearTimers()
  visible.value = false
  if (!message) { hidePopover(); return }
  await nextTick()
  if (current !== revision || !toast.value) return
  if (!toast.value.matches(':popover-open')) toast.value.showPopover()
  // Start from the hidden frame so the top-layer element can fade in.
  toast.value.getBoundingClientRect()
  visible.value = true
  dismissTimer = setTimeout(() => {
    if (current !== revision) return
    visible.value = false
    fadeTimer = setTimeout(() => {
      if (current !== revision) return
      hidePopover()
      emit('update:message', '')
    }, fadeDuration)
  }, duration - fadeDuration)
}, { immediate: true })
onBeforeUnmount(() => { revision++; clearTimers(); hidePopover() })
</script>

<template>
  <Teleport to="body">
    <div ref="toast" class="success-toast" :class="{ 'is-visible': visible }" popover="manual" role="status" aria-live="polite" aria-atomic="true">
      <svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.7"><circle cx="12" cy="12" r="9" /><path stroke-linecap="round" stroke-linejoin="round" d="m8 12 3 3 5-6" /></svg>
      <p>{{ message }}</p>
    </div>
  </Teleport>
</template>
