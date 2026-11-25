<script setup lang="ts">
import { nextTick, ref, useId } from 'vue'
import { uploadDocument } from '../api/knowledge'
import { projectsApi } from '../api/projects'
import { useProjects } from '../stores/projects'
import type { Project } from '../types'
import StatusNotice from './StatusNotice.vue'

interface QueuedSource {
  id: string
  file: File
  kind: 'PDF' | 'MD'
  status: 'queued' | 'uploading' | 'ready' | 'failed'
  error?: string
}

const props = withDefaults(defineProps<{
  defaultStartChat?: boolean
}>(), {
  defaultStartChat: false,
})

const emit = defineEmits<{
  created: [payload: { project: Project; uploadedCount: number; startChat: boolean }]
}>()

const MAX_FILE_BYTES = 20 * 1024 * 1024
const projectsStore = useProjects()
const dialogId = useId()

const dialog = ref<HTMLDialogElement | null>(null)
const nameInput = ref<HTMLInputElement | null>(null)
const fileInput = ref<HTMLInputElement | null>(null)

const name = ref('')
const description = ref('')
const sources = ref<QueuedSource[]>([])
const startChat = ref(props.defaultStartChat)
const dragging = ref(false)
const busy = ref(false)
const progress = ref('')
const error = ref('')
const fileWarning = ref('')
const createdProject = ref<Project | null>(null)
const uploadedReady = ref(0)

