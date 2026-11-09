<script setup lang="ts">
import { computed, inject } from 'vue'
import { useRoute } from 'vue-router'

defineProps<{ title: string }>()
const route = useRoute()
const createConversation = inject<() => Promise<string | undefined>>('astroagent.create-conversation')
const projectPath = computed(() => typeof route.params.projectId === 'string' && route.params.projectId
  ? `/projects/${encodeURIComponent(route.params.projectId)}` : '')
const projectSections = computed(() => [
  { label: '项目记录', path: projectPath.value },
  { label: '来源关联', path: `${projectPath.value}/overview` },
  { label: '科研流程', path: `${projectPath.value}/workflows` },
  { label: '数据绘图', path: `${projectPath.value}/plotting` },
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
      <button class="brand brand-action" type="button" aria-label="AstroAgent：新建会话" data-tooltip="" :disabled="!createConversation" @click="createConversation?.()">
        <span class="brand-mark" aria-hidden="true">✳</span><b>AstroAgent</b>
        <span class="version">1.3 开发版</span>
      </button>
      <span class="workspace-title">{{ title }}</span>
      <nav class="workspace-global-nav" aria-label="全局导航">
        <RouterLink to="/" :aria-current="route.path === '/' || route.path.startsWith('/conversations/') ? 'page' : undefined">查询工作台</RouterLink>
        <RouterLink to="/projects" :aria-current="route.path.startsWith('/projects') ? 'page' : undefined">项目归档</RouterLink>
        <RouterLink to="/settings" :aria-current="route.path === '/settings' ? 'page' : undefined">本机设置</RouterLink>
        <a href="http://127.0.0.1:8000/docs" target="_blank" rel="noopener noreferrer">接口文档 ↗</a>
      </nav>
    </div>
    <nav v-if="projectPath" class="workspace-project-nav" aria-label="当前项目导航">
      <span class="workspace-project-label">当前项目</span>
      <RouterLink
        v-for="section in projectSections" :key="section.path" :to="section.path"
        :aria-current="current(section.path, section.path.endsWith('/knowledge') || section.path.endsWith('/workflows')) ? 'page' : undefined">
        {{ section.label }}
      </RouterLink>
    </nav>
  </header>
</template>
