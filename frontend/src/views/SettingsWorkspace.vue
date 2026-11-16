<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import WorkspaceHeader from '../components/WorkspaceHeader.vue'
import LocalAssistantSettings from '../components/LocalAssistantSettings.vue'
import ModelProvidersSettings from '../components/ModelProvidersSettings.vue'
import AccountWorkspace from './AccountWorkspace.vue'
import StatusNotice from '../components/StatusNotice.vue'
import { ApiError } from '../api'
import { useModels } from '../stores/models'
import { identityUser } from '../identity-state'
import { setupApi } from '../api/rag'
import type { SetupStatus } from '../types'

const route = useRoute(), router = useRouter(), models = useModels()
const displayName = computed(() => identityUser.value?.username?.trim() || identityUser.value?.email?.split('@')[0] || '科研用户')
const avatarText = computed(() => (displayName.value.slice(0, 2) || 'AA').toUpperCase())
const failedAvatarUrl = ref('')
const rawAvatarUrl = computed(() => identityUser.value?.avatar_url || '')
const avatarUrl = computed(() => (rawAvatarUrl.value && rawAvatarUrl.value !== failedAvatarUrl.value ? rawAvatarUrl.value : ''))
function backToApp() {
  const back = typeof window.history.state?.back === 'string' ? window.history.state.back : ''
  if (back && back.startsWith('/') && !back.startsWith('/settings') && !back.startsWith('/account')) {
    router.back()
  } else {
    void router.push('/')
  }
}
const sections = [
  { id: 'security', group: 'account', label: '账户安全与登录', description: '管理你的登录方式、多因素验证与活动会话。', keywords: '登录 密码 身份 验证器 二维码 双因素 TOTP MFA 恢复码 安全 建议 会话 设备 退出', icon: 'M12 3 4 6v6c0 5 8 9 8 9s8-4 8-9V6zM9 12l2 2 4-4' },
  { id: 'account', group: 'account', label: '账户', description: '查看并管理你的个人资料与账户详情。', keywords: '账户 账号 详情 用户名 邮箱 角色 资料', icon: 'M12 12a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7ZM5.5 19.2a7 7 0 0 1 13 0M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18Z' },
  { id: 'general', group: 'app', label: '概览', description: '查看当前工作环境与服务状态。', keywords: '常规 状态 环境 版本', icon: 'M3 3h7v7H3zM14 3h7v7h-7zM3 14h7v7H3zM14 14h7v7h-7z' },
  { id: 'models', group: 'app', label: '模型', description: '管理模型服务商，为工作台选择可用模型。', keywords: '远程 服务商 提供方 千问 deepseek qwen OpenAI API 密钥 默认', icon: 'm12 3 9 5v8l-9 5-9-5V8zM3 8l9 5 9-5M12 13v8' },
  { id: 'assistant', group: 'app', label: '本地助手', description: '设置本机小模型与会话自动命名。', keywords: '本地 模型 自动 标题 命名 摘要 Ollama', icon: 'M9 3h6M12 3v3M5 6h14v14H5zM8 11h1M15 11h1M9 16h6M2 10v6M22 10v6' },
  { id: 'storage', group: 'app', label: '检索与存储', description: '查看数据库与语义检索模型的准备情况。', keywords: '数据库 PostgreSQL 嵌入 向量 语义 检索 索引', icon: 'M20 6c0 2-3.6 3-8 3S4 8 4 6s3.6-3 8-3 8 1 8 3ZM4 6v6c0 2 3.6 3 8 3s8-1 8-3V6M4 12v6c0 2 3.6 3 8 3s8-1 8-3v-6' },
  { id: 'data', group: 'app', label: '数据管理', description: '组织项目与文献，保留可回查的科研记录。', keywords: '备份 导入 导出 归档 PDF 文献 迁移', icon: 'M3 7V4h7l2 3h9v13H3zM8 12h8M8 16h5' },
] as const
type SectionId = typeof sections[number]['id']
const canManage = computed(() => !!identityUser.value?.admin && identityUser.value.mfa_verified)
const availableSections = computed(() => sections.filter(section => canManage.value || section.group === 'account'))
const active = computed(() => availableSections.value.find(section => section.id === (route.path === '/account' ? 'account' : route.query.section))
  || availableSections.value[0] || sections[0])
