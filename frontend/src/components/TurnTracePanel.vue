<script setup lang="ts">
import { computed } from 'vue'
import { identityUser } from '../identity-state'
import { useModels } from '../stores/models'
import type { RunSpan, RunTrace } from '../types'

const props = defineProps<{
  trace?: RunTrace | null
  traceStatus?: 'available' | 'unavailable' | 'not_recorded'
}>()

const emit = defineEmits<{
  'jump-result': [target: { type: string; batchIndex?: number; receiptId?: string }]
}>()

const modelsStore = useModels()
const canConfigurePricing = computed(() => Boolean(identityUser.value?.admin && identityUser.value?.mfa_verified))
const visible = computed(() => Boolean(props.trace) || props.traceStatus === 'unavailable')

function displayModelName(raw: string | null | undefined): string {
  if (!raw) return ''
  return modelsStore.labelFor(raw)
}

function formatDuration(ms: number | null | undefined) {
  if (ms == null || !Number.isFinite(ms)) return '—'
  if (ms < 1000) return `${Math.round(ms)} ms`
  return `${(ms / 1000).toFixed(2)} s`
}

function statusLabel(status: RunSpan['status'] | RunTrace['status']) {
  if (status === 'ok') return '成功'
  if (status === 'partial') return '部分完成'
  if (status === 'not_found') return '无匹配'
  if (status === 'error') return '失败'
  if (status === 'running') return '运行中'
  if (status === 'queued') return '排队中'
  if (status === 'cancelled') return '已取消'
  if (status === 'interrupted') return '已中断'
  return '已跳过'
}

function statusClass(status: RunSpan['status'] | RunTrace['status']) {
  if (status === 'ok') return 'ui-pill-success'
  if (status === 'partial' || status === 'not_found') return 'ui-pill-warning'
  if (status === 'error' || status === 'interrupted') return 'ui-pill-danger'
  return 'ui-pill-neutral'
}

function transportLabel(transport: string | null | undefined) {
  if (transport === 'mcp') return 'MCP'
  if (transport === 'direct') return '直连'
  if (transport === 'internal') return '内置'
  return ''
}

function categoryLabel(category: string | null | undefined) {
  const labels: Record<string, string> = {
    auth: '授权拒绝',
    authorization: '授权拒绝',
    validation: '参数校验',
    timeout: '超时',
    rate_limit: '限流',
    upstream: '上游服务异常',
    upstream_error: '上游服务异常',
    not_found: '无匹配',
    mcp_subprocess: 'MCP 子进程异常',
    mcp_protocol: 'MCP 协议异常',
    mcp_transport: 'MCP 传输异常',
    storage: '存储异常',
    internal: '内部异常',
    unknown: '未知异常',
  }
  return category && category !== 'none' ? (labels[category] || category) : ''
}

function jumpLabel(span: RunSpan) {
  const ref = span.result_ref
  if (!ref) return ''
  const kind = String(ref.type || '')
  if (kind === 'literature') return '查看文献管理 →'
  if (kind === 'ads') return '查看 ADS 结果 →'
  if (kind === 'gaia') return '查看 Gaia 结果 →'
  if (kind === 'simbad') return '查看 SIMBAD 结果 →'
  if (kind === 'compute') return '查看 N 体记录 →'
  if (kind === 'plot') return '查看绘图产物 →'
  return ''
}

function triggerJump(span: RunSpan) {
  const ref = span.result_ref
  if (!ref) return
  emit('jump-result', {
    type: String(ref.type || ''),
    batchIndex: typeof ref.batch_index === 'number' ? ref.batch_index : undefined,
    receiptId: typeof ref.receipt_id === 'string' ? ref.receipt_id : undefined,
  })
}

const tokenSummaryText = computed(() => {
  const usage = props.trace?.usage
  if (!usage) return '用量未报告'
  if (usage.total_tokens != null) {
    return `${usage.total_tokens.toLocaleString()} tokens`
  }
  if (usage.input_tokens != null || usage.output_tokens != null) {
    return `入 ${usage.input_tokens ?? '未知'} / 出 ${usage.output_tokens ?? '未知'}`
  }
  return '用量未报告'
})

const costSummaryText = computed(() => {
  const usage = props.trace?.usage
  if (!usage || usage.usage_source !== 'reported') return '未报告用量'
  if (usage.cost_status !== 'estimated' || usage.estimated_cost == null) {
    return '未配置单价'
  }
  const symbol = usage.currency === 'CNY' ? '¥' : usage.currency === 'USD' ? '$' : `${usage.currency || 'USD'} `
  const digits = usage.estimated_cost < 0.01 ? 5 : usage.estimated_cost < 1 ? 4 : 3
  const version = usage.pricing_version ? `（${usage.pricing_version}）` : ''
  return `${symbol}${usage.estimated_cost.toFixed(digits)}${version}`
})

