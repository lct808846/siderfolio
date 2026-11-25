<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { api, apiUrl, download, safeLink } from '../api'
import { literatureApi } from '../api/literature'
import { useAttachments } from '../stores/attachments'
import type { ArtifactInfo, ChatAttachment, Manifest, PlotSpec, Turn } from '../types'
import ArtifactFileViewer, { type ArtifactPreviewItem } from './ArtifactFileViewer.vue'
import ComputeResultPanel from './ComputeResultPanel.vue'
import PlotResultPanel from './PlotResultPanel.vue'
import StatusNotice from './StatusNotice.vue'

export type ResultViewKey = 'overview' | 'compute' | 'plot' | 'gaia' | 'ads' | 'simbad' | 'files' | 'export'

interface ScopedComputeEntry {
  key: string
  turnId: string
  title: string
  engine: string
  particles: number
  duration: number
  projectId: string
  taskId: string
}

interface ScopedPlotEntry {
  key: string
  turnId: string
  title: string
  engine: string
  chart: string
  projectId: string
  runId: string
  files: string[]
}

interface ScopedQueryEntry {
  key: string
  turnId: string
  kind: 'gaia' | 'ads' | 'simbad'
  title: string
  subtitle: string
}

const props = defineProps<{
  turn: Turn | null
  turns?: Turn[]
  conversationId?: string
  historical: boolean
  artifactPath?: string
  heading?: string
  disableExport?: boolean
  dismissible?: boolean
  pending?: boolean
  projectId?: string
  projectScopedBrowse?: boolean
  focusKind?: 'turn' | 'compute' | 'plot' | 'files'
  focusNonce?: number
  computeTaskId?: string
  plotRunId?: string
  plotTitle?: string
  plotFiles?: string[]
  expandable?: boolean
  expanded?: boolean
}>()

const emit = defineEmits<{
  close: []
  'toggle-expand': []
  'select-turn': [turnId: string]
  'select-compute-task': [taskId: string]
  'select-plot-run': [runId: string]
}>()

const attachmentsStore = useAttachments()

const view = ref<ResultViewKey>('overview')
const activeFileId = ref('')
const activeComputeProjectId = ref('')
const activeComputeTaskId = ref('')
const activePlotProjectId = ref('')
const activePlotRunId = ref('')
const activePlotTitle = ref('')
const activePlotFiles = ref<string[]>([])

const page = ref(0)
const index = ref(0)
const kinds = ref<PlotSpec['kind'][]>([])
const artifact = ref<ArtifactInfo | null>(null)
const manifest = ref<Manifest | null>(null)
const busy = ref(false)
let generation = 0
const error = ref('')

const isStandaloneSnapshot = computed(() => Boolean(props.artifactPath || props.disableExport))
const conversationTurns = computed<Turn[]>(() => {
  if (props.turns !== undefined) return props.turns
  return props.turn ? [props.turn] : []
})

const response = computed(() => props.turn?.response)

// V1.9 Personal literature library status & manual saving for ADS results
const savedLiterature = ref<Record<string, string>>({})
const savingPaperKey = ref('')
const literatureNotice = ref<Record<string, { kind: 'success' | 'error'; message: string }>>({})
let statusCheckToken = 0

const allAdsBibcodes = computed(() => {
  const codes: string[] = []
  for (const batch of response.value?.literature_results || []) {
    for (const paper of batch.papers || []) {
      if (paper.bibcode) codes.push(paper.bibcode)
    }
  }
  return Array.from(new Set(codes))
})

const turnLiteratureReceiptKey = computed(() =>
  [...(props.turn?.literature_receipts || []), ...(response.value?.literature_receipts || [])]
    .map(r => `${r.receipt_id}:${r.added_count}:${r.already_saved_count}`)
    .join('|'),
)

async function refreshLiteratureStatus() {
  const codes = allAdsBibcodes.value
  const token = ++statusCheckToken
  if (!codes.length) {
    savedLiterature.value = {}
    return
  }
  try {
    const res = await literatureApi.status(codes)
    if (token === statusCheckToken) {
      savedLiterature.value = res.saved || {}
    }
  } catch {
    // Non-blocking status check; user can still click save manually.
  }
}

function makeRequestUuid(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID()
  }
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, ch => {
    const rand = (Math.random() * 16) | 0
    return (ch === 'x' ? rand : (rand & 0x3) | 0x8).toString(16)
  })
}

async function saveAdsPaper(batchIndex: number, paperIndex: number, bibcode: string) {
  if (!props.turn || savingPaperKey.value) return
  const key = `${batchIndex}:${bibcode}`
  savingPaperKey.value = key
  const nextNotice = { ...literatureNotice.value }
  delete nextNotice[key]
  literatureNotice.value = nextNotice
  try {
    const snapshotMatch = props.artifactPath?.match(
      /^\/api\/v1\/projects\/([^/]+)\/snapshots\/([^/]+)\/artifacts$/,
    )
    const receipt = await literatureApi.add({
      client_request_id: makeRequestUuid(),
      batch_index: batchIndex,
      paper_indices: [paperIndex],
      note: '',
      ...(snapshotMatch
        ? { project_id: snapshotMatch[1], snapshot_id: snapshotMatch[2] }
        : { conversation_id: props.turn.conversation_id, turn_id: props.turn.turn_id }),
    })
    const receiptItems = receipt.items || []
    const entry = receiptItems.find(item => item.bibcode === bibcode) || receiptItems[0]
    if (entry?.item_id) {
      savedLiterature.value = { ...savedLiterature.value, [bibcode]: entry.item_id }
      literatureNotice.value = {
        ...literatureNotice.value,
        [key]: {
          kind: 'success',
          message: entry.status === 'already_saved' ? '该文献已在您的文献库中。' : '已加入个人文献库。',
        },
      }
    } else {
      literatureNotice.value = {
        ...literatureNotice.value,
        [key]: {
          kind: 'error',
          message: entry?.reason || '未能通过 ADS 核验，未写入文献库。',
        },
      }
    }
  } catch (reason) {
    literatureNotice.value = {
      ...literatureNotice.value,
      [key]: {
        kind: 'error',
        message: reason instanceof Error ? reason.message : '加入文献库失败，请稍后重试。',
      },
    }
  } finally {
    savingPaperKey.value = ''
  }
}

watch([allAdsBibcodes, turnLiteratureReceiptKey], () => {
  literatureNotice.value = {}
  void refreshLiteratureStatus()
}, { immediate: true })

const gaia = computed(() => response.value?.gaia_results?.[index.value])
const querySucceeded = computed(() => gaia.value?.status === 'success' || gaia.value?.status === 'not_found')
const hasPlotData = computed(() => gaia.value?.status === 'success' && !!gaia.value.data?.length)
const plotDestination = computed(() => {
  const snapshot = props.artifactPath?.match(/^\/api\/v1\/projects\/([^/]+)\/snapshots\/([^/]+)\/artifacts$/)
  return snapshot
    ? { path: '/', query: { tool: 'plot', project: snapshot[1], plot_snapshot: snapshot[2], plot_query: String(index.value) } }
    : { path: `/conversations/${props.turn?.conversation_id}`, query: { tool: 'plot', plot_turn: props.turn?.turn_id, plot_query: String(index.value) } }
})
const fields = computed(() => (gaia.value?.data?.[0] ? Object.keys(gaia.value.data[0]) : []))
const rows = computed(() => gaia.value?.data?.slice(page.value * 20, (page.value + 1) * 20) || [])
const names: Record<string, string> = {
  proper_motion: '自行散点图',
  parallax_histogram: '视差直方图',
  observed_cmd: '观测颜色—星等图',
}
const reasons: Record<string, string> = {
  insufficient_data: '有效数据不足',
  query_not_successful: '查询未成功',
  unrepresentable_range: '数值范围无法绘制',
  render_failed: '图片生成失败',
}
const statLabels: Record<string, string> = {
  parallax: '视差 (parallax)',
  pmra: '赤经自行 (pmra)',
  pmdec: '赤纬自行 (pmdec)',
  phot_g_mean_mag: 'G 波段星等',
  bp_rp: 'BP − RP 色指数',
  radial_velocity: '视向速度 (RV)',
}

