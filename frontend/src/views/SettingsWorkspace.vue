<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import WorkspaceHeader from '../components/WorkspaceHeader.vue'
import AppearanceSettings from '../components/AppearanceSettings.vue'
import LocalAssistantSettings from '../components/LocalAssistantSettings.vue'
import ModelProvidersSettings from '../components/ModelProvidersSettings.vue'
import AccountWorkspace from './AccountWorkspace.vue'
import StatusNotice from '../components/StatusNotice.vue'
import SuccessToast from '../components/SuccessToast.vue'
import { api, ApiError } from '../api'
import { importProject } from '../api/projects'
import { useModels } from '../stores/models'
import { useProjects } from '../stores/projects'
import { useWorkbench } from '../stores/workbench'
import { identityUser } from '../identity-state'
import { setupApi } from '../api/rag'
import type { ArchivedConversation, SetupStatus } from '../types'

const route = useRoute(), router = useRouter(), models = useModels(), store = useWorkbench(), projectsStore = useProjects()
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
  { id: 'appearance', group: 'app', label: '外观与主题', description: '自定义配色主题、暗夜护眼模式、界面密度、字号与阅读排版。', keywords: '外观 主题 配色 暗黑 暗夜 深色 浅色 红光 护眼 圆角 密度 字体 字号 排版 毛玻璃 动效', icon: 'M12 3a9 9 0 1 0 0 18 1.5 1.5 0 0 0 1.5-1.5c0-.4-.15-.77-.4-1.05-.25-.28-.4-.65-.4-1.05a1.5 1.5 0 0 1 1.5-1.5H16a5 5 0 0 0 5-5c0-4.42-4.03-7.9-9-7.9ZM7.5 10.5h.01M10.5 7.5h.01M14.5 7.5h.01M17 10.5h.01' },
  { id: 'general', group: 'app', label: '概览', description: '查看当前工作环境与服务状态。', keywords: '常规 状态 环境 版本', icon: 'M3 3h7v7H3zM14 3h7v7h-7zM3 14h7v7H3zM14 14h7v7h-7z' },
  { id: 'models', group: 'app', label: '模型', description: '管理模型服务商，为工作台选择可用模型。', keywords: '远程 服务商 提供方 千问 deepseek qwen OpenAI API 密钥 默认', icon: 'm12 3 9 5v8l-9 5-9-5V8zM3 8l9 5 9-5M12 13v8' },
  { id: 'assistant', group: 'app', label: '本地助手', description: '设置本机小模型与会话自动命名。', keywords: '本地 模型 自动 标题 命名 摘要 Ollama', icon: 'M9 3h6M12 3v3M5 6h14v14H5zM8 11h1M15 11h1M9 16h6M2 10v6M22 10v6' },
  { id: 'storage', group: 'app', label: '检索与存储', description: '查看数据库与语义检索模型的准备情况。', keywords: '数据库 PostgreSQL 嵌入 向量 语义 检索 索引', icon: 'M20 6c0 2-3.6 3-8 3S4 8 4 6s3.6-3 8-3 8 1 8 3ZM4 6v6c0 2 3.6 3 8 3s8-1 8-3V6M4 12v6c0 2 3.6 3 8 3s8-1 8-3v-6' },
  { id: 'data', group: 'app', label: '数据管理', description: '管理已归档会话、科研项目空间与备份迁移包。', keywords: '备份 导入 导出 归档 会话 收纳 恢复 PDF 文献 迁移 项目', icon: 'M3 7V4h7l2 3h9v13H3zM8 12h8M8 16h5' },
] as const
type SectionId = typeof sections[number]['id']
const canManage = computed(() => !!identityUser.value?.admin && identityUser.value.mfa_verified)
const availableSections = computed(() => sections.filter(section => canManage.value || section.group === 'account' || section.id === 'appearance' || section.id === 'data'))
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
const databaseUsagePercent = computed(() => {
  if (!state.value?.business_budget_bytes || state.value.database_used_bytes == null) return 0
  return Math.min(100, Math.round((state.value.database_used_bytes / state.value.business_budget_bytes) * 100))
})
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

