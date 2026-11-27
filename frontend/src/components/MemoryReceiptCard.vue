<script setup lang="ts">
import type { MemorySaveReceipt } from '../types'

defineProps<{
  receipt: MemorySaveReceipt
}>()

function statusLabel(action: MemorySaveReceipt['action']) {
  if (action === 'saved') return '已保存记忆'
  if (action === 'already_saved') return '已存在'
  if (action === 'conflict_candidate') return '待解决冲突'
  return '需补充确认'
}

function statusPillClass(action: MemorySaveReceipt['action']) {
  if (action === 'saved') return 'ui-pill-success'
  if (action === 'already_saved') return 'ui-pill-accent'
  return 'ui-pill-warning'
}
</script>

<template>
  <section class="memory-receipt-card ui-card" aria-label="记忆保存回执">
    <div class="memory-receipt-top">
      <div class="memory-receipt-meta">
        <span class="ui-pill" :class="statusPillClass(receipt.action)">{{ statusLabel(receipt.action) }}</span>
        <span class="ui-pill ui-pill-neutral">{{ receipt.scope === 'project' ? '项目记忆' : '全局个人' }}</span>
        <strong class="memory-receipt-summary">{{ receipt.summary }}</strong>
      </div>
      <RouterLink class="memory-receipt-link" to="/settings?section=memory">
        查看记忆摘要 →
      </RouterLink>
    </div>
    <p class="memory-receipt-message">{{ receipt.message }}</p>
  </section>
</template>

<style scoped>
.memory-receipt-card {
  margin-top: var(--space-3);
  padding: var(--space-3) var(--space-4);
  display: grid;
  gap: 6px;
  background: var(--surface-glass-card);
  border: 1px solid color-mix(in srgb, var(--accent) 28%, var(--line));
  border-radius: var(--radius-card);
}

.memory-receipt-top {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 8px 12px;
}

.memory-receipt-meta {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.memory-receipt-summary {
  font-size: 13.5px;
  font-weight: 600;
  color: var(--ink);
  word-break: break-word;
}

.memory-receipt-message {
  margin: 0;
  font-size: 12.5px;
  line-height: 1.5;
  color: var(--muted);
}

.memory-receipt-link {
  font-size: 12.5px;
  font-weight: 560;
  color: var(--accent);
  text-decoration: none;
  white-space: nowrap;
}

.memory-receipt-link:hover {
  text-decoration: underline;
}

.memory-receipt-link:focus-visible {
  outline: 2px solid var(--focus-ring);
  outline-offset: 2px;
  border-radius: 4px;
}
</style>
