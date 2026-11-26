import { defineStore } from 'pinia'
import { skillsApi } from '../api/skills'
import { identityUser } from '../identity-state'
import type {
  ExternalToolPreview,
  SkillMetadataSummary,
  SkillPreferences,
  ToolCatalogItem,
} from '../types'

let loadedOwner = ''

export const useSkills = defineStore('skills', {
  state: () => ({
    skills: [] as SkillMetadataSummary[],
    preferences: { auto_match: true, disabled_skill_ids: [] as string[] } as SkillPreferences,
    approvedExternalTools: [] as ExternalToolPreview[],
    tools: [] as ToolCatalogItem[],
    toolManifestSha256: '',
    loaded: false,
    loading: false,
    saving: false,
    error: '',
  }),
  getters: {
    enabledSkills: state => state.skills.filter(item => item.enabled !== false),
    byId: state => (id?: string | null) => state.skills.find(item => item.id === id) || null,
  },
  actions: {
    ensureOwner() {
      const owner = identityUser.value?.id || ''
      if (owner !== loadedOwner) {
        this.skills = []
        this.preferences = { auto_match: true, disabled_skill_ids: [] }
        this.approvedExternalTools = []
        this.tools = []
        this.toolManifestSha256 = ''
        this.loaded = false
        this.error = ''
        loadedOwner = owner
      }
    },
    async load(force = false) {
      this.ensureOwner()
      if (this.loading || (this.loaded && !force)) return
      this.loading = true
      this.error = ''
      try {
        const data = await skillsApi.catalog()
        this.skills = data.skills || []
        this.preferences = data.preferences || { auto_match: true, disabled_skill_ids: [] }
        this.approvedExternalTools = data.approved_external_tools || []
        this.loaded = true
      } catch (e) {
        this.error = e instanceof Error ? e.message : '技能列表读取失败。'
      } finally {
        this.loading = false
      }
    },
    async loadTools() {
      this.ensureOwner()
      try {
        const data = await skillsApi.tools()
        this.tools = data.tools || []
        this.toolManifestSha256 = data.tool_manifest_sha256 || ''
      } catch (e) {
        this.error = e instanceof Error ? e.message : '工具目录读取失败。'
      }
    },
    async updatePreferences(next: SkillPreferences) {
      this.ensureOwner()
      this.saving = true
      this.error = ''
      try {
        const data = await skillsApi.updatePreferences(next)
        this.skills = data.skills || []
        this.preferences = data.preferences || next
        this.approvedExternalTools = data.approved_external_tools || []
        this.loaded = true
        return true
      } catch (e) {
        this.error = e instanceof Error ? e.message : '技能偏好保存失败。'
        return false
      } finally {
        this.saving = false
      }
    },
  },
})
