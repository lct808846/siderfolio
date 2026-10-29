<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { api, apiUrl, download, safeLink } from '../api'
import type { ArtifactInfo, Manifest, PlotSpec, Turn } from '../types'

const props = defineProps<{ turn: Turn | null; historical: boolean }>()
const tab = ref<'gaia' | 'ads' | 'simbad'>('gaia')
const page = ref(0)
const index = ref(0)
const kinds = ref<PlotSpec['kind'][]>([])
const artifact = ref<ArtifactInfo | null>(null)
const manifest = ref<Manifest | null>(null)
const busy = ref(false)
let generation = 0
const error = ref('')
const response = computed(() => props.turn?.response)
const gaia = computed(() => response.value?.gaia_results?.[index.value])
const fields = computed(() => gaia.value?.data?.[0] ? Object.keys(gaia.value.data[0]) : [])
const rows = computed(() => gaia.value?.data?.slice(page.value * 20, (page.value + 1) * 20) || [])
const names: Record<string, string> = { proper_motion: '自行散点图', parallax_histogram: '视差直方图', observed_cmd: '观测颜色—星等图' }
const reasons: Record<string, string> = { insufficient_data: '有效数据不足', query_not_successful: '查询未成功', unrepresentable_range: '数值范围无法绘制', render_failed: '图片生成失败' }
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
    const generated = await api.artifact(props.turn.conversation_id, turnId, kinds.value.map(kind => ({ kind, gaia_result_index: index.value })))
    const metadata = await api.manifest(generated.manifest_url)
    if (props.turn?.turn_id === turnId && token === generation) { artifact.value = generated; manifest.value = metadata }
  } catch (e) { error.value = e instanceof Error ? e.message : '生成失败' } finally { busy.value = false }
}
async function save() { if (!artifact.value) return; try { await download(artifact.value.download_url) } catch (e) { error.value = e instanceof Error ? e.message : '下载失败'; artifact.value = null } }
</script>

