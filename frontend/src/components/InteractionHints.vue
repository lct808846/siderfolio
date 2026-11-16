<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref, useId, watch } from 'vue'
import { useRoute } from 'vue-router'

const route = useRoute()
const tooltipId = `astro-hint-${useId()}`
const tooltip = ref<HTMLElement | null>(null)
const visible = ref(false), text = ref(''), x = ref(0), y = ref(0), placement = ref('below')
const selector = 'button, a[href], [role="button"], [role="tab"], [role="menuitem"], [data-tooltip], summary, input[type="file"], input[type="submit"], input[type="button"]'
let current: HTMLElement | null = null, hovered: HTMLElement | null = null, focused: HTMLElement | null = null
let originalTitle: string | null = null, overTooltip = false, dismissed = false, touchInput = false, revision = 0
let showTimer: ReturnType<typeof setTimeout> | undefined, leaveTimer: ReturnType<typeof setTimeout> | undefined

function control(target: EventTarget | null) {
  if (!(target instanceof Element) || tooltip.value?.contains(target)) return null
  const element = target.closest<HTMLElement>(selector)
  return element && !element.closest('[inert], [aria-hidden="true"]') ? element : null
}
function hasReadableText(element: HTMLElement) {
  if (element instanceof HTMLInputElement) {
    if (element.type === 'submit' || element.type === 'button') return /[\p{L}\p{N}]/u.test(element.value)
    return element.type !== 'file'
  }
  const clone = element.cloneNode(true) as HTMLElement
  clone.querySelectorAll('svg, img, [aria-hidden="true"], .sr-only').forEach(node => node.remove())
  const visibleText = (clone.textContent || '').replace(/\s+/g, ' ').trim()
  return /[\p{L}\p{N}]/u.test(visibleText)
}
function formatTooltip(element: HTMLElement, rawText: string) {
  const normalized = rawText.replace(/\s+/g, ' ').trim()
  if (!normalized) return ''
  const shortened = normalized.length > 160 ? `${normalized.slice(0, 159)}…` : normalized
  return element.matches(':disabled, [aria-disabled="true"]') ? `${shortened}（当前不可用）` : shortened
}
function label(element: HTMLElement) {
  const explicit = element.getAttribute('data-tooltip')
  if (explicit === '') return ''
  if (element.hasAttribute('data-tooltip-truncated')) {
    const source = element.querySelector<HTMLElement>('[data-tooltip-source]') || element
    const truncated = source.scrollHeight > source.clientHeight + 2 || source.scrollWidth > source.clientWidth + 2
    return truncated ? formatTooltip(element, explicit || source.textContent || '') : ''
  }
  const title = element.getAttribute('title') ?? (element === current ? originalTitle : null)
  if (explicit || title) return formatTooltip(element, explicit || title || '')
  if (hasReadableText(element)) return ''
  const labelled = (element.getAttribute('aria-labelledby') || '').split(/\s+/)
    .map(id => document.getElementById(id)?.textContent || '').join(' ')
  const fallback = element.getAttribute('aria-label') || labelled
    || (element instanceof HTMLInputElement && element.type === 'file' ? '选择要导入的文件' : '')
  return formatTooltip(element, fallback)
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
