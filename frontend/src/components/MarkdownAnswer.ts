import MarkdownIt, { type Token } from 'markdown-it'
import { defineComponent, h, type VNodeChild } from 'vue'
import { safeLink } from '../api'

const markdown = new MarkdownIt({ html: false, linkify: false, typographer: false })
markdown.validateLink = value => safeLink(value) !== null
const tags = new Set(['p', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'ul', 'ol', 'li', 'blockquote', 'strong', 'em', 's', 'table', 'thead', 'tbody', 'tr', 'th', 'td', 'a'])
type Frame = { tag: string; attributes: Record<string, unknown>; children: VNodeChild[] }

// Build Vue text nodes and a finite set of elements. Never insert model HTML into the DOM.
function renderTokens(tokens: Token[]): VNodeChild[] {
  const frames: Frame[] = [{ tag: 'div', attributes: {}, children: [] }]
  const append = (value: VNodeChild) => frames[frames.length - 1]!.children.push(value)
  for (const token of tokens) {
    if (token.type === 'inline') { renderTokens(token.children || []).forEach(append); continue }
    if (token.type === 'text' || token.type === 'html_inline' || token.type === 'html_block') { append(token.content); continue }
    if (token.type === 'code_inline') { append(h('code', token.content)); continue }
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
