<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import ResultPanel from './ResultPanel.vue'
import { api, ApiError } from '../api'
import { knowledgeApi, uploadDocument } from '../api/knowledge'
import { exportProject, projectsApi } from '../api/projects'
import { useProjects } from '../stores/projects'
import { useWorkbench } from '../stores/workbench'
import type { Comparison, Conversation, ConversationDetail, KnowledgeDocument, ProjectDetail, RerunRequest, Snapshot, Turn } from '../types'

export type DrawerTab = 'context' | 'snapshots' | 'manage'

const MAX_SOURCE_BYTES = 20 * 1024 * 1024

withDefaults(defineProps<{
  canInspectInWorkbench?: boolean
}>(), {
  canInspectInWorkbench: false,
})

const emit = defineEmits<{
  deleted: [projectId: string]
  updated: [projectId: string]
  'inspect-snapshot': [snapshot: Snapshot]
}>()

const router = useRouter()
const projectsStore = useProjects()
const workbenchStore = useWorkbench()

const isOpen = ref(false)
const activeProjectId = ref('')
const activeTab = ref<DrawerTab>('context')
const current = ref<ProjectDetail | null>(null)
const documents = ref<KnowledgeDocument[]>([])
const conversations = ref<Conversation[]>([])
const memberships = ref<Record<string, string>>({})
const snapshot = ref<Snapshot | null>(null)
const inlineResultOpen = ref(false)

const loading = ref(false)
const busy = ref(false)
const uploadingSources = ref(false)
const sourceProgress = ref('')
const sourceDragging = ref(false)
const error = ref('')
const errorCode = ref('')
const message = ref('')
const copiedId = ref(false)

const editingInfo = ref(false)
const editName = ref('')
const editDescription = ref('')
const chatQuery = ref('')
const moveId = ref('')
const saveConversation = ref('')
const saveTurn = ref('')
const snapshotName = ref('')
const renameName = ref('')
const conversationDetail = ref<ConversationDetail | null>(null)
const leftId = ref('')
const rightId = ref('')
const matchIds = ref(false)
const comparison = ref<Comparison | null>(null)
const tool = ref('')
const archiveFormat = ref<1 | 2 | 3 | 4 | 5 | 6>(6)
const knowledgeMode = ref<'full' | 'metadata'>('metadata')
const pending = ref<{ project: string; snapshot: string; payload: RerunRequest } | null>(null)

const confirmDialog = ref<HTMLDialogElement | null>(null)
const confirmAction = ref<'project-delete' | 'snapshot-delete' | 'rerun' | 'archive' | ''>('')
const sourceFileInput = ref<HTMLInputElement | null>(null)
const panelRef = ref<HTMLElement | null>(null)

let loadToken = 0
let snapshotToken = 0
let conversationSelection = 0
let copyTimer: ReturnType<typeof setTimeout> | undefined

const docStateLabels: Record<string, string> = {
  ready: '已就绪',
  partial: '部分可用',
  parsing: '解析中',
  failed: '未完成',
  interrupted: '已中断',
  unavailable: '原文不可用',
}

const isDefaultCurrent = computed(() => !!current.value && current.value.id === projectsStore.defaultProjectId)
const projectDisplayName = computed(() => current.value ? (isDefaultCurrent.value ? '个人空间（默认）' : current.value.name) : '科研项目')
const hasInstructions = computed(() => !!(current.value?.description || '').trim())
const readySourceCount = computed(() => documents.value.filter(d => d.state === 'ready' || d.state === 'partial').length)
const members = computed(() => conversations.value.filter(c => memberships.value[c.id] === current.value?.id))
const filteredMembers = computed(() => {
  const term = chatQuery.value.trim().toLowerCase()
  if (!term) return members.value
  return members.value.filter(c => c.title.toLowerCase().includes(term))
})
const movable = computed(() => conversations.value.filter(c => memberships.value[c.id] !== current.value?.id))
const deliverable = computed(() => conversationDetail.value?.turns.filter(t => t.response_status) || [])

const tools = computed(() => {
  const response = snapshot.value?.response
  if (!response) return []
  return [
    ...(response.results || []).map((r, i) => ({ value: `simbad:${i}`, label: `SIMBAD ${r.object_name}`, parameters: { object_name: r.object_name }, source: r.source })),
    ...(response.literature_results || []).map((r, i) => ({ value: `ads:${i}`, label: `ADS 第${i + 1}次检索`, parameters: { query: r.query, rows: r.rows, start: r.start, sort: r.sort }, source: r.source })),
    ...(response.gaia_results || []).map((r, i) => ({ value: `gaia:${i}`, label: `Gaia DR3 第${i + 1}次查询`, parameters: r.query, source: r.source })),
  ]
})
const selectedTool = computed(() => tools.value.find(t => t.value === tool.value))
const snapshotTurn = computed<Turn | null>(() => snapshot.value ? {
  conversation_id: snapshot.value.project_id,
  turn_id: snapshot.value.id,
  client_request_id: snapshot.value.id,
  revision: 1,
  message: snapshot.value.name,
  received_at: snapshot.value.created_at,
  execution_status: 'completed',
  trace_status: 'not_recorded',
  response: snapshot.value.response,
} : null)

const format = (value: unknown) => JSON.stringify(value, null, 2)

function docKind(filename: string) {
  return filename.toLowerCase().endsWith('.pdf') ? 'PDF' : 'MD'
}

function formatShortDate(iso: string) {
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return iso
  const diffMs = Date.now() - date.getTime()
  const mins = Math.floor(diffMs / 60000)
  if (mins >= 0 && mins < 1) return '刚刚'
  if (mins >= 1 && mins < 60) return `${mins} 分钟前`
  const hours = Math.floor(mins / 60)
  if (hours >= 1 && hours < 24) return `${hours} 小时前`
  return date.toLocaleDateString('zh-CN')
}

function report(e: unknown) {
  error.value = e instanceof Error ? e.message : '操作失败，请核对当前状态。'
  errorCode.value = e instanceof ApiError ? e.code : 'project_operation_failed'
}

function resetState() {
  editingInfo.value = false
  chatQuery.value = ''
  moveId.value = ''
  saveConversation.value = ''
  saveTurn.value = ''
  snapshotName.value = ''
  renameName.value = ''
  conversationDetail.value = null
  leftId.value = ''
  rightId.value = ''
  matchIds.value = false
  comparison.value = null
  tool.value = ''
  snapshot.value = null
  inlineResultOpen.value = false
  pending.value = null
  error.value = ''
  errorCode.value = ''
  message.value = ''
  sourceDragging.value = false
}

