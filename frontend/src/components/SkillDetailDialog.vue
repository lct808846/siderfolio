<script setup lang="ts">
import { computed, nextTick, ref } from 'vue'
import { useSkills } from '../stores/skills'
import StatusNotice from './StatusNotice.vue'
import SuccessToast from './SuccessToast.vue'

type DialogMode = 'manage' | 'skill' | 'tools'

const skillsStore = useSkills()
const dialog = ref<HTMLDialogElement | null>(null)
const isOpen = ref(false)
const mode = ref<DialogMode>('skill')
const rootMode = ref<DialogMode>('skill')
const activeSkillId = ref('')
const notice = ref('')

const selectedSkill = computed(() =>
  activeSkillId.value ? skillsStore.byId(activeSkillId.value) || null : null,
)
const enabledCount = computed(() => skillsStore.skills.filter(s => s.enabled !== false).length)
const builtinToolCount = computed(() => skillsStore.tools.filter(t => t.source !== 'external_mcp').length)
const externalToolCount = computed(() => skillsStore.tools.filter(t => t.source === 'external_mcp').length)
const canGoBack = computed(() => rootMode.value === 'manage' && mode.value !== 'manage')

const toolMap = computed(() => {
  const map = new Map<string, (typeof skillsStore.tools)[number]>()
  for (const tool of skillsStore.tools) map.set(tool.tool_id, tool)
  return map
})

const dialogTitle = computed(() => {
  if (mode.value === 'manage') return '科研技能与工具'
  if (mode.value === 'tools') return '当前可用工具目录'
  return selectedSkill.value?.title || '技能详情'
})

async function ensureModalShown() {
  void Promise.all([skillsStore.load(true), skillsStore.loadTools()])
  isOpen.value = true
  await nextTick()
  const el = dialog.value
  if (el && !el.open) {
    el.showModal()
    el.scrollTop = 0
  }
}

async function openSkill(skillId: string) {
  rootMode.value = 'skill'
  mode.value = 'skill'
  activeSkillId.value = skillId
  await ensureModalShown()
}

async function openTools() {
  rootMode.value = 'tools'
  mode.value = 'tools'
  activeSkillId.value = ''
  await ensureModalShown()
}

async function openManage() {
  rootMode.value = 'manage'
  mode.value = 'manage'
  activeSkillId.value = ''
  await ensureModalShown()
}

function drillToSkill(skillId: string) {
  activeSkillId.value = skillId
  mode.value = 'skill'
  if (dialog.value) dialog.value.scrollTop = 0
}

function drillToTools() {
  activeSkillId.value = ''
  mode.value = 'tools'
  if (dialog.value) dialog.value.scrollTop = 0
}

function goBack() {
  mode.value = 'manage'
  activeSkillId.value = ''
  if (dialog.value) dialog.value.scrollTop = 0
}

function close() {
  if (dialog.value?.open) dialog.value.close()
}

function onDialogClose() {
  isOpen.value = false
}

function onBackdropClick(event: MouseEvent) {
  const el = dialog.value
  if (!el || event.target !== el) return
  const rect = el.getBoundingClientRect()
  const outside =
    event.clientX < rect.left
    || event.clientX > rect.right
    || event.clientY < rect.top
    || event.clientY > rect.bottom
  if (outside) close()
}

async function toggleSkill(skillId: string, event: Event) {
  const checked = (event.target as HTMLInputElement).checked
  const current = new Set(skillsStore.preferences.disabled_skill_ids || [])
  if (checked) current.delete(skillId)
  else current.add(skillId)
  const ok = await skillsStore.updatePreferences({
    auto_match: true,
    disabled_skill_ids: Array.from(current),
  })
  if (ok) {
    const item = skillsStore.byId(skillId)
    notice.value = checked
      ? `已启用技能「${item?.title || skillId}」。`
      : `已停用技能「${item?.title || skillId}」。`
  }
}

function sourceLabel(source: string) {
  if (source === 'external_mcp') return '外部 MCP'
  if (source === 'local_mcp') return '本地 MCP'
  return '内置服务'
}

function effectLabel(level: string) {
  if (level === 'readonly') return '只读查询'
  if (level === 'external_readonly') return '外发查询 · 需确认'
  if (level === 'internal_write') return '写入个人库 · 需明确指令'
  return '生成方案 · 确认后运行'
}

defineExpose({ openSkill, openTools, openManage, close })
</script>