const needsPricingConfig = computed(() => {
  const usage = props.trace?.usage
  return Boolean(usage && usage.usage_source === 'reported' && usage.cost_status !== 'estimated')
})

const traceSpans = computed(() => props.trace?.spans || [])

const hasErrorSpan = computed(() =>
  Boolean(props.trace?.status === 'error' || traceSpans.value.some(span => span.status === 'error')),
)
</script>

<template>
  <details v-if="visible" class="turn-trace-panel">
    <summary class="turn-trace-summary">
      <span class="turn-trace-summary-left">
        <span class="turn-trace-dot" :class="{ 'is-error': hasErrorSpan, 'is-muted': !trace }" aria-hidden="true" />
        <strong class="turn-trace-label">运行追踪</strong>
        <template v-if="trace">
          <span class="turn-trace-inline-meta">
            <span class="turn-trace-mono">{{ formatDuration(trace.duration_ms) }}</span>
            <span class="turn-trace-sep" aria-hidden="true">·</span>
            <span>{{ traceSpans.length }} 阶段</span>
            <template v-if="trace.astronomy_transport">
              <span class="turn-trace-sep" aria-hidden="true">·</span>
              <span class="turn-trace-transport" :class="{ 'is-mcp': trace.astronomy_transport === 'mcp' }">
                {{ transportLabel(trace.astronomy_transport) }}
              </span>
            </template>
            <template v-if="trace.usage?.usage_source === 'reported'">
              <span class="turn-trace-sep" aria-hidden="true">·</span>
              <span class="turn-trace-mono">{{ tokenSummaryText }}</span>
            </template>
          </span>
          <span v-if="trace.status !== 'ok'" class="ui-pill" :class="statusClass(trace.status)">
            {{ statusLabel(trace.status) }}
          </span>
        </template>
        <span v-else class="small muted">追踪记录已过期或不可用</span>
      </span>
      <span class="turn-trace-chevron" aria-hidden="true">
        <span>详情</span>
        <svg viewBox="0 0 24 24"><path d="m6 9 6 6 6-6" /></svg>
      </span>
    </summary>

    <div v-if="trace" class="turn-trace-body">
      <div class="turn-trace-overview">
        <span>追踪编号 <code>{{ trace.trace_id.slice(0, 8) }}</code></span>
        <span>
          Token 用量：
          <template v-if="trace.usage?.usage_source === 'reported'">
            输入 <b>{{ trace.usage?.input_tokens ?? '未知' }}</b> · 输出 <b>{{ trace.usage?.output_tokens ?? '未知' }}</b> · 总计 <b>{{ trace.usage?.total_tokens ?? '未知' }}</b>
          </template>
          <template v-else>模型接口未报告 Token 用量</template>
        </span>
        <span>
          估算费用：<b>{{ costSummaryText }}</b>
          <RouterLink
            v-if="needsPricingConfig && canConfigurePricing"
            class="turn-trace-price-link"
            to="/settings?section=models"
          >
            配置单价 →
          </RouterLink>
        </span>
      </div>

      <ol v-if="traceSpans.length" class="turn-trace-spans">
        <li v-for="span in traceSpans" :key="span.span_id" class="turn-trace-span" :class="{ 'is-error': span.status === 'error' }">
          <div class="turn-trace-span-top">
            <div class="turn-trace-span-title">
              <span class="ui-pill" :class="statusClass(span.status)">{{ statusLabel(span.status) }}</span>
              <strong>{{ span.name }}</strong>
              <span v-if="span.provider" class="ui-pill ui-pill-neutral">{{ span.provider }}</span>
              <span v-if="span.model" class="ui-pill ui-pill-mono">{{ displayModelName(span.model) }}</span>
              <span v-if="span.transport && span.transport !== 'internal'" class="ui-pill" :class="span.transport === 'mcp' ? 'ui-pill-compute' : 'ui-pill-neutral'">
                {{ transportLabel(span.transport) }}
              </span>
            </div>
            <span class="turn-trace-duration">{{ formatDuration(span.duration_ms) }}</span>
          </div>

          <div class="turn-trace-span-meta">
            <span v-if="span.result_count != null">返回 {{ span.result_count }} 项</span>
            <span v-if="span.truncated" class="ui-pill ui-pill-warning">已截断</span>
            <span v-if="span.correlation_id">MCP 关联号 <code>{{ span.correlation_id }}</code></span>
            <span v-if="span.usage?.usage_source === 'reported'">
              Tokens {{ span.usage.total_tokens ?? `${span.usage.input_tokens ?? '?'}/${span.usage.output_tokens ?? '?'}` }}
            </span>
            <span v-if="span.error_code" class="turn-trace-err">
              {{ categoryLabel(span.error_category) ? `${categoryLabel(span.error_category)} · ` : '' }}<code>{{ span.error_code }}</code>
            </span>
            <button
              v-if="jumpLabel(span)"
              type="button"
              class="turn-trace-jump"
              @click="triggerJump(span)"
            >
              {{ jumpLabel(span) }}
            </button>
          </div>
        </li>
      </ol>
      <p v-else class="small muted" style="margin: 0;">本轮未记录工具或模型阶段。</p>
    </div>

    <div v-else class="turn-trace-body">
      <p class="small muted" style="margin: 0;">
        该轮次的运行追踪记录未能保存或已超出保留窗口，原始回答与查询结果不受影响。
      </p>
    </div>
  </details>