async function refresh(targetSnapshotId?: string) {
  const id = activeProjectId.value
  if (!id) return
  const token = ++loadToken
  loading.value = !current.value || current.value.id !== id
  try {
    const [all, mapping, detail, docs] = await Promise.all([
      api.list(),
      projectsApi.memberships(),
      projectsApi.detail(id),
      knowledgeApi.list(id).catch(() => [] as KnowledgeDocument[]),
      projectsStore.load(true).catch(() => undefined),
    ])
    if (token !== loadToken) return
    conversations.value = all
    memberships.value = mapping
    current.value = detail
    documents.value = docs
    editName.value = detail.name
    editDescription.value = detail.description || ''
    projectsStore.setSourceCount(detail.id, docs.filter(d => d.state === 'ready' || d.state === 'partial').length)
    const wantedSnapshot = targetSnapshotId || (snapshot.value && detail.snapshots.some(s => s.id === snapshot.value?.id) ? snapshot.value.id : '')
    if (wantedSnapshot && detail.snapshots.some(s => s.id === wantedSnapshot)) {
      await selectSnapshot(wantedSnapshot, false)
    } else if (snapshot.value && !detail.snapshots.some(s => s.id === snapshot.value?.id)) {
      snapshot.value = null
      inlineResultOpen.value = false
    }
  } catch (e) {
    if (token === loadToken) report(e)
  } finally {
    if (token === loadToken) loading.value = false
  }
}

async function open(
  projectId: string,
  tab: DrawerTab = 'context',
  options?: { snapshotId?: string; promptDelete?: boolean },
) {
  if (!projectId) return
  const projectChanged = activeProjectId.value !== projectId
  activeProjectId.value = projectId
  activeTab.value = options?.snapshotId ? 'snapshots' : tab
  if (projectChanged) {
    current.value = null
    documents.value = []
    resetState()
  } else {
    error.value = ''
    errorCode.value = ''
    message.value = ''
  }
  isOpen.value = true
  await nextTick()
  panelRef.value?.focus({ preventScroll: true })
  await refresh(options?.snapshotId)
  if (options?.promptDelete && current.value && !isDefaultCurrent.value) {
    await openConfirm('project-delete')
  }
}

function close() {
  if (busy.value) return
  confirmDialog.value?.close()
  confirmAction.value = ''
  isOpen.value = false
}

function onGlobalKeydown(event: KeyboardEvent) {
  if (!isOpen.value) return
  if (event.key === 'Escape' && !confirmDialog.value?.open && !busy.value) {
    event.preventDefault()
    close()
  }
}

onMounted(() => {
  window.addEventListener('keydown', onGlobalKeydown)
})

onBeforeUnmount(() => {
  window.removeEventListener('keydown', onGlobalKeydown)
  clearTimeout(copyTimer)
  confirmDialog.value?.close()
})

async function act(task: () => Promise<unknown>) {
  if (busy.value) return
  busy.value = true
  error.value = ''
  errorCode.value = ''
  message.value = ''
  try {
    await task()
    if (isOpen.value && activeProjectId.value) {
      await refresh()
      emit('updated', activeProjectId.value)
    }
  } catch (e) {
    report(e)
  } finally {
    busy.value = false
  }
}

function beginEditInstructions() {
  if (!current.value || busy.value) return
  editName.value = current.value.name
  editDescription.value = current.value.description || ''
  editingInfo.value = true
}

async function updateProject() {
  const p = current.value
  if (!p) return
  await act(async () => {
    await projectsApi.update(p, editName.value.trim(), editDescription.value)
    editingInfo.value = false
    message.value = '项目名称与指令已更新，项目内对话将自动生效。'
  })
}

async function addSources(fileList: FileList | File[]) {
  const project = current.value
  if (!project || busy.value || uploadingSources.value) return
  const valid: File[] = []
  const rejected: string[] = []
  for (const file of Array.from(fileList)) {
    const lower = file.name.toLowerCase()
    if (!lower.endsWith('.pdf') && !lower.endsWith('.md') && !lower.endsWith('.markdown')) {
      rejected.push(`${file.name}（仅支持 PDF / Markdown）`)
      continue
    }
    if (!file.size || file.size > MAX_SOURCE_BYTES) {
      rejected.push(`${file.name}（需非空且 ≤ 20 MiB）`)
      continue
    }
    valid.push(file)
  }
  if (!valid.length) {
    if (rejected.length) error.value = `未能添加来源：${rejected.join('；')}`
    return
  }
  uploadingSources.value = true
  busy.value = true
  error.value = ''
  errorCode.value = ''
  message.value = ''
  let revision = project.revision
  let readyAdded = 0
  const failures: string[] = [...rejected]
  try {
    for (let index = 0; index < valid.length; index++) {
      const file = valid[index]!
      sourceProgress.value = `正在上传并本地解析知识 (${index + 1}/${valid.length})：${file.name}…`
      try {
        if (index > 0) {
          const latest = await projectsApi.detail(project.id)
          revision = latest.revision
        }
        const result = await uploadDocument(project.id, file, {
          expected_revision: revision,
          client_request_id: crypto.randomUUID(),
          allow_duplicate: false,
          metadata: { title: null, authors: [], year: null, doi: null },
          restore_version_id: null,
        })
        if (result.document.state === 'ready' || result.document.state === 'partial') readyAdded++
        else failures.push(`${file.name}（${result.operation.message || '未能提取文本'}）`)
      } catch (reason) {
        failures.push(`${file.name}（${reason instanceof Error ? reason.message : '上传失败'}）`)
      }
    }
    await refresh()
    emit('updated', project.id)
    if (readyAdded) message.value = `已添加并解析 ${readyAdded} 份项目知识，项目内对话将自动参考这些文献。`
    if (failures.length) error.value = `部分来源未成功添加：${failures.join('；')}`
  } finally {
    sourceProgress.value = ''
    uploadingSources.value = false
    busy.value = false
  }
}

function onSourceFilesSelected(event: Event) {
  const input = event.target as HTMLInputElement
  if (input.files?.length) void addSources(input.files)
  input.value = ''
}

function onSourceDrop(event: DragEvent) {
  sourceDragging.value = false
  if (event.dataTransfer?.files?.length) void addSources(event.dataTransfer.files)
}

async function startChatInProject() {
  const p = current.value
  if (!p || busy.value) return
  busy.value = true
  error.value = ''
  errorCode.value = ''
  try {
    const created = await projectsStore.startConversationDetail(p.id)
    workbenchStore.preparedConversation = { ...created, turns: [] }
    void workbenchStore.refreshList().catch(() => undefined)
    isOpen.value = false
    await router.push(`/conversations/${created.id}`)
  } catch (e) {
    report(e)
  } finally {
    busy.value = false
  }
}

async function move(id: string, remove = false) {
  const p = current.value
  const c = conversations.value.find(item => item.id === id)
  if (!p || !c) return
  const sourceId = memberships.value[id] || null
  await act(async () => {
    const source = sourceId && sourceId !== p.id ? await projectsApi.detail(sourceId) : null
    await projectsApi.move(p.id, id, {
      expected_revision: p.revision,
      expected_conversation_revision: c.revision,
      expected_metadata_revision: c.metadata_revision,
      expected_source_project_id: sourceId,
      expected_source_revision: source?.revision ?? null,
    }, remove)
    moveId.value = ''
    conversationDetail.value = null
    saveConversation.value = ''
    saveTurn.value = ''
    message.value = remove ? '已将会话移出此项目。' : '已将会话归入此项目。'
  })
}

watch(saveConversation, async id => {
  const token = ++conversationSelection
  conversationDetail.value = null
  saveTurn.value = ''
  if (!id) return
  try {
    const c = await api.detail(id)
    if (token === conversationSelection) {
      conversationDetail.value = c
      saveTurn.value = c.turns.find(t => t.response_status)?.turn_id || ''
    }
  } catch (e) {
    if (token === conversationSelection) report(e)
  }
})