<template>
  <dialog
    ref="dialog"
    class="project-dialog skill-modal-dialog"
    aria-labelledby="skill-modal-title"
    @close="onDialogClose"
    @click="onBackdropClick"
  >
    <SuccessToast v-model:message="notice" />
    <StatusNotice
      v-if="skillsStore.error && isOpen"
      title="技能设置操作未完成"
      :message="skillsStore.error"
      @dismiss="skillsStore.error = ''"
    />

    <header class="skill-modal-heading">
      <div class="skill-modal-title-group">
        <button
          v-if="canGoBack"
          type="button"
          class="skill-modal-back"
          aria-label="返回上一级"
          @click="goBack"
        >
          <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M19 12H5m6-6-6 6 6 6" /></svg>
        </button>
        <h2 id="skill-modal-title">{{ dialogTitle }}</h2>
      </div>
      <button type="button" class="skill-modal-close" aria-label="关闭" @click="close">×</button>
    </header>

    <!-- 模式 1：从工作台弹出的技能与工具管理总览 -->
    <div v-if="mode === 'manage'" class="skill-modal-body">
      <section class="skill-modal-card">
        <div class="skill-modal-section-head">
          <h3>内置科研技能</h3>
          <span class="ui-pill ui-pill-neutral">已启用 {{ enabledCount }} / {{ skillsStore.skills.length }}</span>
        </div>
        <div class="skill-modal-list">
          <div v-for="skill in skillsStore.skills" :key="skill.id" class="skill-modal-row">
            <button type="button" class="skill-modal-row-main" @click="drillToSkill(skill.id)">
              <span class="skill-modal-inline-title">
                <strong>{{ skill.title }}</strong>
                <span class="ui-pill ui-pill-mono">v{{ skill.version }}</span>
              </span>
              <span class="skill-modal-row-desc">{{ skill.description }}</span>
            </button>
            <div class="skill-modal-row-actions">
              <input
                class="settings-switch"
                type="checkbox"
                role="switch"
                :aria-label="`启用技能 ${skill.title}`"
                :checked="skill.enabled !== false"
                :disabled="skillsStore.saving"
                @change="toggleSkill(skill.id, $event)"
              />
              <button
                type="button"
                class="skill-modal-detail-btn"
                :aria-label="`查看 ${skill.title} 详情`"
                @click="drillToSkill(skill.id)"
              >
                <span>详情</span>
                <span aria-hidden="true">›</span>
              </button>
            </div>
          </div>
        </div>
      </section>

      <section class="skill-modal-card">
        <div class="skill-modal-row">
          <button type="button" class="skill-modal-row-main" @click="drillToTools">
            <span class="skill-modal-inline-title">
              <strong>当前获准工具目录</strong>
              <span class="ui-pill ui-pill-neutral">{{ skillsStore.tools.length }} 项</span>
            </span>
            <span class="skill-modal-row-desc">
              内置工具 {{ builtinToolCount }} 项
              <template v-if="externalToolCount"> · 外部 MCP {{ externalToolCount }} 项</template>
              <template v-else> · 外部 MCP 未启用或暂无获准工具</template>
            </span>
          </button>
          <button type="button" class="skill-modal-detail-btn" @click="drillToTools">
            <span>查看全部</span>
            <span aria-hidden="true">›</span>
          </button>
        </div>
      </section>
    </div>

    <!-- 模式 2：单个技能详情 -->
    <div v-else-if="mode === 'skill'" class="skill-modal-body">
      <p v-if="skillsStore.loading && !selectedSkill" class="small muted" role="status">正在读取技能详情…</p>
      <p v-else-if="!selectedSkill" class="small muted">未找到该技能。</p>
      <template v-else>
        <div class="skill-modal-summary-bar">
          <div class="ui-pill-list">
            <span class="ui-pill ui-pill-mono">v{{ selectedSkill.version }}</span>
            <span
              class="ui-pill"
              :class="selectedSkill.required_tools_available ? 'ui-pill-success' : 'ui-pill-warning'"
            >
              <span class="ui-dot" aria-hidden="true" />
              {{ selectedSkill.required_tools_available ? '工具就绪' : '部分工具受限' }}
            </span>
            <span class="ui-pill ui-pill-neutral">SHA-256 {{ selectedSkill.content_sha256.slice(0, 12) }}</span>
          </div>
          <label class="skill-modal-toggle-label">
            <span>{{ selectedSkill.enabled !== false ? '已启用' : '已停用' }}</span>
            <input
              class="settings-switch"
              type="checkbox"
              role="switch"
              :aria-label="`启用技能 ${selectedSkill.title}`"
              :checked="selectedSkill.enabled !== false"
              :disabled="skillsStore.saving"
              @change="toggleSkill(selectedSkill.id, $event)"
            />
          </label>
        </div>

        <p class="skill-modal-lead">{{ selectedSkill.description }}</p>

        <dl class="skill-modal-dl">
          <div v-if="selectedSkill.delivery_summary" class="skill-modal-card">
            <dt>预期交付</dt>
            <dd>{{ selectedSkill.delivery_summary }}</dd>
          </div>
          <div v-if="selectedSkill.boundaries" class="skill-modal-card">
            <dt>安全与科学边界</dt>
            <dd>{{ selectedSkill.boundaries }}</dd>
          </div>
          <div class="skill-modal-card">
            <dt>所需工具</dt>
            <dd>
              <div class="skill-modal-tool-chips">
                <span v-for="toolId in selectedSkill.allowed_tools" :key="toolId" class="skill-modal-tool-chip">
                  <strong>{{ toolMap.get(toolId)?.title || toolId }}</strong>
                  <code>{{ toolId }}</code>
                </span>
              </div>
              <p v-if="selectedSkill.unavailable_tools?.length" class="small muted" style="margin: 8px 0 0;">
                暂不可用：{{ selectedSkill.unavailable_tools.join('、') }}
              </p>
            </dd>
          </div>
          <div v-if="selectedSkill.example_prompts?.length" class="skill-modal-card">
            <dt>适用提问示例</dt>
            <dd>
              <ul class="skill-modal-examples">
                <li v-for="prompt in selectedSkill.example_prompts" :key="prompt">{{ prompt }}</li>
              </ul>
            </dd>
          </div>
        </dl>

        <p class="skill-modal-footnote">
          技能标识 <code>{{ selectedSkill.id }}</code> · 正文仅在命中当轮后载入，无法覆盖系统权限或扩大工具范围。
        </p>
      </template>
    </div>

    <!-- 模式 3：可用工具目录详情 -->
    <div v-else class="skill-modal-body">
      <div class="skill-modal-summary-bar">
        <span class="small muted">
          共 {{ skillsStore.tools.length }} 项获准工具（内置工具 {{ builtinToolCount }} 项<template v-if="externalToolCount">，外部 MCP {{ externalToolCount }} 项</template>）
        </span>
        <span v-if="skillsStore.toolManifestSha256" class="ui-pill ui-pill-mono">
          清单 {{ skillsStore.toolManifestSha256.slice(0, 12) }}
        </span>
      </div>

      <p v-if="!skillsStore.tools.length" class="small muted" role="status">正在读取工具目录…</p>

      <div v-else class="skill-modal-tools-list">
        <article v-for="tool in skillsStore.tools" :key="tool.tool_id" class="skill-modal-card skill-modal-tool-card">
          <div class="skill-modal-tool-head">
            <div>
              <h4>
                {{ tool.title }}
                <code class="skill-modal-tool-code">{{ tool.tool_id }}</code>
              </h4>
              <p class="small muted">{{ tool.description }}</p>
            </div>
            <div class="ui-pill-list">
              <span class="ui-pill" :class="tool.source === 'external_mcp' ? 'ui-pill-compute' : 'ui-pill-neutral'">
                {{ sourceLabel(tool.source) }}
              </span>
              <span class="ui-pill" :class="tool.requires_confirmation ? 'ui-pill-warning' : 'ui-pill-accent'">
                {{ effectLabel(tool.side_effect_level) }}
              </span>
            </div>
          </div>
          <div class="skill-modal-tool-meta">
            <span>每轮预算上限 {{ tool.max_calls_per_turn }} 次</span>
            <span v-if="tool.protocol_version">· 协议 <code>{{ tool.protocol_version }}</code></span>
            <span v-if="tool.availability_conditions?.length">
              · {{ tool.availability_conditions.join('；') }}
            </span>
          </div>
        </article>
      </div>

      <p class="skill-modal-footnote">
        模型看到的工具定义与实际执行白名单来自同一份服务端目录；技能正文与外部返回数据均无法扩大授权。
      </p>
    </div>
  </dialog>
