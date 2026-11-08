<script setup lang="ts">
import { onBeforeUnmount, ref } from 'vue'
import AttachmentPreview from './AttachmentPreview.vue'
import type { ChatAttachment } from '../types'

const props = defineProps<{ text: string; turnNumber: number; disabled?: boolean; attachments?: ChatAttachment[] }>()
defineEmits<{ edit: [text: string] }>()
const copied = ref(false), copying = ref(false), error = ref('')
let timer: ReturnType<typeof setTimeout> | undefined
async function copy() {
  if (copying.value) return
  copying.value = true; copied.value = false; error.value = ''
  if (timer) clearTimeout(timer)
  try {
    await navigator.clipboard.writeText(props.text)
    copied.value = true
    timer = setTimeout(() => { copied.value = false }, 2000)
  } catch { error.value = '复制未完成，请选中问题文字后手动复制。' }
  finally { copying.value = false }
}
onBeforeUnmount(() => { if (timer) clearTimeout(timer) })
</script>

<template>
  <div class="user-message-block">
    <div v-if="attachments?.length" class="message-attachments"><AttachmentPreview v-for="(attachment, index) in attachments" :key="`${attachment.sha256}-${index}`" :attachment="attachment" /></div>
    <div class="user-message">{{ text }}</div>
    <div class="user-message-actions">
      <span v-if="copied" class="message-action-feedback" role="status">已复制</span>
      <button type="button" :aria-label="`复制第${turnNumber}轮问题`" title="复制问题" :disabled="copying" @click="copy"><svg viewBox="0 0 24 24" aria-hidden="true"><rect x="8" y="8" width="12" height="12" rx="3" /><path d="M16 8V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h2" /></svg></button>
      <button type="button" :aria-label="`编辑第${turnNumber}轮问题`" title="编辑后作为新一轮发送" :disabled="disabled" @click="$emit('edit', text)"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="m14.5 5.5 4 4M4 20l4.5-1 12-12a2.8 2.8 0 0 0-4-4l-12 12L4 20Zm7 0h9" /></svg></button>
    </div>
    <p v-if="error" class="message-copy-error" role="alert">{{ error }}</p>
  </div>
</template>
