import katex from 'katex'
import 'katex/dist/katex.min.css'
import MarkdownIt, { type Token } from 'markdown-it'
import { defineComponent, h, type VNodeChild } from 'vue'
import { safeLink } from '../api'

type MarkdownInstance = InstanceType<typeof MarkdownIt>
type BlockRule = Parameters<MarkdownInstance['block']['ruler']['before']>[2]
type InlineRule = Parameters<MarkdownInstance['inline']['ruler']['before']>[2]

const ASTRO_MACROS: Record<string, string> = {
  '\\sun': '\\odot',
  '\\earth': '\\oplus',
  '\\arcsec': '^{\\prime\\prime}',
  '\\arcmin': '^{\\prime}',
  '\\farcs': '.\\!^{\\prime\\prime}',
  '\\farcm': '.\\!^{\\prime}',
  '\\fdg': '.\\!^{\\circ}',
}

function isEscaped(src: string, index: number): boolean {
  let backslashes = 0
  for (let i = index - 1; i >= 0 && src.charCodeAt(i) === 0x5c; i--) backslashes++
  return backslashes % 2 === 1
}

const mathBlockRule: BlockRule = (state, startLine, endLine, silent) => {
  const startPos = state.bMarks[startLine]! + state.tShift[startLine]!
  const maxPos = state.eMarks[startLine]!
  if (state.sCount[startLine]! - state.blkIndent >= 4) return false
  const line = state.src.slice(startPos, maxPos)
  let openDelim: string
  let closeDelim: string
  if (line.startsWith('$$')) {
    openDelim = '$$'
    closeDelim = '$$'
  } else if (line.startsWith('\\[')) {
    openDelim = '\\['
    closeDelim = '\\]'
  } else {
    return false
  }

  const afterOpen = line.slice(openDelim.length)
  const sameLineClose = afterOpen.indexOf(closeDelim)
  if (sameLineClose !== -1 && afterOpen.slice(sameLineClose + closeDelim.length).trim() === '') {
    const content = afterOpen.slice(0, sameLineClose).trim()
    if (!content) return false
    if (silent) return true
    state.line = startLine + 1
    const token = state.push('math_block', 'math', 0)
    token.block = true
    token.content = content
    token.map = [startLine, state.line]
    return true
  }

  let nextLine = startLine + 1
  let closingLine = -1
  let closingSlice = ''
  while (nextLine < endLine) {
    const pos = state.bMarks[nextLine]! + state.tShift[nextLine]!
    const end = state.eMarks[nextLine]!
    const text = state.src.slice(pos, end)
    const idx = text.lastIndexOf(closeDelim)
    if (idx !== -1 && !isEscaped(text, idx) && text.slice(idx + closeDelim.length).trim() === '') {
      closingLine = nextLine
      closingSlice = text.slice(0, idx)
      break
    }
    nextLine++
  }
  if (closingLine === -1) return false
  if (silent) return true

  const parts: string[] = []
  if (afterOpen.trim()) parts.push(afterOpen)
  for (let i = startLine + 1; i < closingLine; i++) {
    parts.push(state.src.slice(state.bMarks[i]!, state.eMarks[i]!))
  }
  if (closingSlice.trim()) parts.push(closingSlice)
  const content = parts.join('\n').trim()
  if (!content) return false

  state.line = closingLine + 1
  const token = state.push('math_block', 'math', 0)
  token.block = true
  token.content = content
  token.map = [startLine, state.line]
  return true
}

const mathInlineRule: InlineRule = (state, silent) => {
  const src = state.src
  const pos = state.pos
  const max = state.posMax
  const ch = src.charCodeAt(pos)

  // Match \(...\) or \[...\]
  if (ch === 0x5c && pos + 1 < max) {
    const next = src.charCodeAt(pos + 1)
    const isParen = next === 0x28 // (
    const isBracket = next === 0x5b // [
    if (!isParen && !isBracket) return false
    const closeStr = isParen ? '\\)' : '\\]'
    let idx = pos + 2
    let found = -1
    while (idx < max - 1) {
      const candidate = src.indexOf(closeStr, idx)
      if (candidate === -1 || candidate >= max) break
      if (!isEscaped(src, candidate)) {
        found = candidate
        break
      }
      idx = candidate + 2
    }
    if (found === -1) return false
    const content = src.slice(pos + 2, found).trim()
    if (!content) return false
    if (!silent) {
      const token = state.push(isBracket ? 'math_block' : 'math_inline', 'math', 0)
      token.content = content
    }
    state.pos = found + 2
    return true
  }

  // Match $$...$$ or $...$
  if (ch !== 0x24) return false // '$'
  const isDouble = pos + 1 < max && src.charCodeAt(pos + 1) === 0x24
  if (isDouble) {
    let idx = pos + 2
    let found = -1
    while (idx < max - 1) {
      const candidate = src.indexOf('$$', idx)
      if (candidate === -1 || candidate >= max) break
      if (!isEscaped(src, candidate)) {
        found = candidate
        break
      }
      idx = candidate + 2
    }
    if (found === -1) return false
    const content = src.slice(pos + 2, found).trim()
    if (!content) return false
    if (!silent) {
      const token = state.push('math_block', 'math', 0)
      token.content = content
    }
    state.pos = found + 2
    return true
  }

  // Single $...$ inline math: disallow leading/trailing space or currency followed by digit
  if (pos + 1 >= max) return false
  const afterOpen = src.charCodeAt(pos + 1)
  if (afterOpen === 0x20 || afterOpen === 0x09 || afterOpen === 0x0a || afterOpen === 0x0d || afterOpen === 0x24) {
    return false
  }
  let idx = pos + 1
  let found = -1
  while (idx < max) {
    const code = src.charCodeAt(idx)
    if (code === 0x5c) {
      idx += 2
      continue
    }
    if (code === 0x0a) break
    if (code === 0x24) {
      const beforeClose = src.charCodeAt(idx - 1)
      const afterClose = idx + 1 < max ? src.charCodeAt(idx + 1) : 0
      const precededBySpace = beforeClose === 0x20 || beforeClose === 0x09
      const followedByDigit = afterClose >= 0x30 && afterClose <= 0x39
      const followedByDollar = afterClose === 0x24
      if (!precededBySpace && !followedByDigit && !followedByDollar) {
        found = idx
        break
      }
    }
    idx++
  }
  if (found === -1) return false
  const content = src.slice(pos + 1, found)
  if (!content.trim()) return false
  if (!silent) {
    const token = state.push('math_inline', 'math', 0)
    token.content = content
  }
  state.pos = found + 1
  return true
}