<template>
  <aside class="results-panel" aria-label="结果核查">
    <header class="pane-heading"><div><span class="eyebrow">RESULTS / 数据核查</span><h2>{{ turn ? `第 ${turn.revision} 轮结果` : '查询结果' }}</h2></div><span v-if="historical" class="tag">历史结果</span></header>
    <div v-if="!turn" class="results-empty"><span class="crosshair" aria-hidden="true">⊙</span><h3>让每一个结论有据可查</h3><p>查询后在这里核查测量、检索条件和来源。</p><div class="empty-axis"><span>等待查询数据</span></div></div>
    <template v-else>
      <p class="small muted">接收时间（UTC）<br><time>{{ turn.received_at }}</time></p>
      <p v-if="turn.error" class="notice danger">{{ turn.error.message }} <code>{{ turn.error.code }}</code></p>
      <p v-if="!response" class="notice">这一轮暂时没有可核查的完整响应。</p>
      <template v-if="response">
        <div class="result-tabs" role="tablist" aria-label="数据源"><button v-for="item in (['gaia','ads','simbad'] as const)" :key="item" role="tab" :aria-selected="tab === item" :class="{ active: tab === item }" @click="tab = item">{{ item === 'gaia' ? 'Gaia DR3' : item.toUpperCase() }} <span>{{ item === 'gaia' ? response.gaia_results?.length : item === 'ads' ? response.literature_results?.length : response.results?.length }}</span></button></div>
        <section v-if="tab === 'gaia'" class="source-section">
          <p v-if="!response.gaia_results?.length" class="muted">本轮未执行 Gaia 查询。</p>
          <template v-else>
            <label class="field-label" for="query-index">本轮 Gaia 查询</label><select id="query-index" v-model="index"><option v-for="(result, i) in response.gaia_results" :key="i" :value="i">第 {{ i + 1 }} 次 · {{ result.status }} · {{ result.returned_count }} 行</option></select>
            <template v-if="gaia">
              <p v-if="gaia.error" class="notice danger">{{ gaia.error.message }} <code>{{ gaia.error.code }}</code></p>
              <div class="data-metrics"><span><b>{{ gaia.returned_count }}</b>交付行</span><span><b>未知</b>总命中数</span><span><b>{{ gaia.truncated ? '已截断' : '未截断' }}</b>交付范围</span></div>
              <p v-if="gaia.truncated || gaia.archive_overflow" class="notice">仅描述交付样本{{ gaia.archive_overflow ? ' · Archive 报告溢出' : '' }}，不能代表视场总体。</p>
              <details><summary>条件、单位与程序统计</summary><pre>{{ text({ release: gaia.release, table: gaia.table, query: gaia.query, units: gaia.units, analysis: gaia.analysis }) }}</pre></details>
              <details><summary>实际 ADQL</summary><pre>{{ gaia.adql }}</pre></details>
              <details><summary>查看完整交付表格（{{ (gaia.data?.length || 0) }} 行）</summary><div class="table-scroll" tabindex="0" aria-label="Gaia 完整数据表"><table><thead><tr><th v-for="field in fields" :key="field">{{ field }}<small>{{ gaia.units?.[field] }}</small></th></tr></thead><tbody><tr v-for="row in rows" :key="row.source_id"><td v-for="field in fields" :key="field">{{ text((row as unknown as Record<string, unknown>)[field]) }}</td></tr></tbody></table></div><div class="pagination"><button :disabled="page === 0" @click="page--">上一页</button><span>{{ page + 1 }} / {{ Math.max(1, Math.ceil((gaia.data?.length || 0) / 20)) }}</span><button :disabled="(page + 1) * 20 >= (gaia.data?.length || 0)" @click="page++">下一页</button></div></details>
              <p v-for="warning in gaia.warnings" :key="warning" class="small muted">{{ warning }}</p>
            </template>
          </template>
        </section>
        <section v-if="tab === 'ads'" class="source-section">
          <p v-if="!response.literature_results?.length" class="muted">本轮未执行 ADS 检索。</p>
          <article v-for="(result, i) in response.literature_results" :key="i" class="paper-query"><p class="eyebrow">检索 {{ i + 1 }} · {{ result.status }}</p><pre>{{ result.query }}</pre><p class="small">本页 {{ result.returned_count }} 篇 / 总命中 {{ text(result.total_found) }} · {{ result.sort }}</p><p v-if="result.error" class="notice danger">{{ result.error.message }}</p><article v-for="paper in result.papers" :key="paper.bibcode" class="paper"><h3>{{ paper.title || '未提供标题' }}</h3><p class="small">{{ paper.year || '年份未提供' }} · {{ paper.authors?.join('、') || '作者未提供' }}</p><p class="small mono">{{ paper.bibcode }}</p><p class="small">DOI：{{ paper.doi?.join('；') || '未提供' }}</p><p class="small">{{ paper.publication || '刊物未提供' }} · 被引次数 {{ text(paper.citation_count) }}</p><details><summary>摘要 · 总结仅根据摘要</summary><p class="abstract">{{ paper.abstract || '未提供摘要，不推测结论。' }}</p></details><a v-if="safeLink(paper.source.url)" :href="safeLink(paper.source.url)!" target="_blank" rel="noopener noreferrer">ADS 原始记录 ↗</a><span v-else>{{ paper.source.url }}</span><p class="small muted">UTC {{ paper.source.retrieved_at }}</p></article></article>
        </section>
        <section v-if="tab === 'simbad'" class="source-section">
          <p v-if="!response.results?.length" class="muted">本轮未执行 SIMBAD 查询。</p>
          <article v-for="(result, i) in response.results" :key="i" class="object-result"><h3>{{ result.object_name }}</h3><span class="tag">{{ result.status }}</span><p v-if="result.error" class="notice danger">{{ result.error.message }} <code>{{ result.error.code }}</code></p><dl v-if="result.data"><template v-for="(value, field) in result.data" :key="field"><dt>{{ field }}</dt><dd>{{ text(value) }}</dd></template></dl><p class="small muted">UTC {{ result.source.retrieved_at }}</p><a v-if="safeLink(result.source.url)" :href="safeLink(result.source.url)!" target="_blank" rel="noopener noreferrer">SIMBAD 来源 ↗</a><p v-else>{{ result.source.url }}</p></article>
        </section>
        <section class="export-section" aria-label="图表与下载"><h3>图表与数据包</h3><p class="small muted">基于第 {{ turn.revision }} 轮完整响应。图表只描述交付样本。</p><div v-if="response.gaia_results?.length" class="plot-options"><label v-for="(name, kind) in names" :key="kind"><input v-model="kinds" type="checkbox" :value="kind" :disabled="busy">{{ name }}</label></div><div class="export-actions"><button :disabled="busy" class="button-secondary" @click="generate">{{ busy ? '正在生成…' : '生成预览与数据包' }}</button><button v-if="artifact" class="button-primary" @click="save">下载 ZIP</button></div><p v-if="error" class="notice danger" role="alert">{{ error }}</p><template v-if="artifact"><p class="small muted">导出{{ artifact.export_status === 'partial' ? '部分完成' : '完成' }} · {{ artifact.exporter_version }}<br>有效期至 {{ artifact.expires_at }}</p><figure v-for="picture in artifact.figures" :key="picture.figure_id"><img :src="apiUrl(picture.url)" :alt="names[picture.kind] || picture.kind" @error="error = '图片已过期或不可用，请重新生成。'"><figcaption>{{ names[picture.kind] }} · <a :href="apiUrl(picture.url)" target="_blank" rel="noopener noreferrer">原尺寸 ↗</a></figcaption></figure><template v-if="manifest"><p v-for="(plot, i) in manifest.plots" :key="i" class="small">{{ names[String(plot.kind)] }}：{{ plot.status === 'success' ? '已生成' : reasons[String(plot.reason)] || '未生成' }}</p></template></template></section>
      </template>
    </template>
  </aside>
</template>
