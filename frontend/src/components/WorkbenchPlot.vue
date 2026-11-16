<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import PlotWorkspace from '../views/PlotWorkspace.vue'
import { projectsApi } from '../api/projects'
import type { Project, Turn } from '../types'

const props = defineProps<{ turns: Turn[]; conversationId: string; preferredProject?: string; preferredTurn?: string; preferredQuery?: number; datasetIdentifier?: string; snapshotIdentifier?: string }>()
const projects = ref<Project[]>([]), projectId = ref(''), newName = ref(''), creating = ref(false)
const loading = ref(true), error = ref(''), newProjectOpen = ref(false), sourceKey = ref('')
const workspace = ref<InstanceType<typeof PlotWorkspace> | null>(null)
const loadedSource = ref<{ conversation_id: string; turn_id: string; query_index: number } | null>(null)
let navigation = 0, alive = true
const sources = computed(() => props.turns.flatMap(turn => turn.execution_status === 'completed' ? (turn.response?.gaia_results || []).flatMap((result, index) => result.status === 'success' && result.data?.length ? [{ key: `${turn.turn_id}:${index}`, turn, index, label: `第${turn.revision}轮 · Gaia 第${index + 1}次查询 · ${result.returned_count}行` }] : []) : []))
const canPrepare = computed(() => !loading.value && !creating.value && !!workspace.value?.canPrepare)
const busy = computed(() => loading.value || creating.value || !!workspace.value?.busy)
const canUpload = computed(() => !!workspace.value?.canUpload)
const workspaceKey = computed(() => `${projectId.value}:${loadedSource.value?.turn_id || ''}:${loadedSource.value?.query_index ?? ''}:${props.datasetIdentifier || ''}:${props.snapshotIdentifier || ''}`)
function loadSource() {
  const value = sources.value.find(item => item.key === sourceKey.value)
  if (!value || !projectId.value || busy.value) return
  loadedSource.value = { conversation_id: value.turn.conversation_id, turn_id: value.turn.turn_id, query_index: value.index }
}
async function load() {
  const token = ++navigation, scope = props.conversationId
  loading.value = true; error.value = ''
  try {
    const [list, memberships] = await Promise.all([projectsApi.list(), projectsApi.memberships()])
    if (!alive || token !== navigation || scope !== props.conversationId) return
    projects.value = list
    const preferred = props.preferredProject || memberships[scope]
    projectId.value = list.some(item => item.id === preferred) ? preferred : list.length === 1 ? list[0]!.id : ''
  } catch (e) { if (alive && token === navigation) error.value = e instanceof Error ? e.message : '读取绘图项目失败。' }
  finally { if (alive && token === navigation) loading.value = false }
}
async function createProject() {
  if (!newName.value.trim() || creating.value) return
  creating.value = true; error.value = ''
  const token = navigation
  try {
    const value = await projectsApi.create(newName.value.trim())
    if (!alive || token !== navigation) return
    projects.value.unshift(value); projectId.value = value.id; newName.value = ''; newProjectOpen.value = false
  } catch (e) { if (alive && token === navigation) error.value = e instanceof Error ? e.message : '创建项目失败，请刷新项目列表核对。' }
  finally { creating.value = false }
}
watch(sources, items => {
  if (items.some(item => item.key === sourceKey.value)) return
  const preferred = items.find(item => item.turn.turn_id === props.preferredTurn && item.index === (props.preferredQuery ?? 0))
  sourceKey.value = preferred?.key || items.at(-1)?.key || ''
}, { immediate: true })
watch(() => [props.conversationId, props.preferredProject], () => { projectId.value = ''; loadedSource.value = null; void load() }, { immediate: true })
watch(() => [props.preferredTurn, props.preferredQuery, projectId.value, sources.value], () => {
  if (!props.preferredTurn || !projectId.value) return
  const source = sources.value.find(item => item.turn.turn_id === props.preferredTurn && item.index === (props.preferredQuery ?? 0))
  if (source) { sourceKey.value = source.key; loadedSource.value = { conversation_id: source.turn.conversation_id, turn_id: source.turn.turn_id, query_index: source.index } }
}, { immediate: true })
onBeforeUnmount(() => { alive = false; navigation++ })
defineExpose({ canPrepare, busy, canUpload, submitQuestion: (question: string) => workspace.value?.submitQuestion(question) ?? Promise.resolve(false), chooseFile: () => workspace.value?.chooseFile() })
</script>

<template>
  <section class="workbench-plot" aria-label="会话科研绘图" :aria-busy="busy">
    <div class="workbench-plot-context">
      <label>保存到项目<select v-model="projectId" :disabled="loading || creating || !!workspace?.busy"><option value="">{{ loading ? '正在读取项目…' : '选择项目' }}</option><option v-for="project in projects" :key="project.id" :value="project.id">{{ project.name }}</option></select></label>
      <label v-if="sources.length">会话查询数据<select v-model="sourceKey" :disabled="busy"><option v-for="source in sources" :key="source.key" :value="source.key">{{ source.label }}</option></select></label>
      <button v-if="sources.length" type="button" :disabled="busy || !projectId || !sourceKey" @click="loadSource">载入查询数据</button>
      <button type="button" :disabled="busy || projects.length >= 20" :aria-expanded="newProjectOpen" @click="newProjectOpen = !newProjectOpen">新建项目</button>
      <form v-if="newProjectOpen" class="workbench-plot-create" @submit.prevent="createProject"><label for="workbench-plot-project">项目名称</label><input id="workbench-plot-project" v-model="newName" maxlength="100" required :disabled="creating" /><button type="submit" class="button-primary" :disabled="creating || !newName.trim()">创建项目</button></form>
      <p v-if="error" class="notice danger" role="alert">{{ error }}</p>
    </div>
    <PlotWorkspace v-if="projectId" :key="workspaceKey" ref="workspace" embedded :project-identifier="projectId" :source-turn="loadedSource" :dataset-identifier="datasetIdentifier" :snapshot-identifier="snapshotIdentifier" :query-number="preferredQuery" />
    <div v-else-if="!loading" class="workbench-plot-empty"><h2>先选择绘图数据的保存项目</h2><p>选择或新建项目后，可载入本会话的 Gaia 查询结果，或上传 CSV/TSV。在下方聊天框描述图形，审阅方案后再确认执行。</p></div>
    <p v-else class="processing">正在读取绘图项目…</p>
  </section>
</template>
