<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import type { ComputeTask } from '../api/compute'

const props = defineProps<{
  state: ComputeTask['state']
  engine?: 'rebound' | 'petar'
  samplesCompleted: number
  sampleCount: number
  startedAt?: string | null
  createdAt?: string | null
  particleCount?: number
  durationYr?: number
  compact?: boolean
  cancelling?: boolean
  canCancel?: boolean
}>()

const emit = defineEmits<{
  cancel: []
}>()

const nowMs = ref(Date.now())
let ticker: ReturnType<typeof setInterval> | undefined

const isActive = computed(() => ['queued', 'running', 'cancelling'].includes(props.state))

function syncTicker() {
  if (ticker) {
    clearInterval(ticker)
    ticker = undefined
  }
  if (isActive.value) {
    nowMs.value = Date.now()
    ticker = setInterval(() => {
      nowMs.value = Date.now()
    }, 250)
  }
}

watch(isActive, syncTicker, { immediate: true })
onBeforeUnmount(() => {
  if (ticker) clearInterval(ticker)
})

const progressPct = computed(() => {
  if (props.state === 'succeeded') return 100
  if (props.state === 'queued') return 6
  const total = Math.max(1, props.sampleCount || 1)
  const raw = Math.round((Math.max(0, props.samplesCompleted) / total) * 100)
  if (props.state === 'running') return Math.max(10, Math.min(98, raw))
  return Math.max(0, Math.min(100, raw))
})

const ringCircumference = 2 * Math.PI * 24
const ringOffset = computed(() => ringCircumference * (1 - progressPct.value / 100))

const elapsedLabel = computed(() => {
  const anchor = props.startedAt || props.createdAt
  if (!anchor) return '0.0 s'
  const start = Date.parse(anchor)
  if (Number.isNaN(start)) return '0.0 s'
  const sec = Math.max(0, (nowMs.value - start) / 1000)
  return sec >= 60 ? `${Math.floor(sec / 60)}m ${(sec % 60).toFixed(0)}s` : `${sec.toFixed(1)} s`
})

const stageIndex = computed(() => {
  if (props.state === 'succeeded') return 4
  if (props.state === 'queued') return 0
  if (props.state === 'cancelling') return 2
  if (props.sampleCount > 0 && props.samplesCompleted >= props.sampleCount) return 2
  return 1
})

const stages = computed(() => [
  { key: 'queue', label: '排队认领' },
  { key: 'integrate', label: '数值积分' },
  { key: 'verify', label: '守恒校验' },
  { key: 'render', label: '产出图表' },
].map((stage, idx) => ({
  ...stage,
  status: idx < stageIndex.value ? 'done' : idx === stageIndex.value && isActive.value ? 'active' : 'pending',
})))

const headline = computed(() => {
  if (props.state === 'queued') return '等待计算 Worker 认领任务'
  if (props.state === 'cancelling') return '正在安全终止积分器进程'
  if (props.state === 'succeeded') return '模拟计算与守恒校验已完成'
  if (stageIndex.value >= 2) return '正在校验能量 / 角动量守恒并汇总快照'
  return `正在执行 ${props.engine === 'petar' ? 'PeTar' : 'REBOUND'} N 体数值积分`
})
</script>

