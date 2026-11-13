import { defineConfig } from '@playwright/test'

export default defineConfig({
  testDir: './tests/browser', workers: 1, timeout: 60000,
  use: { baseURL: 'http://127.0.0.1:5173', viewport: { width: 1440, height: 900 }, screenshot: 'only-on-failure', trace: 'retain-on-failure' },
  reporter: [['list'], ['json', { outputFile: process.env.ASTROAGENT_BROWSER_REPORT || `../docs/test-records/v1.5.0/container-live/${new Date().toISOString().replaceAll(':', '').replaceAll('-', '')}/report.json` }]],
  projects: [{ name: 'chromium', use: { browserName: 'chromium' } }, { name: 'edge', use: { browserName: 'chromium', channel: 'msedge' } }],
})
