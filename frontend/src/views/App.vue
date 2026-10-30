<script setup lang="ts">
import { onMounted, ref, watch, computed, nextTick } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useWorkbench } from '../stores/workbench'
import ResultPanel from '../components/ResultPanel.vue'
import ProjectWorkspace from './ProjectWorkspace.vue'
import WorkflowWorkspace from './WorkflowWorkspace.vue'
import KnowledgeWorkspace from './KnowledgeWorkspace.vue'
import { safeLink } from '../api'

const store = useWorkbench(), route = useRoute(), router = useRouter()
const draft = ref(''), composing = ref(false), titleEditing = ref(false), title = ref('')
const confirmDelete = ref(false)
const input = ref<HTMLTextAreaElement | null>(null)
const newest = computed(() => store.turns.at(-1)?.turn_id)
const examples = [
  { label: '坐标圆锥查询', text: '以 ICRS 赤经56.75度、赤纬24.12度为中心，查5角分内最近100个Gaia DR3位置候选源，不估算距离。' },
  { label: '指定 DR3 编号', text: '查询 Gaia DR3 source_id 5853498713190525696 的测量信息并估算距离，说明近似条件。' },
  { label: 'ADS 文献检索', text: '检索2020—2026年双星团相关论文，取3篇，按发表日期降序，给出来源。' },
]
async function create() { const id = await store.create(); if (id) await router.push(`/conversations/${id}`) }
async function send() { const message = draft.value; if (!message.trim() || store.running) return; if (!store.current) { await create(); if (!store.current) return } draft.value = ''; await store.send(message); if (store.error && !store.disconnectedRequest) draft.value = message; input.value?.focus() }
function keydown(event: KeyboardEvent) { if (event.key === 'Enter' && !event.shiftKey && !event.isComposing && !composing.value) { event.preventDefault(); void send() } }
function useExample(text: string) { draft.value = text; input.value?.focus() }
async function remove() { await store.remove(); confirmDelete.value = false; if (!store.current) await router.push('/') }
async function rename() { if (title.value.trim()) await store.rename(title.value.trim()); titleEditing.value = false }
function dialogKey(event: KeyboardEvent) {
  if (event.key === 'Escape') { titleEditing.value = false; confirmDelete.value = false; input.value?.focus(); return }
  if (event.key !== 'Tab') return
  const elements = Array.from(document.querySelectorAll<HTMLElement>('[role="dialog"] input, [role="dialog"] button:not(:disabled)'))
  const first = elements[0], last = elements.at(-1)
  if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus() }
  if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus() }
}
watch(() => route.params.id, id => { if (typeof id === 'string' && id !== store.current?.id) void store.load(id); if (!id) { store.loadToken++; store.current = null; store.turns = []; store.selectedTurnId = '' }; store.panel = 'chat' })
watch([titleEditing, confirmDelete], async ([editing, removing]) => { if (editing || removing) { await nextTick(); document.querySelector<HTMLElement>('[role="dialog"] input, [role="dialog"] button')?.focus() } })
onMounted(async () => {
  const initialId = route.params.id
  try {
    await store.refreshList()
    if (typeof initialId === 'string' && route.params.id === initialId && initialId !== store.current?.id) await store.load(initialId)
  } catch (error) { store.report(error) }
})
</script>