function readStoredTool(key: string): { projectId?: string; taskId?: string; runId?: string } | null {
  try {
    const raw = sessionStorage.getItem(key)
    return raw ? (JSON.parse(raw) as { projectId?: string; taskId?: string; runId?: string }) : null
  } catch {
    return null
  }
}

// 1. User-uploaded files strictly scoped to THIS conversation (turns + staged composer files)
const conversationUploads = computed<ArtifactPreviewItem[]>(() => {
  // Depend on focusNonce so newly attached/sent items refresh reactively
  void props.focusNonce
  const seen = new Set<string>()
  const list: ArtifactPreviewItem[] = []
  const pushAttachment = (att: ChatAttachment, originLabel: string) => {
    const dedupeKey = `${att.sha256}:${att.filename}`
    if (seen.has(dedupeKey)) return
    seen.add(dedupeKey)
    const raw = attachmentsStore.rawFile(att.sha256)
    list.push({
      id: `upload:${dedupeKey}`,
      name: att.filename,
      subtitle: `${originLabel} · ${att.media_type}`,
      mediaType: att.media_type,
      blob: raw,
      text: att.text,
    })
  }
  if (!isStandaloneSnapshot.value) {
    const scope = props.conversationId || 'draft'
    for (const staged of attachmentsStore.ready(scope)) {
      pushAttachment(staged, '待发送附件')
    }
  }
  for (let i = conversationTurns.value.length - 1; i >= 0; i--) {
    const t = conversationTurns.value[i]!
    const timeLabel = new Date(t.received_at).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
    for (const att of t.attachments || []) {
      pushAttachment(att, `本对话上传 · ${timeLabel}`)
    }
  }
  return list
})

// 2. Model-generated N-body simulations strictly scoped to THIS conversation
const conversationComputeEntries = computed<ScopedComputeEntry[]>(() => {
  void props.focusNonce
  const list: ScopedComputeEntry[] = []
  const seenTasks = new Set<string>()
  for (let i = conversationTurns.value.length - 1; i >= 0; i--) {
    const t = conversationTurns.value[i]!
    const proposals = t.response?.nbody_proposals || []
    proposals.forEach((proposal, idx) => {
      const saved = readStoredTool(`astroagent.chat_nbody.${t.turn_id}.${idx}`)
      const taskId = saved?.taskId || ''
      const projectId = saved?.projectId || props.projectId || ''
      if (taskId) seenTasks.add(taskId)
      list.push({
        key: `nbody:${t.turn_id}:${idx}`,
        turnId: t.turn_id,
        title: proposal.name || 'N 体模拟',
        engine: proposal.engine === 'petar' ? 'PeTar' : 'REBOUND',
        particles: proposal.particles.length,
        duration: proposal.duration,
        projectId,
        taskId,
      })
    })
  }
  if (props.computeTaskId && !seenTasks.has(props.computeTaskId)) {
    list.unshift({
      key: `nbody-active:${props.computeTaskId}`,
      turnId: props.turn?.turn_id || '',
      title: 'N 体模拟实验',
      engine: 'REBOUND',
      particles: 0,
      duration: 0,
      projectId: props.projectId || '',
      taskId: props.computeTaskId,
    })
  }
  return list
})

const executedComputeTaskIds = computed(() =>
  conversationComputeEntries.value.map(item => item.taskId).filter(Boolean),
)

// 3. Model-generated scientific plots strictly scoped to THIS conversation
const conversationPlotEntries = computed<ScopedPlotEntry[]>(() => {
  void props.focusNonce
  const list: ScopedPlotEntry[] = []
  const seenRuns = new Set<string>()
  for (let i = conversationTurns.value.length - 1; i >= 0; i--) {
    const t = conversationTurns.value[i]!
    const proposals = t.response?.plot_proposals || []
    proposals.forEach((proposal, idx) => {
      const saved = readStoredTool(`astroagent.chat_plot.${t.turn_id}.${idx}`)
      const runId = saved?.runId || ''
      const projectId = saved?.projectId || props.projectId || ''
      if (runId) seenRuns.add(runId)
      list.push({
        key: `plot:${t.turn_id}:${idx}`,
        turnId: t.turn_id,
        title: proposal.title || '科研绘图',
        engine: proposal.engine === 'gnuplot' ? 'Gnuplot' : 'Python',
        chart: proposal.chart,
        projectId,
        runId,
        files: runId === props.plotRunId && props.plotFiles?.length ? props.plotFiles : [],
      })
    })
  }
  if (props.plotRunId && !seenRuns.has(props.plotRunId)) {
    list.unshift({
      key: `plot-active:${props.plotRunId}`,
      turnId: props.turn?.turn_id || '',
      title: props.plotTitle || '科研绘图产物',
      engine: 'Python',
      chart: 'figure',
      projectId: props.projectId || '',
      runId: props.plotRunId,
      files: props.plotFiles || [],
    })
  }
  return list
})

const executedPlotRunIds = computed(() =>
  conversationPlotEntries.value.map(item => item.runId).filter(Boolean),
)

// 4. Astronomical query outputs strictly scoped to THIS conversation
const conversationQueryEntries = computed<ScopedQueryEntry[]>(() => {
  const list: ScopedQueryEntry[] = []
  for (let i = conversationTurns.value.length - 1; i >= 0; i--) {
    const t = conversationTurns.value[i]!
    const res = t.response
    if (!res) continue
    if (res.gaia_results?.length) {
      const totalRows = res.gaia_results.reduce((acc, g) => acc + (g.returned_count || 0), 0)
      list.push({
        key: `gaia:${t.turn_id}`,
        turnId: t.turn_id,
        kind: 'gaia',
        title: `Gaia DR3 星表查询 (${res.gaia_results.length})`,
        subtitle: `${totalRows} 行测量数据 · 表格与统计`,
      })
    }
    if (res.literature_results?.length) {
      const papers = res.literature_results.reduce((acc, l) => acc + (l.papers?.length || 0), 0)
      list.push({
        key: `ads:${t.turn_id}`,
        turnId: t.turn_id,
        kind: 'ads',
        title: `NASA ADS 文献检索`,
        subtitle: `${papers} 篇论文元数据与摘要`,
      })
    }
    if (res.results?.length) {
      const firstObj = res.results[0]?.object_name || '天体'
      list.push({
        key: `simbad:${t.turn_id}`,
        turnId: t.turn_id,
        kind: 'simbad',
        title: `SIMBAD · ${firstObj}${res.results.length > 1 ? ` 等 ${res.results.length} 个` : ''}`,
        subtitle: '坐标、天体类型与光谱信息',
      })
    }
  }
  return list
})

// All previewable files in the file viewer (uploads + generated quick-chart images)
const allPreviewFiles = computed<ArtifactPreviewItem[]>(() => {
  const items = [...conversationUploads.value]
  if (artifact.value?.figures?.length) {
    for (const fig of artifact.value.figures) {
      items.push({
        id: `fig:${fig.figure_id}`,
        name: `${names[fig.kind] || fig.kind}.png`,
        subtitle: '本轮快速导出图表',
        category: 'image',
        mediaType: 'image/png',
        url: apiUrl(fig.url),
      })
    }
  }
  return items
})