const isAccountGroup = (id: SectionId) => id === 'security' || id === 'account'
const accountOpened = ref(isAccountGroup(active.value.id))
watch(() => active.value.id, id => { if (isAccountGroup(id)) accountOpened.value = true })
const search = ref(''), content = ref<HTMLElement | null>(null)
const filteredSections = computed(() => {
  const words = search.value.trim().toLocaleLowerCase().split(/\s+/)
  return availableSections.value.filter(section => words.every(word => `${section.label} ${section.keywords}`.toLocaleLowerCase().includes(word)))
})
const accountNavSections = computed(() => filteredSections.value.filter(section => section.group === 'account'))
const appNavSections = computed(() => filteredSections.value.filter(section => section.group === 'app'))
function selectSection(id: SectionId) {
  if (active.value.id !== id) void router.replace({ path: '/settings', query: id === 'security' ? {} : { section: id } })
}
watch(() => active.value.id, () => { if (content.value) content.value.scrollTop = 0 })
const state = ref<SetupStatus | null>(null), error = ref(''), busy = ref(false), checkedAt = ref('')
const databaseStatus = computed(() => !state.value ? '未确认' : state.value.ready ? '已就绪' : '尚未就绪')
const embeddingStatus = computed(() => !state.value ? '未确认' : state.value.embedding_configured ? '已配置' : '未配置')
const answeringStatus = computed(() => !state.value ? '未确认' : state.value.answering_configured ? '已配置' : '未配置')
function bytes(value?: number | null) {
  if (value == null) return '未确认'
  if (value < 1024) return `${value} B`
  const unit = value < 1024 ** 2 ? 'KiB' : value < 1024 ** 3 ? 'MiB' : 'GiB'
  const size = value / 1024 ** (unit === 'KiB' ? 1 : unit === 'MiB' ? 2 : 3)
  return `${size.toLocaleString('zh-CN', { maximumFractionDigits: 1 })} ${unit}`
}
async function load() {
  if (busy.value) return
  busy.value = true; error.value = ''
  try {
    state.value = await setupApi.status()
    checkedAt.value = new Date().toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai' })
  } catch (e) {
    state.value = null; checkedAt.value = ''
    error.value = e instanceof ApiError && e.code === 'conversation_storage_unavailable'
      ? '暂时无法读取数据库与模型状态，请重试；若仍失败，请联系管理员检查服务。'
      : e instanceof ApiError && e.code === 'connection_lost'
        ? '暂时无法连接服务，请检查连接后重试。'
        : e instanceof Error ? e.message : '暂时无法读取配置状态，请稍后重试。'
  } finally { busy.value = false }
}
watch(canManage, allowed => { if (allowed) { void load(); void models.load() } }, { immediate: true })
</script>

