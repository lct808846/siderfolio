<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { skillsApi } from '../api/skills'
import StatusNotice from './StatusNotice.vue'
import type { ExternalMcpConfirmationRecord, ExternalMcpProposal, ExternalMcpResult } from '../types'

const props = defineProps<{
  proposal: ExternalMcpProposal
  initialResult?: ExternalMcpResult | null
}>()

const emit = defineEmits<{
  updated: [record: ExternalMcpConfirmationRecord]
}>()

const localProposal = ref<ExternalMcpProposal>(props.proposal)
const localResult = ref<ExternalMcpResult | null>(props.initialResult || null)
watch(() => props.proposal, next => { localProposal.value = next })
watch(() => props.initialResult, next => { if (next !== undefined) localResult.value = next || null })
const busy = ref(false)
const error = ref('')
let requestId = ''

const effectiveProposal = computed(() => localProposal.value || props.proposal)
const effectiveResult = computed(() => localResult.value || props.initialResult || null)

const argumentEntries = computed(() =>
  Object.entries(effectiveProposal.value.arguments || {}).map(([key, value]) => ({
    key,
    value: typeof value === 'string' ? value : JSON.stringify(value),
  })),
)

const statusLabel = computed(() => {
  const s = effectiveProposal.value.status
  if (s === 'executed') return '已完成外部查询'
  if (s === 'failed') return '外部查询失败'
  if (s === 'cancelled') return '已取消'
  if (s === 'expired') return '确认已过期'
  return '待确认外发字段'
})

const statusClass = computed(() => {
  const s = effectiveProposal.value.status
  if (s === 'executed') return 'ui-pill-success'
  if (s === 'failed') return 'ui-pill-danger'
  if (s === 'cancelled' || s === 'expired') return 'ui-pill-neutral'
  return 'ui-pill-warning'
})

async function confirmCall() {
  if (busy.value || effectiveProposal.value.status !== 'pending_confirmation') return
  busy.value = true
  error.value = ''
  if (!requestId) requestId = crypto.randomUUID()
  try {
    const record = await skillsApi.confirmExternalMcp(
      effectiveProposal.value.conversation_id,
      effectiveProposal.value.turn_id,
      effectiveProposal.value.confirmation_id,
      {
        client_request_id: requestId,
        expected_definition_sha256: effectiveProposal.value.definition_sha256,
        expected_arguments_sha256: effectiveProposal.value.arguments_sha256,
      },
    )
    localProposal.value = record.proposal
    localResult.value = record.result || null
    emit('updated', record)
  } catch (e) {
    error.value = e instanceof Error ? e.message : '外部 MCP 查询执行失败。'
  } finally {
    busy.value = false
  }
}

async function cancelCall() {
  if (busy.value || effectiveProposal.value.status !== 'pending_confirmation') return
  busy.value = true
  error.value = ''
  try {
    const record = await skillsApi.cancelExternalMcp(
      effectiveProposal.value.conversation_id,
      effectiveProposal.value.turn_id,
      effectiveProposal.value.confirmation_id,
    )
    localProposal.value = record.proposal
    localResult.value = record.result || null
    emit('updated', record)
  } catch (e) {
    error.value = e instanceof Error ? e.message : '取消外部查询失败。'
  } finally {
    busy.value = false
  }
}

function formatJson(data: unknown) {
  try {
    return JSON.stringify(data, null, 2)
  } catch {
    return String(data)
  }
}
</script>

