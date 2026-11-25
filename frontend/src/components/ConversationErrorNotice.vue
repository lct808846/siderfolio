<script setup lang="ts">
import { computed } from 'vue'
import StatusNotice from './StatusNotice.vue'
import ModelBillingLink from './ModelBillingLink.vue'

const props = withDefaults(defineProps<{
  message: string
  code?: string
  operation?: boolean
  announce?: boolean
  advisory?: boolean
  busy?: boolean
  canRetry?: boolean
  inline?: boolean
}>(), { code: '', operation: false, announce: false, advisory: false, busy: false, canRetry: false, inline: false })
defineEmits<{ retry: []; dismiss: [] }>()
const billing = computed(() => ['gemini_billing_required', 'model_billing_required'].includes(props.code))
const limited = computed(() => props.code === 'model_rate_limited')
const timeout = computed(() => props.code.includes('timeout'))
const disconnected = computed(() => props.code === 'connection_lost')
const mcpBusy = computed(() => props.code === 'mcp_pool_exhausted' || props.code === 'mcp_busy')
const mcpFailure = computed(() => props.code.startsWith('mcp_'))
const title = computed(() => billing.value ? '模型服务余额不足'
  : limited.value ? '模型额度或速率受限'
    : timeout.value ? '服务响应超时'
      : disconnected.value ? '服务连接已中断'
        : mcpBusy.value ? 'MCP 查询通道正忙'
          : mcpFailure.value ? 'MCP 查询通道异常'
            : props.advisory ? '查询提示' : props.operation ? '操作未完成' : '回答未完成')
const warning = computed(() => props.advisory || billing.value || limited.value || timeout.value || disconnected.value || mcpBusy.value)
</script>

<template>
  <StatusNotice
    :class="inline ? 'conversation-error' : 'conversation-error-popup'"
    :title="title"
    :message="message"
    :tone="warning ? 'warning' : 'danger'"
    :announce="announce"
    :inline="inline"
    :persistent="canRetry || !!$slots.actions"
    @dismiss="$emit('dismiss')"
  >
    <template v-if="code || canRetry || $slots.actions" #default>
      <div class="conversation-error-tools">
        <ModelBillingLink v-if="code === 'gemini_billing_required'" />
        <button v-if="canRetry" type="button" :disabled="busy" data-tooltip="按当前输入重新发送，会产生新的模型用量" @click="$emit('retry')"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 12h14m-6-6 6 6-6 6" /></svg>重新发送</button>
        <slot name="actions" />
        <details v-if="code" class="conversation-error-details"><summary>技术详情</summary><code>{{ code }}</code></details>
      </div>
    </template>
  </StatusNotice>
</template>
