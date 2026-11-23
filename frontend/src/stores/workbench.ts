import { defineStore } from 'pinia'
import { api, ApiError } from '../api'
import { identityUser } from '../identity-state'
import type { ArchivedConversation, ChatAttachment, ChatToolMode, Conversation, ConversationBundle, ConversationDetail, Turn } from '../types'

interface CachedConversation {
  detail: ConversationDetail
  turns: Turn[]
}

const MAX_CACHED_CONVERSATIONS = 20
let cacheOwnerId = ''
const conversationCache = new Map<string, CachedConversation>()
const inFlightBundles = new Map<string, Promise<ConversationBundle>>()

function ensureCacheOwner(): string {
  const owner = identityUser.value?.id || ''
  if (owner !== cacheOwnerId) {
    conversationCache.clear()
    inFlightBundles.clear()
    cacheOwnerId = owner
  }
  return owner
}

function fetchBundleDeduped(id: string): Promise<ConversationBundle> {
  ensureCacheOwner()
  const existing = inFlightBundles.get(id)
  if (existing) return existing
  const promise = api.bundle(id).finally(() => {
    if (inFlightBundles.get(id) === promise) inFlightBundles.delete(id)
  })
  inFlightBundles.set(id, promise)
  return promise
}

function readCached(id: string): CachedConversation | undefined {
  if (!ensureCacheOwner()) return undefined
  const entry = conversationCache.get(id)
  if (!entry) return undefined
  // Refresh LRU position.
  conversationCache.delete(id)
  conversationCache.set(id, entry)
  return entry
}

function writeCached(id: string, detail: ConversationDetail, turns: Turn[]) {
  if (!ensureCacheOwner()) return
  conversationCache.delete(id)
  conversationCache.set(id, { detail, turns })
  while (conversationCache.size > MAX_CACHED_CONVERSATIONS) {
    const oldest = conversationCache.keys().next().value
    if (oldest) conversationCache.delete(oldest)
    else break
  }
}

function evictCached(id: string) {
  conversationCache.delete(id)
}

export interface PendingTurnState {
  conversationId: string
  message: string
  attachments: ChatAttachment[]
  model?: string
  toolMode?: ChatToolMode
  sentAt: string
  streamedText: string
  statusLabel: string
  statusPhase: string
}