const archivedLoading = ref(false), archivedBusy = ref(false), archivedError = ref(''), archivedMessage = ref('')
const deletingArchived = ref<ArchivedConversation | null>(null)
const deleteArchiveDialog = ref<HTMLDialogElement | null>(null)
async function loadArchived() {
  if (archivedLoading.value) return
  archivedLoading.value = true; archivedError.value = ''
  try { await store.refreshArchived() }
  catch (e) { archivedError.value = e instanceof Error ? e.message : '暂时无法读取已归档会话。' }
  finally { archivedLoading.value = false }
}
async function restoreArchived(item: ArchivedConversation) {
  if (archivedBusy.value) return
  archivedBusy.value = true; archivedError.value = ''; archivedMessage.value = ''
  try {
    await store.unarchiveConversation(item.id)
    archivedMessage.value = `已恢复会话「${item.title}」至左侧会话列表。`
  } catch (e) { archivedError.value = e instanceof Error ? e.message : '取消归档失败，请稍后重试。' }
  finally { archivedBusy.value = false }
}
async function openDeleteArchived(item: ArchivedConversation) {
  if (archivedBusy.value) return
  deletingArchived.value = item
  await nextTick()
  deleteArchiveDialog.value?.showModal()
}
async function confirmDeleteArchived() {
  const item = deletingArchived.value
  if (!item || archivedBusy.value) return
  archivedBusy.value = true; archivedError.value = ''; archivedMessage.value = ''
  try {
    await api.delete(item.id)
    store.archived = store.archived.filter(value => value.id !== item.id)
    deleteArchiveDialog.value?.close()
    deletingArchived.value = null
    archivedMessage.value = `已永久删除已归档会话「${item.title}」。`
  } catch (e) { archivedError.value = e instanceof Error ? e.message : '删除已归档会话失败。' }
  finally { archivedBusy.value = false }
}
async function handleImportZip(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file || archivedBusy.value) return
  archivedBusy.value = true; archivedError.value = ''; archivedMessage.value = ''
  try {
    const result = await importProject(file)
    await projectsStore.load(true)
    archivedMessage.value = `已从备份包恢复为独立科研项目「${result.project.name}」。`
    await router.push(`/projects/${result.project.id}`)
  } catch (e) { archivedError.value = e instanceof Error ? e.message : '导入项目备份包失败。' }
  finally { archivedBusy.value = false }
}
watch(() => active.value.id, id => { if (id === 'data') void loadArchived() }, { immediate: true })
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
          <header class="settings-detail-heading settings-detail-hero">
            <div class="settings-heading-icon" aria-hidden="true">
              <svg viewBox="0 0 24 24"><path :d="active.icon" /></svg>
            </div>
            <div>
              <h2>{{ active.label }}</h2>
              <p>{{ active.description }}</p>
            </div>
          </header>
          <AccountWorkspace v-if="accountOpened" v-show="active.id === 'security' || active.id === 'account'" :mode="active.id === 'account' ? 'account' : 'security'" />
          <div v-show="active.id === 'appearance'">
            <AppearanceSettings />
          </div>
          <template v-if="canManage">
          <StatusNotice v-if="error && active.id !== 'security' && active.id !== 'account' && active.id !== 'appearance' && active.id !== 'data'" class="settings-load-error" title="本机状态读取失败" :message="error" />
          <p v-if="busy && active.id !== 'security' && active.id !== 'account' && active.id !== 'appearance' && active.id !== 'data'" class="settings-loading" role="status">正在读取本机状态…</p>

          <div v-show="active.id === 'general'">
            <div class="ui-kpi-grid" style="margin-bottom: 18px;">
              <div class="ui-kpi-card">
                <span class="ui-kpi-label">运行环境</span>
                <span class="ui-kpi-value">{{ !state ? '未确认' : state.deployment_mode === 'container' ? '容器部署' : '本机部署' }}</span>
                <span class="ui-kpi-sub">{{ checkedAt ? `${checkedAt} 核对` : '自动读取中' }}</span>
              </div>
              <div class="ui-kpi-card">
                <span class="ui-kpi-label">业务数据库</span>
                <span class="ui-kpi-value">{{ databaseStatus }}</span>
                <span class="ui-kpi-sub">PostgreSQL / pgvector</span>
              </div>
              <div class="ui-kpi-card">
                <span class="ui-kpi-label">回答服务</span>
                <span class="ui-kpi-value">{{ answeringStatus }}</span>
                <span class="ui-kpi-sub">对话与文献问答模型</span>
              </div>
              <div class="ui-kpi-card">
                <span class="ui-kpi-label">语义检索</span>
                <span class="ui-kpi-value">{{ embeddingStatus }}</span>
                <span class="ui-kpi-sub">本地多语言嵌入模型</span>
              </div>
            </div>
            <section class="settings-group" aria-labelledby="settings-services">
              <div class="settings-group-head">
                <h3 id="settings-services">核心服务就绪度</h3>
                <span class="ui-pill" :class="!state ? 'ui-pill-warning' : state.ready ? 'ui-pill-success' : 'ui-pill-danger'">
                  <span class="ui-dot" aria-hidden="true" />
                  {{ !state ? '本机状态未确认' : state.ready ? '业务数据库已就绪' : '数据库尚未就绪' }}
                </span>
              </div>
              <div class="settings-row"><div><h4>回答服务</h4><p>工作台对话与文献问答使用的远程或本地大模型</p></div><span class="ui-pill" :class="state?.answering_configured ? 'ui-pill-success' : 'ui-pill-warning'"><span class="ui-dot" aria-hidden="true" />{{ answeringStatus }}</span></div>
              <div class="settings-row"><div><h4>业务数据库</h4><p>会话、项目与科研记录持久化存储（PostgreSQL / pgvector）</p></div><span class="ui-pill" :class="state?.ready ? 'ui-pill-success' : 'ui-pill-warning'"><span class="ui-dot" aria-hidden="true" />{{ databaseStatus }}</span></div>
              <div class="settings-row"><div><h4>语义检索</h4><p>本地多语言嵌入模型配置状态</p></div><span class="ui-pill" :class="state?.embedding_configured ? 'ui-pill-success' : 'ui-pill-warning'"><span class="ui-dot" aria-hidden="true" />{{ embeddingStatus }}</span></div>
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
              <div class="settings-group-head">
                <h3>数据库存储</h3>
                <span class="ui-pill" :class="state?.ready ? 'ui-pill-success' : 'ui-pill-warning'"><span class="ui-dot" aria-hidden="true" />{{ databaseStatus }}</span>
              </div>
              <p class="small muted">{{ state?.message || '尚未确认数据库状态。' }}</p>
              <template v-if="state?.ready">
                <div style="display: grid; gap: 6px; margin: 14px 0 4px;">
                  <div class="ui-card-head"><span class="small muted">业务数据占用</span><span class="small mono">{{ bytes(state.database_used_bytes) }} / {{ bytes(state.business_budget_bytes) }}（{{ databaseUsagePercent }}%）</span></div>
                  <div class="ui-progress" role="progressbar" :aria-valuenow="databaseUsagePercent" aria-valuemin="0" aria-valuemax="100"><div class="ui-progress-fill" :style="{ width: `${databaseUsagePercent}%` }" /></div>
                </div>
                <dl class="ui-param-grid">
                  <div class="ui-param-tile"><dt>PostgreSQL 版本</dt><dd>{{ state.database_version }}</dd></div>
                  <div class="ui-param-tile"><dt>Schema 版本</dt><dd>schema {{ state.database_schema }}</dd></div>
                  <div class="ui-param-tile"><dt>pgvector 扩展</dt><dd>{{ state.vector_version }}</dd></div>
                </dl>
              </template>
              <p v-if="state && !state.ready" class="settings-footnote">数据库尚未就绪，请由管理员按部署维护手册检查连接与账号数据空间。此页不执行数据库初始化。</p>
            </section>
            <section class="settings-group">
              <div class="settings-group-head">
                <h3>语义检索模型</h3>
                <span class="ui-pill" :class="state?.embedding_configured ? 'ui-pill-success' : 'ui-pill-warning'"><span class="ui-dot" aria-hidden="true" />{{ embeddingStatus }}</span>
              </div>
              <p class="small muted">{{ !state ? '配置状态未确认' : state.embedding_configured ? '已配置；文件与推理能力在构建索引时核对' : '未配置时仍可使用词法检索，语义检索显示降级' }}</p>
              <dl class="ui-param-grid">
                <div class="ui-param-tile"><dt>嵌入模型</dt><dd>{{ state?.embedding_model || '未确认' }}</dd></div>
                <div class="ui-param-tile"><dt>向量维度</dt><dd>{{ state?.embedding_dimension ?? '未确认' }}</dd></div>
                <div class="ui-param-tile"><dt>向量存储预算</dt><dd>{{ bytes(state?.vector_budget_bytes) }}</dd></div>
              </dl>
              <p class="settings-footnote">扫描 PDF 暂不支持 OCR；嵌入模型无法补回缺失的原文。</p>
            </section>
            <details class="settings-maintenance"><summary>部署与维护说明</summary><p v-if="state?.deployment_mode === 'container'">数据库与模型存储由容器部署配置管理，原生环境中的数据不会自动迁入。</p><p>连接由服务端的 <code>ASTROAGENT_DATABASE_URL</code> 管理，需提前安装 pgvector 和 pg_trgm。连接串与密钥不能放进浏览器配置或版本仓库。</p><p>本地模型使用固定文件及哈希，通过 <code>ASTROAGENT_RAG_MODEL_PATH</code> 和 <code>ASTROAGENT_RAG_MODEL_SHA256</code> 配置。文件来源、许可及下载体积需先核对；运行时不自动下载或更换模型。CPU 子进程限制为 120 秒、3 GiB。</p><a href="https://huggingface.co/sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2" target="_blank" rel="noopener noreferrer">查看嵌入模型来源与许可 ↗</a><p>旧 V0.9 SQLite 不会被自动打开或迁移；迁移需按维护手册显式执行，保留原备份。</p></details>
          </div>
          </template>

          <div v-show="active.id === 'data'">
            <SuccessToast v-model:message="archivedMessage" />
            <StatusNotice v-if="archivedError" class="settings-load-error" title="数据管理操作未完成" :message="archivedError" />
            <section class="settings-group" aria-labelledby="settings-archived-chats">
              <div class="settings-group-head">
                <h3 id="settings-archived-chats">已归档会话</h3>
                <span class="ui-pill ui-pill-neutral">{{ store.archived.length }} 个</span>
              </div>
              <p v-if="archivedLoading" class="settings-loading" role="status">正在读取已归档会话…</p>
              <div v-else-if="store.archived.length" class="settings-archive-list">
                <div v-for="item in store.archived" :key="item.id" class="settings-row">
                  <div>
                    <h4>{{ item.title }}</h4>
                    <div class="ui-pill-list" style="margin-top: 6px;">
                      <span class="ui-pill ui-pill-accent">{{ item.revision }} 轮对话</span>
                      <span class="ui-pill ui-pill-neutral">归档于 {{ new Date(item.archived_at).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai' }) }}</span>
                    </div>
                  </div>
                  <div class="settings-archive-actions">
                    <RouterLink :to="`/conversations/${item.id}`" class="settings-action-link">查看</RouterLink>
                    <button type="button" :disabled="archivedBusy" @click="restoreArchived(item)">取消归档</button>
                    <button type="button" class="button-danger" :disabled="archivedBusy" @click="openDeleteArchived(item)">删除</button>
                  </div>
                </div>
              </div>
              <div v-else class="ui-empty-card" style="margin-top: 12px;">
                <div class="ui-empty-icon" aria-hidden="true"><svg viewBox="0 0 24 24"><path d="M3 7V4h7l2 3h9v13H3zM8 12h8M8 16h5" /></svg></div>
                <h3>暂无已归档会话</h3>
                <p>可在左侧会话列表的菜单中将不活跃的会话归档收纳，随时在此恢复。</p>
              </div>
            </section>
            <section class="settings-group" aria-labelledby="settings-projects-backup">
              <h3 id="settings-projects-backup">科研项目与备份迁移</h3>
              <div class="settings-row">
                <div><h4>科研项目空间</h4><p>按课题组织会话、知识库、文献问答、科研流程与命名快照</p></div>
                <RouterLink to="/projects" class="settings-action-link">管理科研项目 ↗</RouterLink>
              </div>
              <div class="settings-row">
                <div><h4>导入项目备份包 (ZIP)</h4><p>从本地 ZIP 备份恢复为独立科研项目（上限 32 MiB，不覆盖现有数据）</p></div>
                <label class="settings-upload-btn" :class="{ disabled: archivedBusy }">
                  <span>{{ archivedBusy ? '正在导入…' : '选择 ZIP 导入' }}</span>
                  <input type="file" class="sr-only" accept=".zip,application/zip" :disabled="archivedBusy" @change="handleImportZip" />
                </label>
              </div>
            </section>
            <section v-if="canManage" class="settings-group">
              <h3>服务器备份与保留</h3>
              <p>整库备份通过 PostgreSQL 维护工具完成；恢复时使用全新数据库。卸载程序默认保留数据库、模型和备份。</p>
              <p class="settings-footnote">备份可能包含私人原文和问答，请保存在你控制的位置。此页面不会自动迁移或清理数据。</p>
            </section>
          </div>
        </div>
      </div>
    </main>
    <dialog ref="deleteArchiveDialog" class="project-dialog account-preferences-dialog" aria-labelledby="delete-archived-title" @close="deletingArchived = null" @cancel="archivedBusy && $event.preventDefault()">
      <header class="account-dialog-heading">
        <h2 id="delete-archived-title">永久删除已归档会话？</h2>
        <button type="button" class="account-dialog-close" aria-label="关闭" :disabled="archivedBusy" @click="deleteArchiveDialog?.close()">×</button>
      </header>
      <p>将删除「{{ deletingArchived?.title }}」及全部对话轮次，无法恢复。已经保存的项目快照与下载文件不受影响。</p>
      <div class="project-actions">
        <button type="button" :disabled="archivedBusy" @click="deleteArchiveDialog?.close()">取消</button>
        <button type="button" class="button-danger" :disabled="archivedBusy" @click="confirmDeleteArchived">{{ archivedBusy ? '正在删除…' : '确认永久删除' }}</button>
      </div>
    </dialog>
  </div>
</template>
