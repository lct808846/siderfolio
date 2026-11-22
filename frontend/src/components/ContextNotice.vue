<script setup lang="ts">
defineProps<{ messages: string[] }>()

function displayMessage(message: string) {
  return /^历史窗口未包含 \d+ 轮，请必要时明确补充条件。$/.test(message)
    ? '部分较早的对话未纳入上下文，请按需补充条件。'
    : message
}
</script>

<template>
  <aside class="context-notice" role="note" aria-label="会话上下文提醒">
    <svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="9" /><path d="M12 11v6m0-10v.01" /></svg>
    <ul><li v-for="(message, index) in messages" :key="`${index}-${message}`">{{ displayMessage(message) }}</li></ul>
  </aside>
</template>