async function saveSnapshot() {
  const p = current.value
  if (!p) return
  let savedId = ''
  await act(async () => {
    const s = await projectsApi.save(p, saveConversation.value, saveTurn.value, snapshotName.value.trim())
    savedId = s.id
    snapshotName.value = ''
    message.value = '已保存完整快照，原响应不会随重跑改变。'
  })
  if (savedId) await selectSnapshot(savedId)
}

async function selectSnapshot(id: string, showSnapshotTab = true) {
  const p = current.value
  if (!p) return
  const token = ++snapshotToken
  try {
    const value = await projectsApi.snapshot(p.id, id)
    if (token !== snapshotToken || current.value?.id !== p.id) return
    snapshot.value = value
    renameName.value = value.name
    tool.value = ''
    if (showSnapshotTab) activeTab.value = 'snapshots'
  } catch (e) {
    if (token === snapshotToken) report(e)
  }
}

function inspectInWorkbench() {
  if (!snapshot.value) return
  emit('inspect-snapshot', snapshot.value)
  isOpen.value = false
}

async function renameSnapshot() {
  const p = current.value
  const s = snapshot.value
  if (p && s) {
    await act(async () => {
      await projectsApi.renameSnapshot(p, s.id, renameName.value.trim())
      message.value = '快照名称已更新。'
    })
  }
}

async function compareSnapshots() {
  const p = current.value
  if (!p) return
  await act(async () => {
    const result = await projectsApi.compare(p.id, leftId.value, rightId.value, matchIds.value)
    if (current.value?.id === p.id) comparison.value = result
  })
}

async function downloadArchive() {
  const p = current.value
  if (!p) return
  if (archiveFormat.value >= 3 && knowledgeMode.value === 'full') await openConfirm('archive')
  else await act(() => exportProject(p, archiveFormat.value, knowledgeMode.value))
}

async function copyProjectId() {
  if (!current.value) return
  try {
    await navigator.clipboard.writeText(current.value.id)
    copiedId.value = true
    clearTimeout(copyTimer)
    copyTimer = setTimeout(() => { copiedId.value = false }, 1800)
  } catch { /* Clipboard unavailable in non-secure contexts. */ }
}

async function openConfirm(kind: typeof confirmAction.value) {
  confirmAction.value = kind
  await nextTick()
  confirmDialog.value?.showModal()
}

async function executeConfirm() {
  const kind = confirmAction.value
  const p = current.value
  const s = snapshot.value
  if (!p) return
  confirmDialog.value?.close()
  confirmAction.value = ''
  if (kind === 'archive') {
    await act(() => exportProject(p, archiveFormat.value, 'full', true))
  } else if (kind === 'project-delete') {
    busy.value = true
    error.value = ''
    errorCode.value = ''
    try {
      const deletedId = p.id
      await projectsApi.delete(p)
      projectsStore.removeLocal(deletedId)
      current.value = null
      snapshot.value = null
      isOpen.value = false
      emit('deleted', deletedId)
    } catch (e) {
      report(e)
    } finally {
      busy.value = false
    }
  } else if (kind === 'snapshot-delete' && s) {
    await act(async () => {
      await projectsApi.deleteSnapshot(p, s.id)
      snapshot.value = null
      inlineResultOpen.value = false
      message.value = '已删除该快照，原会话记录仍可查看。'
    })
  } else if (kind === 'rerun' && s && selectedTool.value) {
    const [family, index] = tool.value.split(':')
    pending.value = {
      project: p.id,
      snapshot: s.id,
      payload: {
        family: family as RerunRequest['family'],
        result_index: Number(index),
        expected_revision: p.revision,
        client_request_id: crypto.randomUUID(),
        confirmed: true,
      },
    }
    await executePending()
  }
}

async function executePending() {
  const item = pending.value
  if (!item) return
  let nextSnapshotId = ''
  await act(async () => {
    try {
      const result = await projectsApi.rerun(item.project, item.snapshot, item.payload)
      pending.value = null
      message.value = `重跑执行状态：${result.state}；数据状态：${result.response_status || '尚无响应'}。${result.snapshot_id ? '结果已独立保存，未调用模型。' : '本次没有可交付快照，请核对记录。'}`
      if (current.value?.id === item.project && result.snapshot_id) {
        nextSnapshotId = result.snapshot_id
      }
    } catch (e) {
      if (!(e instanceof ApiError) || e.status !== 0) pending.value = null
      throw e
    }
  })
  if (nextSnapshotId) await selectSnapshot(nextSnapshotId)
}

function modulePath(section: 'knowledge' | 'rag' | 'workflows' | 'compute' | 'overview', subId?: string) {
  const id = current.value?.id || ''
  if (!id) return '/'
  if (section === 'overview') return `/projects/${id}/overview`
  const base = isDefaultCurrent.value ? `/${section}` : `/projects/${id}/${section}`
  return subId ? `${base}/${subId}` : base
}

function navigateAndClose(to: string) {
  isOpen.value = false
  void router.push(to)
}

defineExpose({ open, close })
</script>