<template>
  <div class="workspace-panes primary-workspace settings-workspace">
    <WorkspaceHeader title="本机设置" />
    <main class="settings-main settings-center">
      <aside class="settings-navigation" aria-label="设置导航">
        <button type="button" class="settings-back-btn" @click="backToApp">
          <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M19 12H5m6-6-6 6 6 6" /></svg>
          <span>返回应用</span>
        </button>
        <h1 class="sr-only">设置</h1>
        <label class="settings-search"><svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="10.5" cy="10.5" r="6.5" /><path d="m16 16 4 4" /></svg><input v-model="search" type="search" aria-label="搜索设置" placeholder="搜索设置项…" /></label>
        <div class="settings-nav-scroll">
          <template v-if="!search.trim()">
            <span class="settings-nav-label">个人资料</span>
            <RouterLink to="/profile" class="settings-profile-entry">
              <span class="settings-profile-avatar" aria-hidden="true">
                <img v-if="avatarUrl" :src="avatarUrl" alt="" class="settings-profile-avatar-img" @error="failedAvatarUrl = avatarUrl" />
                <template v-else>{{ avatarText }}</template>
              </span>
              <span class="settings-profile-name">{{ displayName }}</span>
              <span class="settings-link-arrow" aria-hidden="true">↗</span>
            </RouterLink>
          </template>
          <template v-if="accountNavSections.length">
            <span class="settings-nav-label" :class="{ 'settings-nav-label-spaced': !search.trim() }">账户</span>
            <nav aria-label="账户设置">
              <button v-for="section in accountNavSections" :key="section.id" type="button" class="settings-nav-item" :aria-current="active.id === section.id ? 'page' : undefined" data-tooltip="" @click="selectSection(section.id)">
                <svg viewBox="0 0 24 24" aria-hidden="true"><path :d="section.icon" /></svg><span>{{ section.label }}</span>
              </button>
            </nav>
          </template>
          <template v-if="appNavSections.length">
            <span class="settings-nav-label" :class="{ 'settings-nav-label-spaced': accountNavSections.length > 0 }">工作台</span>
            <nav aria-label="工作台设置">
              <button v-for="section in appNavSections" :key="section.id" type="button" class="settings-nav-item" :aria-current="active.id === section.id ? 'page' : undefined" data-tooltip="" @click="selectSection(section.id)">
                <svg viewBox="0 0 24 24" aria-hidden="true"><path :d="section.icon" /></svg><span>{{ section.label }}</span>
              </button>
            </nav>
          </template>
          <p v-if="!filteredSections.length" class="settings-search-empty" role="status">没有匹配的设置，试试“密码”“验证器”“模型”或“存储”。</p>
        </div>
        <div v-if="identityUser?.admin && identityUser.mfa_verified" class="settings-nav-footer">
          <RouterLink to="/admin" class="settings-admin-entry">
            <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3 4 6v6c0 5 8 9 8 9s8-4 8-9V6z" /></svg>
            <span>管理员控制台</span>
            <span class="settings-link-arrow" aria-hidden="true">↗</span>
          </RouterLink>
        </div>
      </aside>

      <div ref="content" class="settings-detail" :aria-busy="busy">
        <div class="settings-detail-reading">
          <header class="settings-detail-heading"><h2>{{ active.label }}</h2><p>{{ active.description }}</p></header>
          <AccountWorkspace v-if="accountOpened" v-show="active.id === 'security' || active.id === 'account'" :mode="active.id === 'account' ? 'account' : 'security'" />
          <template v-if="canManage">
          <StatusNotice v-if="error && active.id !== 'security' && active.id !== 'account'" class="settings-load-error" title="本机状态读取失败" :message="error" />
          <p v-if="busy && active.id !== 'security' && active.id !== 'account'" class="settings-loading" role="status">正在读取本机状态…</p>

          <div v-show="active.id === 'general'">
            <section class="settings-group" aria-labelledby="settings-environment">
              <div class="settings-group-head">
                <h3 id="settings-environment">工作环境</h3>
                <span class="tag" :class="!state ? 'partial' : state.ready ? '' : 'error'">{{ !state ? '本机状态未确认' : state.ready ? '业务数据库已就绪' : '数据库尚未就绪' }}</span>
              </div>
              <div class="settings-row"><div><h4>部署方式</h4><p>当前工作台连接的运行环境</p></div><span class="settings-value-pill">{{ !state ? '未确认' : state.deployment_mode === 'container' ? '容器部署' : '本机部署' }}</span></div>
              <div class="settings-row"><div><h4>配置状态</h4><p>{{ checkedAt ? `最近读取：${checkedAt}（北京时间）` : '正在读取数据库与模型配置状态' }}</p></div><span class="settings-value-pill">{{ state?.ready ? '正常' : '待确认' }}</span></div>
            </section>
            <section class="settings-group" aria-labelledby="settings-services">
              <h3 id="settings-services">核心服务就绪度</h3>
              <div class="settings-row"><div><h4>回答服务</h4><p>工作台对话与文献问答使用的远程或本地大模型</p></div><span class="tag" :class="state?.answering_configured ? '' : 'partial'">{{ answeringStatus }}</span></div>
              <div class="settings-row"><div><h4>业务数据库</h4><p>会话、项目与科研记录持久化存储（PostgreSQL / pgvector）</p></div><span class="tag" :class="state?.ready ? '' : 'partial'">{{ databaseStatus }}</span></div>
              <div class="settings-row"><div><h4>语义检索</h4><p>本地多语言嵌入模型配置状态</p></div><span class="tag" :class="state?.embedding_configured ? '' : 'partial'">{{ embeddingStatus }}</span></div>
              <p class="settings-footnote">配置状态不代表已通过外部服务连通性或回答质量验收；详细参数可在左侧对应分类中查看。</p>
            </section>
          </div>

          <div v-show="active.id === 'models'">
            <ModelProvidersSettings @changed="load()" />
            <section class="settings-group"><h3>文本与文献发送</h3><p>每个会话可在输入区切换模型，保留已有上下文。文献问答会先展示本次问题、引用片段及所选历史，确认后再发送给所选服务商。</p><p class="settings-footnote">上传文档、构建索引和取消预览不会自动发送文献。打开模型设置不会调用回答模型。</p></section>
          </div>

          <div v-show="active.id === 'assistant'" class="settings-assistant-section"><LocalAssistantSettings /></div>

          <div v-show="active.id === 'storage'">
            <section class="settings-group">
              <h3>数据库</h3>
              <div class="settings-row"><div><h4>PostgreSQL</h4><p>{{ state?.message || '尚未确认数据库状态。' }}</p></div><span class="tag">{{ databaseStatus }}</span></div>
              <template v-if="state?.ready"><div class="settings-row"><div><h4>数据库版本</h4></div><span>{{ state.database_version }} / schema {{ state.database_schema }}</span></div><div class="settings-row"><div><h4>向量扩展</h4></div><span>{{ state.vector_version }}</span></div><div class="settings-row"><div><h4>业务数据用量 / 预算</h4></div><span>{{ bytes(state.database_used_bytes) }} / {{ bytes(state.business_budget_bytes) }}</span></div></template>
              <p v-if="state && !state.ready" class="settings-footnote">数据库尚未就绪，请由管理员按部署维护手册检查连接与账号数据空间。此页不执行数据库初始化。</p>
            </section>
            <section class="settings-group">
              <h3>语义检索</h3>
              <div class="settings-row"><div><h4>本地嵌入模型</h4><p>{{ !state ? '配置状态未确认' : state.embedding_configured ? '已配置；文件与推理能力在构建索引时核对' : '未配置时仍可使用词法检索，语义检索显示降级' }}</p></div><span class="tag">{{ embeddingStatus }}</span></div>
              <div class="settings-row"><div><h4>模型</h4></div><span>{{ state?.embedding_model || '未确认' }}</span></div>
              <div class="settings-row"><div><h4>向量维度</h4></div><span>{{ state?.embedding_dimension ?? '未确认' }}</span></div>
              <div class="settings-row"><div><h4>向量存储预算</h4></div><span>{{ bytes(state?.vector_budget_bytes) }}</span></div>
              <p class="settings-footnote">扫描 PDF 暂不支持 OCR；嵌入模型无法补回缺失的原文。</p>
            </section>
            <details class="settings-maintenance"><summary>部署与维护说明</summary><p v-if="state?.deployment_mode === 'container'">数据库与模型存储由容器部署配置管理，原生环境中的数据不会自动迁入。</p><p>连接由服务端的 <code>ASTROAGENT_DATABASE_URL</code> 管理，需提前安装 pgvector 和 pg_trgm。连接串与密钥不能放进浏览器配置或版本仓库。</p><p>本地模型使用固定文件及哈希，通过 <code>ASTROAGENT_RAG_MODEL_PATH</code> 和 <code>ASTROAGENT_RAG_MODEL_SHA256</code> 配置。文件来源、许可及下载体积需先核对；运行时不自动下载或更换模型。CPU 子进程限制为 120 秒、3 GiB。</p><a href="https://huggingface.co/sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2" target="_blank" rel="noopener noreferrer">查看嵌入模型来源与许可 ↗</a><p>旧 V0.9 SQLite 不会被自动打开或迁移；迁移需按维护手册显式执行，保留原备份。</p></details>
          </div>

          <div v-show="active.id === 'data'">
            <section class="settings-group">
              <h3>科研记录与项目归档</h3>
              <div class="settings-row"><div><h4>项目归档与格式 5 迁移包</h4><p>在项目工作区组织会话、保存快照，或导出含原文的格式 5 归档包迁移单个项目</p></div><RouterLink to="/projects" class="settings-action-link">打开项目归档 ↗</RouterLink></div>
            </section>
            <section class="settings-group"><h3>文献问答流程</h3><ol class="settings-workflow"><li>在项目中上传文本型 PDF 或 Markdown，核对解析状态和原文页行。</li><li>进入文献问答，手动构建本地索引；也可单独使用词法检索。</li><li>选择文档、输入问题，核对证据和服务后确认生成，并逐条回查原文。</li></ol></section>
            <section class="settings-group"><h3>备份与保留</h3><p>整库备份通过 PostgreSQL 维护工具完成；恢复时使用全新数据库。卸载程序默认保留数据库、模型和备份。</p><p class="settings-footnote">备份可能包含私人原文和问答，请保存在你控制的位置。此页面不会自动迁移或清理数据。</p></section>
          </div>
          </template>
        </div>
      </div>
    </main>
  </div>
</template>
