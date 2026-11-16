<script setup lang="ts">
withDefaults(defineProps<{
  title: string
  message: string
  actionLabel?: string
  busy?: boolean
  tone?: 'danger' | 'warning'
  announce?: boolean
}>(), { actionLabel: '', busy: false, tone: 'danger', announce: true })
defineEmits<{ action: [] }>()
</script>

<template>
  <div class="status-notice" :data-tone="tone" :role="announce ? 'alert' : 'note'">
    <span class="status-notice-icon" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6"><circle cx="12" cy="12" r="9" /><path stroke-linecap="round" d="M12 7v6m0 4h.01" /></svg></span>
    <div class="status-notice-copy">
      <p class="status-notice-title">{{ title }}</p><p class="status-notice-message">{{ message }}</p>
      <div v-if="$slots.actions" class="status-notice-actions"><slot name="actions" /></div>
      <div v-if="$slots.default" class="status-notice-extra"><slot /></div>
    </div>
    <button v-if="actionLabel" type="button" class="status-notice-action" :disabled="busy" @click="$emit('action')"><svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.6"><path stroke-linecap="round" stroke-linejoin="round" d="M20 7v5h-5M4 17v-5h5M6 7a7 7 0 0 1 12-1l2 3M4 15l2 3a7 7 0 0 0 12-1" /></svg>{{ busy ? '正在重试…' : actionLabel }}</button>
  </div>
</template>
