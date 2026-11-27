<script setup lang="ts">
import { computed, nextTick, onMounted, ref } from 'vue'
import { useMemory } from '../stores/memory'
import { useProjects } from '../stores/projects'
import StatusNotice from './StatusNotice.vue'
import SuccessToast from './SuccessToast.vue'
import UiSelect, { type UiSelectOption } from './UiSelect.vue'

const memoryStore = useMemory()
const projectsStore = useProjects()

const notice = ref('')
const addDialog = ref<HTMLDialogElement | null>(null)
const formScope = ref<'global' | 'project'>('global')
const formProjectId = ref('')
const formSummary = ref('')
const formValidation = ref('')

const hasProjects = computed(() => projectsStore.customProjects.length > 0)

const scopeOptions = computed<UiSelectOption<string>[]>(() => [
  { value: 'global', label: '全局个人（适用于所有会话）' },
  ...projectsStore.customProjects.map(p => ({
    value: `project:${p.id}`,
    label: `项目 · ${p.name}`,
  })),
])

const selectedScopeKey = computed({
  get: () => (formScope.value === 'project' && formProjectId.value ? `project:${formProjectId.value}` : 'global'),
  set: (value: string) => {
    if (value.startsWith('project:')) {
      formScope.value = 'project'
      formProjectId.value = value.slice('project:'.length)
    } else {
      formScope.value = 'global'
      formProjectId.value = ''
    }
  },
})

const updatedLabel = computed(() => {
  const raw = memoryStore.overview?.updated_at
  if (!raw) return ''
  const dt = new Date(raw)
  if (Number.isNaN(dt.getTime())) return ''
  return `更新于 ${dt.toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })}`
})

async function toggleMemory(event: Event) {
  const checked = (event.target as HTMLInputElement).checked
  const ok = await memoryStore.setEnabled(checked)
  if (ok) {
    notice.value = checked
      ? '已开启记忆功能。'
      : '已关闭记忆功能，关闭期间不会学习或向模型发送记忆。'
  } else {
    ;(event.target as HTMLInputElement).checked = memoryStore.enabled
  }
}

async function openAddDialog() {
  formScope.value = 'global'
  formProjectId.value = ''
  formSummary.value = ''
  formValidation.value = ''
  await nextTick()
  addDialog.value?.showModal()
}

async function submitAdd() {
  const text = formSummary.value.trim()
  if (text.length < 2) {
    formValidation.value = '请输入至少 2 个字符的记忆内容。'
    return
  }
  formValidation.value = ''
  const created = await memoryStore.addMemory({
    scope: formScope.value,
    project_id: formScope.value === 'project' ? formProjectId.value : null,
    summary: text,
    verification_status: 'manual',
    conflict_resolution: 'keep_both',
  })
  if (created) {
    addDialog.value?.close()
    notice.value = '已添加记忆，记忆摘要已自动更新。'
  }
}

onMounted(() => {
  void projectsStore.load().catch(() => undefined)
  void memoryStore.loadSummary()
})
</script>

