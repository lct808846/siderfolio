import { createApp } from 'vue'
import { createPinia } from 'pinia'
import { createRouter, createWebHistory } from 'vue-router'
import App from './views/App.vue'
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

const router = createRouter({ history: createWebHistory(), routes: [{ path: '/settings', component: { render: () => null } }, { path: '/projects/:projectId/rag', component: { render: () => null } }, { path: '/', component: { render: () => null } }, { path: '/conversations/:id', component: { render: () => null } }, { path: '/projects/:projectId?', component: { render: () => null } }, { path: '/projects/:projectId/overview', component: { render: () => null } }, { path: '/projects/:projectId/knowledge/:documentId?', component: { render: () => null } }, { path: '/projects/:projectId/workflows/:runId?', component: { render: () => null } }] })
createApp(App).use(createPinia()).use(router).mount('#app')
