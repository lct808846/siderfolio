<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref, useId, watch } from 'vue'
import { useRoute } from 'vue-router'

const route = useRoute()
const tooltipId = `astro-hint-${useId()}`
const tooltip = ref<HTMLElement | null>(null)
const visible = ref(false), text = ref(''), x = ref(0), y = ref(0), placement = ref('below')
const selector = 'button, a[href], [role="button"], [role="tab"], [role="menuitem"], [data-tooltip], summary, input[type="file"], input[type="submit"], input[type="button"]'
const explanations: Record<string, string> = {
  '新建会话': '打开空白会话，开始新的查询',
  '多选': '选择多个会话，集中整理或删除',
  '多选整理': '选择多个会话，集中整理或删除',
  '导出会话 JSON': '下载会话问题、回答和来源记录',
  '发送': '发送当前问题；Enter 发送，Shift + Enter 换行',
  '刷新本机状态': '重新读取数据库、嵌入模型和回答服务的配置状态',
  '查询工作台': '查询天体、Gaia 数据和相关文献',
  '项目归档': '组织会话、保存快照、比较与导出项目记录',
  '本机设置': '查看数据库、嵌入模型和回答服务配置',
  '接口文档 ↗': '在新标签页打开本机 API 文档',
}
let current: HTMLElement | null = null, hovered: HTMLElement | null = null, focused: HTMLElement | null = null
let originalTitle: string | null = null, overTooltip = false, dismissed = false, touchInput = false, revision = 0
let showTimer: ReturnType<typeof setTimeout> | undefined, leaveTimer: ReturnType<typeof setTimeout> | undefined