<template>
  <section class="nbody-progress-card" :class="{ 'is-compact': compact, 'is-active': isActive, 'is-done': state === 'succeeded' }" role="status" aria-live="polite">
    <div class="nbody-progress-main">
      <div class="nbody-orbit-ring" aria-hidden="true">
        <svg viewBox="0 0 60 60">
          <defs>
            <linearGradient id="nbodyRingGrad" x1="0%" y1="0%" x2="100%" y2="100%">
              <stop offset="0%" stop-color="#38bdf8" />
              <stop offset="55%" stop-color="#6366f1" />
              <stop offset="100%" stop-color="#a855f7" />
            </linearGradient>
          </defs>
          <circle class="nbody-ring-track" cx="30" cy="30" r="24" />
          <circle class="nbody-ring-orbit-dash" cx="30" cy="30" r="17" />
          <circle
            class="nbody-ring-fill"
            cx="30"
            cy="30"
            r="24"
            stroke="url(#nbodyRingGrad)"
            :stroke-dasharray="ringCircumference"
            :stroke-dashoffset="ringOffset"
          />
          <g v-if="isActive" class="nbody-orbit-satellite">
            <circle cx="30" cy="13" r="2.6" class="nbody-satellite-dot" />
          </g>
        </svg>
        <span class="nbody-ring-pct">{{ progressPct }}%</span>
      </div>

      <div class="nbody-progress-copy">
        <div class="nbody-progress-top">
          <strong class="nbody-progress-title">{{ headline }}</strong>
          <button
            v-if="canCancel && isActive && state !== 'cancelling'"
            type="button"
            class="nbody-cancel-btn"
            :disabled="cancelling"
            @click="emit('cancel')"
          >
            {{ cancelling ? '取消中…' : '取消' }}
          </button>
        </div>

        <div class="nbody-bar-track" role="progressbar" :aria-valuenow="progressPct" aria-valuemin="0" aria-valuemax="100">
          <div class="nbody-bar-fill" :style="{ width: `${progressPct}%` }" :class="{ 'is-indeterminate': state === 'queued' }" />
        </div>

        <div class="nbody-telemetry-row">
          <span class="nbody-telemetry-chip">
            <em>采样</em>
            <strong>{{ samplesCompleted }} / {{ sampleCount }}</strong>
          </span>
          <span v-if="particleCount" class="nbody-telemetry-chip">
            <em>粒子</em>
            <strong>{{ particleCount }}</strong>
          </span>
          <span v-if="durationYr" class="nbody-telemetry-chip">
            <em>时长</em>
            <strong>{{ durationYr }} yr</strong>
          </span>
          <span class="nbody-telemetry-chip">
            <em>耗时</em>
            <strong>{{ elapsedLabel }}</strong>
          </span>
        </div>
      </div>
    </div>

    <ol class="nbody-stage-rail" aria-label="计算执行阶段">
      <li v-for="stage in stages" :key="stage.key" class="nbody-stage-step" :class="`is-${stage.status}`">
        <span class="nbody-stage-dot" aria-hidden="true" />
        <span class="nbody-stage-label">{{ stage.label }}</span>
      </li>
    </ol>
  </section>
</template>

<style scoped>
.nbody-progress-card {
  position: relative;
  display: grid;
  gap: 12px;
  padding: 14px 16px;
  border-radius: 14px;
  border: 1px solid color-mix(in srgb, var(--accent) 26%, var(--border-subtle));
  background:
    radial-gradient(ellipse 90% 80% at 10% 0%, color-mix(in srgb, var(--accent) 12%, transparent), transparent 65%),
    color-mix(in srgb, var(--surface-card) 86%, transparent);
  box-shadow:
    inset 0 1px 0 var(--surface-specular),
    0 8px 22px -14px rgba(15, 23, 42, 0.25);
  overflow: hidden;
}

.nbody-progress-card.is-compact {
  padding: 12px 14px;
  gap: 10px;
}

.nbody-progress-main {
  display: grid;
  grid-template-columns: 60px minmax(0, 1fr);
  align-items: center;
  gap: 14px;
}

.nbody-orbit-ring {
  position: relative;
  width: 60px;
  height: 60px;
  display: grid;
  place-items: center;
}

.nbody-orbit-ring svg {
  width: 60px;
  height: 60px;
  transform: rotate(-90deg);
}

.nbody-ring-track {
  fill: none;
  stroke: color-mix(in srgb, var(--border-strong) 45%, transparent);
  stroke-width: 4;
}

.nbody-ring-orbit-dash {
  fill: none;
  stroke: color-mix(in srgb, var(--accent) 32%, transparent);
  stroke-width: 1;
  stroke-dasharray: 2.5 3.5;
}

.nbody-ring-fill {
  fill: none;
  stroke-width: 4.2;
  stroke-linecap: round;
  transition: stroke-dashoffset 0.45s cubic-bezier(0.22, 1, 0.36, 1);
}

