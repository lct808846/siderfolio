<script setup lang="ts">
import { computed, onMounted } from 'vue'
import SettingsSelect from './SettingsSelect.vue'
import {
  THEME_PRESETS,
  useAppearance,
  type CornerStyle,
  type DarkThemeId,
  type DensityMode,
  type FontScale,
  type LightThemeId,
  type ReadingFont,
  type ReadingWidth,
} from '../stores/appearance'

const appearance = useAppearance()

const lightThemes = computed(() => THEME_PRESETS.filter(item => item.mode === 'light'))
const darkThemes = computed(() => THEME_PRESETS.filter(item => item.mode === 'dark'))
const lightThemeOptions = computed(() =>
  lightThemes.value.map(item => ({
    value: item.id as LightThemeId,
    label: item.name,
    description: item.badge,
    swatch: [item.swatch.topbar, item.swatch.accent] as const,
  })),
)
const darkThemeOptions = computed(() =>
  darkThemes.value.map(item => ({
    value: item.id as DarkThemeId,
    label: item.name,
    description: item.badge,
    swatch: [item.swatch.topbar, item.swatch.accent] as const,
  })),
)

const densityOptions: readonly { value: DensityMode; label: string }[] = [
  { value: 'compact', label: '紧凑' },
  { value: 'comfortable', label: '标准' },
  { value: 'spacious', label: '舒展' },
]

const fontScaleOptions: readonly { value: FontScale; label: string }[] = [
  { value: 'sm', label: '小 92%' },
  { value: 'md', label: '标准' },
  { value: 'lg', label: '大 108%' },
  { value: 'xl', label: '特大 115%' },
]

const cornerOptions: readonly { value: CornerStyle; label: string }[] = [
  { value: 'sharp', label: '利落' },
  { value: 'rounded', label: '圆润' },
  { value: 'soft', label: '柔和' },
]

const readingWidthOptions: readonly { value: ReadingWidth; label: string }[] = [
  { value: 'narrow', label: '聚焦 760px' },
  { value: 'standard', label: '标准 880px' },
  { value: 'wide', label: '宽幅 1120px' },
]

const readingFontOptions: readonly { value: ReadingFont; label: string }[] = [
  { value: 'sans', label: '现代无衬线' },
  { value: 'serif', label: '学术衬线' },
]

onMounted(() => {
  appearance.syncSystem()
})
</script>

