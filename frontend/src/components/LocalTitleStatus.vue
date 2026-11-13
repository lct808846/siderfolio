<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from 'vue'
import { localAssistantApi, localTaskLabels } from '../api/local-assistant'
import type { LocalTask } from '../api/local-assistant'
import { useWorkbench } from '../stores/workbench'

const props = defineProps<{ conversationId?: string | null; hasMessage: boolean; submitting?: boolean; silent?: boolean }>()
const store = useWorkbench(), task = ref<LocalTask | null>(null)
let timer: ReturnType<typeof setTimeout> | undefined, generation = 0
watch(() => [props.conversationId, props.hasMessage, props.submitting] as const, ([id, hasMessage]) => {
  const token = ++generation
  if (timer) clearTimeout(timer)
  task.value = null
  if (!id || !hasMessage) return
  const started = Date.now()
  let empty = 0
  let failures = 0
  let observed = false
  async function refresh() {
    try {
      const values = await localAssistantApi.titles(id!)
      if (token !== generation) return
      failures = 0
      task.value = values[0]?.task || null
      if (!observed) { await store.refreshList(); observed = true }
      if (task.value && !['queued', 'running'].includes(task.value.state)) { await store.refreshList(); return }
      if (!task.value && ++empty >= 3 && !props.submitting) return
    } catch {
      // Retry reads only; a transient status failure must not stop title delivery.
      if (++failures >= 5) return
    }
    if (token === generation && Date.now() - started < 180000) timer = setTimeout(() => { void refresh() }, 2500)
  }
  void refresh()
}, { immediate: true })
onBeforeUnmount(() => { generation++; if (timer) clearTimeout(timer) })
</script>

<template><span v-if="!silent && task" class="local-title-status" :title="task.error || (task.title_applied ? '本地模型已更新标题，人工改名始终优先' : '自动命名只使用首条问题的有限前缀')" role="status">{{ task.title_applied ? '本地命名' : ['queued', 'running'].includes(task.state) ? '正在本地命名' : `命名${localTaskLabels[task.state]}` }}</span></template>