</template>

<style scoped>
.skill-modal-dialog {
  width: min(720px, calc(100vw - 32px));
  max-height: calc(100dvh - 48px);
  overflow: auto;
  padding: var(--space-5);
  color: var(--ink);
}

.skill-modal-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-4);
  margin-bottom: var(--space-4);
}

.skill-modal-title-group {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.skill-modal-heading h2 {
  margin: 0;
  font: 550 20px/1.4 var(--font-ui);
  color: var(--ink);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.skill-modal-back,
.skill-modal-close {
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
  color: var(--muted);
}

.skill-modal-close {
  font-size: 24px;
  line-height: 1;
}

.skill-modal-back svg {
  width: 17px;
  height: 17px;
  fill: none;
  stroke: currentColor;
  stroke-width: 1.8;
}

.skill-modal-back:hover,
.skill-modal-close:hover {
  background: var(--hover-veil, var(--surface-subtle));
  color: var(--ink);
  transform: none;
  box-shadow: none;
}

.skill-modal-body {
  display: grid;
  gap: 12px;
}

.skill-modal-summary-bar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding-bottom: 12px;
  border-bottom: 1px solid var(--line);
}

.skill-modal-toggle-label {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  font-size: 13px;
  color: var(--muted);
  cursor: pointer;
}

.skill-modal-lead {
  margin: 0;
  font-size: 13.5px;
  line-height: 1.65;
  color: var(--ink);
}

.skill-modal-card {
  display: grid;
  gap: 8px;
  padding: 13px 15px;
  border: 1px solid var(--line);
  border-radius: var(--radius-card);
  background: var(--surface-subtle);
}

.skill-modal-section-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.skill-modal-section-head h3 {
  margin: 0;
  font-size: 14px;
  font-weight: 600;
  color: var(--ink);
}

.skill-modal-switch-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
  cursor: pointer;
}

