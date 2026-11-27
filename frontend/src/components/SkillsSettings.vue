<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useSkills } from '../stores/skills'
import SkillDetailDialog from './SkillDetailDialog.vue'
import StatusNotice from './StatusNotice.vue'
import SuccessToast from './SuccessToast.vue'

const skillsStore = useSkills()
const detailDialog = ref<InstanceType<typeof SkillDetailDialog> | null>(null)
const notice = ref('')

const enabledCount = computed(() => skillsStore.skills.filter(s => s.enabled !== false).length)
const builtinToolCount = computed(() => skillsStore.tools.filter(t => t.source !== 'external_mcp').length)
const externalToolCount = computed(() => skillsStore.tools.filter(t => t.source === 'external_mcp').length)

function openSkillDetail(skillId: string) {
  void detailDialog.value?.openSkill(skillId)
}

function openToolsCatalog() {
  void detailDialog.value?.openTools()
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

onMounted(() => {
  void Promise.all([skillsStore.load(true), skillsStore.loadTools()])
})
</script>

<template>
  <div class="skills-settings">
    <SuccessToast v-model:message="notice" />
    <StatusNotice
      v-if="skillsStore.error"
      title="技能设置操作未完成"
      :message="skillsStore.error"
      @dismiss="skillsStore.error = ''"
    />

    <section class="settings-group" aria-labelledby="skills-builtin-title">
      <div class="settings-group-head">
        <h3 id="skills-builtin-title">内置科研技能</h3>
        <span class="ui-pill ui-pill-neutral">已启用 {{ enabledCount }} / {{ skillsStore.skills.length }}</span>
      </div>

      <p v-if="skillsStore.loading && !skillsStore.skills.length" class="settings-loading" role="status">
        正在读取技能目录…
      </p>

      <div v-else class="skills-overview-list">
        <div v-for="skill in skillsStore.skills" :key="skill.id" class="settings-row skill-overview-row">
          <button
            type="button"
            class="skill-overview-main"
            @click="openSkillDetail(skill.id)"
          >
            <span class="skill-title-inline">
              <strong class="skill-overview-title">{{ skill.title }}</strong>
              <span class="ui-pill ui-pill-mono">v{{ skill.version }}</span>
              <span
                v-if="!skill.required_tools_available"
                class="ui-pill ui-pill-warning"
              >
                工具受限
              </span>
            </span>
            <span class="skill-overview-summary">{{ skill.description }}</span>
          </button>

          <div class="skill-overview-actions">
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
              class="skill-row-detail-btn"
              :aria-label="`查看 ${skill.title} 详情`"
              @click="openSkillDetail(skill.id)"
            >
              <span>详情</span>
              <span aria-hidden="true">›</span>
            </button>
          </div>
        </div>
      </div>
    </section>

    <section class="settings-group" aria-labelledby="skills-tools-entry-title">
      <div class="settings-group-head">
        <h3 id="skills-tools-entry-title">工具目录</h3>
        <span class="ui-pill ui-pill-neutral">{{ skillsStore.tools.length }} 项可用</span>
      </div>
      <div class="settings-row skill-overview-row">
        <button type="button" class="skill-overview-main" @click="openToolsCatalog">
          <strong class="skill-overview-title">查看当前获准工具目录与权限边界</strong>
          <span class="skill-overview-summary">
            内置工具 {{ builtinToolCount }} 项
            <template v-if="externalToolCount"> · 外部 MCP {{ externalToolCount }} 项</template>
            <template v-else> · 外部 MCP 未启用或暂无获准工具</template>
          </span>
        </button>
        <button
          type="button"
          class="skill-row-detail-btn"
          @click="openToolsCatalog"
        >
          <span>查看全部</span>
          <span aria-hidden="true">›</span>
        </button>
      </div>
    </section>

    <SkillDetailDialog ref="detailDialog" />
  </div>
</template>

<style scoped>
.skills-overview-list {
  margin-top: 6px;
}

.skill-overview-row {
  gap: 14px;
  padding: 12px 0;
}

.skill-overview-main {
  flex: 1;
  min-width: 0;
  display: grid;
  gap: 4px;
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

.skill-overview-main:hover {
  background: var(--hover-veil, var(--surface-subtle));
  transform: none;
  box-shadow: none;
}

.skill-title-inline {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}

.skill-overview-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--ink);
}

.skill-overview-summary {
  font-size: 12.5px;
  line-height: 1.5;
  color: var(--muted);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.skill-overview-actions {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  flex: none;
}

.skill-row-detail-btn {
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
  flex: none;
}

.skill-row-detail-btn:hover {
  color: var(--ink);
  border-color: var(--line-strong);
  background: var(--hover-veil, var(--surface-subtle));
  transform: none;
  box-shadow: none;
}
</style>