const hasTurnDataTabs = computed(() =>
  Boolean(
    response.value?.gaia_results?.length ||
    response.value?.literature_results?.length ||
    response.value?.results?.length,
  ),
)

const turnDataTabs = computed<Array<{ key: ResultViewKey; label: string; count?: number }>>(() => {
  const list: Array<{ key: ResultViewKey; label: string; count?: number }> = []
  if (response.value?.gaia_results?.length) {
    list.push({ key: 'gaia', label: 'Gaia DR3', count: response.value.gaia_results.length })
  }
  if (response.value?.literature_results?.length) {
    const paperTotal = response.value.literature_results.reduce((acc, q) => acc + (q.papers?.length || 0), 0)
    list.push({ key: 'ads', label: 'ADS 文献', count: paperTotal || response.value.literature_results.length })
  }
  if (response.value?.results?.length) {
    list.push({ key: 'simbad', label: 'SIMBAD', count: response.value.results.length })
  }
  if (!props.disableExport && hasTurnDataTabs.value) {
    list.push({ key: 'export', label: '导出' })
  }
  return list
})

const hasAnyConversationItems = computed(() =>
  conversationUploads.value.length > 0 ||
  conversationComputeEntries.value.some(item => !!item.taskId) ||
  conversationPlotEntries.value.some(item => !!item.runId) ||
  conversationQueryEntries.value.length > 0 ||
  Boolean(artifact.value?.figures?.length),
)

const canShowBackToOverview = computed(() =>
  !isStandaloneSnapshot.value && !props.projectScopedBrowse && view.value !== 'overview',
)

const effectiveComputeProjectId = computed(() => activeComputeProjectId.value || props.projectId || '')
const effectiveComputeTaskId = computed(() => activeComputeTaskId.value || props.computeTaskId || executedComputeTaskIds.value[0] || '')
const effectivePlotProjectId = computed(() => activePlotProjectId.value || props.projectId || '')
const effectivePlotRunId = computed(() => activePlotRunId.value || props.plotRunId || executedPlotRunIds.value[0] || '')

const dynamicHeading = computed(() => {
  if (props.heading) return props.heading
  if (view.value === 'compute') return props.projectScopedBrowse ? '空间 N 体模拟记录' : 'N 体模拟结果'
  if (view.value === 'plot') return activePlotTitle.value || props.plotTitle || '科研绘图产物'
  if (view.value === 'gaia') return 'Gaia DR3 查询数据'
  if (view.value === 'ads') return 'ADS 学术文献'
  if (view.value === 'simbad') return 'SIMBAD 天体目标'
  if (view.value === 'files') {
    const active = allPreviewFiles.value.find(item => item.id === activeFileId.value)
    return active?.name || '文件预览'
  }
  if (view.value === 'export') return '快速图表与导出'
  return '文件与产物'
})

function fileKindTag(item: ArtifactPreviewItem) {
  const ext = (item.name.split('.').pop() || '').toLowerCase()
  const mime = (item.mediaType || '').toLowerCase()
  if (mime.startsWith('image/') || ['png', 'jpg', 'jpeg', 'webp', 'gif', 'svg'].includes(ext)) return 'IMG'
  if (mime === 'application/pdf' || ext === 'pdf') return 'PDF'
  if (['csv', 'tsv'].includes(ext) || mime.includes('csv') || mime.includes('tab-separated')) return 'CSV'
  if (ext === 'json' || mime.includes('json')) return 'JSON'
  if (['py', 'plt', 'js', 'ts', 'sql', 'md'].includes(ext)) return ext.toUpperCase()
  return 'FILE'
}

function openFile(id: string) {
  activeFileId.value = id
  view.value = 'files'
}

function openComputeEntry(entry: ScopedComputeEntry) {
  if (!entry.taskId) return
  activeComputeProjectId.value = entry.projectId
  activeComputeTaskId.value = entry.taskId
  view.value = 'compute'
}

function openPlotEntry(entry: ScopedPlotEntry) {
  if (!entry.runId) return
  activePlotProjectId.value = entry.projectId
  activePlotRunId.value = entry.runId
  activePlotTitle.value = entry.title
  activePlotFiles.value = entry.files
  view.value = 'plot'
}

function openQueryEntry(entry: ScopedQueryEntry) {
  if (entry.turnId && entry.turnId !== props.turn?.turn_id) {
    emit('select-turn', entry.turnId)
  }
  view.value = entry.kind
}

function formatNum(value: number | null | undefined, digits = 3) {
  if (value === null || value === undefined || !Number.isFinite(value)) return '—'
  return Number(value.toFixed(digits)).toString()
}
function formatRange(minVal: unknown, maxVal: unknown, unit: string) {
  const hasMin = typeof minVal === 'number' && Number.isFinite(minVal)
  const hasMax = typeof maxVal === 'number' && Number.isFinite(maxVal)
  if (hasMin && hasMax) return `${formatNum(minVal)} ~ ${formatNum(maxVal)} ${unit}`.trim()
  if (hasMin) return `≥ ${formatNum(minVal)} ${unit}`.trim()
  if (hasMax) return `≤ ${formatNum(maxVal)} ${unit}`.trim()
  return ''
}
const gaiaConditions = computed(() => {
  const current = gaia.value
  if (!current) return [] as Array<{ label: string; value: string }>
  const q = (current.query || {}) as Record<string, unknown>
  const items: Array<{ label: string; value: string }> = []
  items.push({ label: '数据表', value: `${current.release} · ${current.table}` })
  if (q.mode === 'source_id') {
    items.push({ label: '查询模式', value: `精确 source_id：${String(q.source_id || '—')}` })
  } else {
    items.push({ label: '中心坐标 (ICRS)', value: `RA ${formatNum(Number(q.ra_deg), 4)}°, Dec ${formatNum(Number(q.dec_deg), 4)}°` })
    items.push({ label: '半径 / 上限', value: `${formatNum(Number(q.radius_arcmin), 2)} arcmin · 最多 ${String(q.limit ?? '—')} 行` })
  }
  if (typeof q.ruwe_max === 'number') items.push({ label: 'RUWE 上限', value: `≤ ${formatNum(q.ruwe_max, 2)}` })
  if (typeof q.parallax_snr_min === 'number') items.push({ label: '视差信噪比', value: `ϖ/σϖ ≥ ${formatNum(q.parallax_snr_min, 1)}` })
  const plxRange = formatRange(q.parallax_min, q.parallax_max, 'mas')
  if (plxRange) items.push({ label: '视差筛选', value: plxRange })
  const pmraRange = formatRange(q.pmra_min, q.pmra_max, 'mas/yr')
  if (pmraRange) items.push({ label: 'pmRA 筛选', value: pmraRange })
  const pmdecRange = formatRange(q.pmdec_min, q.pmdec_max, 'mas/yr')
  if (pmdecRange) items.push({ label: 'pmDec 筛选', value: pmdecRange })
  if (typeof q.g_mag_max === 'number') items.push({ label: 'G 星等上限', value: `G ≤ ${formatNum(q.g_mag_max, 2)} mag` })
  return items
})
const gaiaStatRows = computed(() => {
  const stats = gaia.value?.analysis?.statistics
  if (!stats) return [] as Array<{ key: string; label: string; valid: number; total: number; median: string; range: string; unit: string }>
  return Object.entries(stats).map(([key, item]) => ({
    key,
    label: statLabels[key] || key,
    valid: item.valid_count,
    total: item.valid_count + item.missing_count,
    median: formatNum(item.median, 3),
    range: item.valid_count ? `${formatNum(item.minimum, 2)} ~ ${formatNum(item.maximum, 2)}` : '—',
    unit: item.unit || '',
  }))
})

