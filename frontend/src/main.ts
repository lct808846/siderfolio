import { createApp } from 'vue'
import { createPinia } from 'pinia'
import { createRouter, createWebHistory, type RouteLocationNormalized } from 'vue-router'
import IdentityRoot from './views/IdentityRoot.vue'
import { identityGuard } from './identity-state'
import { initAppearance } from './stores/appearance'
import './style.css'
import './observation-log.css'
import './glass-surfaces.css'
import './typography.css'
import './conversation-sidebar.css'
import './conversation-layout.css'
import './markdown-answer.css'
import './user-message.css'
import './interaction-surfaces.css'
import './model-selector.css'
import './attachments.css'
import './plot-workspace.css'
import './research-flow.css'
import './workspace-theme.css'
import './workbench-plot.css'
import './identity.css'

function plottingRedirect(to: Pick<RouteLocationNormalized, 'query' | 'params'>) {
  const conversation = typeof to.query.conversation === 'string' ? to.query.conversation : ''
  const project = typeof to.params.projectId === 'string' ? to.params.projectId : typeof to.query.project === 'string' ? to.query.project : ''
  return { path: conversation ? `/conversations/${encodeURIComponent(conversation)}` : '/', query: {
    tool: 'plot',
    ...(project ? { project } : {}),
    ...(typeof to.query.turn === 'string' ? { plot_turn: to.query.turn } : {}),
    ...(typeof to.query.dataset === 'string' ? { plot_dataset: to.query.dataset } : {}),
    ...(typeof to.query.snapshot === 'string' ? { plot_snapshot: to.query.snapshot } : {}),
    ...(typeof to.query.query === 'string' ? { plot_query: to.query.query } : {}),
  } }
}

function projectRedirect(to: Pick<RouteLocationNormalized, 'query' | 'params'>) {
  const project = typeof to.params.projectId === 'string' ? to.params.projectId : ''
  if (!project) return { path: '/' }
  return { path: '/', query: { ...to.query, project } }
}

function computeRedirect(to: Pick<RouteLocationNormalized, 'query' | 'params'>) {
  const project = typeof to.params.projectId === 'string' ? to.params.projectId : typeof to.query.project === 'string' ? to.query.project : ''
  const taskId = typeof to.params.taskId === 'string' ? to.params.taskId : ''
  return {
    path: '/',
    query: {
      result: 'compute',
      ...(project ? { project } : {}),
      ...(taskId ? { compute_task: taskId } : {}),
    },
  }
}

const router = createRouter({ history: createWebHistory(), routes: [{ path: '/local-assistant', redirect: '/' }, { path: '/projects/:projectId/plotting', redirect: plottingRedirect }, { path: '/settings', component: { render: () => null } }, { path: '/profile', component: { render: () => null } }, { path: '/literature/:itemId?', component: { render: () => null } }, { path: '/knowledge/:documentId?', component: { render: () => null } }, { path: '/rag', component: { render: () => null } }, { path: '/workflows/:runId?', component: { render: () => null } }, { path: '/compute/:taskId?', redirect: computeRedirect }, { path: '/projects/:projectId/rag', component: { render: () => null } }, { path: '/', component: { render: () => null } }, { path: '/conversations/:id', component: { render: () => null } }, { path: '/projects', redirect: '/' }, { path: '/projects/:projectId', redirect: projectRedirect }, { path: '/projects/:projectId/overview', component: { render: () => null } }, { path: '/projects/:projectId/knowledge/:documentId?', component: { render: () => null } }, { path: '/projects/:projectId/workflows/:runId?', component: { render: () => null } }, { path: '/projects/:projectId/compute/:taskId?', redirect: computeRedirect }] })
router.addRoute({ path: '/plotting', redirect: plottingRedirect })
router.addRoute({ path: '/account', redirect: { path: '/settings', query: { section: 'account' } } })
for (const path of ['/login', '/register', '/activate', '/resend', '/forgot-password', '/reset-password', '/admin', '/feedback']) router.addRoute({ path, component: { render: () => null } })
initAppearance()
router.beforeEach(identityGuard)
createApp(IdentityRoot).use(createPinia()).use(router).mount('#app')
