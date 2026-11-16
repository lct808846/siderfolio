<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import WorkspaceHeader from '../components/WorkspaceHeader.vue'
import WorkspacePaneHeader from '../components/WorkspacePaneHeader.vue'
import { api } from '../api'
import { localAssistantApi, localTaskLabels, conditionLabels, intentLabels } from '../api/local-assistant'
import type { LocalStatus, LocalTaskRequest, LocalTaskView, LocalConditionResult } from '../api/local-assistant'
import type { Conversation, ConversationDetail } from '../types'

const state = ref<LocalStatus | null>(null), text = ref(''), operation = ref<LocalTaskRequest['action']>('summary'), format = ref<LocalTaskRequest['output_format']>('bullets')
const view = ref<LocalTaskView | null>(null), error = ref(''), message = ref(''), busy = ref(false), checking = ref(false)
const conversations = ref<Conversation[]>([]), conversationId = ref(''), source = ref<ConversationDetail | null>(null), turnId = ref('')
const pendingId = ref(''), autoRefresh = ref(true)
const bytes = computed(() => new TextEncoder().encode(text.value).length)
const editableResult = ref('')
const conditions = computed(() => view.value?.task.action === 'extract' && view.value.task.output ? view.value.task.output as unknown as LocalConditionResult : null)
const missingLabels = computed(() => (conditions.value?.missing ?? []).map(field => conditionLabels[field] || field).join('、'))
const comparisons: Record<string, string> = { eq: '=', lt: '<', lte: '≤', gt: '>', gte: '≥', unspecified: '' }
const titles = { title: '拟标题', summary: '简短摘要', format: '整理格式', extract: '提取条件与任务建议' }
let timer: ReturnType<typeof setTimeout> | undefined, generation = 0, sourceGeneration = 0
function remember(id: string) { pendingId.value = id; try { if (id) sessionStorage.setItem('astroagent.local-task.pending.v1', id); else sessionStorage.removeItem('astroagent.local-task.pending.v1') } catch { message.value = '浏览器不能保存请求编号，请保留本页核对。' } }
async function refreshStatus() {
  try { state.value = await localAssistantApi.status() } catch (e) { error.value = e instanceof Error ? e.message : '本地服务状态不可用。' }
}
async function chooseConversation() {
  source.value = null; turnId.value = ''
  if (!conversationId.value) return
  const id = conversationId.value, token = ++sourceGeneration
  try { const value = await api.detail(id); if (token === sourceGeneration && id === conversationId.value) source.value = value }
  catch (e) { error.value = e instanceof Error ? e.message : '读取会话失败。' }
}
function fillSelected() {
  const turn = source.value?.turns.find(value => value.turn_id === turnId.value)
  if (turn) { text.value = turn.message; message.value = '已填入选定用户问题；确认生成后才发送给本机模型。' }
}
async function receive(value: LocalTaskView, token: number) {
  if (token !== generation) return
  view.value = value
  editableResult.value = typeof value.task.output?.text === 'string' ? value.task.output.text : typeof value.task.output?.title === 'string' ? value.task.output.title : value.task.output ? JSON.stringify(value.task.output, null, 2) : ''
  if (['queued', 'running'].includes(value.task.state)) {
    busy.value = true
    if (autoRefresh.value) timer = setTimeout(() => { void refreshTask(token) }, 2000)
  } else { busy.value = false; remember(''); void refreshStatus() }
}
async function refreshTask(token = generation) {
  if (!pendingId.value || checking.value) return
  checking.value = true
  try { await receive(await localAssistantApi.task(pendingId.value), token) }
  catch (e) { if (token === generation) { error.value = e instanceof Error ? e.message : '任务状态未确认，请用原编号刷新。'; busy.value = false } }
  finally { checking.value = false }
}
async function submit() {
  if (busy.value || pendingId.value || !text.value.trim() || bytes.value > 4096) return
  const token = ++generation, id = crypto.randomUUID()
  remember(id); error.value = ''; message.value = ''; view.value = null; editableResult.value = ''; busy.value = true
  try { await receive(await localAssistantApi.submit(id, { action: operation.value, text: text.value, output_format: format.value }), token) }
  catch (e) { error.value = e instanceof Error ? e.message : '提交状态未确认，不自动重试。'; busy.value = false }
}
async function copy() { try { await navigator.clipboard.writeText(editableResult.value); message.value = '已复制当前结果。' } catch { error.value = '复制失败，请选中结果手动复制。' } }
function releasePending() { if (timer) clearTimeout(timer); generation++; busy.value = false; remember(''); message.value = '已清除本页等待状态；这不会取消服务端已经开始的推理。' }
onMounted(async () => {
  try { const id = sessionStorage.getItem('astroagent.local-task.pending.v1'); if (id && /^[0-9a-f-]{36}$/.test(id)) pendingId.value = id } catch { /* Keep input in memory only. */ }
  await refreshStatus()
  try { conversations.value = await api.list() } catch { /* Pasted text remains usable. */ }
  if (pendingId.value) await refreshTask()
})
onBeforeUnmount(() => { generation++; sourceGeneration++; if (timer) clearTimeout(timer) })
</script>