function renderMathHtml(source: string, displayMode: boolean): string {
  try {
    return katex.renderToString(source, {
      displayMode,
      throwOnError: false,
      trust: false,
      strict: 'ignore',
      output: 'htmlAndMathml',
      maxSize: 20,
      maxExpand: 200,
      macros: { ...ASTRO_MACROS },
    })
  } catch {
    return ''
  }
}

const markdown = new MarkdownIt({ html: false, linkify: true, typographer: false })
markdown.linkify.set({ fuzzyLink: false, fuzzyEmail: false, fuzzyIP: false })
markdown.block.ruler.before('fence', 'math_block', mathBlockRule, {
  alt: ['paragraph', 'reference', 'blockquote', 'list'],
})
markdown.inline.ruler.before('escape', 'math_inline', mathInlineRule)
markdown.validateLink = value => safeLink(value) !== null
const tags = new Set(['p', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'ul', 'ol', 'li', 'blockquote', 'strong', 'em', 's', 'table', 'thead', 'tbody', 'tr', 'th', 'td', 'a'])
type Frame = { tag: string; attributes: Record<string, unknown>; children: VNodeChild[] }

// Build Vue text nodes and a finite set of elements. Never insert raw model HTML into the DOM.
function renderTokens(tokens: Token[]): VNodeChild[] {
  const frames: Frame[] = [{ tag: 'div', attributes: {}, children: [] }]
  const append = (value: VNodeChild) => frames[frames.length - 1]!.children.push(value)
  for (const token of tokens) {
    if (token.type === 'inline') { renderTokens(token.children || []).forEach(append); continue }
    if (token.type === 'math_inline' || token.type === 'math_block') {
      const displayMode = token.type === 'math_block'
      const html = renderMathHtml(token.content, displayMode)
      if (html) {
        append(
          h(displayMode ? 'div' : 'span', {
            class: displayMode ? 'markdown-math-display' : 'markdown-math-inline',
            innerHTML: html,
          }),
        )
      } else {
        append(displayMode ? `$$${token.content}$$` : `$${token.content}$`)
      }
      continue
    }
    if (token.type === 'text' || token.type === 'html_inline' || token.type === 'html_block') { append(token.content); continue }
    if (token.type === 'code_inline') {
      const trimmed = token.content.trim()
      const href = /^https?:\/\/\S+$/i.test(trimmed) ? safeLink(trimmed) : null
      if (href && !frames.some(frame => frame.tag === 'a')) {
        append(
          h(
            'a',
            {
              class: 'markdown-code-link',
              href,
              target: '_blank',
              rel: 'noopener noreferrer',
              referrerpolicy: 'no-referrer',
            },
            [h('code', token.content)],
          ),
        )
      } else {
        append(h('code', token.content))
      }
      continue
    }
    if (token.type === 'fence' || token.type === 'code_block') {
      const language = token.info.trim().split(/\s+/)[0] || '代码'
      append(h('div', { class: 'markdown-code' }, [h('div', { class: 'markdown-code-label' }, language), h('pre', [h('code', token.content)])]))
      continue
    }
    if (token.type === 'image') { append(`[图片：${token.content || '未提供说明'}]`); continue }
    if (token.type === 'softbreak') { append('\n'); continue }
    if (token.type === 'hardbreak') { append(h('br')); continue }
    if (token.type === 'hr') { append(h('hr')); continue }
    if (token.nesting === 1) {
      let tag = tags.has(token.tag) ? token.tag : 'span'
      const attributes: Record<string, unknown> = {}
      if (tag === 'a') {
        const href = safeLink(String(token.attrGet('href') || ''))
        if (href) { attributes.href = href; attributes.target = '_blank'; attributes.rel = 'noopener noreferrer'; attributes.referrerpolicy = 'no-referrer' }
        else tag = 'span'
      }
      if (tag === 'ol') {
        const start = Number(token.attrGet('start') || 1)
        if (Number.isSafeInteger(start)) attributes.start = start
      }
      if (tag === 'th' || tag === 'td') {
        const alignment = /^text-align:(left|right|center)$/.exec(String(token.attrGet('style') || ''))
        if (alignment) attributes.style = { textAlign: alignment[1] }
      }
      frames.push({ tag, attributes, children: [] })
    } else if (token.nesting === -1 && frames.length > 1) {
      const frame = frames.pop()!
      const element = h(frame.tag, frame.attributes, frame.children)
      append(frame.tag === 'table' ? h('div', { class: 'markdown-table', tabindex: 0, role: 'region', 'aria-label': '回答中的表格' }, [element]) : element)
    } else if (token.content) append(token.content)
  }
  return frames[0]!.children
}

export default defineComponent({
  name: 'MarkdownAnswer',
  props: { text: { type: String, required: true } },
  setup(props) {
    return () => h('div', { class: 'markdown-answer' }, renderTokens(markdown.parse(props.text, {})))
  },
})
