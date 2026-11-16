<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { localAssistantApi } from '../api/local-assistant'
import type { LocalStatus } from '../api/local-assistant'
import StatusNotice from './StatusNotice.vue'

const state = ref<LocalStatus | null>(null), busy = ref(false), error = ref('')
const dialog = ref<HTMLDialogElement | null>(null), mode = ref<'initialize' | 'clear'>('initialize')
const labels = { disabled: '未启用', unavailable: '服务不可用', model_missing: '模型未注册', identity_mismatch: '模型身份不符', ready: '可用', busy: '处理中' }
async function act(task: () => Promise<LocalStatus>) {
  if (busy.value) return
  busy.value = true; error.value = ''
  try { state.value = await task() } catch (e) { error.value = e instanceof Error ? e.message : '本地模型状态未确认。' }
  finally { busy.value = false }
}
function confirm(value: typeof mode.value) { mode.value = value; dialog.value?.showModal() }
async function apply() { dialog.value?.close(); await act(mode.value === 'initialize' ? localAssistantApi.initialize : localAssistantApi.clear) }
async function toggle(kind: 'enabled' | 'auto_titles', event: Event) {
  const checked = (event.target as HTMLInputElement).checked, previous = state.value
  if (!previous) return
  await act(() => localAssistantApi.preferences(previous, kind === 'enabled' ? checked : previous.preferences.enabled, kind === 'auto_titles' ? checked : previous.preferences.auto_titles))
  ;(event.target as HTMLInputElement).checked = state.value?.preferences[kind] || false
}
onMounted(() => { void act(localAssistantApi.status) })
</script>

<template>
  <section class="settings-group local-settings-card">
    <h3>本机模型</h3>
    <StatusNotice v-if="error" title="本地助手操作未完成" :message="error" />
    <p v-if="busy" role="status">正在读取或更新本地助手状态…</p>
    <p v-else-if="!state && !error" role="status">本地助手状态未确认。</p>
    <template v-if="state">
      <div class="settings-row"><div><h4>本地小模型</h4><p>{{ state.model }}<span v-if="state.quantization"> · {{ state.parameter_size }} / {{ state.quantization }}</span></p></div><span class="tag">{{ labels[state.state] }}</span></div>
      <p class="settings-footnote" role="status">{{ state.message }}</p>
      <h3 class="settings-subheading">功能偏好</h3>
      <label class="settings-row settings-switch-row"><div><h4>启用本地助手</h4><p>拟标题、摘要、整理格式与查询条件建议</p></div><input class="settings-switch" type="checkbox" role="switch" :checked="state.preferences.enabled" :disabled="busy || !state.storage_ready || !state.configured" @change="toggle('enabled', $event)" /></label>
      <label class="settings-row settings-switch-row"><div><h4>自动命名会话</h4><p>提交首条问题后生成简短标题，最多 {{ state.title_max_characters ?? 18 }} 个字符</p></div><input class="settings-switch" type="checkbox" role="switch" :checked="state.preferences.auto_titles" :disabled="busy || !state.storage_ready || !state.preferences.enabled" @change="toggle('auto_titles', $event)" /></label>
      <p class="settings-footnote">人工名称优先。自动命名失败时保留简短规则标题，不转发到远程模型。</p>
      <p v-if="!state.storage_ready" class="notice">首次使用需先准备本地助手记录，再开启功能。</p>
      <details class="settings-maintenance"><summary>模型与运行详情</summary><p>身份摘要：{{ state.model_digest || '尚未固定' }}</p><p>{{ state.resource_hint }}</p><p>科研查询、绘图及文献问答使用各自原有路径。关闭本助手不会停止外部 Ollama 服务；人工名称仍可使用 80 个字符。</p></details>
    </template>
    <div class="local-actions settings-local-actions"><button type="button" :disabled="busy" @click="act(localAssistantApi.probe)">检查本机模型</button><button v-if="state && !state.storage_ready" type="button" :disabled="busy" @click="confirm('initialize')">准备本地助手记录</button><button v-if="state?.storage_ready" type="button" :disabled="busy" @click="confirm('clear')">清理已结束的任务记录</button><RouterLink to="/local-assistant">打开本地助手 ↗</RouterLink></div>
    <dialog ref="dialog" class="project-dialog"><h2>{{ mode === 'initialize' ? '准备本地助手记录？' : '清理已结束任务记录？' }}</h2><p>{{ mode === 'initialize' ? '在当前本机数据库中添加助手设置与任务记录。功能初始关闭，现有会话保留；确认后可手动启用，不触发下载或推理。' : '删除本地助手已结束任务的元数据，并清空短期结果缓存；会话、人工名称、原文和运行中的任务保留。' }}</p><div class="project-actions"><button type="button" @click="dialog?.close()">取消</button><button type="button" :disabled="busy" @click="apply">确认</button></div></dialog>
  </section>
</template>
