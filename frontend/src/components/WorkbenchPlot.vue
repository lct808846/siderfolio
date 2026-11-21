<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import PlotWorkspace from '../views/PlotWorkspace.vue'
import { useProjects } from '../stores/projects'
import type { Turn } from '../types'

const props = defineProps<{ turns: Turn[]; conversationId: string; preferredProject?: string; preferredTurn?: string; preferredQuery?: number; datasetIdentifier?: string; snapshotIdentifier?: string }>()
const projectsStore = useProjects()
const projectId = ref(''), newName = ref(''), creating = ref(false)
const loading = ref(true), error = ref(''), newProjectOpen = ref(false), sourceKey = ref('')
const workspace = ref<InstanceType<typeof PlotWorkspace> | null>(null)
const loadedSource = ref<{ conversation_id: string; turn_id: string; query_index: number } | null>(null)
let navigation = 0, alive = true
const sources = computed(() => props.turns.flatMap(turn => turn.execution_status === 'completed' ? (turn.response?.gaia_results || []).flatMap((result, index) => result.status === 'success' && result.data?.length ? [{ key: `${turn.turn_id}:${index}`, turn, index, label: `第${turn.revision}轮 · Gaia 第${index + 1}次查询 · ${result.returned_count}行` }] : []) : []))
const spaceOptions = computed(() => {
  const items: Array<{ id: string; label: string }> = []
  if (projectsStore.defaultProject) items.push({ id: projectsStore.defaultProject.id, label: '个人空间（默认）' })
  for (const item of projectsStore.customProjects) items.push({ id: item.id, label: item.name })
  return items
})
const canPrepare = computed(() => !loading.value && !creating.value && !!workspace.value?.canPrepare)
const busy = computed(() => loading.value || creating.value || !!workspace.value?.busy)
const canUpload = computed(() => !!workspace.value?.canUpload)
const readinessHint = computed(() => loading.value ? '正在准备绘图空间…' : creating.value ? '正在创建项目…' : workspace.value?.readinessHint || '')
const workspaceKey = computed(() => `${projectId.value}:${loadedSource.value?.turn_id || ''}:${loadedSource.value?.query_index ?? ''}:${props.datasetIdentifier || ''}:${props.snapshotIdentifier || ''}`)
function syncLoadedSource() {
  if (!projectId.value || props.datasetIdentifier || props.snapshotIdentifier) return
  if (!sourceKey.value) {
    loadedSource.value = null
    return
  }
  const value = sources.value.find(item => item.key === sourceKey.value)
  if (!value) return
  if (
    loadedSource.value?.conversation_id === value.turn.conversation_id
    && loadedSource.value?.turn_id === value.turn.turn_id
    && loadedSource.value?.query_index === value.index
  ) return
  loadedSource.value = { conversation_id: value.turn.conversation_id, turn_id: value.turn.turn_id, query_index: value.index }
}
async function load() {
  const token = ++navigation, scope = props.conversationId
  loading.value = true; error.value = ''
  try {
    await projectsStore.load(true)
    if (!alive || token !== navigation || scope !== props.conversationId) return
    const preferred = props.preferredProject || projectsStore.memberships[scope]
    if (preferred && projectsStore.projects.some(item => item.id === preferred)) {
      projectId.value = preferred
    } else {
      const fallback = await projectsStore.ensureDefault()
      if (!alive || token !== navigation || scope !== props.conversationId) return
      projectId.value = fallback.id
    }
  } catch (e) { if (alive && token === navigation) error.value = e instanceof Error ? e.message : '准备绘图空间失败。' }
  finally { if (alive && token === navigation) loading.value = false }
}
async function createProject() {
  if (!newName.value.trim() || creating.value) return
  creating.value = true; error.value = ''
  const token = navigation
  try {
    const value = await projectsStore.create(newName.value.trim())
    if (!alive || token !== navigation) return
    projectId.value = value.id; newName.value = ''; newProjectOpen.value = false
  } catch (e) { if (alive && token === navigation) error.value = e instanceof Error ? e.message : '创建项目失败，请稍后重试。' }
  finally { creating.value = false }
}
watch(sources, items => {
  if (props.datasetIdentifier || props.snapshotIdentifier) return
  if (sourceKey.value && items.some(item => item.key === sourceKey.value)) return
  const preferred = items.find(item => item.turn.turn_id === props.preferredTurn && item.index === (props.preferredQuery ?? 0))
  sourceKey.value = preferred?.key || items.at(-1)?.key || ''
}, { immediate: true })
watch(() => [props.conversationId, props.preferredProject], () => { projectId.value = ''; loadedSource.value = null; void load() }, { immediate: true })
watch(() => [props.preferredTurn, props.preferredQuery, sources.value], () => {
  if (!props.preferredTurn) return
  const source = sources.value.find(item => item.turn.turn_id === props.preferredTurn && item.index === (props.preferredQuery ?? 0))
  if (source) sourceKey.value = source.key
}, { immediate: true })
watch(() => [projectId.value, sourceKey.value, sources.value, props.datasetIdentifier, props.snapshotIdentifier], syncLoadedSource, { immediate: true })
onBeforeUnmount(() => { alive = false; navigation++ })
defineExpose({ canPrepare, busy, canUpload, readinessHint, submitQuestion: (question: string) => workspace.value?.submitQuestion(question) ?? Promise.resolve(false), chooseFile: () => workspace.value?.chooseFile() })
</script>

<template>
  <section class="workbench-plot" aria-label="会话科研绘图" :aria-busy="busy">
    <div class="workbench-plot-context">
      <label>保存空间<select v-model="projectId" :disabled="loading || creating || !!workspace?.busy"><option v-if="loading && !spaceOptions.length" value="">正在准备绘图空间…</option><option v-for="space in spaceOptions" :key="space.id" :value="space.id">{{ space.label }}</option></select></label>
      <label v-if="sources.length">会话查询数据<select v-model="sourceKey" :disabled="busy"><option value="">使用项目已有或本地上传数据</option><option v-for="source in sources" :key="source.key" :value="source.key">{{ source.label }}</option></select></label>
      <span v-if="sources.length && loadedSource" class="workbench-plot-loaded-pill">已自动载入</span>
      <button type="button" :disabled="busy || projectsStore.customProjects.length >= 20" :aria-expanded="newProjectOpen" @click="newProjectOpen = !newProjectOpen">新建项目</button>
      <form v-if="newProjectOpen" class="workbench-plot-create" @submit.prevent="createProject"><label for="workbench-plot-project">项目名称</label><input id="workbench-plot-project" v-model="newName" maxlength="100" required :disabled="creating" /><button type="submit" class="button-primary" :disabled="creating || !newName.trim()">创建项目</button></form>
      <p v-if="error" class="notice danger" role="alert">{{ error }}</p>
    </div>
    <PlotWorkspace v-if="projectId" :key="workspaceKey" ref="workspace" embedded :project-identifier="projectId" :source-turn="loadedSource" :dataset-identifier="datasetIdentifier" :snapshot-identifier="snapshotIdentifier" :query-number="preferredQuery" />
    <p v-else-if="loading" class="processing">正在准备绘图空间…</p>
  </section>
</template>
