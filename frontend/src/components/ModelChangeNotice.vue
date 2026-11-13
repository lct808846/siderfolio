<script setup lang="ts">
defineProps<{ from: string; to: string }>()
</script>

<template>
  <div class="model-change-notice" role="note">
    <span class="model-change-copy">
      <svg viewBox="0 0 24 24" aria-hidden="true"><path d="m12 3 8 4.5v9L12 21l-8-4.5v-9zm0 9 8-4.5M12 12 4 7.5M12 12v9" /></svg>
      <span>模型已从 <b>{{ from }}</b> 更改为 <b>{{ to }}</b></span>
    </span>
  </div>
</template>

<style scoped>
.model-change-notice { display: flex; align-items: center; gap: 14px; width: 100%; max-width: 1120px; margin: 12px auto 22px; padding-block: 10px; color: var(--muted); font: 400 12px/1.7 var(--font-ui); }
.model-change-notice::before, .model-change-notice::after { content: ''; flex: 1 1 0; min-width: 12px; height: 1px; background: var(--line); }
.model-change-copy { display: inline-flex; align-items: center; justify-content: center; gap: 8px; min-width: 0; max-width: 85%; text-align: center; overflow-wrap: anywhere; }
.model-change-copy svg { width: 16px; height: 16px; flex: none; fill: none; stroke: currentColor; stroke-width: 1.4; stroke-linejoin: round; }
.model-change-copy b { font-weight: 500; }
@media (max-width: 680px) { .model-change-notice { gap: 8px; font-size: 11px; } .model-change-copy { max-width: 90%; } }
</style>
