import { defineStore } from 'pinia'
import { api, ApiError } from '../api'
import type { Conversation, ConversationDetail, Turn } from '../types'

export const useWorkbench = defineStore('workbench', {
  state: () => ({ conversations: [] as Conversation[], current: null as ConversationDetail | null, turns: [] as Turn[], selectedTurnId: '', pending: false, loading: false, loadToken: 0, error: '', errorCode: '', panel: 'chat' as 'chat' | 'history' | 'results', disconnectedRequest: null as null | { id: string; message: string; requestId: string; revision: number } }),
  getters: {
    selectedTurn: state => state.turns.find(t => t.turn_id === state.selectedTurnId) || null,
    running: state => state.pending || state.turns.some(t => t.execution_status === 'running'),
  },
  actions: {
    report(error: unknown) { this.error = error instanceof Error ? error.message : '操作未完成，请重试。'; this.errorCode = error instanceof ApiError ? error.code : 'unexpected_error' },
    async refreshList() { this.conversations = await api.list() },
    async load(id: string) {
      const token = ++this.loadToken
      if (id !== this.current?.id) { this.current = null; this.turns = []; this.selectedTurnId = '' }
      this.loading = true; this.error = ''; this.errorCode = ''
      try {
        const detail = await api.detail(id)
        const turns = await Promise.all(detail.turns.map(t => api.turn(id, t.turn_id)))
        if (token !== this.loadToken) return
        this.current = detail; this.turns = turns
        if (!turns.some(t => t.turn_id === this.selectedTurnId)) this.selectedTurnId = turns.at(-1)?.turn_id || ''
        if (this.disconnectedRequest?.id === id && turns.some(t => t.client_request_id === this.disconnectedRequest?.requestId)) this.disconnectedRequest = null
      } catch (error) { if (token === this.loadToken) this.report(error) } finally { if (token === this.loadToken) this.loading = false }
    },
    async create() {
      try { const conversation = await api.create(); await this.refreshList(); await this.load(conversation.id); this.panel = 'chat'; return conversation.id } catch (error) { this.report(error) }
    },
    async send(message: string) {
      if (!this.current || this.running || !message.trim()) return
      if (this.disconnectedRequest) { this.error = '上一条请求的状态尚未核对，请先恢复会话。'; return }
      this.pending = true; this.error = ''; this.errorCode = ''
      const id = this.current.id
      const request = { id, message: message.trim(), requestId: crypto.randomUUID(), revision: this.current.revision }
      try {
        const turn = await api.submit(id, request.message, request.requestId, request.revision)
        if (this.current?.id === id) { this.selectedTurnId = turn.turn_id; await this.load(id) }
        await this.refreshList()
      } catch (error) {
        if (error instanceof ApiError && error.code === 'connection_lost') this.disconnectedRequest = request
        if (this.current?.id === id) {
          if (error instanceof ApiError && error.turnId) this.selectedTurnId = error.turnId
          await this.load(id)
        }
        this.report(error)
      } finally { this.pending = false }
    },
    async recover() {
      const id = this.disconnectedRequest?.id || this.current?.id
      if (id) { await this.load(id); try { await this.refreshList() } catch (error) { this.report(error) } }
    },
    async resendSameRequest() {
      const saved = this.disconnectedRequest
      if (!saved || this.pending) return
      this.pending = true
      try {
        // Explicit user action reuses the original key and revision, never generates a duplicate.
        const turn = await api.submit(saved.id, saved.message, saved.requestId, saved.revision)
        this.selectedTurnId = turn.turn_id; this.disconnectedRequest = null; await this.load(saved.id)
      } catch (error) { this.report(error) } finally { this.pending = false }
    },
    async rename(title: string) {
      if (!this.current) return
      try { await api.rename(this.current.id, title); await this.load(this.current.id); await this.refreshList() } catch (error) { this.report(error) }
    },
    async remove() {
      if (!this.current) return
      try { await api.delete(this.current.id); this.current = null; this.turns = []; this.selectedTurnId = ''; await this.refreshList() } catch (error) { this.report(error) }
    },
  },
})
