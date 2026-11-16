import { defineConfig } from '@playwright/test'

// Explicit QA stack only; never point these destructive synthetic-data tests at
// the daily personal instance on 5173.
export default defineConfig({
  testDir: './tests/identity-browser', workers: 1, fullyParallel: false, timeout: 60000,
  use: { baseURL: 'http://127.0.0.1:5174', screenshot: 'only-on-failure', trace: 'retain-on-failure' },
  reporter: [['list'], ['json', { outputFile: process.env.ASTROAGENT_BROWSER_REPORT || 'test-results/identity-report.json' }]],
  projects: [{ name: 'chromium', use: { browserName: 'chromium' } }, ...(process.platform === 'win32' ? [{ name: 'edge', use: { browserName: 'chromium' as const, channel: 'msedge' } }] : [])],
})