function control(target: EventTarget | null) {
  if (!(target instanceof Element) || tooltip.value?.contains(target)) return null
  const element = target.closest<HTMLElement>(selector)
  return element && !element.closest('[inert], [aria-hidden="true"]') ? element : null
}
function label(element: HTMLElement) {
  const explicit = element.getAttribute('data-tooltip')
  if (explicit === '') return ''
  const title = element.getAttribute('title') ?? (element === current ? originalTitle : null)
  const labelled = (element.getAttribute('aria-labelledby') || '').split(/\s+/)
    .map(id => document.getElementById(id)?.textContent || '').join(' ')
  const clone = element.cloneNode(true) as HTMLElement
  clone.querySelectorAll('svg, [aria-hidden="true"], small, time, .tag').forEach(node => node.remove())
  const content = (clone.textContent || '').replace(/\s+/g, ' ').trim()
  const name = explicit || title || element.getAttribute('aria-label') || labelled.trim() || explanations[content] || content
    || (element instanceof HTMLInputElement ? element.type === 'file' ? '选择要导入的文件' : element.value : '')
  if (!name) return ''
  const shortened = name.length > 160 ? `${name.slice(0, 159)}…` : name
  return element.matches(':disabled, [aria-disabled="true"]') ? `${shortened}（当前不可用）` : shortened
}
function removeDescription() {
  if (!current) return
  const ids = (current.getAttribute('aria-describedby') || '').split(/\s+/).filter(id => id && id !== tooltipId)
  if (ids.length) current.setAttribute('aria-describedby', ids.join(' '))
  else current.removeAttribute('aria-describedby')
}
function hide() {
  revision++
  clearTimeout(showTimer)
  clearTimeout(leaveTimer)
  removeDescription()
  if (typeof tooltip.value?.hidePopover === 'function' && tooltip.value.matches(':popover-open')) tooltip.value.hidePopover()
  visible.value = false
}
function release() {
  hide()
  if (current && originalTitle !== null && !current.hasAttribute('title')) current.setAttribute('title', originalTitle)
  current = null; originalTitle = null; dismissed = false; overTooltip = false
}
async function show() {
  if (!current?.isConnected || dismissed || !current.getClientRects().length) return
  text.value = label(current)
  if (!text.value) return
  visible.value = true
  const token = ++revision
  const ids = new Set((current.getAttribute('aria-describedby') || '').split(/\s+/).filter(Boolean))
  ids.add(tooltipId)
  current.setAttribute('aria-describedby', [...ids].join(' '))
  await nextTick()
  if (token !== revision || !current || !tooltip.value) return
  const bubble = tooltip.value
  if (typeof bubble.showPopover === 'function' && !bubble.matches(':popover-open')) bubble.showPopover()
  const anchor = current.getBoundingClientRect(), size = bubble.getBoundingClientRect()
  const below = anchor.bottom + 9
  const above = below + size.height > window.innerHeight - 8 && anchor.top > size.height + 17
  x.value = Math.max(8, Math.min(anchor.left + (anchor.width - size.width) / 2, window.innerWidth - size.width - 8))
  y.value = Math.max(8, Math.min(above ? anchor.top - size.height - 9 : below, window.innerHeight - size.height - 8))
  placement.value = above ? 'above' : 'below'
}
function start(element: HTMLElement, immediate: boolean) {
  clearTimeout(leaveTimer)
  if (current !== element) {
    release()
    current = element
    originalTitle = element.getAttribute('title')
    // Suppress the browser's second tooltip while the styled hint owns this control.
    element.removeAttribute('title')
  }
  if (dismissed || visible.value) return
  clearTimeout(showTimer)
  if (immediate) void show()
  else showTimer = setTimeout(() => { void show() }, 380)
}
function maybeLeave() {
  clearTimeout(leaveTimer)
  if (current === hovered || current === focused || overTooltip) return
  clearTimeout(showTimer)
  leaveTimer = setTimeout(release, 120)
}
function pointerOver(event: PointerEvent) {
  if (event.pointerType === 'touch' || tooltip.value?.contains(event.target as Node)) return
  const element = control(event.target)
  if (!element) return
  hovered = element
  start(element, false)
}
function pointerOut(event: PointerEvent) {
  const element = control(event.target)
  if (!element || element === control(event.relatedTarget)) return
  if (hovered === element) hovered = null
  overTooltip = event.relatedTarget instanceof Node && !!tooltip.value?.contains(event.relatedTarget)
  maybeLeave()
}
function focusIn(event: FocusEvent) {
  focused = control(event.target)
  if (focused && !touchInput && focused.matches(':focus-visible')) start(focused, true)
}
function focusOut(event: FocusEvent) {
  if (control(event.relatedTarget) === focused) return
  focused = null
  maybeLeave()
}
function pointerDown(event: PointerEvent) {
  touchInput = event.pointerType === 'touch'
  dismissed = true
  hide()
}
function keyDown(event: KeyboardEvent) {
  if (event.key === 'Tab') touchInput = false
  if (event.key !== 'Escape' || !visible.value) return
  event.preventDefault(); event.stopPropagation()
  dismissed = true
  hide()
}
function keepOpen() { overTooltip = true; clearTimeout(leaveTimer) }
function leaveTooltip() { overTooltip = false; maybeLeave() }

watch(() => route.fullPath, release)
onMounted(() => {
  document.addEventListener('pointerover', pointerOver)
  document.addEventListener('pointerout', pointerOut)
  document.addEventListener('pointerdown', pointerDown, true)
  document.addEventListener('focusin', focusIn)
  document.addEventListener('focusout', focusOut)
  document.addEventListener('keydown', keyDown, true)
  window.addEventListener('scroll', release, { capture: true, passive: true })
  window.addEventListener('resize', release)
})
onBeforeUnmount(() => {
  release()
  document.removeEventListener('pointerover', pointerOver)
  document.removeEventListener('pointerout', pointerOut)
  document.removeEventListener('pointerdown', pointerDown, true)
  document.removeEventListener('focusin', focusIn)
  document.removeEventListener('focusout', focusOut)
  document.removeEventListener('keydown', keyDown, true)
  window.removeEventListener('scroll', release, true)
  window.removeEventListener('resize', release)
})
</script>

<template>
  <Teleport to="body">
    <div v-show="visible" :id="tooltipId" ref="tooltip" class="app-tooltip" role="tooltip" popover="manual" :data-visible="visible" :data-placement="placement" :style="{ left: `${x}px`, top: `${y}px` }" @pointerenter="keepOpen" @pointerleave="leaveTooltip">{{ text }}</div>
  </Teleport>
</template>