<template>
  <Teleport to="body">
    <Transition name="project-drawer">
      <div v-if="isOpen" class="project-drawer-backdrop" @click.self="close">
        <aside
          ref="panelRef"
          class="project-drawer-panel"
          role="dialog"
          aria-modal="true"
          :aria-label="`管理项目：${projectDisplayName}`"
          tabindex="-1"
        >
          <header class="project-drawer-head">
            <div class="project-drawer-title-group">
              <span class="project-drawer-icon" aria-hidden="true">
                <svg viewBox="0 0 24 24"><path d="M3 7V5a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2Z" /></svg>
              </span>
              <div class="project-drawer-title-copy">
                <div class="project-drawer-title-row">
                  <h2 :title="projectDisplayName">{{ projectDisplayName }}</h2>
                  <span v-if="current" class="ui-pill ui-pill-neutral">r{{ current.revision }}</span>
                  <span v-if="current?.provenance === 'imported_unverified'" class="ui-pill ui-pill-warning">导入 · 未认证</span>
                </div>
                <p class="project-drawer-sub">
                  <template v-if="hasInstructions && readySourceCount">项目指令已生效 · {{ readySourceCount }} 份本地参考知识生效中</template>
                  <template v-else-if="hasInstructions">项目指令已生效 · 可继续拖入 PDF / Markdown 文献</template>
                  <template v-else-if="readySourceCount">{{ readySourceCount }} 份本地参考知识生效中 · 可补充项目指令</template>
                  <template v-else>配置项目指令、参考知识、可复现快照与离线备份</template>
                </p>
              </div>
            </div>
            <button type="button" class="dialog-close" aria-label="关闭项目管理面板" :disabled="busy" @click="close">
              <svg viewBox="0 0 24 24" aria-hidden="true"><path d="m6 6 12 12M6 18 18 6" /></svg>
            </button>
          </header>

          <div class="project-drawer-tabs">
            <div class="ui-segmented" role="tablist" aria-label="项目管理分组">
              <button type="button" role="tab" :aria-selected="activeTab === 'context'" @click="activeTab = 'context'">
                <span>指令与知识</span>
                <span class="ui-count">{{ documents.length }}</span>
              </button>
              <button type="button" role="tab" :aria-selected="activeTab === 'snapshots'" @click="activeTab = 'snapshots'">
                <span>快照与复核</span>
                <span class="ui-count">{{ current?.snapshots.length ?? 0 }}</span>
              </button>
              <button type="button" role="tab" :aria-selected="activeTab === 'manage'" @click="activeTab = 'manage'">
                <span>会话与备份</span>
                <span class="ui-count">{{ members.length }}</span>
              </button>
            </div>
          </div>

          <div class="project-drawer-body">
            <div v-if="error" class="notice danger" role="alert">
              <p>{{ error }}</p>
              <code v-if="errorCode">{{ errorCode }}</code>
            </div>
            <p v-if="message" class="notice info" role="status">{{ message }}</p>
            <p v-if="loading && !current" class="processing" role="status">正在读取项目配置与关联记录…</p>
            <p v-if="busy" class="processing" role="status">{{ sourceProgress || '正在处理，请稍候。不会自动重复提交。' }}</p>
            <div v-if="pending" class="notice">
              <p>重跑请求尚未确认。先核对项目记录，断线不会取消后台查询。</p>
              <button type="button" :disabled="busy" @click="executePending">用原请求编号核对重跑</button>
            </div>
            <p v-if="current?.provenance === 'imported_unverified'" class="notice warning">
              导入来源未经认证。归档哈希只验证包内完整性；历史查询结果不会因导入而重新执行。
            </p>

            <template v-if="current">
              <!-- TAB 1: Project Instructions + Knowledge Sources + Module Links -->
              <div v-if="activeTab === 'context'" class="drawer-stack" role="tabpanel" aria-label="指令与知识">
                <section class="ui-card drawer-card">
                  <div class="drawer-card-head">
                    <div class="drawer-card-title">
                      <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 20h9M16.5 3.5a2.12 2.12 0 1 1 3 3L7 19l-4 1 1-4Z" /></svg>
                      <h3>项目指令</h3>
                      <span class="ui-pill" :class="hasInstructions ? 'ui-pill-success' : 'ui-pill-neutral'">{{ hasInstructions ? '已生效' : '未设置' }}</span>
                    </div>
                    <button type="button" class="drawer-inline-btn" :disabled="busy" @click="editingInfo ? (editingInfo = false) : beginEditInstructions()">
                      {{ editingInfo ? '取消' : '编辑' }}
                    </button>
                  </div>

                  <form v-if="editingInfo" class="project-form drawer-edit-form" @submit.prevent="updateProject">
                    <label for="drawer-project-name">项目名称</label>
                    <input id="drawer-project-name" v-model="editName" maxlength="100" required :disabled="busy">
                    <div class="drawer-field-head">
                      <label for="drawer-project-desc">项目指令与研究背景</label>
                      <span class="drawer-char-count">{{ editDescription.length }}/2000</span>
                    </div>
                    <textarea
                      id="drawer-project-desc"
                      v-model="editDescription"
                      maxlength="2000"
                      rows="6"
                      placeholder="例如：聚焦 M45 疏散星团，默认优先 Gaia DR3 与 2020 年后文献，回答先给关键统计与单位口径…"
                      :disabled="busy"
                    />
                    <div class="drawer-form-actions">
                      <button type="button" :disabled="busy" @click="editingInfo = false">取消</button>
                      <button type="submit" class="button-primary" :disabled="busy || !editName.trim()">保存修改</button>
                    </div>
                  </form>
                  <template v-else>
                    <div v-if="hasInstructions" class="drawer-instructions-body">{{ current.description }}</div>
                    <button v-else type="button" class="drawer-empty-prompt" :disabled="busy" @click="beginEditInstructions">
                      ＋ 添加项目指令：设定目标天体、筛选口径、分析约束或回答偏好…
                    </button>
                    <p class="drawer-footnote">本项目内所有对话均会自动携带此指令（不覆盖系统安全规则，不替代实时数据库查询）。</p>
                  </template>
                </section>

                <section
                  class="ui-card drawer-card drawer-knowledge-card"
                  :class="{ 'is-dragging': sourceDragging }"
                  @dragenter.prevent="sourceDragging = !busy"
                  @dragover.prevent="sourceDragging = !busy"
                  @dragleave.prevent="sourceDragging = false"
                  @drop.prevent="onSourceDrop"
                >
                  <div class="drawer-card-head">
                    <div class="drawer-card-title">
                      <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2Z" /></svg>
                      <h3>项目知识</h3>
                      <span class="ui-pill ui-pill-neutral">{{ documents.length }} 份</span>
                    </div>
                    <button type="button" class="drawer-inline-btn" :disabled="busy" @click="sourceFileInput?.click()">＋ 添加</button>
                  </div>

                  <input
                    ref="sourceFileInput"
                    type="file"
                    multiple
                    accept=".pdf,.md,.markdown"
                    class="sr-only"
                    :disabled="busy"
                    @change="onSourceFilesSelected"
                  >

                  <div v-if="documents.length" class="drawer-source-list">
                    <button
                      v-for="doc in documents"
                      :key="doc.id"
                      type="button"
                      class="drawer-source-item"
                      @click="navigateAndClose(modulePath('knowledge', doc.id))"
                    >
                      <span class="ui-file-badge">{{ docKind(doc.filename) }}</span>
                      <div class="drawer-source-meta">
                        <b :title="doc.metadata.title || doc.filename">{{ doc.metadata.title || doc.filename }}</b>
                        <small>{{ doc.filename }}</small>
                      </div>
                      <span class="tag" :class="{ error: doc.state === 'failed' || doc.state === 'unavailable', partial: doc.state === 'partial' }">{{ docStateLabels[doc.state] || doc.state }}</span>
                    </button>
                  </div>
                  <button v-else type="button" class="drawer-dropzone" :disabled="busy" @click="sourceFileInput?.click()">
                    <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 15V4m-4 4 4-4 4 4M4 15v3a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-3" /></svg>
                    <span>点击或拖放 PDF / Markdown 文献</span>
                    <small>单文件 ≤ 20 MiB · 项目内对话自动检索参考</small>
                  </button>

                  <div class="drawer-card-footer">
                    <button type="button" class="drawer-link-btn" @click="navigateAndClose(modulePath('rag'))">文献问答 →</button>
                    <button type="button" class="drawer-link-btn" @click="navigateAndClose(modulePath('knowledge'))">管理知识库 →</button>
                  </div>
                </section>

                <section class="ui-card-subtle drawer-card">
                  <div class="drawer-card-head">
                    <div class="drawer-card-title">
                      <h3>关联研究模块</h3>
                    </div>
                  </div>
                  <div class="drawer-modules-grid">
                    <button type="button" class="drawer-module-tile" @click="navigateAndClose(modulePath('knowledge'))">
                      <span class="drawer-module-top"><b>本地知识库</b><span class="ui-pill ui-pill-neutral">{{ current.document_count }} 份</span></span>
                      <small>原文检索、多版本留存与定位核对</small>
                    </button>
                    <button type="button" class="drawer-module-tile" @click="navigateAndClose(modulePath('rag'))">
                      <span class="drawer-module-top"><b>文献知识问答</b><span class="ui-pill ui-pill-ads">{{ current.rag_answer_count }} 条</span></span>
                      <small>本地混合检索与发送前片段审阅</small>
                    </button>
                    <button type="button" class="drawer-module-tile" @click="navigateAndClose(modulePath('workflows'))">
                      <span class="drawer-module-top"><b>科研流程</b><span class="ui-pill ui-pill-simbad">{{ current.workflow_count }} 次</span></span>
                      <small>固定步骤模板、断点检查与产物下载</small>
                    </button>
                    <button type="button" class="drawer-module-tile" @click="navigateAndClose(modulePath('compute'))">
                      <span class="drawer-module-top"><b>N 体计算记录</b><span class="ui-pill ui-pill-compute">历史实验</span></span>
                      <small>查看已保存的 REBOUND / PeTar 动力学结果</small>
                    </button>
                    <button type="button" class="drawer-module-tile" @click="navigateAndClose(modulePath('overview'))">
                      <span class="drawer-module-top"><b>来源关联</b><span class="ui-pill ui-pill-neutral">{{ current.link_count }} 条</span></span>
                      <small>建立对话、快照与原文证据显式映射</small>
                    </button>
                  </div>
                </section>
              </div>

              <!-- TAB 2: Snapshots, Single-Tool Rerun & Comparison -->
              <div v-else-if="activeTab === 'snapshots'" class="drawer-stack" role="tabpanel" aria-label="快照与复核">
                <section class="ui-card drawer-card">
                  <div class="drawer-card-head">
                    <div>
                      <h3 class="ui-card-title">命名快照 <span class="small muted">{{ current.snapshots.length }}/100</span></h3>
                      <p class="small muted" style="margin: 4px 0 0;">固定保存完整天文交付响应，重跑与比较均保持旧结果不可变。</p>
                    </div>
                  </div>

                  <div v-if="current.snapshots.length" class="drawer-snapshot-list">
                    <div v-for="s in current.snapshots" :key="s.id" class="snapshot-row" :class="{ selected: snapshot?.id === s.id }">
                      <button type="button" :aria-label="`查看快照 ${s.name}`" @click="selectSnapshot(s.id)">
                        <div class="drawer-snapshot-top">
                          <b>{{ s.name }}</b>
                          <span class="tag">{{ s.status }}</span>
                          <span v-if="s.provenance === 'imported_unverified'" class="ui-pill ui-pill-warning">导入 · 未认证</span>
                        </div>
                        <small>{{ formatShortDate(s.created_at) }} · <code>{{ s.id.slice(0, 8) }}</code></small>
                      </button>
                    </div>
                  </div>
                  <p v-else class="small muted">尚无命名快照，可展开下方从项目内会话保存。</p>

                  <details class="drawer-sub-disclosure">
                    <summary>从项目会话保存新快照</summary>
                    <form class="project-form" @submit.prevent="saveSnapshot">
                      <label for="drawer-save-conversation">项目内会话</label>
                      <select id="drawer-save-conversation" v-model="saveConversation">
                        <option value="">选择会话</option>
                        <option v-for="c in members" :key="c.id" :value="c.id">{{ c.title }}</option>
                      </select>
                      <label for="drawer-save-turn">完整查询结果</label>
                      <select id="drawer-save-turn" v-model="saveTurn">
                        <option value="">选择查询结果</option>
                        <option v-for="t in deliverable" :key="t.turn_id" :value="t.turn_id">{{ t.message.slice(0, 50) }} · {{ formatShortDate(t.received_at) }}</option>
                      </select>
                      <label for="drawer-snapshot-name">快照名称</label>
                      <input id="drawer-snapshot-name" v-model="snapshotName" maxlength="100" placeholder="例如：M45 Gaia DR3 5′ 基线样本">
                      <button type="submit" class="button-primary" :disabled="busy || !saveTurn || !snapshotName.trim()">保存完整快照</button>
                    </form>
                  </details>
                </section>

                <section v-if="snapshot" class="ui-card drawer-card">
                  <div class="drawer-card-head">
                    <div style="min-width: 0;">
                      <h3 class="ui-card-title">当前快照：{{ snapshot.name }}</h3>
                      <code class="drawer-sha">SHA-256 {{ snapshot.sha256 }}</code>
                    </div>
                  </div>
                  <div class="drawer-snapshot-actions">
                    <button v-if="canInspectInWorkbench" type="button" class="button-primary" @click="inspectInWorkbench">在结果栏查看数据</button>
                    <button v-else type="button" class="button-secondary" @click="inlineResultOpen = !inlineResultOpen">{{ inlineResultOpen ? '收起数据预览' : '展开数据预览' }}</button>
                    <button type="button" class="drawer-link-btn" @click="navigateAndClose(`/projects/${snapshot.project_id}/overview?target_type=snapshot&target_id=${encodeURIComponent(snapshot.id)}`)">关联本地原文证据 →</button>
                  </div>
                  <div v-if="!canInspectInWorkbench && inlineResultOpen" class="drawer-inline-result">
                    <ResultPanel
                      :turn="snapshotTurn"
                      :historical="true"
                      :heading="snapshot.name"
                      :artifact-path="`/api/v1/projects/${snapshot.project_id}/snapshots/${snapshot.id}/artifacts`"
                    />
                  </div>
                  <p v-if="!snapshot.conversation_id" class="small muted">原会话已移出项目或删除；完整响应副本仍保留。</p>
                  <form class="inline-form" @submit.prevent="renameSnapshot">
                    <label class="sr-only" for="drawer-rename-snapshot">修改快照名称</label>
                    <input id="drawer-rename-snapshot" v-model="renameName" maxlength="100">
                    <button type="submit" :disabled="busy || !renameName.trim()">快照改名</button>
                    <button type="button" :disabled="busy" class="button-danger" @click="openConfirm('snapshot-delete')">删除快照</button>
                  </form>
                  <details class="drawer-sub-disclosure">
                    <summary>原始来源与软件版本</summary>
                    <pre class="drawer-pre">{{ format({ origin: snapshot.origin, software: snapshot.software, provenance: snapshot.provenance }) }}</pre>
                  </details>
                  <div class="project-form">
                    <label for="drawer-rerun-tool">选择单条工具查询重跑</label>
                    <select id="drawer-rerun-tool" v-model="tool">
                      <option value="">选择查询，先核对参数</option>
                      <option v-for="t in tools" :key="t.value" :value="t.value">{{ t.label }}</option>
                    </select>
                    <template v-if="selectedTool">
                      <pre class="drawer-pre">{{ format({ parameters: selectedTool.parameters, source: selectedTool.source }) }}</pre>
                      <p v-if="tool.startsWith('gaia:')" class="notice">Gaia 重跑沿用已记录的实际坐标与参数，不重新解析天体名称。历史来源时间见上方；需要重新解析时请返回对话独立查询 SIMBAD。</p>
                      <button type="button" class="button-primary" :disabled="busy || !!pending" @click="openConfirm('rerun')">核对并重跑单条查询</button>
                    </template>
                  </div>
                </section>

                <details v-if="current.snapshots.length >= 2" class="ui-card drawer-disclosure-card">
                  <summary>比较两份快照</summary>
                  <div class="project-form">
                    <div class="compare-selectors">
                      <label>左侧快照<select v-model="leftId"><option value="">选择快照</option><option v-for="s in current.snapshots" :key="s.id" :value="s.id">{{ s.name }} · {{ s.id.slice(0, 8) }}</option></select></label>
                      <label>右侧快照<select v-model="rightId"><option value="">选择快照</option><option v-for="s in current.snapshots" :key="s.id" :value="s.id">{{ s.name }} · {{ s.id.slice(0, 8) }}</option></select></label>
                    </div>
                    <label class="match-identifiers"><input v-model="matchIds" type="checkbox">按精确 source_id / bibcode 比较交付编号</label>
                    <button type="button" :disabled="busy || !leftId || !rightId" @click="compareSnapshots">比较已存快照</button>
                    <div v-if="comparison" class="comparison">
                      <p v-for="warning in comparison.warnings" :key="warning" class="notice">{{ warning }}</p>
                      <div class="comparison-columns">
                        <details open><summary>左侧条件、状态与来源</summary><pre class="drawer-pre">{{ format(comparison.left) }}</pre></details>
                        <details open><summary>右侧条件、状态与来源</summary><pre class="drawer-pre">{{ format(comparison.right) }}</pre></details>
                      </div>
                      <details open><summary>结构化字段差异（{{ comparison.differences.length }}）</summary><pre class="drawer-pre">{{ format(comparison.differences) }}</pre></details>
                      <details><summary>交集与独有编号</summary><pre class="drawer-pre">{{ format(comparison.identifiers) }}</pre></details>
                    </div>
                  </div>
                </details>

                <details v-if="current.reruns.length" class="ui-card drawer-disclosure-card">
                  <summary>直接重跑记录 · {{ current.reruns.length }} 条</summary>
                  <div class="project-form">
                    <article v-for="r in current.reruns" :key="r.id" class="rerun-row">
                      <span class="tag">{{ r.state }}</span> {{ r.family }} · 数据状态 {{ r.response_status || '尚无响应' }} · <time>{{ r.created_at }}</time>
                      <p v-if="r.error" class="notice danger">{{ r.error.message }} · {{ r.error.code }}</p>
                      <button v-if="r.snapshot_id" type="button" @click="selectSnapshot(r.snapshot_id)">查看重跑新快照</button>
                      <details><summary>实际参数与记录编号</summary><pre class="drawer-pre">{{ format(r) }}</pre></details>
                    </article>
                  </div>
                </details>
              </div>

              <!-- TAB 3: Conversations, Backup Export & Project Governance -->
              <div v-else class="drawer-stack" role="tabpanel" aria-label="会话与备份">
                <section class="ui-card drawer-card">
                  <div class="drawer-card-head">
                    <div class="drawer-card-title">
                      <h3>项目内会话</h3>
                      <span class="ui-pill ui-pill-neutral">{{ members.length }} 个</span>
                    </div>
                    <button type="button" class="drawer-inline-btn" :disabled="busy" @click="startChatInProject">＋ 新建对话</button>
                  </div>

                  <div v-if="members.length > 3" class="drawer-filter-bar">
                    <svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="11" cy="11" r="7" /><path d="m20 20-3.5-3.5" /></svg>
                    <input v-model="chatQuery" type="search" placeholder="搜索项目内对话…" aria-label="搜索项目内对话">
                  </div>

                  <div v-if="filteredMembers.length" class="drawer-chat-list">
                    <div v-for="c in filteredMembers" :key="c.id" class="drawer-chat-row">
                      <button type="button" class="drawer-chat-link" @click="navigateAndClose(`/conversations/${c.id}`)">
                        <b :title="c.title">{{ c.title }}</b>
                        <small>{{ formatShortDate(c.updated_at) }}</small>
                      </button>
                      <button type="button" class="drawer-chat-remove" :disabled="busy" @click="move(c.id, true)">移出</button>
                    </div>
                  </div>
                  <p v-else class="small muted">此项目尚无关联对话，可点击右上角新建或从下方归入已有会话。</p>

                  <form v-if="movable.length" class="drawer-assign-strip" @submit.prevent="move(moveId)">
                    <label class="sr-only" for="drawer-move-conversation">选择要加入的会话</label>
                    <select id="drawer-move-conversation" v-model="moveId" :disabled="busy">
                      <option value="">将已有会话归入本项目…</option>
                      <option v-for="c in movable" :key="c.id" :value="c.id">{{ c.title }}{{ memberships[c.id] ? '（从其他项目移动）' : '（未归属项目）' }}</option>
                    </select>
                    <button type="submit" :disabled="busy || !moveId">加入项目</button>
                  </form>
                </section>

                <section class="ui-card drawer-card">
                  <div class="drawer-card-head">
                    <div class="drawer-card-title">
                      <h3>导出项目备份包（ZIP 迁移格式）</h3>
                    </div>
                  </div>
                  <p class="small muted" style="margin: 0;">将本项目的会话、快照、知识库与实验记录打包为离线 ZIP；可在「设置 → 数据管理」中导入恢复。</p>
                  <div class="project-form" style="margin-top: 10px;">
                    <label class="small">
                      备份格式
                      <select v-model="archiveFormat" aria-label="项目备份格式">
                        <option :value="6">格式 6（含数据绘图与文献问答）</option>
                        <option :value="5">格式 5（含文献问答，不含绘图）</option>
                        <option :value="4" :disabled="!!current.rag_answer_count || !!current.rag_request_count">V0.9 格式 4（含显式关联）</option>
                        <option :value="3" :disabled="current.link_count > 0 || current.link_request_count > 0 || current.rag_request_count > 0">V0.8 格式 3（无关联历史）</option>
                        <option :value="2" :disabled="current.document_count > 0 || current.knowledge_evidence_count > 0 || current.link_count > 0 || current.link_request_count > 0 || current.rag_request_count > 0">V0.7 格式 2（无知识库）</option>
                        <option :value="1" :disabled="current.workflow_count > 0 || current.document_count > 0 || current.knowledge_evidence_count > 0 || current.link_count > 0 || current.link_request_count > 0 || current.rag_request_count > 0">V0.6 格式 1（仅无流程项目）</option>
                      </select>
                    </label>
                    <label v-if="archiveFormat >= 3" class="small">
                      文献原文
                      <select v-model="knowledgeMode">
                        <option value="metadata">仅元数据（保留标题、检索词及记录）</option>
                        <option value="full">完整备份（含全部原文）</option>
                      </select>
                    </label>
                    <button type="button" :disabled="busy" @click="downloadArchive">导出项目备份 ZIP</button>
                  </div>
                </section>

                <section class="ui-card-subtle drawer-card">
                  <div class="drawer-card-head">
                    <div class="drawer-card-title">
                      <h3>项目元信息与管理</h3>
                    </div>
                  </div>
                  <div class="drawer-meta-body">
                    <div class="drawer-meta-row">
                      <span>项目编号</span>
                      <button type="button" class="drawer-copy-id" :title="current.id" @click="copyProjectId">
                        <code>{{ current.id.slice(0, 12) }}…</code>
                        <span>{{ copiedId ? '已复制' : '复制' }}</span>
                      </button>
                    </div>
                    <div class="drawer-meta-row">
                      <span>来源属性</span>
                      <b>{{ current.provenance === 'imported_unverified' ? '导入 · 未认证' : '本地创建' }}</b>
                    </div>
                    <div class="drawer-meta-row">
                      <span>修订版本</span>
                      <b>r{{ current.revision }}</b>
                    </div>
                    <button v-if="!isDefaultCurrent" type="button" class="button-danger drawer-delete-btn" :disabled="busy" @click="openConfirm('project-delete')">
                      删除项目
                    </button>
                  </div>
                </section>
              </div>
            </template>
          </div>
        </aside>
      </div>
    </Transition>

    <dialog ref="confirmDialog" class="project-dialog" @close="confirmAction = ''" @cancel="confirmAction = ''">
      <div class="dialog-header">
        <div class="dialog-header-copy">
          <h2>{{ confirmAction === 'archive' ? '导出含文献原文的完整备份？' : confirmAction === 'rerun' ? '确认执行这条工具查询？' : confirmAction === 'project-delete' ? '删除这个科研项目？' : '删除这份命名快照？' }}</h2>
        </div>
        <button type="button" class="dialog-close" aria-label="关闭" :disabled="busy" @click="confirmDialog?.close()">
          <svg viewBox="0 0 24 24" aria-hidden="true"><path d="m6 6 12 12M6 18 18 6" /></svg>
        </button>
      </div>
      <form class="project-form" @submit.prevent="executeConfirm">
        <template v-if="confirmAction === 'archive'">
          <p>将复制 {{ current?.document_count || 0 }} 份文档、{{ current?.document_version_count || 0 }} 个版本，原文件合计 {{ current?.document_bytes || 0 }} 字节，连同项目记录写入 ZIP。文件将包含你的文献原文，请自行管理下载副本。</p>
        </template>
        <template v-else-if="confirmAction === 'rerun'">
          <p>将按下列参数访问真实数据源，保存新的查询结果和快照。旧响应不覆盖；本操作不调用语言模型，断线不代表取消。</p>
          <pre class="drawer-pre">{{ format(selectedTool) }}</pre>
        </template>
        <p v-else-if="confirmAction === 'project-delete'">将删除此项目、{{ current?.rag_answer_count || 0 }} 条文献问答、命名快照、重跑记录、{{ current?.workflow_count || 0 }} 次科研流程、{{ current?.link_count || 0 }} 条关联以及知识库原文与索引；会话及其中的消息将移至个人空间。</p>
        <p v-else>只删除这份快照，原会话记录仍可查看。</p>
        <div class="project-actions">
          <button type="button" :disabled="busy" @click="confirmDialog?.close()">取消</button>
          <button :disabled="busy" :class="confirmAction === 'project-delete' || confirmAction === 'snapshot-delete' ? 'button-danger' : 'button-primary'" type="submit">
            {{ confirmAction === 'archive' ? '确认导出全部原文' : confirmAction === 'rerun' ? '确认访问数据源并重跑' : '确认删除' }}
          </button>
        </div>
      </form>
    </dialog>
  </Teleport>
