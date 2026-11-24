<script setup lang="ts">
import FeedbackPanel from '../components/FeedbackPanel.vue'
import WorkspaceHeader from '../components/WorkspaceHeader.vue'
import WorkspacePaneHeader from '../components/WorkspacePaneHeader.vue'
</script>

<template>
  <main class="workspace-panes primary-workspace feedback-workspace">
    <WorkspaceHeader title="帮助与反馈" />
    <section class="settings-main feedback-main" aria-labelledby="feedback-heading">
      <div class="feedback-content">
        <div id="feedback-heading">
          <WorkspacePaneHeader title="帮助与反馈">
            <template #actions>
              <a href="mailto:support@siderfolio.com">support@siderfolio.com</a>
            </template>
          </WorkspacePaneHeader>
        </div>
        <FeedbackPanel />
      </div>
    </section>
  </main>
</template>

<style scoped>
.feedback-workspace { grid-template-rows: auto minmax(0, 1fr); }
.feedback-main { grid-column: 1 / -1; flex: 1; min-width: 0; min-height: 0; overflow: auto; }
.feedback-content { max-width: 1160px; margin-inline: auto; padding: var(--pane-padding); }
.feedback-content a { color: var(--accent); overflow-wrap: anywhere; }
</style>
