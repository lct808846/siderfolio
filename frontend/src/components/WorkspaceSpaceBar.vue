<script setup lang="ts">
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import { useProjects } from '../stores/projects'

const props = defineProps<{
  section: 'knowledge' | 'rag' | 'workflows' | 'compute'
  projectId: string
}>()

const router = useRouter()
const projectsStore = useProjects()

const spaces = computed(() => {
  const items: Array<{ id: string; label: string }> = []
  if (projectsStore.defaultProject) {
    items.push({ id: projectsStore.defaultProject.id, label: '个人空间（默认）' })
  }
  for (const project of projectsStore.customProjects) {
    items.push({ id: project.id, label: project.name })
  }
  if (props.projectId && !items.some(item => item.id === props.projectId)) {
    items.push({ id: props.projectId, label: projectsStore.labelFor(props.projectId) || '当前空间' })
  }
  return items
})

const isDefault = computed(() => !props.projectId || props.projectId === projectsStore.defaultProjectId)
const knowledgeHref = computed(() => (isDefault.value ? '/knowledge' : `/projects/${props.projectId}/knowledge`))
const ragHref = computed(() => (isDefault.value ? '/rag' : `/projects/${props.projectId}/rag`))

function switchSpace(event: Event) {
  const targetId = (event.target as HTMLSelectElement).value
  if (!targetId || targetId === props.projectId) return
  if (targetId === projectsStore.defaultProjectId) {
    projectsStore.setActiveProject('')
    void router.push(`/${props.section}`)
  } else {
    projectsStore.setActiveProject(targetId)
    void router.push(`/projects/${encodeURIComponent(targetId)}/${props.section}`)
  }
}
</script>

<template>
  <div class="workspace-space-bar">
    <div v-if="section === 'knowledge' || section === 'rag'" class="workspace-mode-switch" role="navigation" aria-label="知识库与文献问答切换">
      <RouterLink :to="knowledgeHref" :aria-current="section === 'knowledge' ? 'page' : undefined">本地知识库</RouterLink>
      <RouterLink :to="ragHref" :aria-current="section === 'rag' ? 'page' : undefined">文献问答</RouterLink>
    </div>
    <label class="workspace-space-select">
      <span>当前空间</span>
      <select :value="projectId" aria-label="切换当前科研空间" @change="switchSpace">
        <option v-for="space in spaces" :key="space.id" :value="space.id">{{ space.label }}</option>
      </select>
    </label>
  </div>
</template>