<template>
  <div class="memory-settings">
    <SuccessToast v-model:message="notice" />
    <StatusNotice
      v-if="memoryStore.error"
      title="记忆设置操作未完成"
      :message="memoryStore.error"
      @dismiss="memoryStore.error = ''"
    />

    <section class="settings-group" aria-labelledby="memory-toggle-title">
      <div class="settings-group-head">
        <h3 id="memory-toggle-title">记忆功能</h3>
        <span class="ui-pill" :class="memoryStore.enabled ? 'ui-pill-success' : 'ui-pill-neutral'">
          <span class="ui-dot" aria-hidden="true" />
          {{ memoryStore.enabled ? '已开启' : '已关闭' }}
        </span>
      </div>
      <label class="settings-row settings-switch-row">
        <div>
          <h4>开启记忆</h4>
          <p>在跨会话对话中自动延续你的研究背景、常用工具与偏好，并按需参考历史上下文</p>
        </div>
        <input
          class="settings-switch"
          type="checkbox"
          role="switch"
          aria-label="开启记忆"
          :checked="memoryStore.enabled"
          :disabled="memoryStore.saving || memoryStore.loading"
          @change="toggleMemory"
        />
      </label>
    </section>

    <section class="settings-group" aria-labelledby="memory-summary-title">
      <div class="settings-group-head">
        <div>
          <h3 id="memory-summary-title">记忆摘要</h3>
          <p v-if="updatedLabel" class="small muted">{{ updatedLabel }}</p>
        </div>
        <button
          type="button"
          class="button-primary"
          :disabled="memoryStore.saving"
          @click="openAddDialog"
        >
          添加记忆
        </button>
      </div>

      <p v-if="memoryStore.loading && !memoryStore.overview" class="settings-loading" role="status">
        正在整理记忆摘要…
      </p>

      <div v-else-if="memoryStore.overview?.has_memory && memoryStore.overview.sections?.length" class="memory-summary-body">
        <div
          v-for="section in memoryStore.overview.sections"
          :key="section.title"
          class="memory-summary-block"
        >
          <h4>{{ section.title }}</h4>
          <p>{{ section.content }}</p>
        </div>
      </div>

      <p v-else class="memory-summary-empty">
        暂无记忆摘要。开启记忆功能后，Siderfolio 会在对话中自动整理你的研究方向与常用工具，你也可以点击右上角「添加记忆」直接补充。
      </p>

      <p class="settings-footnote">
        记忆摘要由系统综合生成，不展示逐条原始记录；对话中的明确指令始终优先。
      </p>
    </section>

    <dialog ref="addDialog" class="project-dialog" aria-labelledby="memory-add-title">
      <div class="dialog-header">
        <div class="dialog-header-copy">
          <h2 id="memory-add-title">添加记忆</h2>
          <p class="dialog-subtitle">补充希望 Siderfolio 在后续对话中记住的研究背景、工具习惯或偏好。</p>
        </div>
        <button type="button" class="dialog-close" aria-label="关闭" @click="addDialog?.close()">
          <svg viewBox="0 0 24 24" aria-hidden="true"><path d="m6 6 12 12M6 18 18 6" /></svg>
        </button>
      </div>

      <form class="project-form" @submit.prevent="submitAdd">
        <template v-if="hasProjects">
          <label for="memory-add-scope">适用范围</label>
          <UiSelect
            id="memory-add-scope"
            v-model="selectedScopeKey"
            aria-label="适用范围"
            :options="scopeOptions"
          />
        </template>

        <label for="memory-add-content">记忆内容</label>
        <textarea
          id="memory-add-content"
          v-model="formSummary"
          rows="4"
          maxlength="600"
          placeholder="例如：我主要研究不同外部环境下的双星团动力学演化，常用 Python、Matplotlib 与 PeTar。"
          required
        />

        <p v-if="formValidation" class="small" style="color: var(--danger); margin: 0;" role="alert">
          {{ formValidation }}
        </p>

        <div class="project-actions">
          <button type="button" @click="addDialog?.close()">取消</button>
          <button type="submit" class="button-primary" :disabled="memoryStore.saving">
            {{ memoryStore.saving ? '正在保存…' : '保存记忆' }}
          </button>
        </div>
      </form>
    </dialog>
  </div>
</template>

<style scoped>
.memory-settings {
  display: grid;
  gap: 16px;
}

.memory-summary-body {
  display: grid;
  gap: 14px;
  padding: 14px 0 6px;
}

.memory-summary-block {
  display: grid;
  gap: 4px;
}

.memory-summary-block h4 {
  margin: 0;
  font-size: 13px;
  font-weight: 600;
  color: var(--ink);
}

.memory-summary-block p {
  margin: 0;
  font-size: 13.5px;
  line-height: 1.75;
  color: var(--muted);
  word-break: break-word;
}

.memory-summary-empty {
  margin: 12px 0 4px;
  font-size: 13.5px;
  line-height: 1.65;
  color: var(--muted);
}
</style>