</template>

<style scoped>
.project-drawer-backdrop {
  position: fixed;
  inset: 0;
  z-index: 60;
  display: flex;
  justify-content: flex-end;
  background: rgb(15 24 36 / 34%);
  -webkit-backdrop-filter: blur(4px);
  backdrop-filter: blur(4px);
}

.project-drawer-panel {
  display: flex;
  flex-direction: column;
  width: min(620px, 100vw);
  height: 100dvh;
  max-height: 100dvh;
  border-left: 1px solid var(--line-strong);
  background: var(--surface-float, var(--surface-card));
  box-shadow: var(--shadow-float, var(--shadow-card-hover));
  color: var(--ink);
  outline: none;
}

.project-drawer-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  padding: 18px 20px 14px;
  border-bottom: 1px solid var(--line);
}

.project-drawer-title-group {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  min-width: 0;
  flex: 1;
}

.project-drawer-icon {
  display: grid;
  place-items: center;
  width: 38px;
  height: 38px;
  flex: 0 0 38px;
  border-radius: 10px;
  border: 1px solid color-mix(in srgb, var(--accent) 26%, var(--line));
  background: var(--accent-soft);
  color: var(--accent);
}

.project-drawer-icon svg {
  width: 19px;
  height: 19px;
  fill: none;
  stroke: currentColor;
  stroke-width: 1.7;
  stroke-linecap: round;
  stroke-linejoin: round;
}

