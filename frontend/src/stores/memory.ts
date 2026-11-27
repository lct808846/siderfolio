import { defineStore } from 'pinia'
import { memoryApi } from '../api/memory'
import { identityUser } from '../identity-state'
import type {
  MemoryCreateRequest,
  MemoryPreferences,
  MemorySummaryOverview,
} from '../types'

let loadedOwner = ''

const defaultPreferences = (): MemoryPreferences => ({
  auto_extract: true,
  cross_session_injection: true,
  history_retrieval: true,
  revision: 0,
  updated_at: null,
})

export const useMemory = defineStore('memory', {
  state: () => ({
    preferences: defaultPreferences() as MemoryPreferences,
    overview: null as MemorySummaryOverview | null,
    loading: false,
    saving: false,
    error: '',
  }),
  getters: {
    enabled: state =>
      Boolean(
        state.preferences.auto_extract ||
        state.preferences.cross_session_injection ||
        state.preferences.history_retrieval,
      ),
  },
  actions: {
    ensureOwner() {
      const owner = identityUser.value?.id || ''
      if (owner !== loadedOwner) {
        this.preferences = defaultPreferences()
        this.overview = null
        this.error = ''
        loadedOwner = owner
      }
    },
    async loadSummary() {
      this.ensureOwner()
      this.loading = true
      this.error = ''
      try {
        const data = await memoryApi.summary()
        this.overview = data
        this.preferences = data.preferences ?? defaultPreferences()
      } catch (e) {
        this.error = e instanceof Error ? e.message : '读取记忆摘要失败。'
      } finally {
        this.loading = false
      }
    },
    async setEnabled(enabled: boolean) {
      this.ensureOwner()
      this.saving = true
      this.error = ''
      try {
        const saved = await memoryApi.updatePreferences({
          auto_extract: enabled,
          cross_session_injection: enabled,
          history_retrieval: enabled,
          expected_revision: this.preferences.revision,
        })
        this.preferences = saved
        if (this.overview) {
          this.overview = { ...this.overview, enabled, preferences: saved }
        }
        return true
      } catch (e) {
        this.error = e instanceof Error ? e.message : '更新记忆功能开关失败。'
        return false
      } finally {
        this.saving = false
      }
    },
    async addMemory(payload: MemoryCreateRequest) {
      this.ensureOwner()
      this.saving = true
      this.error = ''
      try {
        const created = await memoryApi.create(payload)
        await this.loadSummary()
        return created
      } catch (e) {
        this.error = e instanceof Error ? e.message : '添加记忆失败。'
        return null
      } finally {
        this.saving = false
      }
    },
  },
})