function text(value: unknown): string {
  return value === null || value === undefined ? '未提供' : typeof value === 'object' ? JSON.stringify(value) : String(value)
}

function formatUtc(raw?: string | null): string {
  if (!raw) return '—'
  const match = raw.match(/^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2}:\d{2})/)
  if (match) return `${match[1]} ${match[2]} UTC`
  return raw
}

function queryStatusLabel(status?: string): string {
  if (status === 'success') return '检索成功'
  if (status === 'not_found') return '无匹配'
  if (status === 'error') return '检索失败'
  return status || '未知'
}

function adsSortLabel(sort?: string): string {
  if (sort === 'citation_count_desc') return '按被引降序'
  if (sort === 'date_desc') return '按日期降序'
  if (sort === 'relevance') return '按相关性'
  return sort || '默认排序'
}

const showTurnTimestamp = computed(() =>
  Boolean(props.turn?.received_at && ['gaia', 'ads', 'simbad', 'export'].includes(view.value)),
)

function resetArtifact() {
  generation++
  artifact.value = null
  manifest.value = null
  error.value = ''
}

function syncDefaultView() {
  if (props.focusKind === 'compute' && (props.projectScopedBrowse || props.computeTaskId || executedComputeTaskIds.value.length)) {
    activeComputeProjectId.value = props.projectId || ''
    activeComputeTaskId.value = props.computeTaskId || executedComputeTaskIds.value[0] || ''
    view.value = 'compute'
    return
  }
  if (props.focusKind === 'plot' && (props.projectScopedBrowse || props.plotRunId || executedPlotRunIds.value.length)) {
    activePlotProjectId.value = props.projectId || ''
    activePlotRunId.value = props.plotRunId || executedPlotRunIds.value[0] || ''
    activePlotTitle.value = props.plotTitle || ''
    activePlotFiles.value = props.plotFiles || []
    view.value = 'plot'
    return
  }
  if (props.focusKind === 'files' && allPreviewFiles.value.length) {
    view.value = 'files'
    return
  }
  if (isStandaloneSnapshot.value || hasTurnDataTabs.value) {
    if (response.value?.gaia_results?.length) { view.value = 'gaia'; return }
    if (response.value?.literature_results?.length) { view.value = 'ads'; return }
    if (response.value?.results?.length) { view.value = 'simbad'; return }
  }
  view.value = 'overview'
}

watch(
  [() => props.conversationId, () => props.turn?.conversation_id],
  () => {
    resetArtifact()
    index.value = 0
    page.value = 0
    kinds.value = []
    activeFileId.value = ''
    activeComputeProjectId.value = ''
    activeComputeTaskId.value = ''
    activePlotProjectId.value = ''
    activePlotRunId.value = ''
    activePlotTitle.value = ''
    activePlotFiles.value = []
    syncDefaultView()
  },
  { immediate: true },
)

watch(
  () => props.turn?.turn_id,
  () => {
    resetArtifact()
    index.value = 0
    page.value = 0
    kinds.value = []
    syncDefaultView()
  },
)

watch(
  [() => props.focusKind, () => props.focusNonce, () => props.computeTaskId, () => props.plotRunId, () => props.projectScopedBrowse],
  () => {
    syncDefaultView()
  },
)

watch([index, kinds], resetArtifact, { deep: true })
watch(index, () => { page.value = 0 })

async function generate() {
  if (!props.turn) return
  busy.value = true
  error.value = ''
  resetArtifact()
  const token = generation
  const turnId = props.turn.turn_id
  try {
    const plots = hasPlotData.value ? kinds.value.map(kind => ({ kind, gaia_result_index: index.value })) : []
    const generated = props.artifactPath
      ? await api.snapshotArtifact(props.artifactPath, plots)
      : await api.artifact(props.turn.conversation_id, turnId, plots)
    const metadata = await api.manifest(generated.manifest_url)
    if (props.turn?.turn_id === turnId && token === generation) {
      artifact.value = generated
      manifest.value = metadata
    }
  } catch (e) {
    error.value = e instanceof Error ? e.message : '生成失败'
  } finally {
    busy.value = false
  }
}

async function save() {
  if (!artifact.value) return
  try {
    await download(artifact.value.download_url)
  } catch (e) {
    error.value = e instanceof Error ? e.message : '下载失败'
    artifact.value = null
  }
}
</script>

