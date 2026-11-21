import { defineConfig } from '@playwright/test'

// This suite creates synthetic projects and tasks on the dedicated test ingress.
if (process.env.ASTROAGENT_COMPUTE_QA !== '1') {
  throw new Error('Start the isolated compute QA stack on port 5287 before running this suite.')
}

export default defineConfig({
  testDir: './tests/compute-browser',
  workers: 1,
  timeout: 90000,
  use: { baseURL: 'http://127.0.0.1:5287', viewport: { width: 1440, height: 900 }, screenshot: 'only-on-failure' },
  reporter: [['list'], ['json', { outputFile: process.env.ASTROAGENT_BROWSER_REPORT || 'test-results/compute-report.json' }]],
  projects: [{ name: 'chromium', use: { browserName: 'chromium' } }, ...(process.platform === 'win32' ? [{ name: 'edge', use: { browserName: 'chromium' as const, channel: 'msedge' } }] : [])],
})