<template>
  <div class="appearance-settings">
    <section class="settings-group appearance-preview-card" aria-label="当前外观实时预览">
      <div class="appearance-preview-head">
        <div class="appearance-preview-title">
          <div class="ui-pill-list">
            <span class="ui-pill ui-pill-accent">实时预览</span>
            <span class="ui-pill" :class="appearance.resolvedPreset.mode === 'dark' ? 'ui-pill-compute' : 'ui-pill-gaia'">
              <span class="ui-dot" aria-hidden="true" />
              {{ appearance.resolvedPreset.name }} · {{ appearance.resolvedPreset.mode === 'dark' ? '暗夜模式' : '日间模式' }}
            </span>
          </div>
          <p class="small muted">以下卡片直接呈现当前配色、字号、圆角、阅读字体与界面密度的实际效果。</p>
        </div>
        <button
          type="button"
          :disabled="appearance.isDefault"
          @click="appearance.resetDefaults()"
        >
          恢复默认外观
        </button>
      </div>

      <div class="appearance-live-stage">
        <div class="appearance-live-topbar" aria-hidden="true">
          <span class="appearance-live-brand"><i />AstroAgent</span>
          <div class="appearance-live-nav">
            <span class="is-active">查询工作台</span>
            <span>知识库</span>
            <span>科研流程</span>
          </div>
        </div>
        <div class="appearance-live-body">
          <div class="ui-pill-list">
            <span class="ui-pill ui-pill-gaia">Gaia DR3 · ϖ = 7.36 mas</span>
            <span class="ui-pill ui-pill-ads">ADS · 2024 A&amp;A</span>
            <span class="ui-pill ui-pill-simbad">SIMBAD · M45</span>
            <span class="ui-pill ui-pill-compute">REBOUND · IAS15</span>
          </div>
          <p class="appearance-live-reading">
            昴星团（M45）核心区域 Gaia DR3 视差中位数约 7.36 mas，自行分布高度集中；可结合视差信噪比与 RUWE 筛选候选源，并在隔离环境中绘制观测色—星等图。
          </p>
          <div class="appearance-live-footer">
            <div class="appearance-live-metric">
              <span>样本能量精度 ΔE/|E₀|</span>
              <b>1.42 × 10⁻¹⁴</b>
            </div>
            <div class="appearance-live-actions">
              <span class="appearance-demo-btn-secondary">次要操作</span>
              <span class="appearance-demo-btn-primary">主要操作</span>
            </div>
          </div>
        </div>
      </div>
    </section>

    <section class="settings-group" aria-labelledby="appearance-themes-heading">
      <div class="settings-group-head">
        <div>
          <h3 id="appearance-themes-heading">主题配色</h3>
          <p class="small muted">精选 6 套天文台科研主题，覆盖日间阅读、低蓝光护眼与夜间圆顶暗适应场景。</p>
        </div>
        <span class="ui-pill ui-pill-neutral">共 {{ THEME_PRESETS.length }} 套</span>
      </div>

      <div class="appearance-theme-grid" role="radiogroup" aria-label="选择主题配色">
        <button
          v-for="preset in THEME_PRESETS"
          :key="preset.id"
          type="button"
          class="theme-card"
          role="radio"
          :aria-checked="appearance.resolvedTheme === preset.id"
          :class="{ 'is-active': appearance.resolvedTheme === preset.id }"
          @click="appearance.setTheme(preset.id)"
        >
          <div
            class="theme-mockup"
            aria-hidden="true"
            :style="{ background: preset.swatch.bg, borderColor: preset.swatch.line }"
          >
            <div class="theme-mockup-topbar" :style="{ background: preset.swatch.topbar }">
              <span class="theme-mockup-dot" :style="{ background: preset.swatch.accent }" />
              <span class="theme-mockup-bar" />
              <span class="theme-mockup-pill" />
            </div>
            <div class="theme-mockup-body">
              <div class="theme-mockup-sidebar" :style="{ background: preset.swatch.sidebar, borderColor: preset.swatch.line }">
                <span :style="{ background: preset.swatch.accent, opacity: 0.32 }" />
                <span :style="{ background: preset.swatch.ink, opacity: 0.14 }" />
                <span :style="{ background: preset.swatch.ink, opacity: 0.1 }" />
              </div>
              <div class="theme-mockup-main" :style="{ background: preset.swatch.card, borderColor: preset.swatch.line }">
                <div class="theme-mockup-pills">
                  <span :style="{ background: preset.swatch.accent }" />
                  <span :style="{ background: preset.swatch.ink, opacity: 0.16 }" />
                </div>
                <div class="theme-mockup-lines">
                  <span :style="{ background: preset.swatch.ink, opacity: 0.24 }" />
                  <span :style="{ background: preset.swatch.ink, opacity: 0.13 }" />
                </div>
              </div>
            </div>
          </div>

          <div class="theme-card-meta">
            <div class="theme-card-top">
              <strong>{{ preset.name }}</strong>
              <span class="ui-pill" :class="preset.mode === 'dark' ? 'ui-pill-compute' : 'ui-pill-neutral'">{{ preset.badge }}</span>
            </div>
            <small>{{ preset.description }}</small>
          </div>
          <span v-if="appearance.resolvedTheme === preset.id" class="theme-check-badge" aria-hidden="true">
            <svg viewBox="0 0 24 24"><path d="m5 12.5 4.5 4.5L19 7.5" /></svg>
          </span>
        </button>
      </div>

      <label class="settings-row settings-switch-row appearance-system-row">
        <div>
          <h4>跟随操作系统自动切换明暗</h4>
          <p>
            根据系统浅色 / 深色模式自动切换下方配对的日间与暗夜主题（当前系统偏好：{{ appearance.systemDark ? '深色' : '浅色' }}）。
          </p>
        </div>
        <input
          class="settings-switch"
          type="checkbox"
          role="switch"
          :checked="appearance.followSystem"
          @change="appearance.setFollowSystem(($event.target as HTMLInputElement).checked)"
        />
      </label>

      <div v-if="appearance.followSystem" class="appearance-system-pair">
        <div class="appearance-pair-field">
          <span class="appearance-pair-label">
            <svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="4" /><path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M6.34 17.66l-1.41 1.41M19.07 4.93l-1.41 1.41" /></svg>
            日间自动使用
          </span>
          <SettingsSelect
            :model-value="appearance.lightTheme"
            label="日间自动使用的主题"
            :options="lightThemeOptions"
            @update:model-value="appearance.setLightTheme($event)"
          />
        </div>
        <div class="appearance-pair-field">
          <span class="appearance-pair-label">
            <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8Z" /></svg>
            夜间自动使用
          </span>
          <SettingsSelect
            :model-value="appearance.darkTheme"
            label="夜间自动使用的主题"
            :options="darkThemeOptions"
            @update:model-value="appearance.setDarkTheme($event)"
          />
        </div>
      </div>
    </section>

    <section class="settings-group" aria-labelledby="appearance-layout-heading">
      <h3 id="appearance-layout-heading">版面密度与阅读排版</h3>

      <div class="settings-row appearance-control-row">
        <div>
          <h4>界面密度</h4>
          <p>紧凑模式适合查看高密度 Gaia 星表与粒子表；舒展模式增加呼吸留白。</p>
        </div>
        <div class="ui-segmented" role="group" aria-label="界面密度">
          <button
            v-for="opt in densityOptions"
            :key="opt.value"
            type="button"
            :aria-pressed="appearance.density === opt.value"
            @click="appearance.update('density', opt.value)"
          >
            {{ opt.label }}
          </button>
        </div>
      </div>

      <div class="settings-row appearance-control-row">
        <div>
          <h4>阅读字号缩放</h4>
          <p>等比调整全局文字与公式阅读字号，兼顾小屏笔记本与 4K 显示器。</p>
        </div>
        <div class="ui-segmented" role="group" aria-label="阅读字号缩放">
          <button
            v-for="opt in fontScaleOptions"
            :key="opt.value"
            type="button"
            :aria-pressed="appearance.fontScale === opt.value"
            @click="appearance.update('fontScale', opt.value)"
          >
            {{ opt.label }}
          </button>
        </div>
      </div>

      <div class="settings-row appearance-control-row">
        <div>
          <h4>边角风格</h4>
          <p>调整面板、卡片、输入框与按钮的圆角气质。</p>
        </div>
        <div class="ui-segmented" role="group" aria-label="边角风格">
          <button
            v-for="opt in cornerOptions"
            :key="opt.value"
            type="button"
            :aria-pressed="appearance.cornerStyle === opt.value"
            @click="appearance.update('cornerStyle', opt.value)"
          >
            {{ opt.label }}
          </button>
        </div>
      </div>

      <div class="settings-row appearance-control-row">
        <div>
          <h4>对话与正文阅读列宽</h4>
          <p>宽幅模式便于阅读包含宽表格、长公式和脚本的模型回答。</p>
        </div>
        <div class="ui-segmented" role="group" aria-label="正文阅读列宽">
          <button
            v-for="opt in readingWidthOptions"
            :key="opt.value"
            type="button"
            :aria-pressed="appearance.readingWidth === opt.value"
            @click="appearance.update('readingWidth', opt.value)"
          >
            {{ opt.label }}
          </button>
        </div>
      </div>

      <div class="settings-row appearance-control-row">
        <div>
          <h4>长文阅读字体</h4>
          <p>使用本机已安装字体，在现代无衬线与传统学术衬线间切换，不请求外部字体服务。</p>
        </div>
        <div class="ui-segmented" role="group" aria-label="长文阅读字体">
          <button
            v-for="opt in readingFontOptions"
            :key="opt.value"
            type="button"
            :aria-pressed="appearance.readingFont === opt.value"
            @click="appearance.update('readingFont', opt.value)"
          >
            {{ opt.label }}
          </button>
        </div>
      </div>
    </section>

    <section class="settings-group" aria-labelledby="appearance-surface-heading">
      <h3 id="appearance-surface-heading">视觉质感与动效</h3>

      <label class="settings-row settings-switch-row">
        <div>
          <h4>柔和背景氛围</h4>
          <p>工作区外层画布呈现轻盈柔和的多点径向色彩过渡；关闭后切换为纯净单色底。</p>
        </div>
        <input
          class="settings-switch"
          type="checkbox"
          role="switch"
          :checked="appearance.ambientBg"
          @change="appearance.update('ambientBg', ($event.target as HTMLInputElement).checked)"
        />
      </label>

      <label class="settings-row settings-switch-row">
        <div>
          <h4>侧栏与弹窗毛玻璃效果</h4>
          <p>开启半透明背景模糊提升空间层次；若希望更低 GPU 负载或更锐利底色可关闭。</p>
        </div>
        <input
          class="settings-switch"
          type="checkbox"
          role="switch"
          :checked="appearance.glassBlur"
          @change="appearance.update('glassBlur', ($event.target as HTMLInputElement).checked)"
        />
      </label>

      <label class="settings-row settings-switch-row">
        <div>
          <h4>减少界面动效</h4>
          <p>关闭卡片微抬升、淡入与光泽过渡动画，同时始终尊重系统级减弱动态设置。</p>
        </div>
        <input
          class="settings-switch"
          type="checkbox"
          role="switch"
          :checked="appearance.reducedMotion"
          @change="appearance.update('reducedMotion', ($event.target as HTMLInputElement).checked)"
        />
      </label>

      <p class="settings-footnote">外观偏好仅保存在当前浏览器本机存储中，即刻生效，不会上传或影响任何科研数据。</p>
    </section>
  </div>
