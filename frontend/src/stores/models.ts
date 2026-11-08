import { defineStore } from 'pinia'
import { api } from '../api'
import type { ChatModelOption } from '../types'

const preferenceKey = 'astroagent.models.preferences.v1'
function preferences(): Map<string, string> {
  try {
    const saved: unknown = JSON.parse(localStorage.getItem(preferenceKey) || '[]')
    if (!Array.isArray(saved)) return new Map()
    return new Map(saved.filter((item): item is [string, string] => Array.isArray(item) && item.length === 2
      && typeof item[0] === 'string' && item[0].length <= 100 && typeof item[1] === 'string' && item[1].length <= 128).slice(-200))
  } catch { return new Map() }
}

export const useModels = defineStore('models', {
  state: () => ({ options: [] as ChatModelOption[], defaultModel: '', configured: false, loading: false, loaded: false, error: '', preferences: preferences() }),
  getters: {
    modelFor: state => (scope: string, previous?: string | null): string => {
      const preferred = state.preferences.get(scope) || previous
      if (preferred && state.options.some(model => model.id === preferred)) return preferred
      return state.defaultModel
    },
    labelFor: state => (id: string): string => id === 'qwen3.8-max' ? id : state.options.find(model => model.id === id)?.label || id,
  },
  actions: {
    async load(force = false) {
      if (this.loading || (this.loaded && !force)) return
      this.loading = true; this.error = ''
      try {
        const catalog = await api.models()
        this.options = catalog.models.map(model => model.id === 'qwen3.8-max' ? { ...model, label: model.id } : model)
        this.defaultModel = catalog.default_model
        this.configured = catalog.configured; this.loaded = true
      } catch (error) { this.error = error instanceof Error ? error.message : '模型列表读取失败，请稍后刷新。' }
      finally { this.loading = false }
    },
    select(scope: string, id: string) {
      if (!this.options.some(model => model.id === id)) return
      this.preferences.delete(scope); this.preferences.set(scope, id)
      this.persist()
    },
    forget(scopes: string[]) {
      for (const scope of scopes) this.preferences.delete(scope)
      this.persist()
    },
    persist() {
      while (this.preferences.size > 200) {
        const first = this.preferences.keys().next().value
        if (first === undefined) break
        this.preferences.delete(first)
      }
      try { localStorage.setItem(preferenceKey, JSON.stringify([...this.preferences])) }
      catch { /* Choices remain usable in memory when browser storage is unavailable. */ }
    },
  },
})
