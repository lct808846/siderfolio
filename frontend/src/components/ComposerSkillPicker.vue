<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, useId, watch } from 'vue'
import { useRoute } from 'vue-router'
import { useSkills } from '../stores/skills'
import SkillDetailDialog from './SkillDetailDialog.vue'

const props = defineProps<{
  modelValue: string | null
  disabled?: boolean
}>()

const emit = defineEmits<{
  'update:modelValue': [skillId: string | null]
}>()

const skillsStore = useSkills()
const route = useRoute()
const listId = `skill-picker-${useId()}`
const trigger = ref<HTMLButtonElement | null>(null)
const popup = ref<HTMLElement | null>(null)
const detailDialog = ref<InstanceType<typeof SkillDetailDialog> | null>(null)
const open = ref(false)
const left = ref(12)
const top = ref(12)
const placement = ref<'above' | 'below'>('above')

const selectedSkill = computed(() =>
  props.modelValue && props.modelValue !== 'none'
    ? skillsStore.enabledSkills.find(item => item.id === props.modelValue) || null
    : null,
)

const isExplicitlyDisabled = computed(() => props.modelValue === 'none')
const autoMatchOn = computed(() => skillsStore.preferences.auto_match !== false)

const triggerLabel = computed(() => {
  if (selectedSkill.value) return selectedSkill.value.title
  if (isExplicitlyDisabled.value) return '本轮不用技能'
  return autoMatchOn.value ? '技能 · 自动' : '技能 · 手动'
})

const triggerTooltip = computed(() => {
  if (selectedSkill.value) return `本轮已显式选择技能「${selectedSkill.value.title}」，点击可切换或取消`
  if (isExplicitlyDisabled.value) return '本轮已临时关闭技能，将按普通对话处理'
  return autoMatchOn.value
    ? '根据当前意图自动匹配最多一个科研技能，也可点击手动指定'
    : '个人设置已关闭自动匹配，点击可为本轮显式指定科研技能'
})

const shortHintMap: Record<string, string> = {
  'celestial-identification-field-query': 'SIMBAD 身份核查与 Gaia DR3 视场候选源',
  'astronomy-literature-curation': 'ADS 文献检索、整理与个人文献库保存',
  'scientific-plotting-nbody-prep': '科研绘图脚本与小规模 N 体模拟方案',
}

function shortHint(skillId: string, fallback: string) {
  return shortHintMap[skillId] || fallback
}

function position() {
  if (!trigger.value || !popup.value) return
  const rect = trigger.value.getBoundingClientRect()
  const width = popup.value.offsetWidth || 292
  left.value = Math.max(12, Math.min(rect.left, window.innerWidth - width - 12))
  const above = rect.top - 16
  const below = window.innerHeight - rect.bottom - 16
  const height = popup.value.offsetHeight || 250
  placement.value = above >= height || above >= below ? 'above' : 'below'
  top.value = Math.max(
    12,
    Math.min(
      placement.value === 'above' ? rect.top - height - 8 : rect.bottom + 8,
      window.innerHeight - height - 12,
    ),
  )
}

async function show() {
  if (props.disabled || open.value) return
  open.value = true
  void skillsStore.load(true).catch(() => undefined)
  await nextTick()
  if (!open.value || !popup.value) return
  if (typeof popup.value.showPopover === 'function' && !popup.value.matches(':popover-open')) {
    popup.value.showPopover()
  }
  position()
  popup.value.querySelector<HTMLButtonElement>('button:not(:disabled)')?.focus({ preventScroll: true })
}

function close(restoreFocus = false) {
  if (!open.value) return
  if (popup.value && typeof popup.value.hidePopover === 'function') {
    try {
      if (popup.value.matches(':popover-open')) popup.value.hidePopover()
    } catch { /* ignore */ }
  }
  open.value = false
  if (restoreFocus) {
    void nextTick(() => trigger.value?.focus({ preventScroll: true }))
  }
}

function choose(skillId: string | null) {
  close(true)
  emit('update:modelValue', skillId)
}

function openManageModal() {
  close(false)
  void detailDialog.value?.openManage()
}

function outside(event: PointerEvent) {
  if (
    event.target instanceof Node
    && !trigger.value?.contains(event.target)
    && !popup.value?.contains(event.target)
  ) {
    close(false)
  }
}

function onKeydown(event: KeyboardEvent) {
  if (event.key === 'Escape' && open.value) {
    event.preventDefault()
    event.stopPropagation()
    close(true)
  }
}

function onResize() {
  if (open.value) position()
}

watch(() => route.fullPath, () => close(false))
watch(() => skillsStore.skills.length, onResize, { flush: 'post' })
watch(() => props.disabled, value => { if (value) close(false) })
watch(
  () => [skillsStore.loaded, skillsStore.enabledSkills] as const,
  ([loaded, enabled]) => {
    if (
      loaded
      && props.modelValue
      && props.modelValue !== 'none'
      && !enabled.some(item => item.id === props.modelValue)
    ) {
      emit('update:modelValue', null)
    }
  },
)

onMounted(() => {
  document.addEventListener('pointerdown', outside)
  window.addEventListener('resize', onResize)
})
onBeforeUnmount(() => {
  document.removeEventListener('pointerdown', outside)
  window.removeEventListener('resize', onResize)
})
</script>