</template>

<style scoped>
.appearance-settings {
  display: grid;
  gap: 0;
}

.appearance-preview-card {
  display: grid;
  gap: 16px;
}

.appearance-preview-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}

.appearance-preview-title {
  display: grid;
  gap: 6px;
  min-width: 0;
}

.appearance-preview-title p {
  margin: 0;
}

.appearance-live-stage {
  border: 1px solid var(--line);
  border-radius: var(--radius-surface);
  background: var(--paper);
  overflow: hidden;
  box-shadow: var(--shadow-card);
}

.appearance-live-topbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 9px 14px;
  background: var(--topbar-bg);
  color: var(--topbar-ink);
  font-size: 12px;
}

.appearance-live-brand {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  font-weight: 650;
  letter-spacing: -0.01em;
}

.appearance-live-brand i {
  width: 10px;
  height: 10px;
  border-radius: 3px;
  background: var(--topbar-mark-ink);
  display: inline-block;
}

.appearance-live-nav {
  display: inline-flex;
  gap: 4px;
}

.appearance-live-nav span {
  padding: 3px 9px;
  border-radius: var(--radius-pill);
  font-size: 11px;
  color: var(--topbar-muted);
}

.appearance-live-nav span.is-active {
  background: var(--topbar-pill-active);
  color: #fff;
}

