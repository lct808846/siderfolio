<script setup lang="ts">
import { computed, nextTick, onMounted, ref } from 'vue'
import { adminMcpApi } from '../api/skills'
import StatusNotice from './StatusNotice.vue'
import SuccessToast from './SuccessToast.vue'
import type { DiscoveredExternalTool, ExternalMcpServerStatus } from '../types'

const props = defineProps<{
  canHandle: boolean
}>()

const featureEnabled = ref(false)
const servers = ref<ExternalMcpServerStatus[]>([])
const loading = ref(false)
const busyKey = ref('')
const error = ref('')
const notice = ref('')

const reviewDialog = ref<HTMLDialogElement | null>(null)
const reviewOpen = ref(false)
const reviewServerId = ref('')
const reviewRemoteName = ref('')

const reviewedServer = computed(() =>
  servers.value.find(item => item.server_id === reviewServerId.value) || null,
)
const reviewedTool = computed(() =>
  (reviewedServer.value?.tools ?? []).find(item => item.remote_name === reviewRemoteName.value) || null,
)

async function loadServers() {
  loading.value = true
  error.value = ''
  try {
    const res = await adminMcpApi.listServers()
    featureEnabled.value = Boolean(res.feature_enabled)
    servers.value = res.servers || []
  } catch (e) {
    error.value = e instanceof Error ? e.message : '外部 MCP 服务状态读取失败。'
  } finally {
    loading.value = false
  }
}

function replaceServer(updated: ExternalMcpServerStatus) {
  servers.value = servers.value.map(item => (item.server_id === updated.server_id ? updated : item))
}

async function openToolReview(server: ExternalMcpServerStatus, tool: DiscoveredExternalTool) {
  reviewServerId.value = server.server_id
  reviewRemoteName.value = tool.remote_name
  reviewOpen.value = true
  await nextTick()
  const el = reviewDialog.value
  if (el && !el.open) {
    el.showModal()
    el.scrollTop = 0
  }
}

function closeReview() {
  if (reviewDialog.value?.open) reviewDialog.value.close()
}

function onReviewClose() {
  reviewOpen.value = false
}

function onReviewBackdropClick(event: MouseEvent) {
  const el = reviewDialog.value
  if (!el || event.target !== el) return
  const rect = el.getBoundingClientRect()
  const outside =
    event.clientX < rect.left
    || event.clientX > rect.right
    || event.clientY < rect.top
    || event.clientY > rect.bottom
  if (outside) closeReview()
}

async function toggleServer(server: ExternalMcpServerStatus, event: Event) {
  const input = event.target as HTMLInputElement
  const next = input.checked
  if (!props.canHandle) {
    input.checked = server.enabled
    error.value = '请先展开上方「敏感操作重新认证」确认管理员身份后再修改外部 MCP 状态。'
    return
  }
  busyKey.value = `toggle:${server.server_id}`
  error.value = ''
  try {
    const updated = await adminMcpApi.toggleServer(server.server_id, next)
    replaceServer(updated)
    notice.value = next
      ? `已启用外部 MCP 服务「${server.title}」并完成协议与工具核验。`
      : `已停用外部 MCP 服务「${server.title}」。`
  } catch (e) {
    input.checked = server.enabled
    error.value = e instanceof Error ? e.message : '外部 MCP 服务切换失败。'
  } finally {
    busyKey.value = ''
  }
}

async function syncChangedServer(server: ExternalMcpServerStatus) {
  if (!props.canHandle) {
    error.value = '请先完成上方管理员重新认证。'
    return
  }
  busyKey.value = `discover:${server.server_id}`
  error.value = ''
  try {
    const updated = await adminMcpApi.discoverServer(server.server_id)
    replaceServer(updated)
    notice.value = updated.last_sync_status === 'ok'
      ? `已完成「${server.title}」工具清单核验（发现 ${(updated.tools ?? []).length} 项）。`
      : `「${server.title}」核验未通过：${updated.last_error_message || updated.last_error_code}`
  } catch (e) {
    error.value = e instanceof Error ? e.message : '外部 MCP 工具发现失败。'
  } finally {
    busyKey.value = ''
  }
}

async function approveTool(server: ExternalMcpServerStatus, tool: DiscoveredExternalTool) {
  if (!props.canHandle) {
    error.value = '请先完成上方管理员重新认证后再批准外部工具。'
    return
  }
  busyKey.value = `approve:${server.server_id}:${tool.remote_name}`
  error.value = ''
  try {
    const updated = await adminMcpApi.approveTool(
      server.server_id,
      tool.remote_name,
      tool.definition_sha256,
    )
    replaceServer(updated)
    notice.value = `已批准外部只读工具「${tool.title}」（摘要 ${tool.definition_sha256.slice(0, 8)}）。`
  } catch (e) {
    error.value = e instanceof Error ? e.message : '批准外部工具失败。'
  } finally {
    busyKey.value = ''
  }
}

