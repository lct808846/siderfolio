import { createApp } from 'vue'
import { createPinia } from 'pinia'
import { createRouter, createWebHistory } from 'vue-router'
import App from './views/App.vue'
import './style.css'

const router = createRouter({ history: createWebHistory(), routes: [{ path: '/', component: { render: () => null } }, { path: '/conversations/:id', component: { render: () => null } }, { path: '/projects/:projectId?', component: { render: () => null } }, { path: '/projects/:projectId/workflows/:runId?', component: { render: () => null } }] })
createApp(App).use(createPinia()).use(router).mount('#app')
