import { defineStore } from 'pinia'

export type LightThemeId = 'emerald' | 'celestial' | 'parchment' | 'nebula'
export type DarkThemeId = 'obsidian' | 'dome'
export type ThemeId = LightThemeId | DarkThemeId
export type DensityMode = 'compact' | 'comfortable' | 'spacious'
export type FontScale = 'sm' | 'md' | 'lg' | 'xl'
export type CornerStyle = 'sharp' | 'rounded' | 'soft'
export type ReadingWidth = 'narrow' | 'standard' | 'wide'
export type ReadingFont = 'sans' | 'serif'

export interface ThemePreset {
  id: ThemeId
  name: string
  englishName: string
  mode: 'light' | 'dark'
  badge: string
  description: string
  swatch: {
    topbar: string
    bg: string
    sidebar: string
    card: string
    accent: string
    ink: string
    line: string
  }
}

export interface AppearancePreferences {
  theme: ThemeId
  followSystem: boolean
  lightTheme: LightThemeId
  darkTheme: DarkThemeId
  density: DensityMode
  fontScale: FontScale
  cornerStyle: CornerStyle
  readingWidth: ReadingWidth
  readingFont: ReadingFont
  ambientBg: boolean
  astroBackdrop: boolean
  astroMotion: boolean
  glassBlur: boolean
  surfaceShadows: boolean
  reducedMotion: boolean
}

export const THEME_PRESETS: readonly ThemePreset[] = [
  {
    id: 'emerald',
    name: '天文台翠绿',
    englishName: 'Observatory Emerald',
    mode: 'light',
    badge: '默认 · 日间',
    description: '深翠导航配温润浅雾白阅读面，克制沉静，适合全天候科研工作。',
    swatch: {
      topbar: 'linear-gradient(112deg, #1f443b, #293f46)',
      bg: '#eef3f0',
      sidebar: '#f5f9f6',
      card: '#ffffff',
      accent: '#2f6853',
      ink: '#1f3530',
      line: '#d5e1d9',
    },
  },
  {
    id: 'celestial',
    name: '靛蓝星海',
    englishName: 'Celestial Slate',
    mode: 'light',
    badge: '星表 · 清爽',
    description: '深海蓝顶栏与冰川白面板，蓝宝石主色，贴近现代天文数据终端质感。',
    swatch: {
      topbar: 'linear-gradient(112deg, #182f4c, #244369)',
      bg: '#edf2f7',
      sidebar: '#f3f7fb',
      card: '#ffffff',
      accent: '#25568d',
      ink: '#1b2d42',
      line: '#d1dde9',
    },
  },
  {
    id: 'parchment',
    name: '暖纸典籍',
    englishName: 'Warm Parchment',
    mode: 'light',
    badge: '低蓝光 · 护眼',
    description: '暖棕顶栏搭配象牙纸张色调与陶土褐强调，降低长时间研读论文疲劳。',
    swatch: {
      topbar: 'linear-gradient(112deg, #3f3427, #514231)',
      bg: '#f2ede3',
      sidebar: '#f7f3ea',
      card: '#fdfbf6',
      accent: '#8c5126',
      ink: '#322920',
      line: '#e1d7c6',
    },
  },
  {
    id: 'nebula',
    name: '星云暮紫',
    englishName: 'Nebula Dusk',
    mode: 'light',
    badge: '星云 · 雅致',
    description: '暮色靛紫顶栏配柔和微紫白面板，现代典雅，适合图表展示与汇报。',
    swatch: {
      topbar: 'linear-gradient(112deg, #2b2244, #3d2f60)',
      bg: '#f0eef6',
      sidebar: '#f6f4fb',
      card: '#ffffff',
      accent: '#5b4394',
      ink: '#28213d',
      line: '#dad4e8',
    },
  },
  {
    id: 'obsidian',
    name: '暗夜深空',
    englishName: 'Deep Space Dark',
    mode: 'dark',
    badge: '深空 · 暗夜',
    description: '深空石板暗色工作台配星光翠绿高对比强调，大幅降低夜间屏幕眩光。',
    swatch: {
      topbar: 'linear-gradient(112deg, #0d1c1d, #13252a)',
      bg: '#0c1216',
      sidebar: '#111a20',
      card: '#18232b',
      accent: '#4bb88c',
      ink: '#e4eef1',
      line: '#283842',
    },
  },
  {
    id: 'dome',
    name: '观测圆顶红光',
    englishName: 'Observatory Red Night',
    mode: 'dark',
    badge: '暗适应 · 夜班',
    description: '致敬天文台圆顶夜班红光照明，暖炭暗底配柔和暗红主色，保护暗视觉。',
    swatch: {
      topbar: 'linear-gradient(112deg, #291316, #39191d)',
      bg: '#110a0b',
      sidebar: '#191012',
      card: '#221618',
      accent: '#d86255',
      ink: '#f0dada',
      line: '#3d282b',
    },
  },
] as const

