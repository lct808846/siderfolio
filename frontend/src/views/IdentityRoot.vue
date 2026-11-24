<script setup lang="ts">
import { computed, defineAsyncComponent, onBeforeUnmount, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import App from './App.vue'
import InteractionHints from '../components/InteractionHints.vue'
import AstroBackdrop from '../components/AstroBackdrop.vue'
import { clearPrivateBrowserData, identityReady, identityUser, isIdentityPage } from '../identity-state'
import { useAppearance } from '../stores/appearance'
const IdentityWorkspace = defineAsyncComponent(() => import('./IdentityWorkspace.vue'))
const SettingsWorkspace = defineAsyncComponent(() => import('./SettingsWorkspace.vue'))
const AdminWorkspace = defineAsyncComponent(() => import('./AdminWorkspace.vue'))
const FeedbackWorkspace = defineAsyncComponent(() => import('./FeedbackWorkspace.vue'))
const route = useRoute()
const appearance = useAppearance()
const showAstroBackdrop = computed(() => identityReady.value && !!identityUser.value && !isIdentityPage(route.path) && appearance.astroBackdrop)
function expired() {
  identityUser.value = null
  clearPrivateBrowserData()
  window.location.replace('/login?next=' + encodeURIComponent(route.fullPath))
}
function changed(event: StorageEvent) {
  if (event.key === 'astroagent.identity.owner' && event.newValue !== identityUser.value?.id) { identityReady.value = false; identityUser.value = null; window.location.replace('/login') }
}
onMounted(() => { window.addEventListener('astroagent:session-expired', expired); window.addEventListener('storage', changed) })
onBeforeUnmount(() => { window.removeEventListener('astroagent:session-expired', expired); window.removeEventListener('storage', changed) })
</script>
<template>
  <AstroBackdrop v-if="showAstroBackdrop" />
  <main v-if="!identityReady" class="identity-loading" role="status">正在验证登录状态…</main>
  <IdentityWorkspace v-else-if="!identityUser || isIdentityPage(route.path)" />
  <template v-else-if="route.path === '/settings' || route.path === '/account'"><InteractionHints /><SettingsWorkspace /></template>
  <AdminWorkspace v-else-if="route.path.startsWith('/admin') && identityUser.admin" />
  <FeedbackWorkspace v-else-if="route.path === '/feedback'" />
  <App v-else :key="identityUser.id" />
</template>
