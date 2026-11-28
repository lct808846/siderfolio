import { test, expect } from '@playwright/test'
import { mkdirSync } from 'node:fs'
import path from 'node:path'
import http from 'node:http'

test('production build: conversation, follow-up, complete table, preview, download and restore', async ({ page, browserName, browser }, testInfo) => {
  testInfo.annotations.push({ type: 'browser_version', description: browser.version() })
  const errors: string[] = []; page.on('pageerror', e => errors.push(e.message))
  await page.goto('/')
  await expect(page.getByRole('heading', { name: '天文数据、星表分析与数值实验工作台' })).toBeVisible()
  if (process.env.ASTROAGENT_RECORD_DIR) { mkdirSync(process.env.ASTROAGENT_RECORD_DIR, { recursive: true }); await page.screenshot({ path: path.join(process.env.ASTROAGENT_RECORD_DIR, `${testInfo.project.name}-empty.png`) }) }
  await page.getByRole('button', { name: '新建会话', exact: true }).click()
  const question = page.getByRole('textbox', { name: '天文问题' })
  await question.fill('合成验收：查询Gaia圆锥100个位置候选源。')
  await page.getByRole('button', { name: '发送问题', exact: true }).click()
  await expect(page.getByText('合成验收结果已返回。', { exact: false })).toBeVisible()
  await expect(page.getByRole('button', { name: '核查与导出查询结果' })).toBeVisible()
  await page.getByRole('button', { name: '核查与导出查询结果' }).click()
  await page.locator('summary').filter({ hasText: /查看完整交付表格\s*100 行/ }).click()
  await expect(page.getByRole('cell', { name: '5853498713190525696', exact: true })).toBeVisible()
  await page.getByRole('button', { name: '下一页' }).click()
  await expect(page.getByRole('cell', { name: '5853498713190525716', exact: true })).toBeVisible()
  await page.getByRole('button', { name: /^导出数据包/ }).click()
  const exportDialog = page.getByRole('dialog', { name: '导出数据包与快速预览图' })
  await exportDialog.getByLabel('自行散点图', { exact: true }).check()
  await exportDialog.getByLabel('视差直方图', { exact: true }).check()
  await exportDialog.getByLabel('观测颜色—星等图', { exact: true }).check()
  await exportDialog.getByRole('button', { name: '生成数据包与预览图' }).click()
  await exportDialog.getByRole('tab', { name: /自行散点图\.png/ }).click()
  const plot = exportDialog.getByRole('img', { name: '自行散点图.png', exact: true })
  await expect(plot).toBeVisible()
  if (process.env.ASTROAGENT_RECORD_DIR) { await plot.scrollIntoViewIfNeeded(); await page.screenshot({ path: path.join(process.env.ASTROAGENT_RECORD_DIR, `${testInfo.project.name}-preview.png`) }) }
  const downloadPromise = page.waitForEvent('download')
  await exportDialog.getByRole('button', { name: '下载 ZIP' }).click()
  const file = await downloadPromise; expect(file.suggestedFilename()).toBe('astroagent-results.zip')
  if (process.env.ASTROAGENT_RECORD_DIR) await file.saveAs(path.join(process.env.ASTROAGENT_RECORD_DIR, `${testInfo.project.name}-download.zip`))
  await exportDialog.getByText('关闭', { exact: true }).click()
  await question.fill('只保留 RUWE≤1.4，其他条件不变，重新查询。')
  await page.getByRole('button', { name: '发送问题', exact: true }).click()
  const filteredTable = page.locator('summary').filter({ hasText: /查看完整交付表格\s*51 行/ })
  await expect(filteredTable).toBeVisible()
  const url = page.url(); await page.reload(); await expect(filteredTable).toBeVisible()
  expect(page.url()).toBe(url)
  await page.getByRole('button', { name: '核查与导出查询结果' }).first().click()
  await expect(page.getByLabel('结果与文件').getByText('历史', { exact: true })).toBeVisible()
  if (process.env.ASTROAGENT_RECORD_DIR) await page.screenshot({ path: path.join(process.env.ASTROAGENT_RECORD_DIR, `${testInfo.project.name}-full.png`) })
  expect(errors).toEqual([]); expect(browserName).toBe('chromium')
})

test('IME composition, explicit examples, plain text literature, rename and delete', async ({ page }) => {
  await page.goto('/'); await page.getByRole('button', { name: '新建会话', exact: true }).click()
  await page.getByRole('button', { name: /^ADS 文献 / }).click()
  const input = page.getByRole('textbox', { name: '天文问题' })
  await input.dispatchEvent('compositionstart'); await input.dispatchEvent('keydown', { key: 'Enter', isComposing: true })
  await expect(page.getByText('第 1 轮', { exact: true })).toHaveCount(0)
  await input.dispatchEvent('compositionend')
  await page.getByRole('button', { name: '发送问题', exact: true }).click()
  await expect(page.getByText('合成验收结果已返回。', { exact: false })).toBeVisible()
  await expect(page.getByRole('heading', { name: '<img src=x onerror="window.syntheticXss=true"> 合成论文标题' })).toBeVisible()
  expect(await page.evaluate(() => 'syntheticXss' in window)).toBe(false)
  await page.locator('.conversation-row.selected').getByRole('button', { name: /会话操作：/ }).click()
  await page.getByRole('menuitem', { name: '重命名' }).click(); await page.getByRole('textbox', { name: '会话名称' }).fill('我的文献核查')
  await page.getByRole('button', { name: '保存名称', exact: true }).click()
  await expect(page.getByRole('heading', { name: '我的文献核查' })).toBeVisible()
  await page.locator('.conversation-row.selected').getByRole('button', { name: /会话操作：/ }).click()
  await page.getByRole('menuitem', { name: '删除会话' }).click(); await expect(page.getByRole('dialog')).toBeVisible()
  await page.getByRole('button', { name: '确认删除' }).click(); await expect(page).toHaveURL(new URL('/', page.url()).href)
})

