import { test, expect } from '@playwright/test'
import { mkdirSync } from 'node:fs'
import path from 'node:path'
import http from 'node:http'

test('production build: conversation, follow-up, complete table, preview, download and restore', async ({ page, browserName, browser }, testInfo) => {
  testInfo.annotations.push({ type: 'browser_version', description: browser.version() })
  const errors: string[] = []; page.on('pageerror', e => errors.push(e.message))
  await page.goto('/')
  await expect(page.getByRole('heading', { name: '观测与文献，从这里开始' })).toBeVisible()
  if (process.env.ASTROAGENT_RECORD_DIR) { mkdirSync(process.env.ASTROAGENT_RECORD_DIR, { recursive: true }); await page.screenshot({ path: path.join(process.env.ASTROAGENT_RECORD_DIR, `${testInfo.project.name}-empty.png`) }) }
  await page.getByRole('button', { name: '新建会话' }).click()
  await expect(page).toHaveURL(/conversations\/[0-9a-f-]+/)
  const question = page.getByRole('textbox', { name: '天文问题' })
  await question.fill('合成验收：查询Gaia圆锥100个位置候选源。')
  await page.getByRole('button', { name: '发送', exact: true }).click()
  await expect(page.getByText('合成验收结果已返回。', { exact: false })).toBeVisible()
  await expect(page.getByRole('button', { name: '核查本轮结果与导出' })).toBeVisible()
  await page.getByRole('button', { name: '核查本轮结果与导出' }).click()
  await page.getByText('查看完整交付表格（100 行）').click()
  await expect(page.getByRole('cell', { name: '5853498713190525696', exact: true })).toBeVisible()
  await page.getByRole('button', { name: '下一页' }).click()
  await expect(page.getByRole('cell', { name: '5853498713190525716', exact: true })).toBeVisible()
  await page.getByLabel('自行散点图', { exact: true }).check()
  await page.getByLabel('视差直方图', { exact: true }).check()
  await page.getByLabel('观测颜色—星等图', { exact: true }).check()
  await page.getByRole('button', { name: '生成预览与数据包' }).click()
  await expect(page.getByRole('img', { name: '自行散点图', exact: true })).toBeVisible()
  if (process.env.ASTROAGENT_RECORD_DIR) { await page.getByRole('img', { name: '自行散点图', exact: true }).scrollIntoViewIfNeeded(); await page.screenshot({ path: path.join(process.env.ASTROAGENT_RECORD_DIR, `${testInfo.project.name}-preview.png`) }) }
  const downloadPromise = page.waitForEvent('download')
  await page.getByRole('button', { name: '下载 ZIP' }).click()
  const file = await downloadPromise; expect(file.suggestedFilename()).toBe('astroagent-results.zip')
  if (process.env.ASTROAGENT_RECORD_DIR) await file.saveAs(path.join(process.env.ASTROAGENT_RECORD_DIR, `${testInfo.project.name}-download.zip`))
  await question.fill('只保留 RUWE≤1.4，其他条件不变，重新查询。')
  await page.getByRole('button', { name: '发送', exact: true }).click()
  await expect(page.getByText('使用了 1 轮历史上下文')).toBeVisible()
  const url = page.url(); await page.reload(); await expect(page.getByText('使用了 1 轮历史上下文')).toBeVisible()
  expect(page.url()).toBe(url)
  await page.getByRole('button', { name: '核查本轮结果与导出' }).first().click()
  await expect(page.getByLabel('结果核查').getByText('历史结果', { exact: true })).toBeVisible()
  if (process.env.ASTROAGENT_RECORD_DIR) await page.screenshot({ path: path.join(process.env.ASTROAGENT_RECORD_DIR, `${testInfo.project.name}-full.png`) })
  expect(errors).toEqual([]); expect(browserName).toBe('chromium')
})

test('IME composition, explicit examples, plain text literature, rename and delete', async ({ page }) => {
  await page.goto('/'); await page.getByRole('button', { name: '新建会话' }).click()
  await page.getByRole('button', { name: 'ADS 文献检索' }).click()
  const input = page.getByRole('textbox', { name: '天文问题' })
  await input.dispatchEvent('compositionstart'); await input.dispatchEvent('keydown', { key: 'Enter', isComposing: true })
  await expect(page.getByText('第 1 轮', { exact: true })).toHaveCount(0)
  await input.dispatchEvent('compositionend')
  await page.getByRole('button', { name: '发送', exact: true }).click()
  await expect(page.getByText('合成验收结果已返回。', { exact: false })).toBeVisible()
  await page.getByRole('tab', { name: /ADS/ }).click()
  await expect(page.getByRole('heading', { name: '<img src=x onerror="window.syntheticXss=true"> 合成论文标题' })).toBeVisible()
  expect(await page.evaluate(() => 'syntheticXss' in window)).toBe(false)
  await page.getByRole('button', { name: '重命名会话' }).click(); await page.getByRole('textbox', { name: '会话名称' }).fill('我的文献核查')
  await page.getByRole('button', { name: '保存', exact: true }).click()
  await expect(page.getByRole('heading', { name: '我的文献核查' })).toBeVisible()
  await page.getByRole('button', { name: '删除会话' }).click(); await expect(page.getByRole('dialog')).toBeVisible()
  await page.getByRole('button', { name: '确认删除' }).click(); await expect(page).toHaveURL('http://127.0.0.1:5173/')
})

