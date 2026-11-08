<script setup lang="ts">
import { ref } from 'vue'
import { attachmentAccept } from '../api/attachments'
import { useAttachments } from '../stores/attachments'

const props = defineProps<{ scope: string; disabled?: boolean }>()
const store = useAttachments(), picker = ref<HTMLInputElement | null>(null)
function change(event: Event) {
  const input = event.target as HTMLInputElement
  const files = Array.from(input.files || [])
  input.value = ''
  if (!props.disabled && files.length) void store.add(props.scope, files)
}
</script>

<template>
  <input ref="picker" type="file" class="sr-only" tabindex="-1" :accept="attachmentAccept" multiple :disabled="disabled" aria-label="选择附件" @change="change">
  <button class="attachment-add" type="button" :disabled="disabled || store.rows(scope).length >= 3" aria-label="添加附件" data-tooltip="添加附件：PDF、DOCX、TXT、Markdown、CSV、JSON；最多3个，单个10 MiB" @click="picker?.click()"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="m21.4 11-9.2 9.2a6 6 0 0 1-8.5-8.5l9.2-9.2a4 4 0 0 1 5.7 5.7l-9.2 9.2a2 2 0 0 1-2.8-2.8l8.5-8.5" /></svg></button>
</template>
