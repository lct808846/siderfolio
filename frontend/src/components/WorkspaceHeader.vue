<script setup lang="ts">
import { computed, inject, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { identityUser } from '../identity-state'
import { useProjects } from '../stores/projects'

defineProps<{ title: string }>()
const route = useRoute(), router = useRouter()
const projectsStore = useProjects()
const createConversation = inject<() => Promise<string | undefined>>('astroagent.create-conversation')
function openNewConversation() {
  if (createConversation) void createConversation()
  else void router.push('/')
}
watch(() => route.params.projectId, projectId => {
  if (typeof projectId === 'string' && projectId) {
    projectsStore.setActiveProject(projectId)
  }
}, { immediate: true })
const projectPath = computed(() => typeof route.params.projectId === 'string' && route.params.projectId
  ? `/projects/${encodeURIComponent(route.params.projectId)}` : '')
const activeProjectPrefix = computed(() => {
  const id = (typeof route.params.projectId === 'string' && route.params.projectId && route.params.projectId !== projectsStore.defaultProjectId)
    ? route.params.projectId
    : projectsStore.activeCustomProjectId
  return id ? `/projects/${encodeURIComponent(id)}` : ''
})
const knowledgeNavTo = computed(() => activeProjectPrefix.value ? `${activeProjectPrefix.value}/knowledge` : '/knowledge')
const workflowsNavTo = computed(() => activeProjectPrefix.value ? `${activeProjectPrefix.value}/workflows` : '/workflows')
const projectSections = computed(() => [
  { label: '项目主页', path: projectPath.value },
  { label: '来源关联', path: `${projectPath.value}/overview` },
  { label: '科研流程', path: `${projectPath.value}/workflows` },
  { label: '计算任务', path: `${projectPath.value}/compute` },
  { label: '数据绘图', path: `/?mode=plot&plot_project=${encodeURIComponent(String(route.params.projectId || ''))}` },
  { label: '本地知识库', path: `${projectPath.value}/knowledge` },
  { label: '文献问答', path: `${projectPath.value}/rag` },
])
function current(path: string, descendants = false) {
  return route.path === path || (descendants && route.path.startsWith(`${path}/`))
}
</script>

<template>
  <header class="topbar workspace-header">
    <div class="workspace-header-main">
      <button class="brand brand-action" type="button" aria-label="AstroAgent：新建会话" data-tooltip="" @click="openNewConversation">
        <span class="brand-mark" aria-hidden="true">
          <svg viewBox="0 0 24 24" fill="none">
            <ellipse cx="12" cy="12" rx="9.5" ry="4.2" transform="rotate(-28 12 12)" stroke="currentColor" stroke-opacity="0.48" stroke-width="1.4" />
            <path d="M12 3.2L13.85 10.15L20.8 12L13.85 13.85L12 20.8L10.15 13.85L3.2 12L10.15 10.15L12 3.2Z" fill="currentColor" />
          </svg>
        </span>
        <b>AstroAgent</b>
        <span class="version">1.7</span>
      </button>
      <span class="workspace-title">{{ title }}</span>
      <nav class="workspace-global-nav" aria-label="全局导航">
        <RouterLink to="/" :aria-current="route.path === '/' || route.path.startsWith('/conversations/') || route.path === '/profile' ? 'page' : undefined">查询工作台</RouterLink>
        <RouterLink :to="knowledgeNavTo" :aria-current="route.path === '/knowledge' || route.path.startsWith('/knowledge/') || route.path === '/rag' || route.path.includes('/knowledge') || route.path.endsWith('/rag') ? 'page' : undefined">知识库与问答</RouterLink>
        <RouterLink :to="workflowsNavTo" :aria-current="route.path === '/workflows' || route.path.startsWith('/workflows/') || route.path.includes('/workflows') ? 'page' : undefined">科研流程</RouterLink>
        <RouterLink to="/local-assistant" :aria-current="route.path === '/local-assistant' ? 'page' : undefined">本地助手</RouterLink>
        <a v-if="identityUser?.admin && identityUser.mfa_verified" href="/openapi.json" target="_blank" rel="noopener noreferrer">接口定义 ↗</a>
      </nav>
    </div>
    <nav v-if="projectPath" class="workspace-project-nav" aria-label="当前项目导航">
      <span class="workspace-project-label">当前项目</span>
      <RouterLink
        v-for="section in projectSections" :key="section.path" :to="section.path"
        :aria-current="current(section.path, /\/(knowledge|workflows|compute)$/.test(section.path)) ? 'page' : undefined">
        {{ section.label }}
      </RouterLink>
    </nav>
  </header>
</template>