.appearance-live-body {
  display: grid;
  gap: 12px;
  padding: 16px 18px;
}

.appearance-live-reading {
  margin: 0;
  color: var(--ink);
  font-family: var(--reading-font, var(--font-ui));
  font-size: calc(13.5px * var(--font-scale, 1));
  line-height: 1.8;
}

.appearance-live-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  padding-top: 10px;
  border-top: 1px solid var(--line);
}

.appearance-live-metric {
  display: grid;
  gap: 2px;
}

.appearance-live-metric span {
  font-size: 11px;
  color: var(--muted);
}

.appearance-live-metric b {
  font-size: 14px;
  font-variant-numeric: tabular-nums;
  color: var(--accent);
}

.appearance-live-actions {
  display: inline-flex;
  align-items: center;
  gap: 8px;
}

.appearance-demo-btn-secondary,
.appearance-demo-btn-primary {
  display: inline-flex;
  align-items: center;
  padding: 5px 12px;
  border-radius: var(--radius-control);
  font-size: 12px;
  font-weight: 550;
}

.appearance-demo-btn-secondary {
  border: 1px solid var(--line-strong);
  background: var(--button-bg);
  color: var(--ink);
}

.appearance-demo-btn-primary {
  border: 1px solid var(--button-primary-border);
  background: var(--button-primary-bg);
  color: #fff;
}

.appearance-theme-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
  margin: 14px 0 6px;
}

.theme-card {
  position: relative;
  display: grid;
  gap: 10px;
  align-content: start;
  padding: 11px;
  border: 1.5px solid var(--line);
  border-radius: var(--radius-card);
  background: var(--paper);
  box-shadow: var(--shadow-card);
  color: var(--ink);
  text-align: left;
  cursor: pointer;
  transition: transform var(--duration-fast) var(--ease-out), border-color var(--duration-fast) var(--ease-out), box-shadow var(--duration-fast) var(--ease-out);
}