async function revokeTool(server: ExternalMcpServerStatus, tool: DiscoveredExternalTool) {
  if (!props.canHandle) {
    error.value = '请先完成上方管理员重新认证后再停用授权。'
    return
  }
  busyKey.value = `revoke:${server.server_id}:${tool.remote_name}`
  error.value = ''
  try {
    const updated = await adminMcpApi.revokeTool(server.server_id, tool.remote_name)
    replaceServer(updated)
    notice.value = `已停用外部工具「${tool.title}」的调用授权。`
  } catch (e) {
    error.value = e instanceof Error ? e.message : '停用外部工具授权失败。'
  } finally {
    busyKey.value = ''
  }
}

function approvedCount(server: ExternalMcpServerStatus) {
  return (server.tools ?? []).filter(t => t.approved && !t.definition_changed).length
}

function changedCount(server: ExternalMcpServerStatus) {
  return (server.tools ?? []).filter(t => t.definition_changed).length
}

function syncStatusLabel(status: ExternalMcpServerStatus['last_sync_status']) {
  if (status === 'ok') return '已核验'
  if (status === 'incompatible') return '协议不兼容'
  if (status === 'error') return '发现异常'
  return '尚未发现'
}

function syncStatusClass(status: ExternalMcpServerStatus['last_sync_status']) {
  if (status === 'ok') return 'ui-pill-success'
  if (status === 'incompatible' || status === 'error') return 'ui-pill-danger'
  return 'ui-pill-neutral'
}

function formatTime(value?: string | null) {
  if (!value) return '尚未同步'
  const dt = new Date(value)
  if (Number.isNaN(dt.getTime())) return value
  return dt.toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai', hour12: false })
}

function formatJson(value: unknown) {
  try {
    return JSON.stringify(value, null, 2)
  } catch {
    return String(value)
  }
}

onMounted(() => {
  void loadServers()
})
</script>

