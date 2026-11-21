<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { api, apiUrl, download, safeLink } from '../api'
import type { ArtifactInfo, Manifest, PlotSpec, Turn } from '../types'

const props = defineProps<{ turn: Turn | null; historical: boolean; artifactPath?: string; heading?: string; disableExport?: boolean; dismissible?: boolean; pending?: boolean }>()
defineEmits<{ close: [] }>()
const tab = ref<'gaia' | 'ads' | 'simbad'>('gaia')
const page = ref(0)
const index = ref(0)
const kinds = ref<PlotSpec['kind'][]>([])
const artifact = ref<ArtifactInfo | null>(null)
const manifest = ref<Manifest | null>(null)
const busy = ref(false)
let generation = 0
const error = ref('')
const quickCharts = ref<HTMLElement | null>(null)
const response = computed(() => props.turn?.response)
const gaia = computed(() => response.value?.gaia_results?.[index.value])
const querySucceeded = computed(() => gaia.value?.status === 'success' || gaia.value?.status === 'not_found')
const hasPlotData = computed(() => gaia.value?.status === 'success' && !!gaia.value.data?.length)
const plotDestination = computed(() => {
  const snapshot = props.artifactPath?.match(/^\/api\/v1\/projects\/([^/]+)\/snapshots\/([^/]+)\/artifacts$/)
  return snapshot ? { path: '/', query: { mode: 'plot', plot_project: snapshot[1], plot_snapshot: snapshot[2], plot_query: String(index.value) } }
    : { path: `/conversations/${props.turn?.conversation_id}`, query: { mode: 'plot', plot_turn: props.turn?.turn_id, plot_query: String(index.value) } }
})
const fields = computed(() => gaia.value?.data?.[0] ? Object.keys(gaia.value.data[0]) : [])
const rows = computed(() => gaia.value?.data?.slice(page.value * 20, (page.value + 1) * 20) || [])
const names: Record<string, string> = { proper_motion: '自行散点图', parallax_histogram: '视差直方图', observed_cmd: '观测颜色—星等图' }
const reasons: Record<string, string> = { insufficient_data: '有效数据不足', query_not_successful: '查询未成功', unrepresentable_range: '数值范围无法绘制', render_failed: '图片生成失败' }
const statLabels: Record<string, string> = {
  parallax: '视差 (parallax)',
  pmra: '赤经自行 (pmra)',
  pmdec: '赤纬自行 (pmdec)',
  phot_g_mean_mag: 'G 波段星等',
  bp_rp: 'BP − RP 色指数',
  radial_velocity: '视向速度 (RV)',
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
function text(value: unknown): string { return value === null || value === undefined ? '未提供' : typeof value === 'object' ? JSON.stringify(value) : String(value) }
function resetArtifact() { generation++; artifact.value = null; manifest.value = null; error.value = '' }
watch(() => props.turn?.turn_id, () => { resetArtifact(); index.value = 0; page.value = 0; kinds.value = []; tab.value = props.turn?.response?.gaia_results?.length ? 'gaia' : props.turn?.response?.literature_results?.length ? 'ads' : 'simbad' })
watch([index, kinds], resetArtifact, { deep: true })
watch(index, () => { page.value = 0 })
async function generate() {
  if (!props.turn) return
  busy.value = true; error.value = ''; resetArtifact()
  const token = generation
  const turnId = props.turn.turn_id
  try {
    const plots = hasPlotData.value ? kinds.value.map(kind => ({ kind, gaia_result_index: index.value })) : []
    const generated = props.artifactPath ? await api.snapshotArtifact(props.artifactPath, plots) : await api.artifact(props.turn.conversation_id, turnId, plots)
    const metadata = await api.manifest(generated.manifest_url)
    if (props.turn?.turn_id === turnId && token === generation) { artifact.value = generated; manifest.value = metadata }
  } catch (e) { error.value = e instanceof Error ? e.message : '生成失败' } finally { busy.value = false }
}
async function save() { if (!artifact.value) return; try { await download(artifact.value.download_url) } catch (e) { error.value = e instanceof Error ? e.message : '下载失败'; artifact.value = null } }
</script>

<template>
  <aside class="results-panel" aria-label="结果核查">
    <header class="pane-heading workspace-pane-header"><div><span class="eyebrow">RESULTS / 数据核查</span><h2>{{ heading || (turn ? `第 ${turn.revision} 轮结果` : '查询结果') }}</h2></div><span v-if="historical" class="tag">历史结果</span><button v-if="dismissible" class="result-close" aria-label="收起结果面板" @click="$emit('close')">×</button></header>
    <div class="workspace-pane-body">
    <p v-if="pending" class="notice" role="status">{{ turn ? '本轮正在查询；下方为此前保存的结果，返回后会自动切换到本轮。' : '本轮正在查询，返回后将在这里展示实际结果。' }}</p>
    <div v-if="!turn" class="results-empty">
      <slot name="empty">
        <h3>暂无查询结果</h3>
        <p>提交查询后，可在此查看数据、检索条件、来源与导出选项。</p>
      </slot>
    </div>
    <template v-else>
      <p class="small muted">{{ artifactPath ? "快照保存时间（UTC）" : "接收时间（UTC）" }}<br><time>{{ turn.received_at }}</time></p>
      <p v-if="turn.error" class="notice danger">{{ turn.error.message }} <code>{{ turn.error.code }}</code></p>
      <p v-if="!response" class="notice">这一轮暂时没有可核查的完整响应。</p>
      <template v-if="response">
        <div class="result-tabs" role="tablist" aria-label="数据源"><button v-for="item in (['gaia','ads','simbad'] as const)" :key="item" role="tab" :aria-selected="tab === item" :class="{ active: tab === item }" @click="tab = item">{{ item === 'gaia' ? 'Gaia DR3' : item.toUpperCase() }} <span>{{ item === 'gaia' ? response.gaia_results?.length : item === 'ads' ? response.literature_results?.length : response.results?.length }}</span></button></div>
        <section v-if="tab === 'gaia'" class="source-section">
          <p v-if="!response.gaia_results?.length" class="muted">本轮未执行 Gaia 查询。</p>
          <template v-else>
            <label class="field-label" for="query-index">本轮 Gaia 查询</label><select id="query-index" v-model="index"><option v-for="(result, i) in response.gaia_results" :key="i" :value="i">第 {{ i + 1 }} 次 · {{ result.status === 'success' ? `${result.returned_count} 行 · 成功` : result.status === 'not_found' ? '0 行 · 条件下无匹配' : '未取得数据' }}</option></select>
            <template v-if="gaia">
              <p v-if="gaia.error" class="notice" :class="{ danger: !querySucceeded }">{{ gaia.error.message }} <code>{{ gaia.error.code }}</code></p>
              <p v-if="!querySucceeded" class="notice" role="status">本次未取得可用数据，不能据此判断视场中没有天体。交付数量和截断状态不适用；可核对条件后手动重试，旧记录保留。</p>
              <div v-if="hasPlotData && !disableExport" class="result-plot-actions"><RouterLink class="plot-primary" :to="plotDestination">用本轮结果绘图</RouterLink><button type="button" @click="quickCharts?.scrollIntoView({ behavior: 'smooth', block: 'start' })">快速图表</button><p class="small muted">自定义图形会保留完整数据、单位和来源；快速图表可直接预览。</p></div>
              <div class="data-metrics"><span><b>{{ querySucceeded ? gaia.returned_count : '未取得' }}</b>交付行</span><span><b>未知</b>总命中数</span><span><b>{{ !querySucceeded ? '不适用' : gaia.truncated ? '已截断' : '未截断' }}</b>交付范围</span></div>
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
              <details v-if="querySucceeded"><summary>查看完整交付表格（{{ (gaia.data?.length || 0) }} 行）</summary><div class="table-scroll" tabindex="0" aria-label="Gaia 完整数据表"><table><thead><tr><th v-for="field in fields" :key="field">{{ field }}<small>{{ gaia.units?.[field] }}</small></th></tr></thead><tbody><tr v-for="row in rows" :key="row.source_id"><td v-for="field in fields" :key="field">{{ text((row as unknown as Record<string, unknown>)[field]) }}</td></tr></tbody></table></div><div class="pagination"><button :disabled="page === 0" @click="page--">上一页</button><span>{{ page + 1 }} / {{ Math.max(1, Math.ceil((gaia.data?.length || 0) / 20)) }}</span><button :disabled="(page + 1) * 20 >= (gaia.data?.length || 0)" @click="page++">下一页</button></div></details>
              <p v-for="warning in gaia.warnings" :key="warning" class="small muted">{{ warning }}</p>
            </template>
          </template>
        </section>
        <section v-if="tab === 'ads'" class="source-section">
          <p v-if="!response.literature_results?.length" class="muted">本轮未执行 ADS 检索。</p>
          <article v-for="(result, i) in response.literature_results" :key="i" class="paper-query">
            <div class="ui-pill-list">
              <span class="ui-pill ui-pill-ads">ADS 检索 {{ i + 1 }}</span>
              <span class="ui-pill" :class="result.status === 'success' ? 'ui-pill-success' : 'ui-pill-warning'">{{ result.status }}</span>
              <span class="ui-pill ui-pill-neutral">本页 {{ result.returned_count }} / 总命中 {{ text(result.total_found) }}</span>
              <span class="ui-pill ui-pill-neutral">{{ result.sort }}</span>
            </div>
            <pre>{{ result.query }}</pre>
            <p v-if="result.error" class="notice danger">{{ result.error.message }}</p>
            <article v-for="paper in result.papers" :key="paper.bibcode" class="paper">
              <div class="ui-pill-list">
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
              <div class="ui-card-head">
                <a v-if="safeLink(paper.source.url)" :href="safeLink(paper.source.url)!" class="ui-pill ui-pill-ads" target="_blank" rel="noopener noreferrer">ADS 原始记录 ↗</a>
                <span v-else class="small muted">{{ paper.source.url }}</span>
                <span class="small muted">UTC {{ paper.source.retrieved_at }}</span>
              </div>
            </article>
          </article>
        </section>
        <section v-if="tab === 'simbad'" class="source-section">
          <p v-if="!response.results?.length" class="muted">本轮未执行 SIMBAD 查询。</p>
          <article v-for="(result, i) in response.results" :key="i" class="object-result">
            <div class="ui-card-head">
              <h3>{{ result.object_name }}</h3>
              <span class="ui-pill" :class="result.status === 'success' ? 'ui-pill-simbad' : 'ui-pill-warning'">{{ result.status }}</span>
            </div>
            <p v-if="result.error" class="notice danger">{{ result.error.message }} <code>{{ result.error.code }}</code></p>
            <dl v-if="result.data" class="ui-param-grid">
              <div v-for="(value, field) in result.data" :key="field" class="ui-param-tile">
                <dt>{{ field }}</dt>
                <dd>{{ text(value) }}</dd>
              </div>
            </dl>
            <div class="ui-card-head">
              <a v-if="safeLink(result.source.url)" :href="safeLink(result.source.url)!" class="ui-pill ui-pill-simbad" target="_blank" rel="noopener noreferrer">SIMBAD 来源 ↗</a>
              <span v-else class="small muted">{{ result.source.url }}</span>
              <span class="small muted">UTC {{ result.source.retrieved_at }}</span>
            </div>
          </article>
        </section>
        <section v-if="!disableExport" ref="quickCharts" class="export-section ui-card-subtle" aria-label="图表与下载"><h3>快速图表与数据包</h3><p class="small muted">{{ artifactPath ? "基于保存的完整快照。" : `基于第 ${turn.revision} 轮完整响应。` }}图表只描述交付样本。</p><div v-if="response.gaia_results?.length" class="plot-options"><label v-for="(name, kind) in names" :key="kind" class="ui-chip-toggle"><input v-model="kinds" type="checkbox" :value="kind" :disabled="busy || !hasPlotData">{{ name }}</label></div><div class="export-actions"><button :disabled="busy" class="button-secondary" @click="generate">{{ busy ? '正在生成…' : '生成预览与数据包' }}</button><button v-if="artifact" class="button-primary" @click="save">下载 ZIP</button></div><p v-if="error" class="notice danger" role="alert">{{ error }}</p><template v-if="artifact"><p class="small muted">导出{{ artifact.export_status === 'partial' ? '部分完成' : '完成' }} · {{ artifact.exporter_version }}<br>有效期至 {{ artifact.expires_at }}</p><figure v-for="picture in artifact.figures" :key="picture.figure_id"><img :src="apiUrl(picture.url)" :alt="names[picture.kind] || picture.kind" @error="error = '图片已过期或不可用，请重新生成。'"><figcaption>{{ names[picture.kind] }} · <a :href="apiUrl(picture.url)" target="_blank" rel="noopener noreferrer">原尺寸 ↗</a></figcaption></figure><template v-if="manifest"><p v-for="(plot, i) in manifest.plots" :key="i" class="small">{{ names[String(plot.kind)] }}：{{ plot.status === 'success' ? '已生成' : reasons[String(plot.reason)] || '未生成' }}</p></template></template></section>
      </template>
    </template>
    </div>
  </aside>
</template>
