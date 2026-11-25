<script setup lang="ts">
import FeedbackPanel from '../components/FeedbackPanel.vue'
import WorkspaceHeader from '../components/WorkspaceHeader.vue'
</script>

<template>
  <main class="workspace-panes primary-workspace feedback-workspace">
    <WorkspaceHeader title="帮助与反馈" />
    <section class="settings-main feedback-shell" aria-labelledby="feedback-heading">
      <header class="workspace-pane-header feedback-pane-header">
        <div class="feedback-header-title-group">
          <span class="feedback-header-icon" aria-hidden="true">
            <svg viewBox="0 0 24 24">
              <path d="M21 12a8.5 8.5 0 0 1-8.5 8.5c-1.45 0-2.82-.36-4.02-1L3 21l1.55-5.1A8.46 8.46 0 0 1 4 12a8.5 8.5 0 1 1 17 0Z" />
              <path d="M9 10.75h6" />
              <path d="M9 14h4" />
            </svg>
          </span>
          <div class="feedback-header-copy">
            <h1 id="feedback-heading">帮助与反馈</h1>
            <p class="feedback-header-subtitle">提交异常报告、功能建议或科研计算问题，并实时查看处理进度与回复。</p>
          </div>
        </div>
        <div class="feedback-header-actions">
          <a class="feedback-mail-pill" href="mailto:support@siderfolio.com">
            <svg viewBox="0 0 24 24" aria-hidden="true">
              <rect x="3" y="5" width="18" height="14" rx="2.5" />
              <path d="m4 7 8 6 8-6" />
            </svg>
            <span>support@siderfolio.com</span>
          </a>
        </div>
      </header>

      <div class="feedback-scroll">
        <div class="feedback-reading">
          <FeedbackPanel />
        </div>
      </div>
    </section>
  </main>
</template>

<style scoped>
.feedback-workspace {
  grid-template-rows: auto minmax(0, 1fr);
}

.feedback-shell {
  grid-column: 1 / -1;
  display: flex;
  flex-direction: column;
  flex: 1;
  min-width: 0;
  min-height: 0;
  overflow: hidden;
}

.feedback-pane-header {
  flex-wrap: wrap;
  gap: 12px 18px;
  padding: 14px 24px;
}

.feedback-header-title-group {
  display: flex;
  align-items: center;
  gap: 13px;
  min-width: 0;
  flex: 1 1 280px;
}

.feedback-header-icon {
  display: grid;
  place-items: center;
  width: 40px;
  height: 40px;
  flex: 0 0 40px;
  border-radius: var(--radius-control);
  border: 1px solid color-mix(in srgb, var(--accent) 26%, var(--line));
  background: var(--accent-soft);
  color: var(--accent);
  box-shadow: var(--specular-top);
}

.feedback-header-icon svg {
  width: 20px;
  height: 20px;
  fill: none;
  stroke: currentColor;
  stroke-width: 1.75;
  stroke-linecap: round;
  stroke-linejoin: round;
}

.feedback-header-copy {
  display: grid;
  gap: 3px;
  min-width: 0;
}

.feedback-pane-header h1 {
  font-size: 17px;
  font-weight: 620;
  letter-spacing: -0.015em;
  color: var(--ink);
}

.feedback-header-subtitle {
  margin: 0;
  color: var(--muted);
  font-size: 12.5px;
  line-height: 1.5;
}

.feedback-header-actions {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  min-width: 0;
}

.feedback-mail-pill {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  min-height: 34px;
  max-width: 100%;
  padding: 5px 13px;
  border-radius: var(--radius-pill);
  border: 1px solid color-mix(in srgb, var(--accent) 24%, var(--line-strong));
  background: color-mix(in srgb, var(--accent) 7%, var(--surface-card));
  color: var(--accent);
  font-size: 12.5px;
  font-weight: 550;
  text-decoration: none;
  overflow-wrap: anywhere;
  transition:
    background-color var(--duration-fast) var(--ease-out),
    border-color var(--duration-fast) var(--ease-out),
    transform var(--duration-fast) var(--ease-out),
    box-shadow var(--duration-fast) var(--ease-out);
}

.feedback-mail-pill:hover {
  text-decoration: none;
  color: var(--accent-hover);
  border-color: color-mix(in srgb, var(--accent) 44%, var(--line-strong));
  background: var(--accent-soft);
  box-shadow: 0 4px 12px -4px color-mix(in srgb, var(--accent) 22%, transparent);
  transform: translateY(-1px);
}

.feedback-mail-pill:active {
  transform: scale(0.98);
}

.feedback-mail-pill svg {
  width: 15px;
  height: 15px;
  flex: none;
  fill: none;
  stroke: currentColor;
  stroke-width: 1.75;
  stroke-linecap: round;
  stroke-linejoin: round;
}

.feedback-scroll {
  flex: 1;
  min-width: 0;
  min-height: 0;
  overflow: auto;
  overscroll-behavior: contain;
  -webkit-overflow-scrolling: touch;
  padding: clamp(18px, 2.5vw, 28px) clamp(16px, 3vw, 34px) 36px;
}

.feedback-reading {
  max-width: 1180px;
  margin-inline: auto;
  min-width: 0;
}

@media (max-width: 680px) {
  .feedback-pane-header {
    padding: 12px 16px;
    gap: 10px;
  }

  .feedback-header-icon {
    width: 34px;
    height: 34px;
    flex-basis: 34px;
  }

  .feedback-header-icon svg {
    width: 17px;
    height: 17px;
  }

  .feedback-header-subtitle {
    font-size: 12px;
  }

  .feedback-header-actions {
    width: 100%;
  }

  .feedback-mail-pill {
    font-size: 12px;
    min-height: 32px;
    padding: 4px 11px;
  }

  .feedback-scroll {
    padding: 14px 12px 28px;
  }
}
</style>
