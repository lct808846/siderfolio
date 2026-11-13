<script setup lang="ts">
withDefaults(defineProps<{ title: string; subtitle?: string; level?: 1 | 2 }>(), { level: 1, subtitle: '' })
</script>

<template>
  <header class="workspace-pane-header">
    <div class="workspace-pane-heading">
      <component :is="level === 1 ? 'h1' : 'h2'">{{ title }}</component>
      <p v-if="subtitle" class="workspace-pane-subtitle">{{ subtitle }}</p>
    </div>
    <div v-if="$slots.actions" class="workspace-pane-actions"><slot name="actions" /></div>
  </header>
</template>