<template>
  <aside class="results-panel" :class="{ 'is-expanded': expanded }" aria-label="结果与文件">
    <div class="results-sheet-handle" aria-hidden="true"><span /></div>
    <header class="pane-heading workspace-pane-header results-header">
      <div class="results-title-block">
        <h2>{{ dynamicHeading }}</h2>
      </div>
      <div class="results-header-actions">
        <span v-if="historical" class="tag">历史</span>
        <button
          v-if="expandable"
          type="button"
          class="result-icon-action result-expand-btn"
          :aria-pressed="expanded"
          :aria-label="expanded ? '恢复标准宽度' : '加宽展开结果栏'"
          :title="expanded ? '恢复标准宽度' : '加宽展开结果栏'"
          @click="emit('toggle-expand')"
        >
          <svg v-if="!expanded" viewBox="0 0 24 24" aria-hidden="true"><path d="M15 4h5v5m-6 1 6-6M9 20H4v-5m6-1-6 6" /></svg>
          <svg v-else viewBox="0 0 24 24" aria-hidden="true"><path d="M20 9h-5V4m0 5 5-5M4 15h5v5m0-5-5 5" /></svg>
        </button>
        <button v-if="dismissible" type="button" class="result-icon-action result-close" aria-label="收起结果面板" title="收起结果栏" @click="emit('close')">
          <svg viewBox="0 0 24 24" aria-hidden="true"><path d="m6 6 12 12M6 18 18 6" /></svg>
        </button>
      </div>
    </header>

    <div class="workspace-pane-body results-body">
      <p v-if="pending" class="results-live-banner" role="status">
        <span class="live-dot" aria-hidden="true" />
        <span>正在处理当前对话，生成的文件与数据会实时同步到这里。</span>
      </p>

      <!-- Top Utility Strip: Back to Overview + Clean Formatted UTC Timestamp -->
      <div v-if="canShowBackToOverview || showTurnTimestamp" class="results-nav-strip">
        <button v-if="canShowBackToOverview" type="button" class="results-back-btn" @click="view = 'overview'">
          <svg viewBox="0 0 24 24" aria-hidden="true"><path d="m15 18-6-6 6-6" /></svg>
          <span>本次对话概览</span>
        </button>
        <span v-else />
        <time
          v-if="showTurnTimestamp && turn"
          class="results-timestamp"
          :datetime="turn.received_at"
          :title="`${artifactPath ? '快照保存' : '接收时间'}：${turn.received_at}`"
        >
          {{ artifactPath ? '快照 · ' : '' }}{{ formatUtc(turn.received_at) }}
        </time>
      </div>

      <!-- OVERVIEW MODE: Strictly scoped to THIS conversation's uploads & generated artifacts -->
      <template v-if="view === 'overview'">
        <div v-if="!hasAnyConversationItems" class="results-empty-studio">
          <slot name="empty">
            <div class="empty-icon-ring" aria-hidden="true">
              <svg viewBox="0 0 24 24"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8Z" /><path d="M14 2v6h6M9 13h6M9 17h4" /></svg>
            </div>
            <h3>暂无文件与产物</h3>
            <p>上传的附件与生成的图表、数据将显示在此。</p>
          </slot>
        </div>

        <div v-else class="overview-sections">
          <!-- Model-Generated Artifacts & Tasks in THIS conversation -->
          <section
            v-if="conversationComputeEntries.some(i => i.taskId) || conversationPlotEntries.some(i => i.runId) || conversationQueryEntries.length || artifact?.figures?.length"
            class="overview-group"
          >
            <header class="overview-group-head">
              <span>模型生成与任务产物</span>
              <em>
                {{
                  conversationComputeEntries.filter(i => i.taskId).length
                  + conversationPlotEntries.filter(i => i.runId).length
                  + conversationQueryEntries.length
                  + (artifact?.figures?.length || 0)
                }}
              </em>
            </header>
            <div class="overview-list">
              <button
                v-for="item in conversationComputeEntries.filter(i => i.taskId)"
                :key="item.key"
                type="button"
                class="overview-row"
                @click="openComputeEntry(item)"
              >
                <span class="overview-row-badge is-compute">N体</span>
                <span class="overview-row-copy">
                  <strong>{{ item.title }}</strong>
                  <small>{{ item.engine }}{{ item.particles ? ` · ${item.particles} 粒子 · ${item.duration} yr` : ' · 轨道与守恒诊断' }}</small>
                </span>
                <span class="overview-row-arrow" aria-hidden="true">›</span>
              </button>

              <button
                v-for="item in conversationPlotEntries.filter(i => i.runId)"
                :key="item.key"
                type="button"
                class="overview-row"
                @click="openPlotEntry(item)"
              >
                <span class="overview-row-badge is-plot">图表</span>
                <span class="overview-row-copy">
                  <strong>{{ item.title }}</strong>
                  <small>{{ item.engine }} · PNG / PDF / 复现脚本</small>
                </span>
                <span class="overview-row-arrow" aria-hidden="true">›</span>
              </button>

              <button
                v-for="item in conversationQueryEntries"
                :key="item.key"
                type="button"
                class="overview-row"
                @click="openQueryEntry(item)"
              >
                <span class="overview-row-badge" :class="`is-${item.kind}`">{{ item.kind === 'gaia' ? 'DR3' : item.kind === 'ads' ? 'ADS' : 'OBJ' }}</span>
                <span class="overview-row-copy">
                  <strong>{{ item.title }}</strong>
                  <small>{{ item.subtitle }}</small>
                </span>
                <span class="overview-row-arrow" aria-hidden="true">›</span>
              </button>

              <button
                v-for="fig in artifact?.figures || []"
                :key="fig.figure_id"
                type="button"
                class="overview-row"
                @click="openFile(`fig:${fig.figure_id}`)"
              >
                <span class="overview-row-badge is-image">PNG</span>
                <span class="overview-row-copy">
                  <strong>{{ names[fig.kind] || fig.kind }}.png</strong>
                  <small>本轮快速导出图表</small>
                </span>
                <span class="overview-row-arrow" aria-hidden="true">›</span>
              </button>
            </div>
          </section>

          <!-- User Uploads in THIS conversation -->
          <section v-if="conversationUploads.length" class="overview-group">
            <header class="overview-group-head">
              <span>本次对话上传的文件</span>
              <em>{{ conversationUploads.length }}</em>
            </header>
            <div class="overview-list">
              <button
                v-for="file in conversationUploads"
                :key="file.id"
                type="button"
                class="overview-row"
                @click="openFile(file.id)"
              >
                <span class="overview-row-badge" :class="fileKindTag(file) === 'PDF' ? 'is-pdf' : fileKindTag(file) === 'IMG' ? 'is-image' : 'is-file'">
                  {{ fileKindTag(file) }}
                </span>
                <span class="overview-row-copy">
                  <strong>{{ file.name }}</strong>
                  <small>{{ file.subtitle }}</small>
                </span>
                <span class="overview-row-arrow" aria-hidden="true">›</span>
              </button>
            </div>
          </section>
        </div>
      </template>

      <!-- N-BODY COMPUTE VIEW (Strictly scoped to THIS conversation unless projectScopedBrowse) -->
      <section v-else-if="view === 'compute' && effectiveComputeProjectId" class="source-section">
        <ComputeResultPanel
          :project-id="effectiveComputeProjectId"
          :task-id="effectiveComputeTaskId"
          :allowed-task-ids="projectScopedBrowse ? undefined : executedComputeTaskIds"
          @select-task="activeComputeTaskId = $event; emit('select-compute-task', $event)"
        />
      </section>

      <!-- SCIENTIFIC PLOT VIEW (Strictly scoped to THIS conversation unless projectScopedBrowse) -->
      <section v-else-if="view === 'plot' && effectivePlotProjectId" class="source-section">
        <PlotResultPanel
          :project-id="effectivePlotProjectId"
          :run-id="effectivePlotRunId"
          :initial-title="activePlotTitle || plotTitle"
          :initial-files="activePlotFiles.length ? activePlotFiles : plotFiles"
          :allowed-run-ids="projectScopedBrowse ? undefined : executedPlotRunIds"
          @select-run="activePlotRunId = $event; emit('select-plot-run', $event)"
        />
      </section>

      <!-- MULTI-FORMAT FILE PREVIEW VIEW -->
      <section v-else-if="view === 'files'" class="source-section">
        <ArtifactFileViewer :items="allPreviewFiles" :initial-id="activeFileId" />
      </section>

      <!-- TURN DATA VIEWS (Gaia / ADS / SIMBAD / Export) -->
      <template v-else-if="turn">
        <div v-if="turnDataTabs.length > 1" class="result-tabs" role="tablist" aria-label="本轮数据视图">
          <button
            v-for="item in turnDataTabs"
            :key="item.key"
            type="button"
            role="tab"
            :aria-selected="view === item.key"
            :class="{ active: view === item.key }"
            @click="view = item.key"
          >
            <span>{{ item.label }}</span>
            <em v-if="item.count !== undefined" class="tab-count">{{ item.count }}</em>
          </button>
        </div>

        <div v-if="turn.error" class="result-advisory-card is-danger" role="alert">
          <span class="result-advisory-icon" aria-hidden="true">
            <svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="9" /><path d="M12 8v5m0 3.5h.01" /></svg>
          </span>
          <div class="result-advisory-copy">
            <p>{{ turn.error.message }}</p>
            <code class="result-advisory-code">{{ turn.error.code }}</code>
          </div>
        </div>
        <div
          v-for="item in response?.warnings || []"
          :key="`${item.code}:${item.message}`"
          class="result-advisory-card is-warning"
          role="status"
        >
          <span class="result-advisory-icon" aria-hidden="true">
            <svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="9" /><path d="M12 8v4.5m0 3.5h.01" /></svg>
          </span>
          <div class="result-advisory-copy">
            <p>{{ item.message }}</p>
            <code class="result-advisory-code">{{ item.code }}</code>
          </div>
        </div>

        <!-- Gaia DR3 -->
        <section v-if="view === 'gaia' && response?.gaia_results?.length" class="source-section">
          <label v-if="response.gaia_results.length > 1" class="field-label" for="query-index">Gaia 查询批次</label>
          <select v-if="response.gaia_results.length > 1" id="query-index" v-model="index">
            <option v-for="(result, i) in response.gaia_results" :key="i" :value="i">
              第 {{ i + 1 }} 次 · {{ result.status === 'success' ? `${result.returned_count} 行 · 成功` : result.status === 'not_found' ? '0 行 · 条件下无匹配' : '未取得数据' }}
            </option>
          </select>
          <template v-if="gaia">
            <p v-if="gaia.error" class="notice" :class="{ danger: !querySucceeded }">{{ gaia.error.message }} <code>{{ gaia.error.code }}</code></p>
            <p v-if="!querySucceeded" class="notice" role="status">本次未取得可用数据，不能据此判断视场中没有天体。交付数量和截断状态不适用；可核对条件后手动重试，旧记录保留。</p>
            <div v-if="hasPlotData && !disableExport" class="result-plot-actions">
              <RouterLink class="plot-primary" :to="plotDestination">用此结果科研绘图</RouterLink>
              <button type="button" @click="view = 'export'">快速图表与导出</button>
            </div>
            <div class="data-metrics">
              <span><b>{{ querySucceeded ? gaia.returned_count : '未取得' }}</b>交付行</span>
              <span><b>未知</b>总命中数</span>
              <span><b>{{ !querySucceeded ? '不适用' : gaia.truncated ? '已截断' : '未截断' }}</b>交付范围</span>
            </div>
            <p v-if="gaia.truncated || gaia.archive_overflow" class="notice">仅描述交付样本{{ gaia.archive_overflow ? ' · Archive 报告溢出' : '' }}，不能代表视场总体。</p>
            <div class="result-stats-card">
              <div class="result-stats-head">
                <h3>查询条件与样本统计</h3>
                <span v-if="gaia.analysis" class="small muted">负视差 {{ gaia.analysis.negative_parallax_count }} · 缺失视差 {{ gaia.analysis.missing_parallax_count }}</span>
              </div>
              <dl class="result-conditions-grid">
                <template v-for="cond in gaiaConditions" :key="cond.label">
                  <dt>{{ cond.label }}</dt>
                  <dd>{{ cond.value }}</dd>
                </template>
              </dl>
              <div v-if="gaiaStatRows.length" class="result-stats-scroll">
                <table class="result-stats-table">
                  <thead>
                    <tr><th>物理量</th><th>有效</th><th>中位数</th><th>最小 ~ 最大</th><th>单位</th></tr>
                  </thead>
                  <tbody>
                    <tr v-for="stat in gaiaStatRows" :key="stat.key">
                      <td>{{ stat.label }}</td>
                      <td class="num">{{ stat.valid }}/{{ stat.total }}</td>
                      <td class="num">{{ stat.median }}</td>
                      <td class="num">{{ stat.range }}</td>
                      <td>{{ stat.unit }}</td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </div>
            <details><summary>原始条件、单位与统计 JSON</summary><pre>{{ text({ release: gaia.release, table: gaia.table, query: gaia.query, units: gaia.units, analysis: gaia.analysis }) }}</pre></details>
            <details><summary>实际 ADQL</summary><pre>{{ gaia.adql }}</pre></details>
            <details v-if="querySucceeded">
              <summary>查看完整交付表格（{{ (gaia.data?.length || 0) }} 行）</summary>
              <div class="table-scroll" tabindex="0" aria-label="Gaia 完整数据表">
                <table>
                  <thead><tr><th v-for="field in fields" :key="field">{{ field }}<small>{{ gaia.units?.[field] }}</small></th></tr></thead>
                  <tbody><tr v-for="row in rows" :key="row.source_id"><td v-for="field in fields" :key="field">{{ text((row as unknown as Record<string, unknown>)[field]) }}</td></tr></tbody>
                </table>
              </div>
              <div class="pagination">
                <button :disabled="page === 0" @click="page--">上一页</button>
                <span>{{ page + 1 }} / {{ Math.max(1, Math.ceil((gaia.data?.length || 0) / 20)) }}</span>
                <button :disabled="(page + 1) * 20 >= (gaia.data?.length || 0)" @click="page++">下一页</button>
              </div>
            </details>
            <div class="ui-card-head">
              <a v-if="safeLink(gaia.source.url)" :href="safeLink(gaia.source.url)!" class="ui-pill ui-pill-gaia" target="_blank" rel="noopener noreferrer">{{ gaia.status === 'error' ? 'Gaia 查询目标 ↗' : 'Gaia 来源 ↗' }}</a>
              <span v-else class="small muted">{{ gaia.source.url }}</span>
              <span class="small muted results-source-time" :title="gaia.source.retrieved_at">{{ formatUtc(gaia.source.retrieved_at) }}</span>
            </div>
            <p v-for="warning in gaia.warnings" :key="warning" class="small muted">{{ warning }}</p>
          </template>
        </section>

        <!-- ADS Literature -->
        <section v-else-if="view === 'ads' && response?.literature_results?.length" class="source-section">
          <article v-for="(result, i) in response.literature_results" :key="i" class="paper-query">
            <div class="ui-pill-list">
              <span class="ui-pill ui-pill-ads">ADS 检索 {{ i + 1 }}</span>
              <span class="ui-pill" :class="result.status === 'success' ? 'ui-pill-success' : result.status === 'not_found' ? 'ui-pill-warning' : 'ui-pill-danger'" :title="result.status">{{ queryStatusLabel(result.status) }}</span>
              <span class="ui-pill ui-pill-neutral">本页 {{ result.returned_count }} / 总命中 {{ text(result.total_found) }}</span>
              <span class="ui-pill ui-pill-neutral" :title="result.sort">{{ adsSortLabel(result.sort) }}</span>
            </div>
            <pre>{{ result.query }}</pre>
            <p v-if="result.error" class="notice danger">{{ result.error.message }} <code>{{ result.error.code }}</code></p>
            <div class="ui-card-head">
              <a v-if="safeLink(result.source.url)" :href="safeLink(result.source.url)!" class="ui-pill ui-pill-ads" target="_blank" rel="noopener noreferrer">{{ result.status === 'error' ? 'ADS 查询目标 ↗' : 'ADS 检索来源 ↗' }}</a>
              <span v-else class="small muted">{{ result.source.url }}</span>
              <span class="small muted results-source-time" :title="result.source.retrieved_at">{{ formatUtc(result.source.retrieved_at) }}</span>
            </div>
            <article v-for="(paper, paperIdx) in result.papers" :key="paper.bibcode" class="paper">
              <div class="ui-pill-list">
                <span class="ui-pill ui-pill-mono">#{{ paperIdx + 1 }}</span>
                <span class="ui-pill ui-pill-ads">{{ paper.year || '年份未知' }}</span>
                <span v-if="paper.publication" class="ui-pill ui-pill-neutral">{{ paper.publication }}</span>
                <span class="ui-pill ui-pill-accent">被引 {{ text(paper.citation_count) }}</span>
              </div>
              <h3>{{ paper.title || '未提供标题' }}</h3>
              <p class="small muted">{{ paper.authors?.join('、') || '作者未提供' }}</p>
              <div class="ui-pill-list">
                <span class="ui-pill ui-pill-mono">{{ paper.bibcode }}</span>
                <span v-if="paper.doi?.length" class="ui-pill ui-pill-mono">DOI {{ paper.doi[0] }}</span>
              </div>
              <details><summary>摘要 · 总结仅根据摘要</summary><p class="abstract">{{ paper.abstract || '未提供摘要，不推测结论。' }}</p></details>
              <div class="paper-actions-row">
                <div class="paper-source-links">
                  <a v-if="safeLink(paper.source.url)" :href="safeLink(paper.source.url)!" class="ui-pill ui-pill-ads" target="_blank" rel="noopener noreferrer">ADS 原始记录 ↗</a>
                  <span v-else class="small muted">{{ paper.source.url }}</span>
                  <span class="small muted results-source-time" :title="paper.source.retrieved_at">{{ formatUtc(paper.source.retrieved_at) }}</span>
                </div>
                <div v-if="result.status === 'success'" class="paper-library-control">
                  <template v-if="savedLiterature[paper.bibcode]">
                    <span class="ui-pill ui-pill-success">已在文献库</span>
                    <RouterLink
                      class="paper-library-link"
                      :to="`/literature/${encodeURIComponent(savedLiterature[paper.bibcode]!)}`"
                    >
                      查看详情 ↗
                    </RouterLink>
                  </template>
                  <button
                    v-else
                    type="button"
                    class="paper-save-btn"
                    :disabled="savingPaperKey !== ''"
                    @click="saveAdsPaper(i, paperIdx + 1, paper.bibcode)"
                  >
                    {{ savingPaperKey === `${i}:${paper.bibcode}` ? '正在入库…' : '加入文献库' }}
                  </button>
                </div>
              </div>
              <p
                v-if="literatureNotice[`${i}:${paper.bibcode}`]"
                class="paper-save-feedback"
                :class="literatureNotice[`${i}:${paper.bibcode}`]?.kind === 'error' ? 'is-error' : 'is-success'"
                role="status"
              >
                {{ literatureNotice[`${i}:${paper.bibcode}`]?.message }}
              </p>
            </article>
          </article>
        </section>

        <!-- SIMBAD Objects -->
        <section v-else-if="view === 'simbad' && response?.results?.length" class="source-section">
          <article v-for="(result, i) in response.results" :key="i" class="object-result">
            <div class="ui-card-head">
              <h3>{{ result.object_name }}</h3>
              <span class="ui-pill" :class="result.status === 'success' ? 'ui-pill-simbad' : result.status === 'not_found' ? 'ui-pill-warning' : 'ui-pill-danger'" :title="result.status">{{ queryStatusLabel(result.status) }}</span>
            </div>
            <p v-if="result.error" class="notice" :class="{ danger: result.status === 'error' }">{{ result.error.message }} <code>{{ result.error.code }}</code></p>
            <dl v-if="result.data" class="ui-param-grid">
              <div v-for="(value, field) in result.data" :key="field" class="ui-param-tile">
                <dt>{{ field }}</dt>
                <dd>{{ text(value) }}</dd>
              </div>
            </dl>
            <div class="ui-card-head">
              <a v-if="safeLink(result.source.url)" :href="safeLink(result.source.url)!" class="ui-pill ui-pill-simbad" target="_blank" rel="noopener noreferrer">{{ result.status === 'error' ? 'SIMBAD 查询目标 ↗' : 'SIMBAD 来源 ↗' }}</a>
              <span v-else class="small muted">{{ result.source.url }}</span>
              <span class="small muted results-source-time" :title="result.source.retrieved_at">{{ formatUtc(result.source.retrieved_at) }}</span>
            </div>
          </article>
        </section>

        <!-- Quick Charts & Data Export Bundle -->
        <section v-else-if="view === 'export' && !disableExport" class="export-section ui-card-subtle" aria-label="图表与下载">
          <h3>快速图表与数据包</h3>
          <p class="small muted">{{ artifactPath ? '基于保存的完整快照。' : '基于完整查询结果。' }}图表只描述交付样本。</p>
          <div v-if="response?.gaia_results?.length" class="plot-options">
            <label v-for="(name, kind) in names" :key="kind" class="ui-chip-toggle">
              <input v-model="kinds" type="checkbox" :value="kind" :disabled="busy || !hasPlotData">
              {{ name }}
            </label>
          </div>
          <div class="export-actions">
            <button :disabled="busy" class="button-secondary" @click="generate">{{ busy ? '正在生成…' : '生成预览与数据包' }}</button>
            <button v-if="artifact" class="button-primary" @click="save">下载 ZIP</button>
          </div>
          <StatusNotice v-if="error" title="结果导出未完成" :message="error" @dismiss="error = ''" />
          <template v-if="artifact">
            <p class="small muted">导出{{ artifact.export_status === 'partial' ? '部分完成' : '完成' }} · {{ artifact.exporter_version }}<br>有效期至 {{ artifact.expires_at }}</p>
            <ArtifactFileViewer
              v-if="artifact.figures.length"
              :items="artifact.figures.map(fig => ({ id: fig.figure_id, name: `${names[fig.kind] || fig.kind}.png`, subtitle: '快速图表导出', category: 'image', mediaType: 'image/png', url: apiUrl(fig.url) }))"
              compact
            />
            <template v-if="manifest">
              <p v-for="(plot, i) in manifest.plots" :key="i" class="small">{{ names[String(plot.kind)] }}：{{ plot.status === 'success' ? '已生成' : reasons[String(plot.reason)] || '未生成' }}</p>
            </template>
          </template>
        </section>
      </template>
    </div>
  </aside>