<template>
  <div class="workspace-panes primary-workspace local-assistant-workspace">
    <WorkspaceHeader title="本地轻量助手" />
    <main class="local-assistant-main">
      <WorkspacePaneHeader title="本地助手"><template #actions><div class="local-actions"><span v-if="state" class="tag">{{ state.state === 'ready' ? '本机可用' : state.state === 'busy' ? '本机处理中' : state.message }}</span><RouterLink to="/settings?section=assistant">模型与开关设置 →</RouterLink></div></template></WorkspacePaneHeader>
      <div class="local-assistant-reading">
        <p class="muted">由本机千问辅助处理选定文本。明示条件按原文提取，模型只建议任务类型；摘要选取原文片段，格式整理保留原文。结果供核对和编辑，不自动改写会话或执行科研工具。</p>
        <p v-if="error" class="notice danger" role="alert">{{ error }}</p><p v-if="message" class="notice info" role="status">{{ message }}</p>
        <div class="local-task-tabs" role="group" aria-label="选择本地文本任务"><button v-for="(label, key) in titles" :key="key" type="button" :aria-pressed="operation === key" :disabled="busy || !!pendingId" @click="operation = key">{{ label }}</button></div>
        <div class="local-assistant-grid">
          <section class="local-input-panel">
<h2>选择输入</h2>
            <details class="local-source"><summary>填入当前会话中的用户问题</summary><label>会话<select v-model="conversationId" :disabled="busy" @change="chooseConversation"><option value="">选择会话</option><option v-for="conversation in conversations" :key="conversation.id" :value="conversation.id">{{ conversation.title }}</option></select></label><label v-if="source">用户问题<select v-model="turnId" :disabled="busy"><option value="">选择轮次</option><option v-for="turn in source.turns" :key="turn.turn_id" :value="turn.turn_id">第{{ turn.revision }}轮 · {{ turn.message.slice(0, 28) }}</option></select></label><button type="button" :disabled="busy || !turnId" @click="fillSelected">填入选定问题</button><p class="small muted">只填入明确选中的问题，不读取整段回答、附件或数据库结果。</p></details>
            <label for="local-source-text">{{ titles[operation] }}的原文</label><textarea id="local-source-text" v-model="text" maxlength="4000" rows="12" :disabled="busy" placeholder="粘贴或填入需要本机模型处理的文本…" />
            <p v-if="operation === 'title'" class="small muted">标题最多{{ state?.title_max_characters ?? 18 }}个字符，概括主题；过长编号可省略，不截断编号。</p>
            <div class="local-section-heading"><small :class="{ danger: bytes > 4096 }">{{ text.length }}/4000字符 · {{ bytes }}/4096 UTF-8字节</small><label v-if="operation === 'format'">格式<select v-model="format" :disabled="busy"><option value="bullets">无序要点</option><option value="paragraph">段落</option><option value="markdown">Markdown</option></select></label></div>
            <p class="small muted">仅发送这里显示的原文到本机模型。输入和手动结果不写入任务历史；结果仅在服务内存缓存10分钟。</p>
            <button type="button" class="button-primary" :disabled="busy || !!pendingId || !text.trim() || bytes > 4096 || !state?.preferences.enabled || !state?.configured" @click="submit">{{ busy ? '本地处理中…' : `生成${titles[operation]}` }}</button>
          </section>
          <section class="local-result-panel">
<div class="local-section-heading"><h2>结果与依据</h2><button type="button" :disabled="!editableResult" @click="copy">复制当前结果</button></div>
            <template v-if="view">
              <p class="small">{{ localTaskLabels[view.task.state] }} · {{ view.task.model }}</p>
              <p v-if="view.task.error" class="notice danger">{{ view.task.error }}</p><p class="small muted">{{ view.warning }}</p>
              <div v-if="conditions" class="local-conditions">
                <div class="local-condition-table"><table><thead><tr><th>条件</th><th>原文值</th><th>依据</th></tr></thead><tbody><tr v-for="condition in conditions.conditions" :key="condition.field"><th>{{ conditionLabels[condition.field] || condition.field }}</th><td>{{ condition.status === 'ambiguous' ? '需要确认' : `${comparisons[condition.comparison] || ''} ${condition.value || '—'} ${condition.unit || ''}` }}</td><td>{{ condition.evidence }}</td></tr></tbody></table></div>
                <p v-if="!conditions.conditions.length" class="small muted">未提取出明确条件。</p>
                <h3>任务建议</h3><ul><li v-for="suggestion in conditions.suggestions" :key="suggestion.kind"><strong>{{ intentLabels[suggestion.kind] || suggestion.kind }}</strong><span class="small">依据：{{ suggestion.evidence }}</span></li></ul>
                <p v-if="conditions.missing.length" class="small">缺失：{{ missingLabels }}</p>
                <ul v-if="conditions.clarification.length"><li v-for="question in conditions.clarification" :key="question">{{ question }}</li></ul>
                <details><summary>查看或编辑条件 JSON</summary><textarea v-model="editableResult" rows="12" aria-label="可编辑的条件结果 JSON" /></details>
              </div>
              <textarea v-else-if="editableResult" v-model="editableResult" rows="16" aria-label="可编辑的本地模型结果" />
              <p v-else-if="view.task.state === 'completed'" class="notice">结果缓存已过期或服务已重启。任务不会自动重新推理。</p>
              <details><summary>任务范围与用量</summary><p class="small">编号：{{ view.task.id }}<br />实际输入：{{ view.task.input_characters }}字符{{ view.task.input_truncated ? '（已截取）' : '' }}<br />模型摘要：{{ view.task.model_digest }}<br />输入摘要：{{ view.task.input_sha256 }}</p><pre>{{ JSON.stringify(view.task.usage, null, 2) }}</pre></details>
            </template>
            <div v-else class="local-assistant-empty"><h3>先选择文本和操作</h3><p>条件提取会显示原文依据、缺失值与任务建议；建议不会直接发起查询。</p></div>
            <div v-if="pendingId" class="notice"><p class="small">当前请求：{{ pendingId }}。断开页面不代表取消；自动更新只查询状态，不自动重发。</p><label class="local-check"><input v-model="autoRefresh" type="checkbox" />自动更新状态</label><div class="local-actions"><button type="button" @click="releasePending">结束本页等待</button></div></div>
          </section>
        </div>
      </div>
    </main>
  </div>
</template>
