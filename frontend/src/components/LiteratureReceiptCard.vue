<script setup lang="ts">
import type { LiteratureSaveReceipt, LiteratureSaveReceiptItem } from '../types'

defineProps<{
  receipt: LiteratureSaveReceipt
}>()

function itemStatusLabel(status: LiteratureSaveReceiptItem['status']) {
  if (status === 'added') return '已新增入库'
  if (status === 'already_saved') return '已在文献库'
  return '未入库'
}

function itemStatusClass(status: LiteratureSaveReceiptItem['status']) {
  if (status === 'added') return 'ui-pill-success'
  if (status === 'already_saved') return 'ui-pill-ads'
  return 'ui-pill-danger'
}
</script>

<template>
  <section class="lit-receipt-card ui-card" aria-label="文献入库回执">
    <header class="lit-receipt-head">
      <div class="lit-receipt-title-row">
        <span class="ui-pill ui-pill-ads">个人文献库</span>
        <strong class="lit-receipt-title">
          {{ receipt.status === 'success' ? '已核验并记录文献入库回执' : receipt.status === 'partial' ? '部分文献已写入个人文献库' : '本次未写入个人文献库' }}
        </strong>
        <span v-if="receipt.replayed" class="ui-pill ui-pill-neutral">重放回执</span>
      </div>
      <div class="ui-pill-list">
        <span v-if="receipt.added_count" class="ui-pill ui-pill-success">新增 {{ receipt.added_count }} 篇</span>
        <span v-if="receipt.already_saved_count" class="ui-pill ui-pill-ads">已在库 {{ receipt.already_saved_count }} 篇</span>
        <span v-if="receipt.rejected_count" class="ui-pill ui-pill-danger">未入库 {{ receipt.rejected_count }} 篇</span>
      </div>
    </header>

    <ul v-if="(receipt.items || []).length" class="lit-receipt-list">
      <li v-for="(item, idx) in receipt.items || []" :key="`${item.bibcode}-${idx}`" class="lit-receipt-item">
        <div class="lit-receipt-item-main">
          <div class="lit-receipt-item-meta">
            <span class="ui-pill" :class="itemStatusClass(item.status)">{{ itemStatusLabel(item.status) }}</span>
            <span class="ui-pill ui-pill-mono">{{ item.bibcode }}</span>
          </div>
          <span class="lit-receipt-paper-title">{{ item.title || '未提供标题' }}</span>
        </div>
        <div class="lit-receipt-item-actions">
          <RouterLink
            v-if="item.item_id"
            class="lit-receipt-link"
            :to="`/literature/${encodeURIComponent(item.item_id)}`"
          >
            打开详情 ↗
          </RouterLink>
          <span v-else-if="item.reason" class="lit-receipt-reason">{{ item.reason }}</span>
        </div>
      </li>
    </ul>

    <p v-for="warning in receipt.warnings" :key="warning" class="lit-receipt-warning" role="status">
      {{ warning }}
    </p>
  </section>
</template>

<style scoped>
.lit-receipt-card {
  margin-top: var(--space-3);
  padding: var(--space-3) var(--space-4);
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  background: var(--surface-glass-card);
  border: 1px solid var(--badge-ads-border);
  border-radius: var(--radius-card);
}

.lit-receipt-head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-2);
}

.lit-receipt-title-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-2);
}

.lit-receipt-title {
  font-size: 13.5px;
  font-weight: 600;
  color: var(--ink);
}

.lit-receipt-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.lit-receipt-item {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: center;
  gap: var(--space-3);
  padding: 9px 12px;
  border-radius: 10px;
  background: color-mix(in srgb, var(--surface-card) 72%, transparent);
  border: 1px solid color-mix(in srgb, var(--line) 88%, transparent);
}

.lit-receipt-item-main {
  display: flex;
  flex-direction: column;
  gap: 5px;
  min-width: 0;
}

.lit-receipt-item-meta {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
}

.lit-receipt-paper-title {
  font-size: 13px;
  font-weight: 540;
  line-height: 1.45;
  color: var(--ink);
  word-break: break-word;
}

.lit-receipt-item-actions {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  flex-shrink: 0;
}

.lit-receipt-link {
  font-size: 12px;
  font-weight: 560;
  color: var(--accent);
  text-decoration: none;
  white-space: nowrap;
}

.lit-receipt-link:hover {
  text-decoration: underline;
}

.lit-receipt-link:focus-visible {
  outline: 2px solid var(--focus-ring);
  outline-offset: 2px;
  border-radius: 4px;
}

.lit-receipt-reason {
  font-size: 12px;
  color: var(--danger);
}

.lit-receipt-warning {
  margin: 0;
  padding: 6px 10px;
  border-radius: var(--radius-control);
  background: var(--warning-soft);
  color: var(--warning);
  font-size: 12.5px;
}
</style>