<template>
  <KnowledgeWorkspace v-if="route.path.includes('/knowledge')" />
  <WorkflowWorkspace v-else-if="route.path.includes('/workflows')" />
  <ProjectWorkspace v-else-if="route.path.startsWith('/projects')" />
  <div v-else class="workbench" :data-panel="store.panel">
    <header class="topbar"><a class="brand" href="/" @click.prevent="router.push('/')"><span class="brand-mark" aria-hidden="true">✳</span><b>AstroAgent</b><span class="version">0.8</span></a><div class="topbar-caption"><span class="status-dot"></span>本地科研工作台</div><RouterLink class="project-link" to="/projects">项目归档 →</RouterLink><a href="http://127.0.0.1:8000/docs" target="_blank" rel="noopener noreferrer" class="docs-link">接口文档 ↗</a></header>
    <nav class="mobile-panels" aria-label="工作区面板"><button :class="{active:store.panel==='history'}" @click="store.panel='history'">会话</button><button :class="{active:store.panel==='chat'}" @click="store.panel='chat'">对话</button><button :class="{active:store.panel==='results'}" @click="store.panel='results'">结果</button></nav>
    <aside class="history-panel" aria-label="会话列表"><div class="history-title"><span class="eyebrow">WORKSPACE</span><span class="small muted">{{ store.conversations.length }}/20</span></div><button class="new-conversation" @click="create"><span aria-hidden="true">＋</span>新建会话</button><p class="history-label">本地会话</p><nav><button v-for="conversation in store.conversations" :key="conversation.id" class="conversation-item" :class="{selected:store.current?.id===conversation.id}" @click="router.push(`/conversations/${conversation.id}`)"><span class="conversation-symbol" aria-hidden="true">◌</span><span><b>{{ conversation.title }}</b><small>{{ conversation.revision }} 轮 · {{ new Date(conversation.updated_at).toLocaleDateString('zh-CN') }}</small></span></button></nav><p v-if="!store.conversations.length" class="small muted empty-history">会话保存在本机，<br>从一个问题开始。</p><footer class="history-footer"><span>SIMBAD / ADS / Gaia</span><small>测量 · 文献 · 可追溯结果</small></footer></aside>
    <main class="chat-panel">
      <header class="chat-heading"><div><span class="eyebrow">RESEARCH NOTEBOOK</span><h1>{{ store.current?.title || '观测与文献，从这里开始' }}</h1></div><div v-if="store.current" class="conversation-actions"><button :disabled="store.running" aria-label="重命名会话" @click="title = store.current.title; titleEditing = true">改名</button><button :disabled="store.running" aria-label="删除会话" @click="confirmDelete=true">删除</button></div></header>
      <div v-if="store.error" class="global-error notice danger" role="alert"><p>{{ store.error }}</p><details><summary>错误详情</summary><code>{{ store.errorCode }}</code></details><button @click="store.recover">恢复会话 / 刷新状态</button><button v-if="draft.trim() && !store.disconnectedRequest" :disabled="store.running" title="会产生新的模型用量" @click="send">重新执行（新一轮）</button></div>
      <div v-if="store.disconnectedRequest" class="notice"><p>断线前的问题尚未确认。先恢复会话；若仍未显示，可用原请求编号重新核对，避免重复执行。</p><button @click="store.resendSameRequest">用原请求编号核对</button></div>
      <div class="chat-scroll" aria-live="polite">
        <div v-if="!store.turns.length && !store.pending" class="welcome"><div class="orbital" aria-hidden="true"><span>✳</span><i></i><b></b></div><p class="eyebrow">ASK. VERIFY. EXPLORE.</p><h2>把问题交给星空，<br><em>把依据留在手边。</em></h2><p>查询天体、核查文献、查看 Gaia 测量。<br>每轮结果独立保存，后续可以继续追问。</p><div class="example-list"><button v-for="example in examples" :key="example.label" @click="useExample(example.text)"><span>{{ example.label }}</span><span aria-hidden="true">↗</span></button></div><p class="small muted">以上为待发送的问题，点击仅填入输入框。</p></div>
        <article v-for="turn in store.turns" :key="turn.turn_id" class="turn" :class="{ 'selected-turn':store.selectedTurnId===turn.turn_id }"><div class="turn-label"><span class="eyebrow">第 {{ turn.revision }} 轮</span><time>{{ new Date(turn.received_at).toLocaleTimeString('zh-CN',{hour:'2-digit',minute:'2-digit'}) }}</time><span v-if="turn.turn_id!==newest" class="tag">历史记录</span></div><div class="user-message">{{ turn.message }}</div><div class="answer"><div class="answer-label"><span class="mini-star" aria-hidden="true">✳</span><b>AstroAgent</b><span v-if="turn.response" class="tag" :class="turn.response.status">{{ turn.response.status === 'success' ? '已完成' : turn.response.status === 'partial' ? '部分完成' : '查询未成功' }}</span></div><p v-if="turn.execution_status==='running'" class="processing">正在处理。刷新页面可恢复状态，不会自动重新执行。<button @click="store.recover">刷新状态</button></p><p v-if="turn.error" class="notice danger">{{ turn.error.message }}</p><p v-if="turn.response" class="answer-text">{{ turn.response.answer }}</p><p v-for="warning in turn.context?.warnings" :key="warning" class="notice">{{ warning }}</p><details v-if="turn.context?.included_turn_ids?.length" class="small"><summary>使用了 {{ turn.context.included_turn_ids.length }} 轮历史上下文</summary><p>历史数据保持原查询时间，不代表本轮重新查询。</p><code>{{ turn.context.included_turn_ids.join('\n') }}</code></details><div v-if="turn.response?.sources?.length" class="source-links"><template v-for="source in turn.response.sources" :key="source.url"><a v-if="safeLink(source.url)" :href="safeLink(source.url)!" target="_blank" rel="noopener noreferrer">{{ source.name }} ↗</a><span v-else>{{ source.url }}</span></template></div><button class="view-results" @click="store.selectedTurnId=turn.turn_id; store.panel='results'">核查本轮结果与导出 <span aria-hidden="true">→</span></button></div></article>
        <p v-if="store.pending" class="processing pending"><span class="status-dot"></span>正在处理，请稍候…</p>
        <p v-if="store.loading" class="small muted">正在读取本地记录…</p>
      </div>
      <form class="composer" @submit.prevent="send"><label class="sr-only" for="question">天文问题</label><textarea id="question" ref="input" v-model="draft" rows="3" maxlength="4000" placeholder="输入一个天文问题，或继续追问刚才的结果…" :disabled="store.running || !!store.disconnectedRequest" @keydown="keydown" @compositionstart="composing=true" @compositionend="composing=false"></textarea><div class="composer-bottom"><span>Enter 发送 · Shift + Enter 换行</span><button class="button-primary" :disabled="!draft.trim() || store.running || !!store.disconnectedRequest" type="submit">{{ store.running ? '处理中…' : '发送' }} <span aria-hidden="true">↑</span></button></div><p>模型回答需对照原始数据核查；位置候选源不等于星团成员。</p></form>
    </main>
    <ResultPanel :turn="store.selectedTurn" :historical="!!store.selectedTurn && store.selectedTurn.turn_id!==newest" />
    <div v-if="titleEditing || confirmDelete" class="modal-backdrop"><section class="modal" role="dialog" aria-modal="true" :aria-label="titleEditing ? '重命名会话' : '删除会话'" @keydown="dialogKey"><template v-if="titleEditing"><h2>重命名会话</h2><label for="title">会话名称</label><input id="title" v-model="title" maxlength="80" autofocus @keydown.enter="rename"><div class="modal-actions"><button @click="titleEditing=false">取消</button><button class="button-primary" :disabled="!title.trim()" @click="rename">保存</button></div></template><template v-else><h2>删除这个会话？</h2><p>将删除本机会话及其全部轮次和缓存预览。已经下载的文件不受影响。</p><div class="modal-actions"><button autofocus @click="confirmDelete=false">保留会话</button><button class="button-danger" @click="remove">确认删除</button></div></template></section></div>
  </div>
</template>