<template>
  <div class="admin-mcp-panel">
    <SuccessToast v-model:message="notice" />
    <StatusNotice v-if="error" title="外部 MCP 管理操作未完成" :message="error" @dismiss="error = ''" />

    <p v-if="!canHandle" class="notice warning admin-mcp-reauth-tip">
      当前为只读视图。启用/停用外部服务及批准或撤销工具授权前，请先展开上方「敏感操作重新认证」。
    </p>

    <p v-if="loading && !servers.length" class="small muted" role="status">正在同步外部 MCP 服务状态…</p>

    <div v-else-if="!featureEnabled" class="ui-empty-card">
      <h3>外部 MCP 接入默认关闭</h3>
      <p>
        如需接入运营者预配的只读 Streamable HTTP 科研 MCP 服务，请在服务端私有配置中启用
        <code>ASTROAGENT_EXTERNAL_MCP_ENABLED=true</code> 并配置固定白名单端点
        <code>ASTROAGENT_EXTERNAL_MCP_SERVERS_JSON</code>。浏览器不允许注册任意外部地址或本地命令。
      </p>
    </div>

    <div v-else-if="!servers.length" class="ui-empty-card">
      <h3>尚未配置外部 MCP 服务</h3>
      <p>已开启外部 MCP 开关，但 <code>ASTROAGENT_EXTERNAL_MCP_SERVERS_JSON</code> 中暂无预配服务。</p>
    </div>

    <div v-else class="admin-mcp-server-list">
      <article v-for="server in servers" :key="server.server_id" class="admin-mcp-server-card">
        <header class="admin-mcp-server-head">
          <div class="admin-mcp-server-meta">
            <div class="admin-mcp-title-row">
              <h3>{{ server.title }}</h3>
              <span class="ui-pill ui-pill-mono">{{ server.server_id }}</span>
              <span class="ui-pill" :class="server.enabled ? 'ui-pill-success' : 'ui-pill-neutral'">
                {{ server.enabled ? '已启用' : '已停用' }}
              </span>
              <span class="ui-pill" :class="syncStatusClass(server.last_sync_status)">
                {{ syncStatusLabel(server.last_sync_status) }}
              </span>
            </div>
            <p class="small muted">
              固定端点 <code>{{ server.endpoint_display }}</code> · 协议
              <code>{{ server.protocol_version }}</code>
              <template v-if="server.tools?.length">
                · 已批准 {{ approvedCount(server) }} / {{ server.tools.length }} 项
              </template>
              <template v-if="changedCount(server)">
                · {{ changedCount(server) }} 项定义已变更
              </template>
            </p>
            <p class="small muted">
              最近发现：{{ formatTime(server.last_discovered_at) }}
              <template v-if="server.auth_env_ref">
                · 凭据 <code>{{ server.auth_env_ref }}</code>（{{ server.auth_configured ? '已配置' : '未配置' }}）
              </template>
            </p>
            <p v-if="server.last_error_message" class="admin-mcp-error-record">
              最近失败：{{ server.last_error_message }}
              <code v-if="server.last_error_code">{{ server.last_error_code }}</code>
            </p>
          </div>

          <div class="admin-mcp-server-controls">
            <button
              v-if="server.enabled && (server.last_sync_status !== 'ok' || changedCount(server) > 0)"
              type="button"
              :disabled="!!busyKey || !canHandle"
              @click="syncChangedServer(server)"
            >
              {{ busyKey === `discover:${server.server_id}` ? '正在核验…' : '重新核验定义' }}
            </button>
            <label class="admin-mcp-toggle">
              <span>{{ server.enabled ? '启用' : '停用' }}</span>
              <input
                class="settings-switch"
                type="checkbox"
                role="switch"
                :aria-label="`切换外部 MCP 服务 ${server.title}`"
                :checked="server.enabled"
                :disabled="!!busyKey"
                @change="toggleServer(server, $event)"
              />
            </label>
          </div>
        </header>

        <div v-if="server.tools?.length" class="admin-mcp-tools-list">
          <div
            v-for="tool in server.tools"
            :key="tool.remote_name"
            class="admin-mcp-tool-row"
            :class="{ 'is-changed': tool.definition_changed }"
          >
            <button
              type="button"
              class="admin-mcp-tool-main"
              @click="openToolReview(server, tool)"
            >
              <span class="admin-mcp-title-row">
                <strong>{{ tool.title }}</strong>
                <span class="ui-pill" :class="tool.eligible_readonly ? 'ui-pill-accent' : 'ui-pill-danger'">
                  {{ tool.eligible_readonly ? '只读' : '非只读' }}
                </span>
                <span v-if="tool.definition_changed" class="ui-pill ui-pill-warning">定义变更</span>
                <span v-else-if="tool.approved" class="ui-pill ui-pill-success">已批准</span>
                <span v-else class="ui-pill ui-pill-neutral">未批准</span>
              </span>
              <span class="admin-mcp-tool-summary">
                {{ tool.description || tool.tool_id }}
              </span>
            </button>

            <div class="admin-mcp-tool-actions">
              <button
                type="button"
                class="admin-mcp-review-btn"
                @click="openToolReview(server, tool)"
              >
                <span>审查</span>
                <span aria-hidden="true">›</span>
              </button>
              <button
                v-if="tool.approved || tool.definition_changed"
                type="button"
                class="button-danger"
                :disabled="!!busyKey || !canHandle"
                @click="revokeTool(server, tool)"
              >
                停用授权
              </button>
            </div>
          </div>
        </div>
        <p v-else class="small muted admin-mcp-empty-tools">
          {{ server.enabled ? '尚未发现可审查的工具，或远端连接尚未就绪。' : '启用服务后将自动校验协议版本并分页发现工具清单。' }}
        </p>
      </article>
    </div>

    <!-- 模糊背景工具审查弹窗 -->
    <dialog
      ref="reviewDialog"
      class="project-dialog admin-mcp-dialog"
      aria-labelledby="admin-mcp-review-title"
      @close="onReviewClose"
      @click="onReviewBackdropClick"
    >
      <header class="admin-mcp-dialog-head">
        <h2 id="admin-mcp-review-title">{{ reviewedTool?.title || '外部工具审查' }}</h2>
        <button type="button" class="admin-mcp-dialog-close" aria-label="关闭" @click="closeReview">×</button>
      </header>

      <div v-if="reviewedServer && reviewedTool" class="admin-mcp-dialog-body">
        <div class="admin-mcp-dialog-bar">
          <div class="ui-pill-list">
            <span class="ui-pill" :class="reviewedTool.eligible_readonly ? 'ui-pill-accent' : 'ui-pill-danger'">
              {{ reviewedTool.eligible_readonly ? '声明为只读 · 可审核' : '非只读 / 具破坏性（禁止批准）' }}
            </span>
            <span v-if="reviewedTool.definition_changed" class="ui-pill ui-pill-warning">
              定义已变更 · 已自动暂停调用
            </span>
            <span v-else-if="reviewedTool.approved" class="ui-pill ui-pill-success">已批准</span>
            <span v-else class="ui-pill ui-pill-neutral">未批准</span>
            <span class="ui-pill ui-pill-mono">协议 {{ reviewedServer.negotiated_protocol_version || reviewedServer.protocol_version }}</span>
          </div>
        </div>

        <p v-if="reviewedTool.description" class="admin-mcp-dialog-desc">{{ reviewedTool.description }}</p>

        <dl class="admin-mcp-dialog-dl">
          <div class="admin-mcp-dialog-card">
            <dt>工具标识与归属</dt>
            <dd>
              目录 ID：<code>{{ reviewedTool.tool_id }}</code> · 远端名称：<code>{{ reviewedTool.remote_name }}</code>
              · 服务：{{ reviewedServer.title }}（<code>{{ reviewedServer.endpoint_display }}</code>）
            </dd>
          </div>
          <div class="admin-mcp-dialog-card">
            <dt>定义摘要与审批记录</dt>
            <dd>
              <div>当前定义 SHA-256：<code>{{ reviewedTool.definition_sha256 }}</code></div>
              <div v-if="reviewedTool.approved_definition_sha256">
                已批定义 SHA-256：<code>{{ reviewedTool.approved_definition_sha256 }}</code>
              </div>
              <div v-if="reviewedTool.approved_at" class="small muted">
                最近批准：{{ formatTime(reviewedTool.approved_at) }}
              </div>
              <div v-if="reviewedTool.revoked_at" class="small muted">
                最近撤销：{{ formatTime(reviewedTool.revoked_at) }}
              </div>
            </dd>
          </div>
          <div class="admin-mcp-dialog-card">
            <dt>只读声明与允许外发字段</dt>
            <dd>
              <div>
                readOnlyHint：<code>{{ String(reviewedTool.read_only_hint) }}</code> ·
                destructiveHint：<code>{{ String(reviewedTool.destructive_hint) }}</code>
              </div>
              <div v-if="reviewedTool.parameter_names?.length" class="ui-pill-list" style="margin-top: 6px;">
                <span v-for="field in reviewedTool.parameter_names" :key="field" class="ui-pill ui-pill-mono">
                  {{ field }}
                </span>
              </div>
              <div v-else class="small muted" style="margin-top: 4px;">无入参字段（空对象）。</div>
            </dd>
          </div>
          <div class="admin-mcp-dialog-card">
            <dt>完整输入契约（inputSchema）</dt>
            <dd>
              <pre class="admin-mcp-schema-pre">{{ formatJson(reviewedTool.input_schema) }}</pre>
            </dd>
          </div>
          <div v-if="reviewedTool.output_schema" class="admin-mcp-dialog-card">
            <dt>输出契约（outputSchema）</dt>
            <dd>
              <pre class="admin-mcp-schema-pre">{{ formatJson(reviewedTool.output_schema) }}</pre>
            </dd>
          </div>
        </dl>

        <footer class="admin-mcp-dialog-actions">
          <button type="button" @click="closeReview">关闭</button>
          <button
            v-if="reviewedTool.approved || reviewedTool.definition_changed"
            type="button"
            class="button-danger"
            :disabled="!!busyKey || !canHandle"
            @click="revokeTool(reviewedServer, reviewedTool)"
          >
            停用授权
          </button>
          <button
            v-if="!reviewedTool.approved && reviewedTool.eligible_readonly"
            type="button"
            class="button-primary"
            :disabled="!!busyKey || !canHandle || !reviewedServer.enabled"
            @click="approveTool(reviewedServer, reviewedTool)"
          >
            {{ reviewedTool.definition_changed ? '核对无误，重新批准' : '核对无误，批准只读调用' }}
          </button>
        </footer>
      </div>
    </dialog>
  </div>