test('narrow viewport has usable panel navigation and no page overflow', async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 390, height: 844 }); await page.goto('/')
  await page.getByRole('button', { name: '会话', exact: true }).click(); await page.getByRole('button', { name: '新建会话' }).click()
  const input = page.getByRole('textbox', { name: '天文问题' }); await input.fill('合成Gaia圆锥查询')
  await page.getByRole('button', { name: '发送', exact: true }).click()
  await expect(page.getByText('合成验收结果已返回。', { exact: false })).toBeVisible()
  await page.getByRole('button', { name: '核查本轮结果与导出' }).click(); await expect(page.getByRole('heading', { name: '第 1 轮结果' })).toBeVisible()
  const width = await page.evaluate(() => ({ body: document.body.scrollWidth, viewport: innerWidth })); expect(width.body).toBeLessThanOrEqual(width.viewport)
  if (process.env.ASTROAGENT_RECORD_DIR) await page.screenshot({ path: path.join(process.env.ASTROAGENT_RECORD_DIR, `${testInfo.project.name}-mobile.png`) })
})

test('backend connection error is explicit', async ({ page }) => {
  await page.route('**/api/v1/conversations', route => route.abort())
  await page.goto('/'); await expect(page.getByRole('alert')).toContainText('连接已断开')
})

test('a rejected send preserves the question and only retries on explicit action', async ({ page }) => {
  await page.goto('/'); await page.getByRole('button', { name: '新建会话' }).click()
  let calls = 0
  await page.route('**/api/v1/conversations/*/turns', async route => {
    calls++
    if (calls === 1) return route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ error: { code: 'conversation_service_busy', message: '已有两轮正在处理', retryable: true } }) })
    return route.continue()
  })
  const question = page.getByRole('textbox', { name: '天文问题' })
  await question.fill('合成Gaia查询，验证重试')
  await page.getByRole('button', { name: '发送', exact: true }).click()
  await expect(page.getByRole('alert')).toContainText('已有两轮正在处理')
  await expect(question).toHaveValue('合成Gaia查询，验证重试'); expect(calls).toBe(1)
  await page.getByRole('button', { name: '重新执行（新一轮）' }).click()
  await expect(page.getByText('合成验收结果已返回。', { exact: false })).toBeVisible(); expect(calls).toBe(2)
})

test('a late initial list does not clear a send error after navigation', async ({ page }) => {
  let release!: () => void, started!: () => void
  const gate = new Promise<void>(resolve => { release = resolve })
  const waiting = new Promise<void>(resolve => { started = resolve })
  await page.route('**/api/v1/conversations', async route => {
    if (route.request().method() === 'GET') { started(); await gate }
    await route.continue()
  }, { times: 1 })
  try {
    await page.goto('/'); await waiting
    await page.getByRole('button', { name: '新建会话' }).click()
    await expect(page).toHaveURL(/conversations\/[0-9a-f-]+/)
    await page.route('**/api/v1/conversations/*/turns', route => route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ error: { code: 'conversation_service_busy', message: '已有两轮正在处理', retryable: true } }) }))
    await page.getByRole('textbox', { name: '天文问题' }).fill('测试异步加载')
    await page.getByRole('button', { name: '发送', exact: true }).click()
    await expect(page.getByRole('alert')).toContainText('已有两轮正在处理')
    const initialList = page.waitForResponse(response => response.request().method() === 'GET' && response.url().endsWith('/api/v1/conversations'))
    release()
    await initialList
    await expect(page.getByRole('alert')).toContainText('已有两轮正在处理')
  } finally { release() }
})

test('local static proxy keeps its API target and never returns SPA HTML for API errors', async ({ request }) => {
  const missing = await request.get('/api/v1/nonexistent')
  expect(missing.status()).toBe(404); expect(missing.headers()['content-type']).toContain('application/json')
  const response = await new Promise<{status:number;body:string}>(resolve => {
    http.get({ host: '127.0.0.1', port: 5173, path: '//example.invalid/api/v1/conversations' }, reply => {
      let body = ''; reply.on('data', chunk => body += chunk); reply.on('end', () => resolve({ status: reply.statusCode || 0, body }))
    })
  })
  expect(response.status).toBe(200); expect(Array.isArray(JSON.parse(response.body))).toBe(true)
})