.project-drawer-title-copy {
  min-width: 0;
  flex: 1;
}

.project-drawer-title-row {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.project-drawer-title-row h2 {
  margin: 0;
  font-size: 16.5px;
  font-weight: 600;
  color: var(--ink);
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.project-drawer-sub {
  margin: 4px 0 0;
  font-size: 12px;
  color: var(--muted);
  line-height: 1.5;
}

.project-drawer-tabs {
  flex: none;
  padding: 10px 20px;
  border-bottom: 1px solid var(--line);
  background: color-mix(in srgb, var(--surface-tint) 60%, transparent);
}

.project-drawer-body {
  flex: 1 1 0;
  min-height: 0;
  overflow: auto;
  padding: 16px 20px 28px;
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.drawer-stack {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.drawer-card {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 16px;
}

.drawer-card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.drawer-card-title {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.drawer-card-title svg {
  width: 16px;
  height: 16px;
  flex: none;
  fill: none;
  stroke: var(--accent);
  stroke-width: 1.75;
  stroke-linecap: round;
  stroke-linejoin: round;
}

.drawer-card-title h3 {
  margin: 0;
  font-size: 14px;
  font-weight: 600;
  color: var(--ink);
}

.drawer-inline-btn {
  height: 30px;
  min-height: 30px;
  padding: 0 11px;
  font-size: 12px;
  border-radius: var(--radius-control, 8px);
}

.drawer-edit-form {
  margin-top: 2px;
}

.drawer-field-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.drawer-char-count {
  font-size: 11px;
  color: var(--muted);
  font-variant-numeric: tabular-nums;
}

.drawer-form-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 4px;
}

.drawer-instructions-body {
  padding: 12px 14px;
  border: 1px solid var(--line);
  border-radius: 10px;
  background: var(--surface-tint);
  color: var(--ink);
  font-size: 13px;
  line-height: 1.7;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}

.drawer-empty-prompt {
  width: 100%;
  padding: 12px 14px;
  border: 1px dashed var(--line-strong);
  border-radius: 10px;
  background: transparent;
  color: var(--muted);
  font-size: 12.5px;
  text-align: left;
  box-shadow: none;
}

.drawer-empty-prompt:hover:not(:disabled) {
  border-color: var(--accent);
  background: var(--accent-soft);
  color: var(--accent);
  box-shadow: none;
}

.drawer-footnote {
  margin: 0;
  font-size: 11.5px;
  color: var(--muted);
  line-height: 1.55;
}

.drawer-knowledge-card.is-dragging {
  border-color: var(--accent);
  box-shadow: 0 0 0 2px color-mix(in srgb, var(--accent) 24%, transparent);
}

.drawer-source-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.drawer-source-item {
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
  min-height: 48px;
  padding: 8px 10px;
  border: 1px solid var(--line);
  border-radius: 10px;
  background: var(--surface-tint);
  color: var(--ink);
  text-align: left;
  box-shadow: none;
  transform: none;
}

.drawer-source-item:hover {
  border-color: color-mix(in srgb, var(--accent) 40%, var(--line));
  background: var(--accent-soft);
  box-shadow: none;
  transform: none;
}

.drawer-source-meta {
  display: grid;
  gap: 2px;
  flex: 1;
  min-width: 0;
}

.drawer-source-meta b {
  font-size: 12.5px;
  font-weight: 550;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.drawer-source-meta small {
  font-size: 11px;
  color: var(--muted);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.drawer-dropzone {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 6px;
  width: 100%;
  padding: 20px 14px;
  border: 1px dashed var(--line-strong);
  border-radius: 10px;
  background: transparent;
  color: var(--ink);
  box-shadow: none;
}

.drawer-dropzone svg {
  width: 22px;
  height: 22px;
  fill: none;
  stroke: var(--accent);
  stroke-width: 1.7;
  stroke-linecap: round;
  stroke-linejoin: round;
}

.drawer-dropzone span {
  font-size: 13px;
  font-weight: 550;
}

.drawer-dropzone small {
  font-size: 11.5px;
  color: var(--muted);
}

.drawer-dropzone:hover:not(:disabled) {
  border-color: var(--accent);
  background: var(--accent-soft);
  box-shadow: none;
}

.drawer-card-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding-top: 8px;
  border-top: 1px solid var(--line);
}

.drawer-link-btn {
  padding: 4px 8px;
  min-height: 28px;
  border: 0;
  border-radius: 6px;
  background: transparent;
  color: var(--accent);
  font-size: 12px;
  font-weight: 550;
  box-shadow: none;
  transform: none;
}

.drawer-link-btn:hover {
  background: var(--accent-soft);
  border: 0;
  box-shadow: none;
  transform: none;
}

.drawer-modules-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
}

.drawer-module-tile {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  justify-content: space-between;
  gap: 6px;
  min-height: 76px;
  padding: 11px 12px;
  border: 1px solid var(--line);
  border-radius: 10px;
  background: var(--surface-card);
  color: var(--ink);
  text-align: left;
  box-shadow: none;
  transform: none;
}

.drawer-module-tile:hover {
  border-color: color-mix(in srgb, var(--accent) 44%, var(--line));
  background: var(--accent-soft);
  box-shadow: none;
  transform: none;
}

.drawer-module-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
  width: 100%;
}

.drawer-module-top b {
  font-size: 13px;
  font-weight: 600;
}

.drawer-module-tile small {
  font-size: 11.5px;
  color: var(--muted);
  line-height: 1.45;
}

.drawer-snapshot-list {
  display: flex;
  flex-direction: column;
  border: 1px solid var(--line);
  border-radius: 10px;
  overflow: hidden;
}

.drawer-snapshot-top {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.drawer-sha {
  display: block;
  margin-top: 4px;
  font-size: 11px;
  color: var(--muted);
  overflow-wrap: anywhere;
}

.drawer-snapshot-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  flex-wrap: wrap;
}

.drawer-inline-result {
  border: 1px solid var(--line);
  border-radius: 10px;
  padding: 12px;
  background: var(--surface-evidence, var(--surface-tint));
  max-height: 420px;
  overflow: auto;
}

.drawer-inline-result :deep(.results-panel) {
  display: block;
}

.drawer-sub-disclosure {
  padding-top: 8px;
  border-top: 1px solid var(--line);
}

.drawer-sub-disclosure summary {
  cursor: pointer;
  font-size: 12.5px;
  font-weight: 550;
  color: var(--accent);
}

.drawer-disclosure-card {
  padding: 14px 16px;
}

.drawer-disclosure-card summary {
  cursor: pointer;
  font-size: 13.5px;
  font-weight: 600;
  color: var(--ink);
}

.drawer-pre {
  max-height: 240px;
  overflow: auto;
  font-size: 11.5px;
}

.drawer-filter-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 0 10px;
  height: 36px;
  border: 1px solid var(--line-strong);
  border-radius: var(--radius-control, 8px);
  background: var(--paper);
}

.drawer-filter-bar svg {
  width: 15px;
  height: 15px;
  flex: none;
  fill: none;
  stroke: var(--muted);
  stroke-width: 1.8;
}

.drawer-filter-bar input {
  flex: 1;
  min-width: 0;
  border: 0;
  background: transparent;
  color: var(--ink);
  font-size: 12.5px;
  outline: none;
}

.drawer-chat-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.drawer-chat-row {
  display: flex;
  align-items: center;
  gap: 8px;
  height: 50px;
  min-height: 50px;
  padding: 4px 6px 4px 10px;
  border: 1px solid var(--line);
  border-radius: 9px;
  background: var(--surface-tint);
}

.drawer-chat-link {
  display: grid;
  gap: 2px;
  flex: 1;
  min-width: 0;
  padding: 0;
  border: 0;
  background: transparent;
  color: var(--ink);
  text-align: left;
  box-shadow: none;
  transform: none;
}

.drawer-chat-link:hover {
  border: 0;
  background: transparent;
  color: var(--accent);
  box-shadow: none;
  transform: none;
}

.drawer-chat-link b {
  font-size: 12.5px;
  font-weight: 550;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.drawer-chat-link small {
  font-size: 11px;
  color: var(--muted);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.drawer-chat-remove {
  flex: none;
  height: 28px;
  min-height: 28px;
  padding: 0 10px;
  font-size: 11.5px;
}

.drawer-assign-strip {
  display: flex;
  align-items: center;
  gap: 8px;
  padding-top: 8px;
  border-top: 1px solid var(--line);
}

.drawer-assign-strip select {
  flex: 1;
  min-width: 0;
  height: 36px;
}

.drawer-assign-strip button {
  flex: none;
  height: 36px;
  min-height: 36px;
}

.drawer-meta-body {
  display: grid;
  gap: 8px;
}

.drawer-meta-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  font-size: 12.5px;
  padding: 6px 0;
  border-bottom: 1px solid var(--line);
}

.drawer-meta-row span {
  color: var(--muted);
}

.drawer-copy-id {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  height: 28px;
  min-height: 28px;
  padding: 0 9px;
  font-size: 11.5px;
}

.drawer-delete-btn {
  justify-self: start;
  margin-top: 4px;
}

.project-drawer-enter-active,
.project-drawer-leave-active {
  transition: opacity 200ms ease;
}

.project-drawer-enter-active .project-drawer-panel,
.project-drawer-leave-active .project-drawer-panel {
  transition: transform 220ms cubic-bezier(.22, 1, .36, 1);
}

.project-drawer-enter-from,
.project-drawer-leave-to {
  opacity: 0;
}

.project-drawer-enter-from .project-drawer-panel,
.project-drawer-leave-to .project-drawer-panel {
  transform: translateX(32px);
}

@media (max-width: 640px) {
  .drawer-modules-grid {
    grid-template-columns: minmax(0, 1fr);
  }
}

@media (prefers-reduced-motion: reduce) {
  .project-drawer-enter-active,
  .project-drawer-leave-active,
  .project-drawer-enter-active .project-drawer-panel,
  .project-drawer-leave-active .project-drawer-panel {
    transition: none;
  }
}
</style>
