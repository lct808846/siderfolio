import { defineConfig } from '@playwright/test'
import { mkdtempSync } from 'node:fs'
import { tmpdir } from 'node:os'
import path from 'node:path'

const data = process.env.ASTROAGENT_BROWSER_DATA || mkdtempSync(path.join(tmpdir(), 'astroagent-browser-'))
const python = process.env.ASTROAGENT_PYTHON || 'python'
export default defineConfig({
  testDir: './tests/browser', workers: 1, fullyParallel: false, timeout: 60000,
  use: { baseURL: 'http://127.0.0.1:5173', viewport: { width: 1440, height: 900 }, screenshot: 'only-on-failure', trace: 'retain-on-failure' },
  reporter: [['list'], ['json', { outputFile: process.env.ASTROAGENT_BROWSER_REPORT || 'test-results/report.json' }]],
  projects: [{ name: 'chromium', use: { browserName: 'chromium' } }, ...(process.platform === 'win32' ? [{ name: 'edge', use: { browserName: 'chromium' as const, channel: 'msedge' } }] : [])],
  webServer: [
    { command: `"${python}" -m uvicorn scripts.fixture_server:app --host 127.0.0.1 --port 8000`, cwd: '..', url: 'http://127.0.0.1:8000/health', reuseExistingServer: false, timeout: 45000, env: { ASTROAGENT_DATA_DIR: data, DEEPSEEK_API_KEY: '', ADS_API_TOKEN: '', ASTROAGENT_ALLOWED_ORIGINS: '["http://127.0.0.1:5173","http://127.0.0.1:8000"]' } },
    { command: 'node server.mjs', url: 'http://127.0.0.1:5173', reuseExistingServer: false, timeout: 20000 },
  ],
})