export const useWorkbench = defineStore('workbench', {
  state: () => ({ conversations: [] as Conversation[], archived: [] as ArchivedConversation[], current: null as ConversationDetail | null, preparedConversation: null as ConversationDetail | null, turns: [] as Turn[], selectedTurnId: '', pending: false, pendingTurn: null as null | PendingTurnState, creating: false, loading: false, loadToken: 0, error: '', errorCode: '', errorTurnId: '', panel: 'chat' as 'chat' | 'history' | 'results', disconnectedRequest: null as null | { id: string; message: string; requestId: string; revision: number; model?: string; attachments?: ChatAttachment[]; toolMode?: ChatToolMode } }),
  getters: {
    selectedTurn: state => state.turns.find(t => t.turn_id === state.selectedTurnId) || null,
    running: state => state.pending || state.turns.some(t => t.execution_status === 'running'),
  },
  actions: {
    clearError() { this.error = ''; this.errorCode = ''; this.errorTurnId = '' },
    report(error: unknown) {
      this.error = error instanceof Error ? error.message : '操作未完成，请重试。'
      this.errorCode = error instanceof ApiError ? error.code : 'unexpected_error'
      this.errorTurnId = error instanceof ApiError ? error.turnId || '' : ''
    },
    async refreshList() {
      const values = await api.list()
      const previous = new Map(this.conversations.map(value => [value.id, value]))
      if (this.current && this.current.metadata_revision > (previous.get(this.current.id)?.metadata_revision ?? -1)) previous.set(this.current.id, this.current)
      this.conversations = values.map(value => {
        const current = previous.get(value.id)
        return current && current.metadata_revision > value.metadata_revision
          ? { ...value, title: current.title, metadata_revision: current.metadata_revision }
          : value
      })
      if (this.current) {
        const saved = this.conversations.find(value => value.id === this.current?.id)
        if (saved && saved.metadata_revision >= this.current.metadata_revision) {
          this.current.title = saved.title; this.current.metadata_revision = saved.metadata_revision
        }
      }
    },
    async refreshArchived() {
      this.archived = await api.archived()
    },
    async archiveConversation(id: string) {
      const archived = await api.archive(id)
      evictCached(id)
      this.conversations = this.conversations.filter(item => item.id !== id)
      this.archived = [archived, ...this.archived.filter(item => item.id !== id)]
      if (this.current?.id === id) {
        this.loadToken++
        this.current = null
        this.turns = []
        this.selectedTurnId = ''
      }
      return archived
    },
    async unarchiveConversation(id: string) {
      const restored = await api.unarchive(id)
      evictCached(id)
      this.archived = this.archived.filter(item => item.id !== id)
      await this.refreshList()
      return restored
    },
    prefetch(id: string) {
      if (!id || readCached(id) || inFlightBundles.has(id)) return
      const owner = ensureCacheOwner()
      if (!owner) return
      void fetchBundleDeduped(id)
        .then(bundled => {
          if (ensureCacheOwner() !== owner) return
          writeCached(id, bundled.conversation, bundled.turns || [])
        })
        .catch(() => undefined)
    },
    async load(id: string, forceFresh = false) {
      const token = ++this.loadToken
      const cached = forceFresh ? undefined : readCached(id)
      if (cached) {
        this.current = cached.detail
        this.turns = cached.turns
        if (!cached.turns.some(t => t.turn_id === this.selectedTurnId)) {
          this.selectedTurnId = cached.turns.at(-1)?.turn_id || ''
        }
        this.loading = false
        this.clearError()
      } else {
        if (id !== this.current?.id) { this.current = null; this.turns = []; this.selectedTurnId = '' }
        this.loading = true
        this.clearError()
      }
      try {
        const bundled = forceFresh ? await api.bundle(id) : await fetchBundleDeduped(id)
        const detail = bundled.conversation
        const turns = bundled.turns || []
        if (token !== this.loadToken) return
        // A slower detail response must not replace a title already refreshed or edited.
        const known = [this.current, this.conversations.find(value => value.id === id)]
          .filter((value): value is Conversation => !!value && value.id === id)
          .sort((left, right) => right.metadata_revision - left.metadata_revision)[0]
        if (known && known.metadata_revision > detail.metadata_revision) {
          detail.title = known.title; detail.metadata_revision = known.metadata_revision
        }
        this.current = detail; this.turns = turns
        writeCached(id, detail, turns)
        if (!turns.some(t => t.turn_id === this.selectedTurnId)) this.selectedTurnId = turns.at(-1)?.turn_id || ''
        if (this.disconnectedRequest?.id === id && turns.some(t => t.client_request_id === this.disconnectedRequest?.requestId)) this.disconnectedRequest = null
      } catch (error) {
        if (token === this.loadToken && !cached) this.report(error)
      } finally {
        if (token === this.loadToken) this.loading = false
      }
    },
    async create(persist = true) {
      if (this.creating || this.loading || this.running || this.disconnectedRequest) return
      // Reopening the unsaved draft is a local no-op. Do not toggle creating,
      // disable the composer, or refetch history on every click.
      if (!persist && !this.current && !this.turns.length) {
        this.panel = 'chat'
        return null
      }
      if (this.current?.title === '新会话' && this.current.revision === 0 && !this.current.turns.length && !this.turns.length) {
        this.panel = 'chat'
        return this.current.id
      }
      // Preparing an unsaved destination must leave the displayed conversation
      // intact. The router commits it together with the new URL.
      if (persist) this.creating = true
      this.preparedConversation = null
      const token = ++this.loadToken
      let createdId: string | undefined
      try {
        // Reuse an unused conversation anywhere in the list, not just the active one.
        await this.refreshList()
        if (token !== this.loadToken) return
        for (const candidate of this.conversations.filter(item => item.title === '新会话' && item.revision === 0)) {
          let detail: ConversationDetail
          try { detail = await api.detail(candidate.id) }
          catch (error) {
            if (error instanceof ApiError && error.status === 404) continue
            throw error
          }
          if (token !== this.loadToken) return
          if (detail.id !== candidate.id || detail.title !== '新会话' || detail.revision !== 0 || detail.turns.length) continue
          if (!persist) {
            this.preparedConversation = detail
            return detail.id
          }
          this.current = detail; this.turns = []; this.selectedTurnId = ''; this.panel = 'chat'
          this.clearError()
          return detail.id
        }
        if (!persist) {
          // An unused local draft is not a saved conversation and consumes no list slot.
          return null
        }
        const conversation = await api.create()
        createdId = conversation.id
        // Keep a confirmed creation even if refreshing the sidebar fails afterward.
        if (token === this.loadToken) {
          this.current = { ...conversation, turns: [] }
          this.turns = []; this.selectedTurnId = ''; this.panel = 'chat'
          this.clearError()
        }
        await this.refreshList()
        return createdId
      } catch (error) {
        if (token === this.loadToken) this.report(error)
        return createdId
      } finally { if (persist) this.creating = false }
    },
    async send(message: string, expectedConversationId?: string, model?: string, attachments: ChatAttachment[] = [], toolMode?: ChatToolMode) {
      if (!this.current || this.running || this.creating || this.loading || !message.trim()) return
      if (expectedConversationId && this.current.id !== expectedConversationId) return
      if (this.disconnectedRequest) { this.report(new ApiError('connection_lost', '上一条请求的状态尚未核对，请先恢复会话。')); return }
      this.pending = true; this.clearError()
      const id = this.current.id
      const request = { id, message: message.trim(), requestId: crypto.randomUUID(), revision: this.current.revision, model, attachments: attachments.map(item => ({ ...item, warnings: [...(item.warnings || [])] })), toolMode }
      this.pendingTurn = { conversationId: id, message: request.message, attachments: request.attachments, model: request.model, toolMode: request.toolMode, sentAt: new Date().toISOString(), streamedText: '', statusLabel: '正在处理，请稍候…', statusPhase: 'thinking' }
      let submitted = false
      try {
        const turn = await api.submitStream(id, request.message, request.requestId, request.revision, request.model, request.attachments, request.toolMode, {
          onStatus: status => {
            if (!this.pendingTurn || this.pendingTurn.conversationId !== id) return
            if (status.label) this.pendingTurn.statusLabel = status.label
            if (status.phase) this.pendingTurn.statusPhase = status.phase
          },
          onDelta: text => {
            if (!this.pendingTurn || this.pendingTurn.conversationId !== id) return
            this.pendingTurn.streamedText += text
          },
          onReset: () => {
            if (!this.pendingTurn || this.pendingTurn.conversationId !== id) return
            this.pendingTurn.streamedText = ''
          },
        })
        submitted = true
        this.archived = this.archived.filter(item => item.id !== id)
        if (this.current?.id === id) {
          const existingIdx = this.turns.findIndex(item => item.turn_id === turn.turn_id)
          const nextTurns = existingIdx >= 0
            ? this.turns.map((item, idx) => (idx === existingIdx ? turn : item))
            : [...this.turns, turn]
          const nextSummary = {
            turn_id: turn.turn_id,
            revision: turn.revision,
            message: turn.message,
            model: turn.model ?? null,
            execution_status: turn.execution_status,
            received_at: turn.received_at,
            completed_at: turn.completed_at ?? null,
            response_status: turn.response?.status ?? null,
          }
          const nextDetail: ConversationDetail = {
            ...this.current,
            revision: Math.max(this.current.revision, turn.revision),
            updated_at: turn.completed_at || turn.received_at,
            turns: existingIdx >= 0
              ? this.current.turns.map((item, idx) => (idx === existingIdx ? nextSummary : item))
              : [...this.current.turns, nextSummary],
          }
          this.current = nextDetail
          this.turns = nextTurns
          writeCached(id, nextDetail, nextTurns)
          this.selectedTurnId = turn.turn_id
          this.pendingTurn = null
        } else {
          evictCached(id)
        }
        void this.refreshList().catch(() => undefined)
      } catch (error) {
        const unconfirmed = !submitted && error instanceof ApiError && error.code === 'connection_lost'
        if (unconfirmed) this.disconnectedRequest = request
        if (this.current?.id === id) {
          if (error instanceof ApiError && error.turnId) this.selectedTurnId = error.turnId
          await this.load(id, true)
        }
        if (unconfirmed && !this.disconnectedRequest) return
        this.report(error)
        if (!submitted && !unconfirmed) return 'rejected'
      } finally { this.pending = false; this.pendingTurn = null }
    },
    async recover() {
      const id = this.disconnectedRequest?.id || this.current?.id
      this.clearError()
      if (id) await this.load(id, true)
      try { await this.refreshList() } catch (error) { this.report(error) }
    },
    async resendSameRequest() {
      const saved = this.disconnectedRequest
      if (!saved || this.pending) return
      this.pending = true
      this.pendingTurn = { conversationId: saved.id, message: saved.message, attachments: saved.attachments || [], model: saved.model, toolMode: saved.toolMode, sentAt: new Date().toISOString(), streamedText: '', statusLabel: '正在处理，请稍候…', statusPhase: 'thinking' }
      try {
        // Explicit user action reuses the original key and revision, never generates a duplicate.
        const turn = await api.submitStream(saved.id, saved.message, saved.requestId, saved.revision, saved.model, saved.attachments, saved.toolMode, {
          onStatus: status => {
            if (!this.pendingTurn || this.pendingTurn.conversationId !== saved.id) return
            if (status.label) this.pendingTurn.statusLabel = status.label
            if (status.phase) this.pendingTurn.statusPhase = status.phase
          },
          onDelta: text => {
            if (!this.pendingTurn || this.pendingTurn.conversationId !== saved.id) return
            this.pendingTurn.streamedText += text
          },
          onReset: () => {
            if (!this.pendingTurn || this.pendingTurn.conversationId !== saved.id) return
            this.pendingTurn.streamedText = ''
          },
        })
        this.selectedTurnId = turn.turn_id; this.disconnectedRequest = null
        if (this.current?.id === saved.id && !this.turns.some(item => item.turn_id === turn.turn_id)) {
          this.turns = [...this.turns, turn]
        }
        this.pendingTurn = null
        await this.load(saved.id, true)
      } catch (error) { this.report(error) } finally { this.pending = false; this.pendingTurn = null }
    },
    async rename(title: string) {
      if (!this.current) return
      try { await api.rename(this.current.id, title, this.current.metadata_revision); evictCached(this.current.id); await this.load(this.current.id, true); await this.refreshList() } catch (error) { this.report(error) }
    },
    async remove() {
      if (!this.current) return
      const targetId = this.current.id
      try { await api.delete(targetId); evictCached(targetId); this.current = null; this.turns = []; this.selectedTurnId = ''; await this.refreshList() } catch (error) { this.report(error) }
    },
  },
})
