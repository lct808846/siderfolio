<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, useId, watch } from 'vue'
import { useRoute } from 'vue-router'
import { useProjects } from '../stores/projects'

const props = defineProps<{
  modelValue: string
  disabled?: boolean
  busy?: boolean
}>()
const emit = defineEmits<{
  'update:modelValue': [projectId: string]
  create: []
}>()

const projectsStore = useProjects()
const route = useRoute()
const listId = `project-picker-${useId()}`
const trigger = ref<HTMLButtonElement | null>(null)
const popup = ref<HTMLElement | null>(null)
const open = ref(false)
const left = ref(12)
const top = ref(12)
const placement = ref<'above' | 'below'>('above')

const selectedProject = computed(() =>
  props.modelValue && props.modelValue !== projectsStore.defaultProjectId
    ? projectsStore.customProjects.find(item => item.id === props.modelValue) || null
    : null,
)
const triggerLabel = computed(() => selectedProject.value?.name || '选择项目')

function position() {
  if (!trigger.value || !popup.value) return
  const rect = trigger.value.getBoundingClientRect()
  const width = popup.value.offsetWidth || 264
  left.value = Math.max(12, Math.min(rect.left, window.innerWidth - width - 12))
  const above = rect.top - 16
  const below = window.innerHeight - rect.bottom - 16
  const height = popup.value.offsetHeight || 260
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
  if (props.disabled || props.busy || open.value) return
  open.value = true
  void projectsStore.load().catch(() => undefined)
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
  open.value = false
  if (restoreFocus) {
    void nextTick(() => trigger.value?.focus({ preventScroll: true }))
  }
}

function choose(projectId: string) {
  close(true)
  emit('update:modelValue', projectId)
}

