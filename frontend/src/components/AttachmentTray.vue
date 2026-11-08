<script setup lang="ts">
import AttachmentPreview from './AttachmentPreview.vue'
import { useAttachments } from '../stores/attachments'

defineProps<{ scope: string; disabled?: boolean }>()
const store = useAttachments()
function size(bytes: number) { return bytes >= 1024 ** 2 ? `${(bytes / 1024 ** 2).toFixed(1)} MiB` : `${Math.max(1, Math.round(bytes / 1024))} KiB` }
</script>

<template>
  <div v-if="store.rows(scope).length || store.notices.get(scope)" class="attachment-tray">
    <div class="attachment-drafts">
      <div v-for="row in store.rows(scope)" :key="row.id" class="attachment-draft" :data-state="row.state">
        <AttachmentPreview v-if="row.state === 'ready' && row.data" :attachment="row.data" />
        <div v-else class="attachment-file attachment-pending"><span class="attachment-state-icon" aria-hidden="true">{{ row.state === 'reading' ? '…' : '!' }}</span><span><b>{{ row.file.name }}</b><small>{{ row.state === 'reading' ? '正在解析…' : '解析失败' }} · {{ size(row.file.size) }}</small></span></div>
        <button v-if="row.state === 'error'" type="button" class="attachment-retry" :disabled="disabled" @click="store.read(scope, row.id)">重试</button>
        <button class="attachment-remove" type="button" :disabled="disabled" :aria-label="`移除附件：${row.file.name}`" @click="store.remove(scope, row.id)">×</button>
        <p v-if="row.error" class="attachment-error">{{ row.error }}</p>
      </div>
    </div>
    <p v-if="store.notices.get(scope)" class="attachment-error" role="status">{{ store.notices.get(scope) }}</p>
  </div>
</template>