test('narrow viewport has usable panel navigation and no page overflow', async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 390, height: 844 }); await page.goto('/')
  await page.getByRole('button', { name: '展开会话列表' }).click(); await page.getByRole('button', { name: '新建会话', exact: true }).click()
  const input = page.getByRole('textbox', { name: '天文问题' }); await input.fill('合成Gaia圆锥查询')
  await page.getByRole('button', { name: '发送问题', exact: true }).click()
  await expect(page.getByText('合成验收结果已返回。', { exact: false })).toBeVisible()
  await page.getByRole('button', { name: '核查与导出查询结果' }).click()
  await expect(page.getByRole('heading', { name: 'Gaia DR3 查询数据' })).toBeVisible()
  await page.getByRole('button', { name: '收起结果面板' }).click()
  await expect(page.getByText('合成验收结果已返回。', { exact: false })).toBeVisible()
  const width = await page.evaluate(() => ({ body: document.body.scrollWidth, viewport: innerWidth })); expect(width.body).toBeLessThanOrEqual(width.viewport)
  if (process.env.ASTROAGENT_RECORD_DIR) await page.screenshot({ path: path.join(process.env.ASTROAGENT_RECORD_DIR, `${testInfo.project.name}-mobile.png`) })
})

test('backend connection error is explicit', async ({ page }) => {
  await page.route('**/api/v1/conversations', route => route.abort())
  await page.goto('/'); await expect(page.getByRole('alert')).toContainText('连接已断开')
})

test('a rejected send clears the composer and retries the original question on explicit action', async ({ page }) => {
  await page.goto('/'); await page.getByRole('button', { name: '新建会话', exact: true }).click()
  const sent: string[] = []
  const originalQuestion = '合成Gaia查询，验证重试'
  const nextDraft = '尚未发送的新草稿'
  await page.route(/\/api\/v1\/conversations\/[^/]+\/turns(?:\/stream)?$/, async route => {
    sent.push(route.request().postDataJSON().message)
    if (sent.length === 1) return route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ error: { code: 'conversation_service_busy', message: '已有两个请求正在处理', retryable: true } }) })
    return route.continue()
  })
  const question = page.getByRole('textbox', { name: '天文问题' })
  await question.fill(originalQuestion)
  await page.getByRole('button', { name: '发送问题', exact: true }).click()
  await expect(page.getByRole('alert')).toContainText('已有两个请求正在处理')
  await expect(question).toHaveValue('')
  expect(sent).toEqual([originalQuestion])
  await question.fill(nextDraft)
  await page.getByRole('button', { name: '重新发送', exact: true }).click()
  await expect(page.getByText('合成验收结果已返回。', { exact: false })).toBeVisible()
  expect(sent).toEqual([originalQuestion, originalQuestion])
  await expect(question).toHaveValue(nextDraft)
})

test('a late initial list does not clear a send error after navigation', async ({ page, request }) => {
  const created = await (await request.post('/api/v1/conversations', { data: { title: '延迟列表测试' } })).json()
  let release!: () => void, started!: () => void
  const gate = new Promise<void>(resolve => { release = resolve })
  const waiting = new Promise<void>(resolve => { started = resolve })
  await page.route('**/api/v1/conversations', async route => {
    if (route.request().method() === 'GET') { started(); await gate }
    await route.continue()
  }, { times: 1 })
  try {
    await page.goto(`/conversations/${created.id}`); await waiting
    await expect(page).toHaveURL(/conversations\/[0-9a-f-]+/)
    await page.route(/\/api\/v1\/conversations\/[^/]+\/turns(?:\/stream)?$/, route => route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ error: { code: 'conversation_service_busy', message: '已有两个请求正在处理', retryable: true } }) }))
    await page.getByRole('textbox', { name: '天文问题' }).fill('测试异步加载')
    await page.getByRole('button', { name: '发送问题', exact: true }).click()
    await expect(page.getByRole('alert')).toContainText('已有两个请求正在处理')
    const initialList = page.waitForResponse(response => response.request().method() === 'GET' && response.url().endsWith('/api/v1/conversations'))
    release()
    await initialList
    await expect(page.getByRole('alert')).toContainText('已有两个请求正在处理')
  } finally { release() }
})

test('local static proxy keeps its API target and never returns SPA HTML for API errors', async ({ request, baseURL }) => {
  const missing = await request.get('/api/v1/nonexistent')
  expect(missing.status()).toBe(404); expect(missing.headers()['content-type']).toContain('application/json')
  const response = await new Promise<{status:number;body:string}>(resolve => {
    http.get({ host: '127.0.0.1', port: Number(new URL(baseURL!).port), path: '//example.invalid/api/v1/conversations' }, reply => {
      let body = ''; reply.on('data', chunk => body += chunk); reply.on('end', () => resolve({ status: reply.statusCode || 0, body }))
    })
  })
  expect(response.status).toBe(200); expect(Array.isArray(JSON.parse(response.body))).toBe(true)
})