</template>

<style scoped>
.results-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.results-title-block {
  min-width: 0;
  display: flex;
  align-items: center;
}

.results-title-block h2 {
  margin: 0;
  font-size: 15px;
  font-weight: 600;
  line-height: 1.35;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.results-header-actions {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-shrink: 0;
}

.result-icon-action {
  width: 30px;
  height: 30px;
  min-height: 30px;
  padding: 0;
  margin: 0;
  align-self: center;
  border-radius: 9px;
  border: 1px solid var(--border-subtle);
  background: color-mix(in srgb, var(--surface-card) 72%, transparent);
  box-shadow: none;
  color: var(--text-secondary);
  display: grid;
  place-items: center;
  cursor: pointer;
  transition: border-color 0.16s ease, color 0.16s ease, background 0.16s ease;
}

.result-icon-action svg {
  width: 15px;
  height: 15px;
  fill: none;
  stroke: currentColor;
  stroke-width: 1.8;
  stroke-linecap: round;
  stroke-linejoin: round;
}

.result-icon-action:hover,
.result-icon-action[aria-pressed="true"] {
  border-color: color-mix(in srgb, var(--accent) 52%, var(--border-strong));
  color: var(--accent);
  background: color-mix(in srgb, var(--accent) 10%, var(--surface-card));
}

.results-live-banner {
  margin: 0;
  padding: 9px 12px;
  border-radius: 11px;
  border: 1px solid color-mix(in srgb, var(--accent) 26%, var(--border-subtle));
  background: color-mix(in srgb, var(--accent) 8%, var(--surface-card));
  color: var(--text-secondary);
  font-size: 12px;
  display: flex;
  align-items: center;
  gap: 8px;
}

.live-dot {
  width: 7px;
  height: 7px;
  border-radius: 999px;
  background: var(--accent);
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--accent) 22%, transparent);
  flex-shrink: 0;
}