.nbody-orbit-satellite {
  transform-origin: 30px 30px;
  animation: nbody-orbit-spin 2.4s linear infinite;
}

.nbody-satellite-dot {
  fill: var(--accent);
  filter: drop-shadow(0 0 4px var(--accent));
}

.nbody-ring-pct {
  position: absolute;
  font-size: 12px;
  font-weight: 700;
  font-variant-numeric: tabular-nums;
  color: var(--text-primary);
  letter-spacing: -0.02em;
}

.nbody-progress-copy {
  display: grid;
  gap: 8px;
  min-width: 0;
}

.nbody-progress-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.nbody-progress-title {
  font-size: 13px;
  font-weight: 650;
  color: var(--text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.nbody-cancel-btn {
  min-height: 24px;
  padding: 0 9px;
  border-radius: 999px;
  border: 1px solid color-mix(in srgb, var(--danger-text) 30%, var(--border-subtle));
  background: color-mix(in srgb, var(--danger-bg) 50%, transparent);
  color: var(--danger-text);
  font-size: 11.5px;
  font-weight: 600;
  cursor: pointer;
  flex-shrink: 0;
}

.nbody-cancel-btn:hover:not(:disabled) {
  background: color-mix(in srgb, var(--danger-bg) 85%, transparent);
}

.nbody-bar-track {
  position: relative;
  height: 6px;
  border-radius: 999px;
  background: color-mix(in srgb, var(--border-strong) 35%, transparent);
  overflow: hidden;
}

.nbody-bar-fill {
  height: 100%;
  border-radius: 999px;
  background: linear-gradient(90deg, #38bdf8, #6366f1 55%, #a855f7);
  background-size: 200% 100%;
  transition: width 0.4s cubic-bezier(0.22, 1, 0.36, 1);
  animation: nbody-bar-shimmer 2.1s ease-in-out infinite;
}

.nbody-bar-fill.is-indeterminate {
  width: 34% !important;
  animation: nbody-bar-slide 1.5s ease-in-out infinite;
}

.nbody-telemetry-row {
  display: flex;
  flex-wrap: wrap;
  gap: 6px 12px;
}

.nbody-telemetry-chip {
  display: inline-flex;
  align-items: baseline;
  gap: 4px;
  font-size: 11.5px;
  font-variant-numeric: tabular-nums;
}

.nbody-telemetry-chip em {
  font-style: normal;
  color: var(--text-muted);
}

.nbody-telemetry-chip strong {
  font-weight: 650;
  color: var(--text-primary);
}

.nbody-stage-rail {
  list-style: none;
  margin: 0;
  padding: 8px 0 0;
  border-top: 1px solid color-mix(in srgb, var(--border-subtle) 70%, transparent);
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 6px;
}

.nbody-stage-step {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
  font-size: 11.5px;
  color: var(--text-muted);
}

.nbody-stage-dot {
  width: 7px;
  height: 7px;
  border-radius: 999px;
  background: color-mix(in srgb, var(--border-strong) 75%, transparent);
  flex-shrink: 0;
  transition: transform 0.25s ease, background 0.25s ease, box-shadow 0.25s ease;
}

.nbody-stage-step.is-done {
  color: var(--text-secondary);
}

.nbody-stage-step.is-done .nbody-stage-dot {
  background: var(--success-text);
}

.nbody-stage-step.is-active {
  color: var(--accent);
  font-weight: 650;
}

.nbody-stage-step.is-active .nbody-stage-dot {
  background: var(--accent);
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--accent) 24%, transparent);
  animation: nbody-dot-pulse 1.4s ease-in-out infinite;
}

.nbody-stage-label {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

@keyframes nbody-orbit-spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

@keyframes nbody-bar-shimmer {
  0% { background-position: 0% 50%; }
  50% { background-position: 100% 50%; }
  100% { background-position: 0% 50%; }
}

@keyframes nbody-bar-slide {
  0% { transform: translateX(-110%); }
  100% { transform: translateX(320%); }
}

@keyframes nbody-dot-pulse {
  0%, 100% { transform: scale(1); }
  50% { transform: scale(1.25); }
}
</style>