<template>
  <div class="composer-skill-picker">
    <button
      ref="trigger"
      type="button"
      class="composer-task-button composer-skill-trigger"
      :class="{
        active: !!selectedSkill,
        'is-muted': isExplicitlyDisabled,
      }"
      :disabled="disabled"
      :aria-expanded="open"
      :aria-controls="listId"
      aria-haspopup="listbox"
      :data-tooltip="triggerTooltip"
      @click="open ? close(true) : show()"
    >
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <path d="M12 3l2.2 5.2L19.5 10l-5.3 1.8L12 17l-2.2-5.2L4.5 10l5.3-1.8L12 3z" />
        <path d="M18.5 15.5l.8 1.9 1.9.8-1.9.8-.8 1.9-.8-1.9-1.9-.8 1.9-.8.8-1.9z" />
      </svg>
      <span class="skill-trigger-text">{{ triggerLabel }}</span>
      <svg class="skill-trigger-caret" viewBox="0 0 24 24" aria-hidden="true">
        <path d="m7 10 5 5 5-5" />
      </svg>
    </button>

    <div
      v-if="open"
      :id="listId"
      ref="popup"
      class="skill-picker-popup"
      :data-placement="placement"
      popover="manual"
      role="listbox"
      aria-label="选择本轮科研技能"
      :style="{ left: `${left}px`, top: `${top}px` }"
      @keydown="onKeydown"
    >
      <div class="skill-picker-header">
        <span>科研技能</span>
        <button type="button" class="skill-picker-manage" @click="openManageModal">
          管理与详情 →
        </button>
      </div>

      <div class="skill-picker-list">
        <button
          type="button"
          role="option"
          class="skill-picker-item"
          :aria-selected="modelValue === null"
          @click="choose(null)"
        >
          <span class="skill-picker-item-head">
            <strong>{{ autoMatchOn ? '自动匹配' : '按个人默认（自动已关）' }}</strong>
            <span v-if="modelValue === null" class="skill-picker-check" aria-hidden="true">✓</span>
          </span>
          <small>{{ autoMatchOn ? '按当前意图自动选用最多一个技能' : '未指定技能时按普通对话回答' }}</small>
        </button>

        <div class="skill-picker-divider" aria-hidden="true" />

        <button
          v-for="skill in skillsStore.enabledSkills"
          :key="skill.id"
          type="button"
          role="option"
          class="skill-picker-item"
          :aria-selected="modelValue === skill.id"
          @click="choose(skill.id)"
        >
          <span class="skill-picker-item-head">
            <strong>{{ skill.title }}</strong>
            <span v-if="modelValue === skill.id" class="skill-picker-check" aria-hidden="true">✓</span>
          </span>
          <small>{{ shortHint(skill.id, skill.description) }}</small>
        </button>

        <template v-if="autoMatchOn || modelValue !== null">
          <div class="skill-picker-divider" aria-hidden="true" />
          <button
            type="button"
            role="option"
            class="skill-picker-item is-off"
            :aria-selected="isExplicitlyDisabled"
            @click="choose('none')"
          >
            <span class="skill-picker-item-head">
              <strong>本轮不使用技能</strong>
              <span v-if="isExplicitlyDisabled" class="skill-picker-check" aria-hidden="true">✓</span>
            </span>
            <small>跳过技能匹配，直接按普通对话回答</small>
          </button>
        </template>
      </div>
    </div>

    <SkillDetailDialog ref="detailDialog" />
  </div>
</template>

<style scoped>
.composer-skill-picker {
  position: relative;
  display: inline-flex;
  align-items: center;
}

.composer-skill-trigger {
  max-width: 190px;
}

.composer-skill-trigger.is-muted {
  color: var(--muted);
}

.skill-trigger-text {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.skill-trigger-caret {
  width: 13px;
  height: 13px;
  flex: none;
  opacity: 0.72;
}

.skill-picker-popup {
  position: fixed;
  margin: 0;
  padding: 6px;
  width: min(296px, calc(100vw - 24px));
  max-height: min(380px, calc(100vh - 32px));
  overflow-y: auto;
  border: 1px solid var(--line-strong);
  border-radius: calc(var(--radius-control) + 6px);
  background: var(--specular-spot), var(--surface-glass-float);
  -webkit-backdrop-filter: blur(22px) saturate(160%);
  backdrop-filter: blur(22px) saturate(160%);
  box-shadow: var(--shadow-float);
  color: var(--ink);
}

.skill-picker-popup::backdrop {
  background: transparent;
  pointer-events: none;
}

.skill-picker-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 5px 10px 7px;
  font-size: 12px;
  font-weight: 600;
  color: var(--muted);
}

.skill-picker-manage {
  padding: 2px 4px;
  border: 0;
  background: transparent;
  box-shadow: none;
  font-size: 12px;
  font-weight: 500;
  color: var(--accent);
  text-decoration: none;
}

.skill-picker-manage:hover {
  text-decoration: underline;
  background: transparent;
  transform: none;
  box-shadow: none;
}

.skill-picker-list {
  display: grid;
  gap: 2px;
}

.skill-picker-divider {
  height: 1px;
  margin: 3px 8px;
  background: var(--line);
}

.skill-picker-item {
  display: grid;
  gap: 2px;
  width: 100%;
  padding: 7px 10px;
  border: 1px solid transparent;
  border-radius: var(--radius-control);
  background: transparent;
  box-shadow: none;
  text-align: left;
  color: var(--ink);
  transition: background-color 140ms ease, border-color 140ms ease;
}

.skill-picker-item:hover {
  background: var(--hover-veil, var(--surface-subtle));
  border-color: var(--line);
  transform: none;
  box-shadow: none;
}

.skill-picker-item[aria-selected="true"] {
  background: var(--accent-soft);
  border-color: color-mix(in srgb, var(--accent) 34%, var(--line));
}

.skill-picker-item-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  font-size: 13px;
}

.skill-picker-check {
  color: var(--accent);
  font-weight: 700;
  font-size: 13px;
}

.skill-picker-item small {
  color: var(--muted);
  font-size: 11.5px;
  line-height: 1.4;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
</style>