</template>

<style scoped>
.turn-trace-panel {
  margin-top: 8px;
  border: 1px solid color-mix(in srgb, var(--line) 90%, transparent);
  border-radius: 11px;
  background: color-mix(in srgb, var(--surface-card) 62%, transparent);
  backdrop-filter: blur(8px);
  overflow: hidden;
  transition: border-color 0.15s ease, background-color 0.15s ease;
}

.turn-trace-panel:hover,
.turn-trace-panel[open] {
  border-color: color-mix(in srgb, var(--accent) 24%, var(--line));
  background: color-mix(in srgb, var(--surface-card) 78%, transparent);
}

.turn-trace-summary {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 7px 12px;
  cursor: pointer;
  list-style: none;
  font-size: 12px;
  color: var(--ink);
}

.turn-trace-summary::-webkit-details-marker {
  display: none;
}

.turn-trace-summary:focus-visible {
  outline: 2px solid var(--focus-ring);
  outline-offset: -2px;
}

.turn-trace-summary-left {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.turn-trace-label {
  font-weight: 600;
  color: var(--ink);
}

.turn-trace-inline-meta {
  display: inline-flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  font-size: 11.5px;
  color: var(--muted);
  font-variant-numeric: tabular-nums;
}

.turn-trace-mono {
  font-family: var(--font-mono);
}

.turn-trace-sep {
  opacity: 0.45;
}

.turn-trace-transport {
  font-weight: 560;
}

.turn-trace-transport.is-mcp {
  color: var(--accent);
}

.turn-trace-dot {
  width: 6.5px;
  height: 6.5px;
  border-radius: 50%;
  background: var(--success);
  flex-shrink: 0;
}

.turn-trace-dot.is-error {
  background: var(--danger);
}

.turn-trace-dot.is-muted {
  background: var(--muted);
}

.turn-trace-chevron {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  font-size: 11.5px;
  color: var(--muted);
}

.turn-trace-chevron svg {
  width: 14px;
  height: 14px;
  fill: none;
  stroke: currentColor;
  stroke-width: 1.9;
  stroke-linecap: round;
  stroke-linejoin: round;
  transition: transform 0.18s ease;
}

.turn-trace-panel[open] .turn-trace-chevron svg {
  transform: rotate(180deg);
}

.turn-trace-body {
  padding: var(--space-3);
  border-top: 1px solid var(--line);
  background: var(--surface-card);
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.turn-trace-overview {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 16px;
  font-size: 12px;
  color: var(--muted);
  padding-bottom: 6px;
  border-bottom: 1px dashed var(--line);
}

.turn-trace-price-link {
  margin-left: 6px;
  font-weight: 560;
  color: var(--accent);
  text-decoration: none;
}

.turn-trace-price-link:hover {
  text-decoration: underline;
}

.turn-trace-spans {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.turn-trace-span {
  padding: 8px 10px;
  border-radius: var(--radius-control);
  border: 1px solid var(--line);
  background: var(--surface-subtle);
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.turn-trace-span.is-error {
  border-color: color-mix(in srgb, var(--danger) 35%, transparent);
  background: var(--danger-soft);
}

.turn-trace-span-top {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-2);
}

.turn-trace-span-title {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  font-size: 12.5px;
  color: var(--ink);
}

.turn-trace-duration {
  font-family: var(--font-mono);
  font-size: 12px;
  color: var(--muted);
}

.turn-trace-span-meta {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  color: var(--muted);
}

.turn-trace-err {
  color: var(--danger);
}

.turn-trace-jump {
  margin-left: auto;
  padding: 2px 8px;
  min-height: 24px;
  font-size: 12px;
  color: var(--accent);
  background: transparent;
  border: 1px solid color-mix(in srgb, var(--accent) 28%, transparent);
  border-radius: var(--radius-pill);
  cursor: pointer;
}

.turn-trace-jump:hover {
  background: var(--accent-soft);
}

.turn-trace-jump:focus-visible {
  outline: 2px solid var(--focus-ring);
  outline-offset: 2px;
}
</style>
