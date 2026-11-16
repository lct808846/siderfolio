<script setup lang="ts">
import { computed } from 'vue'
import StatusNotice from './StatusNotice.vue'
import ModelBillingLink from './ModelBillingLink.vue'

const props = withDefaults(defineProps<{
  message: string
  code?: string
  current?: boolean
  busy?: boolean
  canRetry?: boolean
}>(), { code: '', current: false, busy: false, canRetry: false })
defineEmits<{ retry: [] }>()
const billing = computed(() => ['gemini_billing_required', 'model_billing_required'].includes(props.code))
const limited = computed(() => props.code === 'model_rate_limited')
const timeout = computed(() => props.code.includes('timeout'))
const disconnected = computed(() => props.code === 'connection_lost')
const title = computed(() => billing.value ? '模型服务余额不足'
  : limited.value ? '模型额度或速率受限'
    : timeout.value ? '服务响应超时'
      : disconnected.value ? '服务连接已中断'
        : props.current ? '本次操作未完成' : '本轮回答未完成')
const warning = computed(() => billing.value || limited.value || timeout.value || disconnected.value)
</script>

<template>
  <StatusNotice class="conversation-error" :class="{ 'conversation-error-history': !current }" :title="title" :message="message" :tone="warning ? 'warning' : 'danger'" :announce="current">
    <template v-if="(current && canRetry) || code === 'gemini_billing_required'" #actions>
      <ModelBillingLink v-if="code === 'gemini_billing_required'" />
      <button v-if="current && canRetry" type="button" :disabled="busy" data-tooltip="按当前输入新建一轮请求，会产生新的模型用量" @click="$emit('retry')"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 12h14m-6-6 6 6-6 6" /></svg>重新发送</button>
    </template>
    <details v-if="code" class="conversation-error-details"><summary>技术详情</summary><code>{{ code }}</code></details>
  </StatusNotice>
</template>
