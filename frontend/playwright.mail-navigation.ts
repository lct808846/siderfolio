import { defineConfig } from '@playwright/test'

// Real cross-site clicks between localhost and 127.0.0.1, with disposable HTTP
// fixtures. This never opens a personal activation token or the daily database.
export default defineConfig({
  testDir: './tests/mail-navigation', workers: 1, fullyParallel: false, timeout: 30000,
  use: { baseURL: 'http://127.0.0.1:5275', screenshot: 'only-on-failure' },
  reporter: [['list'], ['json', { outputFile: process.env.ASTROAGENT_BROWSER_REPORT || 'test-results/mail-navigation.json' }]],
  projects: [{ name: 'chromium', use: { browserName: 'chromium' } }, ...(process.platform === 'win32' ? [{ name: 'edge', use: { browserName: 'chromium' as const, channel: 'msedge' } }] : [])],
})