.results-nav-strip {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  min-height: 28px;
}

.results-timestamp {
  margin-left: auto;
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--text-muted);
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.results-source-time {
  font-family: var(--font-mono);
  font-size: 11px;
  font-variant-numeric: tabular-nums;
}

.result-advisory-card {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 10px 12px;
  border-radius: 12px;
  border: 1px solid color-mix(in srgb, var(--line) 92%, transparent);
  background: color-mix(in srgb, var(--surface-card) 82%, transparent);
  box-shadow: var(--shadow-card);
}

.result-advisory-card.is-warning {
  border-color: color-mix(in srgb, var(--warning) 24%, var(--line));
}

.result-advisory-card.is-danger {
  border-color: color-mix(in srgb, var(--danger) 28%, var(--line));
}

.result-advisory-icon {
  width: 24px;
  height: 24px;
  border-radius: 8px;
  display: grid;
  place-items: center;
  flex-shrink: 0;
  margin-top: 1px;
}

.result-advisory-card.is-warning .result-advisory-icon {
  background: var(--warning-soft);
  color: var(--warning);
  border: 1px solid color-mix(in srgb, var(--warning) 22%, transparent);
}

.result-advisory-card.is-danger .result-advisory-icon {
  background: var(--danger-soft);
  color: var(--danger);
  border: 1px solid color-mix(in srgb, var(--danger) 24%, transparent);
}