.theme-card:hover {
  transform: translateY(-2px);
  border-color: var(--accent);
  box-shadow: var(--shadow-card-hover);
  background: var(--paper);
}

.theme-card.is-active {
  border-color: var(--accent);
  box-shadow: 0 0 0 2px color-mix(in srgb, var(--accent) 24%, transparent), var(--shadow-card);
}

.theme-mockup {
  display: grid;
  gap: 5px;
  padding: 6px;
  border: 1px solid transparent;
  border-radius: 9px;
  height: 82px;
  box-sizing: border-box;
}

.theme-mockup-topbar {
  display: flex;
  align-items: center;
  gap: 5px;
  height: 15px;
  padding: 0 6px;
  border-radius: 5px;
}

.theme-mockup-dot {
  width: 6px;
  height: 6px;
  border-radius: 2px;
  flex: none;
}

.theme-mockup-bar {
  width: 28px;
  height: 4px;
  border-radius: 99px;
  background: rgb(255 255 255 / 55%);
}

.theme-mockup-pill {
  margin-left: auto;
  width: 20px;
  height: 6px;
  border-radius: 99px;
  background: rgb(255 255 255 / 26%);
}

.theme-mockup-body {
  display: grid;
  grid-template-columns: 30% minmax(0, 1fr);
  gap: 5px;
  min-height: 0;
  flex: 1;
}

.theme-mockup-sidebar,
.theme-mockup-main {
  border: 1px solid transparent;
  border-radius: 6px;
  padding: 5px;
  display: grid;
  align-content: start;
  gap: 4px;
}

.theme-mockup-sidebar span {
  height: 5px;
  border-radius: 99px;
}

.theme-mockup-pills {
  display: flex;
  gap: 4px;
}

.theme-mockup-pills span {
  width: 26px;
  height: 6px;
  border-radius: 99px;
}

.theme-mockup-lines {
  display: grid;
  gap: 4px;
  margin-top: 3px;
}

.theme-mockup-lines span {
  height: 5px;
  border-radius: 99px;
}

.theme-mockup-lines span:last-child {
  width: 72%;
}

.theme-card-meta {
  display: grid;
  gap: 4px;
}

.theme-card-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
  flex-wrap: wrap;
}

.theme-card-top strong {
  font-size: 13.5px;
  font-weight: 600;
  color: var(--ink);
}

.theme-card-meta small {
  color: var(--muted);
  font-size: 11.5px;
  line-height: 1.5;
}

.theme-check-badge {
  position: absolute;
  top: 15px;
  right: 15px;
  display: grid;
  place-items: center;
  width: 22px;
  height: 22px;
  border-radius: 999px;
  background: var(--accent);
  color: #fff;
  box-shadow: 0 2px 8px rgb(0 0 0 / 24%);
}

.theme-check-badge svg {
  width: 13px;
  height: 13px;
  fill: none;
  stroke: currentColor;
  stroke-width: 2.5;
  stroke-linecap: round;
  stroke-linejoin: round;
}

.appearance-system-row {
  margin-top: 14px;
}

.appearance-system-pair {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px;
  padding: 14px 16px;
  margin-top: 10px;
  border: 1px solid var(--line);
  border-radius: var(--radius-card);
  background: var(--surface-subtle);
}

.appearance-pair-field {
  display: grid;
  gap: 7px;
  min-width: 0;
}

.appearance-pair-label {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: var(--muted);
  font-weight: 550;
}

.appearance-pair-label svg {
  width: 14px;
  height: 14px;
  flex: none;
  fill: none;
  stroke: var(--accent);
  stroke-width: 1.8;
  stroke-linecap: round;
  stroke-linejoin: round;
}

.appearance-control-row {
  flex-wrap: wrap;
  gap: 12px 20px;
}

.appearance-control-row > .ui-segmented {
  max-width: 100%;
  flex: 0 1 auto;
}

@media (max-width: 920px) {
  .appearance-theme-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 640px) {
  .appearance-theme-grid,
  .appearance-system-pair {
    grid-template-columns: minmax(0, 1fr);
  }
}
</style>