<template>
  <section class="ui-card external-mcp-card" aria-label="外部 MCP 只读查询确认">
    <StatusNotice v-if="error" title="外部 MCP 查询未完成" :message="error" @dismiss="error = ''" />

    <header class="external-mcp-head">
      <div>
        <div class="ui-pill-list">
          <span class="ui-pill ui-pill-compute">外部 MCP · 只读</span>
          <span class="ui-pill" :class="statusClass">
            <span class="ui-dot" aria-hidden="true" />{{ statusLabel }}
          </span>
          <span class="ui-pill ui-pill-mono">协议 {{ effectiveProposal.protocol_version }}</span>
        </div>
        <h4>{{ effectiveProposal.tool_title }}</h4>
        <p class="small muted">
          目标服务：{{ effectiveProposal.server_title }}
          <template v-if="effectiveProposal.server_host">（<code>{{ effectiveProposal.server_host }}</code>）</template>
          · 工具标识 <code>{{ effectiveProposal.tool_id }}</code>
        </p>
      </div>
    </header>

    <div class="external-mcp-fields">
      <p class="external-mcp-section-title">本次将外发的精确字段</p>
      <dl v-if="argumentEntries.length" class="external-mcp-dl">
        <div v-for="entry in argumentEntries" :key="entry.key">
          <dt><code>{{ entry.key }}</code></dt>
          <dd><code>{{ entry.value }}</code></dd>
        </div>
      </dl>
      <p v-else class="small muted">无附加参数字段（空对象）。</p>
      <p class="external-mcp-boundary">
        仅向已获准的外部只读端点发送上述字段；完整会话、账号凭据、项目 RAG 原文与上传附件不会外发。
      </p>
    </div>

    <div v-if="effectiveProposal.status === 'pending_confirmation'" class="external-mcp-actions">
      <button type="button" :disabled="busy" @click="cancelCall">取消</button>
      <button type="button" class="button-primary" :disabled="busy" @click="confirmCall">
        {{ busy ? '正在执行外部只读查询…' : '确认并执行外部查询' }}
      </button>
    </div>

    <div v-if="effectiveResult" class="external-mcp-result">
      <div class="external-mcp-result-head">
        <strong>{{ effectiveResult.status === 'success' ? '外部查询返回结果' : '外部查询失败记录' }}</strong>
        <div class="ui-pill-list">
          <span v-if="effectiveResult.status === 'success'" class="ui-pill ui-pill-neutral">
            {{ effectiveResult.returned_count }} 项
          </span>
          <span v-if="effectiveResult.duration_ms != null" class="ui-pill ui-pill-mono">
            {{ effectiveResult.duration_ms }} ms
          </span>
          <span v-if="effectiveResult.truncated" class="ui-pill ui-pill-warning">已收敛截断</span>
        </div>
      </div>
      <p v-if="effectiveResult.summary" class="external-mcp-summary">{{ effectiveResult.summary }}</p>
      <p v-if="effectiveResult.error_code" class="small muted">
        错误代码：<code>{{ effectiveResult.error_code }}</code>
      </p>
      <details v-if="effectiveResult.structured_data != null || effectiveResult.text_excerpt" class="external-mcp-details">
        <summary>查看收敛后的外部数据（不可信外部来源）</summary>
        <pre v-if="effectiveResult.structured_data != null">{{ formatJson(effectiveResult.structured_data) }}</pre>
        <pre v-else>{{ effectiveResult.text_excerpt }}</pre>
      </details>
    </div>
  </section>
</template>

<style scoped>
.external-mcp-card {
  display: grid;
  gap: 12px;
  margin-top: 10px;
  padding: 14px 16px;
}

.external-mcp-head h4 {
  margin: 8px 0 3px;
  font-size: 14.5px;
  font-weight: 620;
  color: var(--ink);
}

.external-mcp-head p {
  margin: 0;
}

.external-mcp-fields {
  padding: 10px 12px;
  border: 1px solid var(--line);
  border-radius: var(--radius-control);
  background: var(--surface-subtle);
}

.external-mcp-section-title {
  margin: 0 0 8px;
  font-size: 12px;
  font-weight: 600;
  color: var(--muted);
}

.external-mcp-dl {
  display: grid;
  gap: 6px;
  margin: 0;
}

.external-mcp-dl > div {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: baseline;
  font-size: 12.5px;
}

.external-mcp-dl dt {
  color: var(--muted);
}

.external-mcp-dl dd {
  margin: 0;
  color: var(--ink);
  overflow-wrap: anywhere;
}

.external-mcp-boundary {
  margin: 8px 0 0;
  font-size: 11.5px;
  color: var(--muted);
  line-height: 1.55;
}

.external-mcp-actions {
  display: flex;
  justify-content: flex-end;
  flex-wrap: wrap;
  gap: 8px;
}

.external-mcp-result {
  display: grid;
  gap: 8px;
  padding-top: 10px;
  border-top: 1px solid var(--line);
}

.external-mcp-result-head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  font-size: 13px;
}

.external-mcp-summary {
  margin: 0;
  font-size: 13px;
  line-height: 1.65;
  color: var(--ink);
}

.external-mcp-details summary {
  cursor: pointer;
  font-size: 12px;
  color: var(--accent);
}

.external-mcp-details pre {
  margin: 8px 0 0;
  padding: 10px;
  max-height: 280px;
  overflow: auto;
  border: 1px solid var(--line);
  border-radius: var(--radius-control);
  background: var(--surface-evidence);
  font: 11.5px/1.55 var(--font-mono);
}
</style>
