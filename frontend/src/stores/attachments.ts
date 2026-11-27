import { defineStore } from 'pinia'
import { attachmentExtensions, attachmentFileLimit, parseAttachment } from '../api/attachments'
import type { ChatAttachment } from '../types'

export interface AttachmentDraft { id: string; file: File; state: 'reading' | 'ready' | 'error'; error: string; data?: ChatAttachment }
const requests = new Map<string, AbortController>()
const rawFilesBySha = new Map<string, File>()
function rememberRawFile(sha256: string, file: File) {
  rawFilesBySha.delete(sha256)
  rawFilesBySha.set(sha256, file)
  while (rawFilesBySha.size > 24) {
    const oldest = rawFilesBySha.keys().next().value
    if (oldest === undefined) break
    rawFilesBySha.delete(oldest)
  }
}
export const useAttachments = defineStore('attachments', {
  state: () => ({ drafts: new Map<string, AttachmentDraft[]>(), notices: new Map<string, string>() }),
  getters: {
    rows: state => (scope: string): AttachmentDraft[] => state.drafts.get(scope) || [],
    ready: state => (scope: string): ChatAttachment[] => (state.drafts.get(scope) || []).flatMap(item => item.state === 'ready' && item.data ? [item.data] : []),
    blocked: state => (scope: string): boolean => (state.drafts.get(scope) || []).some(item => item.state !== 'ready'),
    rawFile: () => (sha256: string): File | undefined => rawFilesBySha.get(sha256),
  },
  actions: {
    async add(scope: string, files: File[]) {
      this.notices.delete(scope)
      const added: string[] = []
      const problems: string[] = []
      for (const rawFile of files) {
        let file = rawFile
        const rawExt = file.name.includes('.') ? '.' + (file.name.split('.').at(-1) || '').toLowerCase() : ''
        if (!rawExt && file.type.startsWith('image/')) {
          const fallbackExt = file.type === 'image/jpeg' ? '.jpg' : file.type === 'image/webp' ? '.webp' : file.type === 'image/gif' ? '.gif' : '.png'
          file = new File([file], `pasted-image-${Date.now()}${fallbackExt}`, { type: file.type, lastModified: file.lastModified })
        }
        const rows = this.drafts.get(scope) || []
        if (rows.some(row => row.file.name === file.name && row.file.size === file.size && row.file.lastModified === file.lastModified)) continue
        if (rows.length >= 3) { problems.push('每条消息最多添加 3 个附件。'); break }
        const extension = '.' + (file.name.split('.').at(-1) || '').toLowerCase()
        if (!attachmentExtensions.has(extension)) { problems.push(`${file.name}：支持图片（PNG、JPG、WebP、GIF）及 PDF、DOCX、TXT、Markdown、CSV、TSV、JSON。`); continue }
        if (!file.size || file.size > attachmentFileLimit) { problems.push(`${file.name}：文件不能为空，单个最多 10 MiB。`); continue }
        const id = crypto.randomUUID()
        this.drafts.set(scope, [...rows, { id, file, state: 'reading', error: '' }])
        added.push(id)
      }
      if (problems.length) this.notices.set(scope, problems.slice(0, 3).join(' '))
      // Sequential parsing keeps a multi-file selection within the server parser budget.
      for (const id of added) await this.read(scope, id)
    },
    async read(scope: string, id: string) {
      const row = this.drafts.get(scope)?.find(item => item.id === id)
      if (!row || requests.has(id)) return
      row.state = 'reading'; row.error = ''
      const controller = new AbortController()
      requests.set(id, controller)
      try {
        const data = await parseAttachment(row.file, controller.signal)
        const latest = this.drafts.get(scope)?.find(item => item.id === id)
        if (latest && !controller.signal.aborted) {
          latest.data = data
          latest.state = 'ready'
          rememberRawFile(data.sha256, latest.file)
        }
      } catch (error) {
        const latest = this.drafts.get(scope)?.find(item => item.id === id)
        if (latest && !controller.signal.aborted) { latest.state = 'error'; latest.error = error instanceof Error ? error.message : '附件解析失败。' }
      } finally { requests.delete(id) }
    },
    remove(scope: string, id: string) {
      requests.get(id)?.abort()
      this.drafts.set(scope, (this.drafts.get(scope) || []).filter(item => item.id !== id))
      this.notices.delete(scope)
    },
    clear(scope: string) {
      for (const row of this.drafts.get(scope) || []) requests.get(row.id)?.abort()
      this.drafts.delete(scope); this.notices.delete(scope)
    },
    move(from: string, to: string) {
      if (from === to) return
      const rows = this.drafts.get(from)
      if (rows) { this.drafts.set(to, rows); this.drafts.delete(from) }
      const notice = this.notices.get(from)
      if (notice) { this.notices.set(to, notice); this.notices.delete(from) }
    },
  },
})
