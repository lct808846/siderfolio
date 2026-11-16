<script setup lang="ts">
defineProps<{ messages: string[] }>()
</script>

<template>
  <aside class="context-notice" role="note" aria-label="会话上下文提醒">
    <svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="9" /><path d="M12 11v6m0-10v.01" /></svg>
    <ul><li v-for="(message, index) in messages" :key="`${index}-${message}`">{{ message }}</li></ul>
  </aside>
</template>