</template>

<style scoped>
.admin-mcp-panel {
  display: grid;
  gap: 14px;
}

.admin-mcp-reauth-tip {
  margin: 0;
}

.admin-mcp-server-list {
  display: grid;
  gap: 14px;
}

.admin-mcp-server-card {
  display: grid;
  gap: 12px;
  padding: 16px;
  border: 1px solid var(--line);
  border-radius: var(--radius-card);
  background: var(--surface-subtle);
}

.admin-mcp-server-head {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.admin-mcp-server-meta {
  display: grid;
  gap: 4px;
  min-width: 0;
}

.admin-mcp-title-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}

.admin-mcp-title-row h3 {
  margin: 0;
  font-size: 15px;
  font-weight: 620;
  color: var(--ink);
}

.admin-mcp-server-controls {
  display: flex;
  align-items: center;
  gap: 12px;
  flex: none;
}

.admin-mcp-toggle {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  color: var(--muted);
  cursor: pointer;
}

.admin-mcp-error-record {
  margin: 4px 0 0;
  font-size: 12.5px;
  color: var(--danger);
}

.admin-mcp-tools-list {
  display: grid;
  gap: 6px;
  padding-top: 10px;
  border-top: 1px solid var(--line);
}

.admin-mcp-tool-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 8px 10px;
  border: 1px solid var(--line);
  border-radius: var(--radius-control);
  background: var(--paper);
}

