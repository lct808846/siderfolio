<script setup lang="ts">
import WorkspaceHeader from '../components/WorkspaceHeader.vue'
import { onMounted, ref } from 'vue'
import { setupApi } from '../api/rag'
import type { SetupStatus } from '../types'

const state = ref<SetupStatus | null>(null), error = ref(''), busy = ref(false)
const checkedAt = ref('')
const dialog = ref<HTMLDialogElement | null>(null)
async function load(initialize = false) {
  if (busy.value) return
  busy.value = true; error.value = ''
  try {
    state.value = initialize ? await setupApi.initialize() : await setupApi.status()
    checkedAt.value = new Date().toLocaleString('zh-CN')
  }
  catch (e) {
    state.value = null; checkedAt.value = ''
    error.value = e instanceof Error ? e.message : '配置状态未确认，请核对服务端。'
  }
  finally { busy.value = false }
}
onMounted(() => { void load() })
</script>

<template>
  <div class="settings-workspace">
    <WorkspaceHeader title="首次配置与本机设置" />
    <main class="settings-main">
<p class="eyebrow">GET STARTED / 本机个人工作台</p><h1>连接数据，准备文献问答</h1><p class="muted">数据库、模型文件和密钥由服务端管理。此页面不保存密码，不自动下载模型，也不检查外部科研服务。</p>
      <div class="settings-status" aria-live="polite"><span class="tag" :class="{error:!!error}">{{ busy ? '正在读取本机状态' : !state ? '本机状态未确认' : state.ready ? '业务数据库已就绪' : '业务数据库尚未就绪' }}</span><small v-if="checkedAt">最近读取：{{ checkedAt }}</small></div>
      <p v-if="error" class="notice danger" role="alert">{{ error }}</p><p v-if="busy" role="status">正在读取配置或初始化，请稍候。</p>
      <section class="settings-card"><h2>1 · PostgreSQL 数据库</h2><p v-if="state" class="notice" :class="{danger:!state.ready}">{{ state.message }} <code>{{ state.code }}</code></p><p>在服务端环境设置 <code>ASTROAGENT_DATABASE_URL</code>，连接本机、独立且为空的 PostgreSQL 数据库，然后重启后端。连接示例仅说明格式：</p><pre>postgresql://astroagent:&lt;服务端密码&gt;@127.0.0.1:5432/astroagent</pre><p class="small muted">连接串不能放进 VITE_、浏览器存储、截图或版本仓库。pgvector 和 pg_trgm 需先在数据库服务器安装；初始化账号需有启用扩展及建表权限。</p><div class="project-actions"><button :disabled="busy" @click="load()">刷新本机状态</button><button v-if="state?.configured && !state.ready" :disabled="busy" class="button-primary" @click="dialog?.showModal()">核对后初始化空库</button></div><dl v-if="state?.ready" class="settings-facts"><dt>数据库</dt><dd>{{ state.database_version }} / schema {{ state.database_schema }}</dd><dt>向量扩展</dt><dd>{{ state.vector_version }}</dd><dt>业务数据预算</dt><dd>{{ state.database_used_bytes }} / {{ state.business_budget_bytes }} 字节</dd></dl><p class="small">旧 V0.9 SQLite 不会被自动打开或迁移；迁移到独立新库需按维护手册显式执行，旧备份保留。</p></section>
      <section class="settings-card"><h2>2 · 本地嵌入模型</h2><p>{{ !state ? '本机状态未确认，请先读取配置。' : state.embedding_configured ? '已填写本地模型配置；实际文件哈希、依赖和CPU推理在显式构建时核对。' : '尚未配置。仍可管理数据及使用词法检索；语义检索会显示降级。' }}</p><p class="small">模型：{{ state?.embedding_model || '未确认' }} · 目标维度 {{ state?.embedding_dimension ?? '未确认' }}。向量预算 {{ state?.vector_budget_bytes ?? '未确认' }} 字节。</p><p>先检查固定版本的模型来源、许可和下载体积，再用维护工具确认下载或准备离线文件。设置服务端的 <code>ASTROAGENT_RAG_MODEL_PATH</code> 与 <code>ASTROAGENT_RAG_MODEL_SHA256</code> 后重启。运行时只加载本地固定文件，不静默换模型。</p><a href="https://huggingface.co/sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2" target="_blank" rel="noopener noreferrer">查看候选模型来源与许可 ↗</a><p class="small muted">模型与向量各有预算；CPU子进程限120秒、3 GiB。扫描PDF仍不支持OCR，嵌入不能补回缺失文字。</p></section>
      <section class="settings-card"><h2>3 · 回答服务与文本发送</h2><p>{{ !state ? '回答服务配置状态未确认，请先读取本机状态。' : state.answering_configured ? '服务端已填写回答密钥；没有在此调用模型或验证连通性。' : '尚未填写回答密钥。检索和原文摘录仍可使用。' }}</p><p>服务：{{ state?.answering_provider || '未确认' }} · 模型：{{ state?.answering_model || '未确认' }}</p><p>仅在“知识问答”中看到本次问题、片段及所选历史，并确认后才发送。取消、上传、建索引和旧聊天都不会自动将文献交给回答模型。</p></section>
      <section class="settings-card"><h2>4 · 开始使用与保留数据</h2><ol><li>新建项目，上传文本型PDF或Markdown，核对解析状态和页行。</li><li>进入知识问答，显式构建本地索引；失败时查看状态，词法检索可单独使用。</li><li>输入问题，选择文档，核对证据及服务，确认生成，再逐条回查原文。</li><li>使用含原文的项目格式5包迁移单个项目；整库备份使用PostgreSQL维护工具。</li></ol><p>备份可能包含私人原文和问答，请保存在你控制的位置。恢复到全新数据库；卸载程序默认保留数据库、模型和备份。</p><RouterLink class="button-primary" to="/projects">打开项目工作区 →</RouterLink></section>
    </main>
    <dialog ref="dialog" class="project-dialog"><h2>在已配置的空数据库初始化？</h2><p>将创建 schema6 业务表、向量表并启用 pgvector / pg_trgm。不读取旧SQLite，不覆盖已有业务表，不下载模型。</p><p>请先确认这是你准备的独立空库，且初始化账号有建表和扩展权限。</p><div class="project-actions"><button @click="dialog?.close()">取消</button><button :disabled="busy" class="button-primary" @click="dialog?.close();load(true)">确认初始化空库</button></div></dialog>
  </div>
</template>