export const APPEARANCE_STORAGE_KEY = 'astroagent.appearance.v1'
const STORAGE_KEY = APPEARANCE_STORAGE_KEY
const LIGHT_THEMES: readonly LightThemeId[] = ['emerald', 'celestial', 'parchment', 'nebula']
const DARK_THEMES: readonly DarkThemeId[] = ['obsidian', 'dome']

export const DEFAULT_APPEARANCE: AppearancePreferences = {
  theme: 'emerald',
  followSystem: false,
  lightTheme: 'emerald',
  darkTheme: 'obsidian',
  density: 'comfortable',
  fontScale: 'md',
  cornerStyle: 'rounded',
  readingWidth: 'standard',
  readingFont: 'sans',
  ambientBg: true,
  astroBackdrop: true,
  astroMotion: true,
  glassBlur: true,
  surfaceShadows: true,
  reducedMotion: false,
}

function isThemeId(value: unknown): value is ThemeId {
  return typeof value === 'string' && THEME_PRESETS.some(item => item.id === value)
}
function isLightTheme(value: unknown): value is LightThemeId {
  return typeof value === 'string' && (LIGHT_THEMES as readonly string[]).includes(value)
}
function isDarkTheme(value: unknown): value is DarkThemeId {
  return typeof value === 'string' && (DARK_THEMES as readonly string[]).includes(value)
}

export function loadSavedAppearance(): AppearancePreferences {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return { ...DEFAULT_APPEARANCE }
    const parsed = JSON.parse(raw) as Partial<AppearancePreferences>
    return {
      theme: isThemeId(parsed.theme) ? parsed.theme : DEFAULT_APPEARANCE.theme,
      followSystem: typeof parsed.followSystem === 'boolean' ? parsed.followSystem : DEFAULT_APPEARANCE.followSystem,
      lightTheme: isLightTheme(parsed.lightTheme) ? parsed.lightTheme : DEFAULT_APPEARANCE.lightTheme,
      darkTheme: isDarkTheme(parsed.darkTheme) ? parsed.darkTheme : DEFAULT_APPEARANCE.darkTheme,
      density: parsed.density === 'compact' || parsed.density === 'comfortable' || parsed.density === 'spacious'
        ? parsed.density : DEFAULT_APPEARANCE.density,
      fontScale: parsed.fontScale === 'sm' || parsed.fontScale === 'md' || parsed.fontScale === 'lg' || parsed.fontScale === 'xl'
        ? parsed.fontScale : DEFAULT_APPEARANCE.fontScale,
      cornerStyle: parsed.cornerStyle === 'sharp' || parsed.cornerStyle === 'rounded' || parsed.cornerStyle === 'soft'
        ? parsed.cornerStyle : DEFAULT_APPEARANCE.cornerStyle,
      readingWidth: parsed.readingWidth === 'narrow' || parsed.readingWidth === 'standard' || parsed.readingWidth === 'wide'
        ? parsed.readingWidth : DEFAULT_APPEARANCE.readingWidth,
      readingFont: parsed.readingFont === 'sans' || parsed.readingFont === 'serif'
        ? parsed.readingFont : DEFAULT_APPEARANCE.readingFont,
      ambientBg: typeof parsed.ambientBg === 'boolean' ? parsed.ambientBg : DEFAULT_APPEARANCE.ambientBg,
      astroBackdrop: typeof parsed.astroBackdrop === 'boolean' ? parsed.astroBackdrop : DEFAULT_APPEARANCE.astroBackdrop,
      astroMotion: typeof parsed.astroMotion === 'boolean' ? parsed.astroMotion : DEFAULT_APPEARANCE.astroMotion,
      glassBlur: typeof parsed.glassBlur === 'boolean' ? parsed.glassBlur : DEFAULT_APPEARANCE.glassBlur,
      surfaceShadows: typeof parsed.surfaceShadows === 'boolean' ? parsed.surfaceShadows : DEFAULT_APPEARANCE.surfaceShadows,
      reducedMotion: typeof parsed.reducedMotion === 'boolean' ? parsed.reducedMotion : DEFAULT_APPEARANCE.reducedMotion,
    }
  } catch {
    return { ...DEFAULT_APPEARANCE }
  }
}

let mediaQuery: MediaQueryList | null = null
let systemDark = false

function readSystemDark(): boolean {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return false
  mediaQuery ||= window.matchMedia('(prefers-color-scheme: dark)')
  return mediaQuery.matches
}

export function resolveTheme(prefs: AppearancePreferences, preferDark = readSystemDark()): ThemeId {
  if (prefs.followSystem) return preferDark ? prefs.darkTheme : prefs.lightTheme
  return prefs.theme
}