function formatSize(bytes: number) {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KiB`
  return `${(bytes / (1024 * 1024)).toFixed(2)} MiB`
}

function detectKind(filename: string): 'PDF' | 'MD' | null {
  const lower = filename.toLowerCase()
  if (lower.endsWith('.pdf')) return 'PDF'
  if (lower.endsWith('.md') || lower.endsWith('.markdown')) return 'MD'
  return null
}

function resetState() {
  name.value = ''
  description.value = ''
  sources.value = []
  startChat.value = props.defaultStartChat
  dragging.value = false
  busy.value = false
  progress.value = ''
  error.value = ''
  fileWarning.value = ''
  createdProject.value = null
  uploadedReady.value = 0
}

async function open() {
  resetState()
  dialog.value?.showModal()
  await nextTick()
  nameInput.value?.focus()
}

function close() {
  if (busy.value) return
  dialog.value?.close()
}

function addFiles(fileList: FileList | File[]) {
  if (busy.value || createdProject.value) return
  fileWarning.value = ''
  const rejected: string[] = []
  for (const file of Array.from(fileList)) {
    const kind = detectKind(file.name)
    if (!kind) {
      rejected.push(`${file.name}（仅支持 .pdf、.md、.markdown）`)
      continue
    }
    if (!file.size || file.size > MAX_FILE_BYTES) {
      rejected.push(`${file.name}（需非空且不超过 20 MiB）`)
      continue
    }
    const exists = sources.value.some(
      item => item.file.name === file.name && item.file.size === file.size,
    )
    if (exists) continue
    sources.value.push({
      id: `${file.name}-${file.size}-${crypto.randomUUID()}`,
      file,
      kind,
      status: 'queued',
    })
  }
  if (rejected.length) {
    fileWarning.value = `已跳过不支持或超限的文件：${rejected.join('；')}`
  }
}

function onFileChange(event: Event) {
  const input = event.target as HTMLInputElement
  if (input.files?.length) addFiles(input.files)
  input.value = ''
}

function onDrop(event: DragEvent) {
  dragging.value = false
  if (event.dataTransfer?.files?.length) {
    addFiles(event.dataTransfer.files)
  }
}

function removeSource(id: string) {
  if (busy.value || createdProject.value) return
  sources.value = sources.value.filter(item => item.id !== id)
}

function finishCreated(openChat: boolean) {
  const project = createdProject.value
  if (!project) return
  dialog.value?.close()
  emit('created', { project, uploadedCount: uploadedReady.value, startChat: openChat })
}

async function submit() {
  if (busy.value || createdProject.value || !name.value.trim()) return
  busy.value = true
  error.value = ''
  fileWarning.value = ''
  progress.value = '正在创建科研项目…'

  let project: Project
  try {
    project = await projectsStore.create(name.value.trim(), description.value.trim())
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : '创建科研项目失败，请稍后重试。'
    progress.value = ''
    busy.value = false
    return
  }

  let expectedRevision = project.revision
  let readyCount = 0
  let failedCount = 0

  for (let index = 0; index < sources.value.length; index++) {
    const item = sources.value[index]!
    item.status = 'uploading'
    item.error = undefined
    progress.value = `正在上传并解析参考来源 (${index + 1}/${sources.value.length})：${item.file.name}…`
    try {
      if (index > 0) {
        const latest = await projectsApi.detail(project.id)
        expectedRevision = latest.revision
      }
      const result = await uploadDocument(project.id, item.file, {
        expected_revision: expectedRevision,
        client_request_id: crypto.randomUUID(),
        allow_duplicate: false,
        metadata: { title: null, authors: [], year: null, doi: null },
        restore_version_id: null,
      })
      if (result.document.state === 'ready' || result.document.state === 'partial') {
        item.status = 'ready'
        readyCount++
      } else {
        item.status = 'failed'
        item.error = result.operation.message || '未能提取可检索文本（可能为扫描件）。'
        failedCount++
      }
    } catch (reason) {
      item.status = 'failed'
      item.error = reason instanceof Error ? reason.message : '上传或解析失败。'
      failedCount++
    }
  }

  projectsStore.setSourceCount(project.id, readyCount)
  void projectsStore.load(true).catch(() => undefined)
  progress.value = ''
  busy.value = false

  if (failedCount > 0) {
    createdProject.value = project
    uploadedReady.value = readyCount
    error.value = `科研项目「${project.name}」已创建（${readyCount}/${sources.value.length} 份来源就绪），部分文件未能解析，你仍可先进入项目或在知识库中补充。`
    return
  }

  dialog.value?.close()
  emit('created', { project, uploadedCount: readyCount, startChat: startChat.value })
}

defineExpose({ open, close })
</script>

<template>
  <dialog
    ref="dialog"
    class="project-dialog create-project-dialog"
    :aria-labelledby="`${dialogId}-title`"
    @cancel="busy && $event.preventDefault()"
  >
    <div class="dialog-header">
      <div class="dialog-header-copy">
        <h2 :id="`${dialogId}-title`">新建科研项目</h2>
        <p class="dialog-subtitle">按课题组织关联会话、参考来源文献、科研流程与实验记录。</p>
      </div>
      <button
        type="button"
        class="dialog-close"
        aria-label="关闭"
        :disabled="busy"
        @click="close"
      >
        <svg viewBox="0 0 24 24" aria-hidden="true"><path d="m6 6 12 12M6 18 18 6" /></svg>
      </button>
    </div>

    <form class="create-project-form" @submit.prevent="submit">
      <div class="create-project-body">
        <div class="dialog-field">
          <label :for="`${dialogId}-name`">项目名称 <span class="required-mark" aria-hidden="true">*</span></label>
          <input
            :id="`${dialogId}-name`"
            ref="nameInput"
            v-model="name"
            maxlength="100"
            required
            placeholder="例如：M45 双星团成员筛选"
            :disabled="busy || !!createdProject"
          >
        </div>

        <div class="dialog-field">
          <label :for="`${dialogId}-description`">项目指令与说明 <span class="field-optional">可选</span></label>
          <textarea
            :id="`${dialogId}-description`"
            v-model="description"
            maxlength="2000"
            rows="3"
            placeholder="写明课题目标、目标天体、筛选口径或回答侧重；项目内所有对话将自动携带此指令…"
            :disabled="busy || !!createdProject"
          />
        </div>

        <div class="dialog-field">
          <div class="source-field-heading">
            <label :for="`${dialogId}-files`">参考来源 <span class="field-optional">可选</span></label>
            <span class="source-field-meta">PDF / Markdown · 单文件 ≤ 20 MiB</span>
          </div>
          <p class="source-field-hint">上传的文献与课题笔记将保存在本项目知识库中，项目内对话回答时会自动参考这些来源。</p>

          <div
            v-if="!createdProject"
            class="source-dropzone"
            :class="{ 'is-dragging': dragging, 'is-disabled': busy }"
            role="button"
            tabindex="0"
            aria-label="选择或拖放参考来源文件"
            @click="!busy && fileInput?.click()"
            @keydown.enter.prevent="!busy && fileInput?.click()"
            @keydown.space.prevent="!busy && fileInput?.click()"
            @dragenter.prevent="dragging = !busy"
            @dragover.prevent="dragging = !busy"
            @dragleave.prevent="dragging = false"
            @drop.prevent="onDrop"
          >
            <svg viewBox="0 0 24 24" aria-hidden="true">
              <path d="M12 15V4m-4 4 4-4 4 4M4 15v3a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-3" />
            </svg>
            <div class="source-dropzone-text">
              <b>点击添加来源文件，或拖放到此处</b>
              <span>支持一次添加多份 .pdf、.md、.markdown 文件，创建后自动本地解析</span>
            </div>
            <input
              :id="`${dialogId}-files`"
              ref="fileInput"
              type="file"
              multiple
              accept=".pdf,.md,.markdown"
              class="sr-only"
              :disabled="busy"
              @change="onFileChange"
            >
          </div>

          <p v-if="fileWarning" class="notice warning source-warning" role="status">{{ fileWarning }}</p>

          <ul v-if="sources.length" class="source-queue" aria-label="已选参考来源">
            <li v-for="item in sources" :key="item.id" class="source-queue-item" :class="`is-${item.status}`">
              <span class="source-kind-badge">{{ item.kind }}</span>
              <div class="source-queue-meta">
                <b :title="item.file.name">{{ item.file.name }}</b>
                <small>
                  {{ formatSize(item.file.size) }}
                  <template v-if="item.status === 'uploading'"> · 正在本地解析…</template>
                  <template v-else-if="item.status === 'ready'"> · 解析就绪</template>
                  <template v-else-if="item.status === 'failed'"> · {{ item.error || '解析未完成' }}</template>
                </small>
              </div>
              <button
                v-if="!busy && !createdProject"
                type="button"
                class="source-remove-btn"
                :aria-label="`移除 ${item.file.name}`"
                @click="removeSource(item.id)"
              >
                <svg viewBox="0 0 24 24" aria-hidden="true"><path d="m6 6 12 12M6 18 18 6" /></svg>
              </button>
            </li>
          </ul>
        </div>

        <label v-if="!createdProject" class="dialog-check-row">
          <input v-model="startChat" type="checkbox" :disabled="busy">
          <span>创建后立即在项目中新建对话</span>
        </label>

        <p v-if="progress" class="processing" role="status">{{ progress }}</p>
        <StatusNotice v-if="error" title="项目创建未完成" :message="error" @dismiss="error = ''" />
      </div>

      <div class="project-actions dialog-footer">
        <template v-if="createdProject">
          <button type="button" @click="finishCreated(false)">进入项目空间</button>
          <button type="button" class="button-primary" @click="finishCreated(true)">在项目中新建对话</button>
        </template>
        <template v-else>
          <button type="button" :disabled="busy" @click="close">取消</button>
          <button type="submit" class="button-primary" :disabled="busy || !name.trim()">
            {{ busy ? '正在创建…' : sources.length ? `创建并解析 ${sources.length} 份来源` : '创建科研项目' }}
          </button>
        </template>
      </div>
    </form>
  </dialog>
</template>

<style scoped>
.create-project-dialog {
  width: min(560px, calc(100vw - 32px));
  max-height: min(85dvh, 760px);
  padding: 0;
  overflow: hidden;
}

.create-project-dialog[open] {
  display: flex;
  flex-direction: column;
}

.create-project-dialog > .dialog-header {
  flex: none;
  margin: 0;
  padding: 20px 24px 14px;
  border-bottom: 1px solid var(--line);
}

.create-project-form {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-height: 0;
  overflow: hidden;
}

.create-project-body {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 18px 24px;
  display: grid;
  gap: 18px;
  align-content: start;
}

.dialog-field {
  display: grid;
  gap: 7px;
  min-width: 0;
}

.dialog-field > label,
.source-field-heading > label {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  margin: 0;
  color: var(--ink);
  font-size: 13px;
  font-weight: 550;
}

.required-mark {
  color: var(--danger);
}

.field-optional {
  color: var(--muted);
  font-size: 11.5px;
  font-weight: 450;
}

.dialog-field input,
.dialog-field textarea {
  width: 100%;
  box-sizing: border-box;
  margin: 0;
}

.dialog-field textarea {
  min-height: 84px;
  resize: vertical;
}

.source-field-heading {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 10px;
  flex-wrap: wrap;
}

.source-field-meta {
  color: var(--muted);
  font-size: 11.5px;
  font-variant-numeric: tabular-nums;
}

.source-field-hint {
  margin: 0;
  color: var(--muted);
  font-size: 12px;
  line-height: 1.6;
}

.source-dropzone {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 14px 16px;
  border: 1.5px dashed var(--line-strong);
  border-radius: 11px;
  background: var(--surface-evidence);
  color: var(--ink);
  cursor: pointer;
  transition: border-color var(--duration-fast) var(--ease-out), background-color var(--duration-fast) var(--ease-out);
}

.source-dropzone:hover:not(.is-disabled),
.source-dropzone.is-dragging {
  border-color: var(--accent);
  background: var(--accent-soft);
}

.source-dropzone.is-disabled {
  opacity: 0.6;
  cursor: default;
}

.source-dropzone svg {
  width: 22px;
  height: 22px;
  flex: 0 0 22px;
  fill: none;
  stroke: var(--accent);
  stroke-width: 1.7;
  stroke-linecap: round;
  stroke-linejoin: round;
}

.source-dropzone-text {
  display: grid;
  gap: 2px;
  min-width: 0;
}

.source-dropzone-text b {
  font-size: 13px;
  font-weight: 550;
  color: var(--ink);
}

.source-dropzone-text span {
  font-size: 11.5px;
  color: var(--muted);
  line-height: 1.5;
}

.source-warning {
  margin: 2px 0 0;
  font-size: 12px;
}

.source-queue {
  list-style: none;
  margin: 4px 0 0;
  padding: 0;
  display: grid;
  gap: 6px;
  max-height: 184px;
  overflow-y: auto;
}

.source-queue-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 10px;
  border: 1px solid var(--line);
  border-radius: 9px;
  background: var(--paper);
}

.source-queue-item.is-ready {
  border-color: color-mix(in srgb, var(--success) 34%, var(--line));
  background: var(--success-soft);
}

.source-queue-item.is-failed {
  border-color: color-mix(in srgb, var(--danger) 36%, var(--line));
  background: var(--danger-soft);
}

.source-kind-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 34px;
  height: 22px;
  padding: 0 6px;
  border-radius: 6px;
  background: var(--accent-soft);
  color: var(--accent);
  font-size: 10.5px;
  font-weight: 650;
  letter-spacing: 0.04em;
  flex: none;
}

.source-queue-meta {
  flex: 1;
  min-width: 0;
  display: grid;
  gap: 2px;
}

.source-queue-meta b {
  font-size: 12.5px;
  font-weight: 550;
  color: var(--ink);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.source-queue-meta small {
  font-size: 11px;
  color: var(--muted);
  overflow-wrap: anywhere;
}

.source-queue-item.is-failed .source-queue-meta small {
  color: var(--danger);
}

.source-remove-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 26px;
  height: 26px;
  min-height: 26px;
  padding: 0;
  border: 0;
  border-radius: 7px;
  background: transparent;
  box-shadow: none;
  color: var(--muted);
  flex: none;
}

.source-remove-btn:hover:not(:disabled) {
  border: 0;
  background: var(--soft);
  color: var(--danger);
  box-shadow: none;
}

.source-remove-btn svg {
  width: 14px;
  height: 14px;
  fill: none;
  stroke: currentColor;
  stroke-width: 2;
  stroke-linecap: round;
}

.dialog-check-row {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  color: var(--ink);
  cursor: pointer;
  user-select: none;
}

.dialog-check-row input {
  width: 15px;
  height: 15px;
  min-height: 0;
  margin: 0;
}

.dialog-footer {
  flex: none;
  margin: 0;
  padding: 14px 24px 18px;
  border-top: 1px solid var(--line);
  background: var(--paper);
}

@media (max-width: 680px) {
  .create-project-dialog {
    max-height: 90dvh;
  }

  .create-project-dialog > .dialog-header {
    padding: 16px 18px 12px;
  }

  .create-project-body {
    padding: 14px 18px;
  }

  .dialog-footer {
    padding: 12px 18px 16px;
  }
}
</style>