.admin-mcp-tool-row.is-changed {
  border-color: color-mix(in srgb, var(--warning) 48%, var(--line));
}

.admin-mcp-tool-main {
  flex: 1;
  min-width: 0;
  display: grid;
  gap: 3px;
  padding: 3px 5px;
  margin: -3px -5px;
  border: 0;
  border-radius: var(--radius-control);
  background: transparent;
  box-shadow: none;
  text-align: left;
  color: inherit;
  cursor: pointer;
}

.admin-mcp-tool-main:hover {
  background: var(--hover-veil, var(--surface-subtle));
  transform: none;
  box-shadow: none;
}

.admin-mcp-tool-summary {
  font-size: 12px;
  color: var(--muted);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.admin-mcp-tool-actions {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  flex: none;
}

.admin-mcp-review-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 5px 10px;
  border: 1px solid var(--line);
  border-radius: var(--radius-control);
  background: transparent;
  color: var(--muted);
  font-size: 12.5px;
  box-shadow: none;
}

.admin-mcp-review-btn:hover {
  color: var(--ink);
  border-color: var(--line-strong);
  background: var(--hover-veil, var(--surface-subtle));
  transform: none;
  box-shadow: none;
}

.admin-mcp-empty-tools {
  margin: 0;
  padding-top: 8px;
  border-top: 1px solid var(--line);
}

.admin-mcp-dialog {
  width: min(740px, calc(100vw - 32px));
  max-height: calc(100dvh - 48px);
  overflow: auto;
  padding: var(--space-5);
  color: var(--ink);
}

.admin-mcp-dialog-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-4);
  margin-bottom: var(--space-4);
}

.admin-mcp-dialog-head h2 {
  margin: 0;
  font: 550 20px/1.4 var(--font-ui);
}

.admin-mcp-dialog-close {
  display: grid;
  place-items: center;
  width: 34px;
  height: 34px;
  flex: none;
  padding: 0;
  border: 1px solid transparent;
  border-radius: var(--radius-control);
  background: transparent;
  box-shadow: none;
  font-size: 24px;
  line-height: 1;
  color: var(--muted);
}

.admin-mcp-dialog-close:hover {
  background: var(--hover-veil, var(--surface-subtle));
  color: var(--ink);
  transform: none;
  box-shadow: none;
}

.admin-mcp-dialog-body {
  display: grid;
  gap: 12px;
}

.admin-mcp-dialog-bar {
  padding-bottom: 10px;
  border-bottom: 1px solid var(--line);
}

.admin-mcp-dialog-desc {
  margin: 0;
  font-size: 13.5px;
  line-height: 1.65;
}

.admin-mcp-dialog-dl {
  display: grid;
  gap: 10px;
  margin: 0;
}

.admin-mcp-dialog-card {
  display: grid;
  gap: 6px;
  padding: 12px 14px;
  border: 1px solid var(--line);
  border-radius: var(--radius-card);
  background: var(--surface-subtle);
}

.admin-mcp-dialog-card dt {
  font-size: 11.5px;
  font-weight: 600;
  color: var(--muted);
}

.admin-mcp-dialog-card dd {
  margin: 0;
  font-size: 12.5px;
  line-height: 1.6;
  overflow-wrap: anywhere;
}

.admin-mcp-schema-pre {
  margin: 0;
  padding: 10px;
  max-height: 240px;
  overflow: auto;
  border: 1px solid var(--line);
  border-radius: var(--radius-control);
  background: var(--surface-card);
  font: 11.5px/1.5 var(--font-mono);
}

.admin-mcp-dialog-actions {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 8px;
  padding-top: 10px;
  border-top: 1px solid var(--line);
}
</style>
