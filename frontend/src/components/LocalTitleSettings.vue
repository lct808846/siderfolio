<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { localTitlesApi, type LocalStatus } from '../api/local-titles'
import StatusNotice from './StatusNotice.vue'

const state = ref<LocalStatus | null>(null), busy = ref(false), error = ref('')
const labels = { disabled: '未启用', unavailable: '服务不可用', model_missing: '模型未注册', identity_mismatch: '模型身份不符', ready: '可用', busy: '处理中' }
async function act(task: () => Promise<LocalStatus>) {
  if (busy.value) return
  busy.value = true; error.value = ''
  try {
    state.value = await task()
  } catch (e) { error.value = e instanceof Error ? e.message : '本地模型状态未确认。' }
  finally { busy.value = false }
}
async function toggle(event: Event) {
  const input = event.target as HTMLInputElement
  const previous = state.value
  if (!previous) return
  await act(() => localTitlesApi.preferences(previous, input.checked))
  const preferences = state.value?.preferences
  input.checked = !!(preferences?.enabled && preferences.auto_titles)
}
onMounted(() => { void act(localTitlesApi.status) })
</script>

<template>
  <section class="settings-group local-settings-card">
    <h3>本机模型</h3>
    <StatusNotice v-if="error" title="自动命名操作未完成" :message="error" @dismiss="error = ''" />
    <p v-if="busy" role="status">正在读取或更新本地模型状态…</p>
    <template v-if="state">
      <div class="settings-row">
        <div>
          <h4>本地小模型</h4>
          <div class="ui-pill-list" style="margin-top: 6px;">
            <span class="ui-pill ui-pill-mono">{{ state.model }}</span>
            <span v-if="state.parameter_size" class="ui-pill ui-pill-compute">{{ state.parameter_size }}</span>
            <span v-if="state.quantization" class="ui-pill ui-pill-neutral">{{ state.quantization }}</span>
          </div>
        </div>
        <span class="ui-pill" :class="state.state === 'ready' ? 'ui-pill-success' : state.state === 'busy' ? 'ui-pill-warning' : 'ui-pill-neutral'"><span class="ui-dot" aria-hidden="true" />{{ labels[state.state] }}</span>
      </div>
      <p class="settings-footnote" role="status">{{ state.message }}</p>
      <label class="settings-row settings-switch-row"><div><h4>自动命名会话</h4><p>提交首条问题后生成简短标题，最多 {{ state.title_max_characters ?? 18 }} 个字符</p></div><input class="settings-switch" type="checkbox" role="switch" aria-label="自动命名会话" :checked="state.preferences.enabled && state.preferences.auto_titles" :disabled="busy || !state.storage_ready || !state.configured" @change="toggle" /></label>
      <p class="settings-footnote">人工名称优先。自动命名失败时保留简短规则标题，不转发到远程模型。</p>
      <details class="settings-maintenance"><summary>模型与运行详情</summary><p>模型摘要 {{ state.model_digest || '尚未配置' }}</p><p>{{ state.resource_hint }}</p></details>
    </template>
    <div class="settings-local-actions"><button type="button" :disabled="busy" @click="act(localTitlesApi.probe)">检查本机模型</button></div>
  </section>
</template>