function requestCreate() {
  close(false)
  emit('create')
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
watch(() => projectsStore.customProjects.length, onResize, { flush: 'post' })
watch(() => props.disabled, value => { if (value) close(false) })

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
  <div class="composer-project-picker">
    <button
      ref="trigger"
      type="button"
      class="composer-task-button composer-project-trigger"
      :class="{ active: !!selectedProject }"
      :disabled="disabled || busy"
      aria-haspopup="dialog"
      :aria-expanded="open"
      :aria-controls="listId"
      :aria-label="selectedProject ? `当前项目空间：${selectedProject.name}` : '选择项目或保存空间'"
      :data-tooltip="open ? '' : selectedProject ? `当前空间：${selectedProject.name}（点击切换项目或新建）` : '当前空间：个人空间（默认），点击选择项目或新建'"
      @click="open ? close(true) : show()"
    >
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <path d="M3 7V5a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2Z" />
      </svg>
      <span class="composer-project-label">{{ busy ? '切换中…' : triggerLabel }}</span>
      <svg class="composer-project-chevron" :class="{ open }" viewBox="0 0 24 24" aria-hidden="true">
        <path d="m7 10 5 5 5-5" />
      </svg>
    </button>

    <Teleport to="body">
      <Transition name="model-picker">
        <div
          v-if="open"
          :id="listId"
          ref="popup"
          class="project-picker-popover"
          role="dialog"
          aria-label="选择项目空间"
          popover="manual"
          :data-placement="placement"
          :style="{ left: `${left}px`, top: `${top}px` }"
          @keydown="onKeydown"
        >
          <button
            type="button"
            class="project-picker-item is-create"
            :disabled="projectsStore.customProjects.length >= 20"
            @click="requestCreate"
          >
            <svg viewBox="0 0 24 24" aria-hidden="true">
              <path d="M3 7V5a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2Z" />
              <path d="M12 10v6M9 13h6" />
            </svg>
            <span>新建项目</span>
          </button>

          <div class="project-picker-divider" />

          <div class="project-picker-list" role="listbox" aria-label="可用项目空间">
            <button
              type="button"
              role="option"
              class="project-picker-item"
              :aria-selected="!selectedProject"
              @click="choose('')"
            >
              <svg viewBox="0 0 24 24" aria-hidden="true">
                <circle cx="12" cy="12" r="8.5" />
                <path d="M12 7.5v4.5l3 1.8" />
              </svg>
              <span class="project-picker-name">个人空间（默认）</span>
              <svg v-if="!selectedProject" class="project-picker-check" viewBox="0 0 24 24" aria-hidden="true">
                <path d="m5 12 4 4L19 6" />
              </svg>
            </button>

            <button
              v-for="project in projectsStore.customProjects"
              :key="project.id"
              type="button"
              role="option"
              class="project-picker-item"
              :aria-selected="selectedProject?.id === project.id"
              @click="choose(project.id)"
            >
              <svg viewBox="0 0 24 24" aria-hidden="true">
                <path d="M3 7V5a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2Z" />
              </svg>
              <span class="project-picker-name">{{ project.name }}</span>
              <span v-if="(project.description || '').trim()" class="project-picker-hint">指令</span>
              <svg v-if="selectedProject?.id === project.id" class="project-picker-check" viewBox="0 0 24 24" aria-hidden="true">
                <path d="m5 12 4 4L19 6" />
              </svg>
            </button>
          </div>
        </div>
      </Transition>
    </Teleport>
  </div>
</template>

<style scoped>
.composer-project-picker {
  display: inline-flex;
  align-items: center;
  flex: 0 0 auto;
  width: 140px;
  height: 34px;
  min-width: 0;
}

.composer-project-trigger {
  display: inline-flex;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
  width: 100%;
  height: 34px;
  min-height: 34px;
  min-width: 0;
  padding: 0 10px;
  white-space: nowrap;
}

.composer-project-trigger.active {
  color: var(--accent);
  font-weight: 550;
  background: linear-gradient(155deg, color-mix(in srgb, var(--paper) 94%, #fff) 0%, color-mix(in srgb, var(--accent) 12%, var(--paper)) 100%);
  border-color: color-mix(in srgb, var(--accent) 46%, var(--line));
  box-shadow: 0 6px 18px -6px color-mix(in srgb, var(--accent) 32%, transparent), inset 0 1px 0 0 rgb(255 255 255 / 85%);
}

.composer-project-trigger.active:hover:not(:disabled) {
  color: var(--accent);
  background: linear-gradient(155deg, #fff 0%, color-mix(in srgb, var(--accent) 16%, var(--paper)) 100%);
  border-color: var(--accent);
  box-shadow: 0 8px 22px -6px color-mix(in srgb, var(--accent) 42%, transparent), inset 0 1px 0 0 #fff;
}

.composer-project-label {
  flex: 1 1 auto;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  text-align: left;
}

.composer-project-chevron {
  width: 13px !important;
  height: 13px !important;
  flex: 0 0 13px !important;
  margin-left: -2px;
  transition: transform 150ms ease;
}

.composer-project-chevron.open {
  transform: rotate(180deg);
}

.project-picker-popover {
  position: fixed;
  inset: auto;
  z-index: 9050;
  width: min(280px, calc(100vw - 24px));
  margin: 0;
  padding: 6px;
  border: 1px solid var(--line-strong);
  border-radius: calc(var(--radius-control, 8px) + 6px);
  background: var(--specular-spot, none), var(--surface-glass-float, var(--surface-float));
  color: var(--ink);
  box-shadow: var(--shadow-float, var(--shadow-card-hover));
  -webkit-backdrop-filter: blur(28px) saturate(190%);
  backdrop-filter: blur(28px) saturate(190%);
  font-family: var(--font-ui);
  transform-origin: bottom left;
}
.project-picker-popover::before {
  content: '';
  position: absolute;
  top: 0;
  left: 10%;
  right: 10%;
  height: 1.5px;
  background: var(--specular-sheen);
  pointer-events: none;
}

.project-picker-popover[data-placement="below"] {
  transform-origin: top left;
}

.project-picker-popover::backdrop {
  background: transparent;
  pointer-events: none;
}

.project-picker-divider {
  height: 1px;
  margin: 4px 6px;
  background: var(--line);
}

.project-picker-list {
  display: grid;
  gap: 2px;
  max-height: min(260px, 42dvh);
  overflow-y: auto;
  overscroll-behavior: contain;
}

.project-picker-item {
  display: flex;
  align-items: center;
  gap: 9px;
  width: 100%;
  min-height: 34px;
  padding: 6px 9px;
  border: 1px solid transparent;
  border-radius: var(--radius-control, 8px);
  background: transparent;
  box-shadow: none;
  transform: none;
  color: var(--ink);
  font-size: 12.5px;
  font-weight: 450;
  text-align: left;
  transition: background-color 140ms ease, color 140ms ease;
}

.project-picker-item:hover:not(:disabled) {
  background: var(--soft);
  border-color: transparent;
  box-shadow: none;
  transform: none;
}

.project-picker-item[aria-selected="true"] {
  background: var(--accent-soft);
  color: var(--accent);
  font-weight: 550;
}

.project-picker-item.is-create {
  color: var(--accent);
  font-weight: 550;
}

.project-picker-item.is-create:hover:not(:disabled) {
  background: var(--accent-soft);
}

.project-picker-item svg {
  width: 15px;
  height: 15px;
  flex: none;
  fill: none;
  stroke: currentColor;
  stroke-width: 1.7;
  stroke-linecap: round;
  stroke-linejoin: round;
  color: var(--muted);
}

.project-picker-item.is-create svg,
.project-picker-item[aria-selected="true"] svg {
  color: var(--accent);
}

.project-picker-name {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.project-picker-hint {
  flex: none;
  padding: 1px 6px;
  border-radius: var(--radius-pill, 999px);
  background: var(--surface-tint);
  color: var(--muted);
  font-size: 10px;
  font-weight: 550;
}

.project-picker-check {
  width: 15px;
  height: 15px;
  color: var(--accent);
}

@media (max-width: 680px) {
  .project-picker-popover {
    left: 10px !important;
    right: 10px !important;
    width: calc(100vw - 20px) !important;
    max-width: none;
    border-radius: 16px;
    padding: 8px;
  }
  .project-picker-item {
    min-height: 44px;
    padding: 10px 12px;
    font-size: 13.5px;
  }
}

@media (prefers-reduced-motion: reduce) {
  .composer-project-chevron,
  .project-picker-item {
    transition: none;
  }
}
</style>