.skill-modal-switch-row strong {
  display: block;
  font-size: 14px;
  color: var(--ink);
}

.skill-modal-switch-row p {
  margin: 3px 0 0;
}

.skill-modal-list {
  display: grid;
  gap: 2px;
}

.skill-modal-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 9px 0;
  border-top: 1px solid var(--line);
}

.skill-modal-list .skill-modal-row:first-child,
.skill-modal-card > .skill-modal-row:first-child {
  border-top: 0;
  padding-top: 2px;
}

.skill-modal-list .skill-modal-row:last-child,
.skill-modal-card > .skill-modal-row:last-child {
  padding-bottom: 2px;
}

.skill-modal-row-main {
  flex: 1;
  min-width: 0;
  display: grid;
  gap: 3px;
  padding: 4px 6px;
  margin: -4px -6px;
  border: 0;
  border-radius: var(--radius-control);
  background: transparent;
  box-shadow: none;
  text-align: left;
  color: inherit;
  cursor: pointer;
}

.skill-modal-row-main:hover {
  background: var(--hover-veil, var(--surface-card));
  transform: none;
  box-shadow: none;
}

.skill-modal-inline-title {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  font-size: 13.5px;
  color: var(--ink);
}

.skill-modal-row-desc {
  font-size: 12px;
  color: var(--muted);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.skill-modal-row-actions {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  flex: none;
}

.skill-modal-detail-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 5px 10px;
  border: 1px solid var(--line);
  border-radius: var(--radius-control);
  background: var(--surface-card);
  color: var(--muted);
  font-size: 12px;
  box-shadow: none;
  flex: none;
}

.skill-modal-detail-btn:hover {
  color: var(--ink);
  border-color: var(--line-strong);
  transform: none;
  box-shadow: none;
}

.skill-modal-dl {
  display: grid;
  gap: 10px;
  margin: 0;
}

.skill-modal-dl dt {
  font-size: 11.5px;
  font-weight: 600;
  color: var(--muted);
}

.skill-modal-dl dd {
  margin: 0;
  font-size: 13px;
  line-height: 1.65;
  color: var(--ink);
}

.skill-modal-tool-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.skill-modal-tool-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 5px 10px;
  border: 1px solid var(--line);
  border-radius: var(--radius-control);
  background: var(--surface-card);
  font-size: 12.5px;
}

.skill-modal-tool-chip code {
  font-size: 11.5px;
  color: var(--muted);
}

.skill-modal-examples {
  margin: 0;
  padding-left: 18px;
  display: grid;
  gap: 4px;
  font-size: 13px;
}

.skill-modal-tools-list {
  display: grid;
  gap: 10px;
}

.skill-modal-tool-head {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-start;
  justify-content: space-between;
  gap: 10px;
}

.skill-modal-tool-head h4 {
  margin: 0 0 4px;
  font-size: 14px;
  font-weight: 600;
  color: var(--ink);
}

.skill-modal-tool-head p {
  margin: 0;
}

.skill-modal-tool-code {
  margin-left: 6px;
  font-size: 11.5px;
  color: var(--muted);
}

.skill-modal-tool-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  padding-top: 6px;
  border-top: 1px solid var(--line);
  font-size: 12px;
  color: var(--muted);
}

.skill-modal-footnote {
  margin: 2px 0 0;
  font-size: 12px;
  line-height: 1.6;
  color: var(--muted);
}
</style>