export function applyAppearanceToDom(prefs: AppearancePreferences, preferDark = readSystemDark()) {
  if (typeof document === 'undefined') return
  const root = document.documentElement
  const activeTheme = resolveTheme(prefs, preferDark)
  const meta = THEME_PRESETS.find(item => item.id === activeTheme) ?? THEME_PRESETS[0]!
  root.dataset.theme = activeTheme
  root.dataset.themeMode = meta.mode
  root.dataset.density = prefs.density
  root.dataset.fontScale = prefs.fontScale
  root.dataset.radius = prefs.cornerStyle
  root.dataset.readingWidth = prefs.readingWidth
  root.dataset.readingFont = prefs.readingFont
  root.dataset.ambient = prefs.ambientBg ? 'on' : 'off'
  root.dataset.astroBackdrop = prefs.astroBackdrop ? 'on' : 'off'
  root.dataset.astroMotion = prefs.astroBackdrop && prefs.astroMotion && !prefs.reducedMotion ? 'on' : 'off'
  root.dataset.glass = prefs.glassBlur ? 'on' : 'off'
  root.dataset.shadows = prefs.surfaceShadows ? 'on' : 'off'
  root.dataset.motion = prefs.reducedMotion ? 'reduced' : 'normal'
}

function persistAppearance(prefs: AppearancePreferences) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(prefs))
  } catch { /* Ignore storage quota or private mode restrictions. */ }
}

let initialized = false

export function initAppearance() {
  if (initialized || typeof window === 'undefined') return
  initialized = true
  systemDark = readSystemDark()
  applyAppearanceToDom(loadSavedAppearance(), systemDark)
  mediaQuery?.addEventListener('change', event => {
    systemDark = event.matches
    applyAppearanceToDom(loadSavedAppearance(), systemDark)
  })
}

export const useAppearance = defineStore('appearance', {
  state: (): AppearancePreferences & { systemDark: boolean } => ({
    ...loadSavedAppearance(),
    systemDark: readSystemDark(),
  }),
  getters: {
    resolvedTheme(): ThemeId {
      return resolveTheme(this, this.systemDark)
    },
    resolvedPreset(): ThemePreset {
      const id = this.resolvedTheme
      return THEME_PRESETS.find(item => item.id === id) ?? THEME_PRESETS[0]!
    },
    isDefault(): boolean {
      return (Object.keys(DEFAULT_APPEARANCE) as (keyof AppearancePreferences)[])
        .every(key => this[key] === DEFAULT_APPEARANCE[key])
    },
    isPerformanceMode(): boolean {
      return !this.astroBackdrop && !this.ambientBg && !this.glassBlur && !this.surfaceShadows && this.reducedMotion
    },
    activeEffectCount(): number {
      return [
        this.astroBackdrop,
        this.astroBackdrop && this.astroMotion && !this.reducedMotion,
        this.ambientBg,
        this.glassBlur,
        this.surfaceShadows,
        !this.reducedMotion,
      ].filter(Boolean).length
    },
  },
  actions: {
    syncSystem() {
      this.systemDark = readSystemDark()
      this.apply()
    },
    apply() {
      const prefs: AppearancePreferences = {
        theme: this.theme,
        followSystem: this.followSystem,
        lightTheme: this.lightTheme,
        darkTheme: this.darkTheme,
        density: this.density,
        fontScale: this.fontScale,
        cornerStyle: this.cornerStyle,
        readingWidth: this.readingWidth,
        readingFont: this.readingFont,
        ambientBg: this.ambientBg,
        astroBackdrop: this.astroBackdrop,
        astroMotion: this.astroMotion,
        glassBlur: this.glassBlur,
        surfaceShadows: this.surfaceShadows,
        reducedMotion: this.reducedMotion,
      }
      persistAppearance(prefs)
      applyAppearanceToDom(prefs, this.systemDark)
    },
    setTheme(id: ThemeId) {
      this.theme = id
      this.followSystem = false
      if (isLightTheme(id)) this.lightTheme = id
      if (isDarkTheme(id)) this.darkTheme = id
      this.apply()
    },
    setFollowSystem(enabled: boolean) {
      this.followSystem = enabled
      this.systemDark = readSystemDark()
      this.apply()
    },
    setLightTheme(id: LightThemeId) {
      this.lightTheme = id
      if (!this.followSystem && isLightTheme(this.theme)) this.theme = id
      this.apply()
    },
    setDarkTheme(id: DarkThemeId) {
      this.darkTheme = id
      if (!this.followSystem && isDarkTheme(this.theme)) this.theme = id
      this.apply()
    },
    update<K extends keyof AppearancePreferences>(key: K, value: AppearancePreferences[K]) {
      ;(this as AppearancePreferences)[key] = value
      this.apply()
    },
    setPerformanceMode(enabled: boolean) {
      if (enabled) {
        this.astroBackdrop = false
        this.astroMotion = false
        this.ambientBg = false
        this.glassBlur = false
        this.surfaceShadows = false
        this.reducedMotion = true
      } else {
        this.astroBackdrop = true
        this.astroMotion = true
        this.ambientBg = true
        this.glassBlur = true
        this.surfaceShadows = true
        this.reducedMotion = false
      }
      this.apply()
    },
    resetDefaults() {
      Object.assign(this, DEFAULT_APPEARANCE)
      this.apply()
    },
  },
})