.result-advisory-icon svg {
  width: 14px;
  height: 14px;
  fill: none;
  stroke: currentColor;
  stroke-width: 1.9;
  stroke-linecap: round;
  stroke-linejoin: round;
}

.result-advisory-copy {
  min-width: 0;
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 5px;
}

.result-advisory-copy p {
  margin: 0;
  font-size: 12.5px;
  line-height: 1.55;
  color: var(--text-primary);
  word-break: break-word;
}

.result-advisory-code {
  display: inline-flex;
  align-items: center;
  padding: 1px 7px;
  border-radius: 6px;
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--text-muted);
  background: color-mix(in srgb, var(--surface-muted) 86%, transparent);
  border: 1px solid color-mix(in srgb, var(--line) 80%, transparent);
}

.results-back-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  min-height: 26px;
  padding: 0 9px 0 6px;
  border-radius: 999px;
  border: 1px solid color-mix(in srgb, var(--border-subtle) 85%, transparent);
  background: color-mix(in srgb, var(--surface-card) 70%, transparent);
  box-shadow: none;
  color: var(--text-secondary);
  font-size: 12px;
  font-weight: 560;
  cursor: pointer;
  transition: border-color 0.15s ease, color 0.15s ease, background 0.15s ease;
}

.results-back-btn svg {
  width: 14px;
  height: 14px;
  fill: none;
  stroke: currentColor;
  stroke-width: 1.9;
  stroke-linecap: round;
  stroke-linejoin: round;
}

.results-back-btn:hover {
  border-color: color-mix(in srgb, var(--accent) 45%, var(--border-strong));
  color: var(--accent);
  background: color-mix(in srgb, var(--accent) 8%, var(--surface-card));
}

.overview-sections {
  display: grid;
  gap: 18px;
}

.overview-group {
  display: grid;
  gap: 7px;
}

.overview-group-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 4px;
  font-size: 11.5px;
  font-weight: 640;
  color: var(--text-muted);
  letter-spacing: 0.02em;
}

.overview-group-head em {
  font-style: normal;
  font-size: 11px;
  font-weight: 660;
  padding: 1px 7px;
  border-radius: 999px;
  background: color-mix(in srgb, var(--surface-muted) 90%, transparent);
  color: var(--text-secondary);
  font-variant-numeric: tabular-nums;
}

.overview-list {
  display: grid;
  gap: 4px;
}

.overview-row {
  width: 100%;
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto;
  align-items: center;
  gap: 10px;
  padding: 9px 11px;
  border-radius: 11px;
  border: 1px solid transparent;
  background: color-mix(in srgb, var(--surface-card) 52%, transparent);
  box-shadow: none;
  text-align: left;
  cursor: pointer;
  transition: background 0.15s ease, border-color 0.15s ease, transform 0.15s ease;
}

.overview-row:hover {
  background: color-mix(in srgb, var(--surface-card) 88%, transparent);
  border-color: color-mix(in srgb, var(--accent) 30%, var(--border-subtle));
  transform: translateY(-1px);
}

.overview-row-badge {
  min-width: 34px;
  height: 24px;
  padding: 0 6px;
  border-radius: 7px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.03em;
  background: color-mix(in srgb, var(--accent) 12%, var(--surface-muted));
  color: var(--accent);
}

.overview-row-badge.is-pdf {
  background: rgba(239, 68, 68, 0.12);
  color: #dc2626;
}

.overview-row-badge.is-image,
.overview-row-badge.is-plot {
  background: rgba(16, 185, 129, 0.12);
  color: #059669;
}

.overview-row-badge.is-compute {
  background: rgba(99, 102, 241, 0.13);
  color: #4f46e5;
}

.overview-row-badge.is-ads {
  background: rgba(59, 130, 246, 0.12);
  color: #2563eb;
}

.overview-row-badge.is-simbad {
  background: rgba(217, 119, 6, 0.12);
  color: #b45309;
}

.overview-row-copy {
  display: grid;
  gap: 2px;
  min-width: 0;
}

.overview-row-copy strong {
  font-size: 12.5px;
  font-weight: 620;
  color: var(--text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.overview-row-copy small {
  font-size: 11px;
  color: var(--text-muted);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.overview-row-arrow {
  font-size: 16px;
  color: var(--text-muted);
  line-height: 1;
}

.tab-count {
  font-style: normal;
  font-size: 10.5px;
  font-weight: 700;
  padding: 0 5px;
  border-radius: 999px;
  background: color-mix(in srgb, var(--accent) 14%, transparent);
  color: var(--accent);
  font-variant-numeric: tabular-nums;
}

.results-empty-studio {
  margin: auto 0;
  padding: 40px 20px;
  display: grid;
  justify-items: center;
  text-align: center;
  gap: 8px;
}

.empty-icon-ring {
  width: 40px;
  height: 40px;
  border-radius: 12px;
  display: grid;
  place-items: center;
  color: var(--accent);
  background: color-mix(in srgb, var(--accent) 10%, var(--surface-card));
  border: 1px solid color-mix(in srgb, var(--accent) 22%, var(--border-subtle));
}

.empty-icon-ring svg {
  width: 19px;
  height: 19px;
  fill: none;
  stroke: currentColor;
  stroke-width: 1.7;
  stroke-linecap: round;
  stroke-linejoin: round;
}

.results-empty-studio h3 {
  margin: 0;
  font-size: 14px;
  font-weight: 660;
  color: var(--text-primary);
}

.results-empty-studio p {
  margin: 0;
  font-size: 12px;
  line-height: 1.7;
  color: var(--text-muted);
  max-width: 280px;
}

.paper-actions-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding-top: 4px;
}

.paper-source-links,
.paper-library-control {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}

.paper-save-btn {
  padding: 4px 11px;
  min-height: 28px;
  font-size: 12px;
  border-radius: var(--radius-pill);
  border: 1px solid color-mix(in srgb, var(--accent) 38%, transparent);
  background: var(--accent-soft);
  color: var(--accent);
  font-weight: 550;
  cursor: pointer;
}

.paper-save-btn:hover:not(:disabled) {
  background: color-mix(in srgb, var(--accent) 16%, transparent);
}

.paper-save-btn:disabled {
  opacity: 0.6;
  cursor: wait;
}

.paper-library-link {
  font-size: 12px;
  font-weight: 550;
  color: var(--accent);
  text-decoration: none;
}

.paper-library-link:hover {
  text-decoration: underline;
}

.paper-save-feedback {
  margin: 4px 0 0;
  font-size: 12px;
}

.paper-save-feedback.is-success {
  color: var(--success);
}

.paper-save-feedback.is-error {
  color: var(--danger);
}

.results-sheet-handle {
  display: none;
}

@media (max-width: 980px) {
  .results-sheet-handle {
    display: flex;
    justify-content: center;
    padding: 8px 0 2px;
    flex: none;
  }

  .results-sheet-handle span {
    width: 38px;
    height: 4px;
    border-radius: 999px;
    background: color-mix(in srgb, var(--muted) 36%, transparent);
  }

  .result-expand-btn {
    display: none;
  }

  .result-close {
    width: 36px;
    height: 36px;
    min-height: 36px;
  }
}
</style>
