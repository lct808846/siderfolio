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
const projectSections = computed(() => {
  const encodedId = encodeURIComponent(String(route.params.projectId || ''))
  return [
    { label: '项目对话', path: `/?project=${encodedId}` },
    { label: '指令与快照', path: `/?project=${encodedId}&manage=context` },
    { label: '来源关联', path: `${projectPath.value}/overview` },
    { label: '科研流程', path: `${projectPath.value}/workflows` },
    { label: 'N 体记录', path: `/?project=${encodedId}&result=compute` },
    { label: '本地知识库', path: `${projectPath.value}/knowledge` },
    { label: '文献问答', path: `${projectPath.value}/rag` },
  ]
})
const WORKBENCH_RETURN_KEY = 'astroagent.last_workbench_path.v1'
function readLastWorkbenchPath() {
  try {
    const value = sessionStorage.getItem(WORKBENCH_RETURN_KEY)
    if (value && (value === '/' || value.startsWith('/?') || value.startsWith('/conversations/'))) {
      return value
    }
  } catch { /* Ignore storage unavailability. */ }
  return '/'
}
const lastWorkbenchPath = computed(() => {
  void route.fullPath
  return readLastWorkbenchPath()
})
watch(() => route.fullPath, fullPath => {
  if (route.path === '/' || route.path.startsWith('/conversations/')) {
    try { sessionStorage.setItem(WORKBENCH_RETURN_KEY, fullPath) } catch { /* Ignore storage unavailability. */ }
  }
}, { immediate: true })
const isWorkbenchRoute = computed(() => route.path === '/' || route.path.startsWith('/conversations/') || route.path === '/profile')
const isLiteratureRoute = computed(() => route.path === '/literature' || route.path.startsWith('/literature/'))
const isSettingsRoute = computed(() => route.path === '/settings' || route.path === '/account' || route.path.startsWith('/admin'))
const workbenchTarget = computed(() => (isWorkbenchRoute.value ? '/' : lastWorkbenchPath.value))
function current(path: string, descendants = false) {
  return route.path === path || (descendants && route.path.startsWith(`${path}/`))
}
</script>

<template>
  <header class="topbar workspace-header">
    <div class="workspace-header-main">
      <button class="brand brand-action" type="button" aria-label="Siderfolio：新建会话" data-tooltip="" @click="openNewConversation">
        <span class="brand-mark" aria-hidden="true">
          <svg viewBox="0 0 24 24" fill="none">
            <ellipse cx="12" cy="12" rx="9.5" ry="4.2" transform="rotate(-28 12 12)" stroke="currentColor" stroke-opacity="0.48" stroke-width="1.4" />
            <path d="M12 3.2L13.85 10.15L20.8 12L13.85 13.85L12 20.8L10.15 13.85L3.2 12L10.15 10.15L12 3.2Z" fill="currentColor" />
          </svg>
        </span>
        <b>Siderfolio</b>
        <span class="version">2.2</span>
      </button>
      <span class="workspace-title">{{ title }}</span>
      <nav class="workspace-global-nav" aria-label="全局导航">
        <RouterLink :to="workbenchTarget" :aria-current="isWorkbenchRoute ? 'page' : undefined">查询工作台</RouterLink>
        <RouterLink to="/literature" :aria-current="isLiteratureRoute ? 'page' : undefined">文献管理</RouterLink>
        <RouterLink
          to="/settings"
          class="workspace-mobile-settings"
          aria-label="设置"
          title="设置"
          :aria-current="isSettingsRoute ? 'page' : undefined"
        >
          <svg viewBox="0 0 24 24" aria-hidden="true">
            <circle cx="12" cy="12" r="3" />
            <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l-.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9c.26.604.852.997 1.51 1H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1Z" />
          </svg>
          <span class="sr-only">设置</span>
        </RouterLink>
        <a v-if="identityUser?.admin" class="workspace-openapi-link" href="/openapi.json" target="_blank" rel="noopener noreferrer">接口定义 ↗</a>
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
