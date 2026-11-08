# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: workbench.spec.ts >> narrow viewport has usable panel navigation and no page overflow
- Location: tests\browser\workbench.spec.ts:65:1

# Error details

```
Error: expect(locator).toBeVisible() failed

Locator:  getByText('合成验收结果已返回。')
Expected: visible
Received: hidden
Timeout:  5000ms

Call log:
  - Expect "toBeVisible" getByText('合成验收结果已返回。') with timeout 5000ms
  - waiting for getByText('合成验收结果已返回。')
    11 × locator resolved to <p>合成验收结果已返回。请在右侧核查完整测量、单位和查询条件；这些不是实际观测。</p>
       - unexpected value "hidden"

```

```yaml
- banner:
  - button "AstroAgent：新建会话": AstroAgent
  - navigation "全局导航":
    - link "查询工作台":
      - /url: /
    - link "项目归档":
      - /url: /projects
    - link "本机设置":
      - /url: /settings
- complementary "结果核查":
  - text: RESULTS / 数据核查
  - heading "第 1 轮结果" [level=2]
  - button "收起结果面板": ×
  - paragraph:
    - text: 接收时间（UTC）
    - time: 2026-11-08T08:38:49.823116+00:00
  - tablist "数据源":
    - tab "Gaia DR3 1" [selected]
    - tab "ADS 0"
    - tab "SIMBAD 0"
  - text: 本轮 Gaia 查询
  - combobox "本轮 Gaia 查询":
    - option "第 1 次 · success · 100 行" [selected]
  - text: 100 交付行 未知 总命中数 未截断 交付范围
  - group: 条件、单位与程序统计
  - group: 实际 ADQL
  - group: 查看完整交付表格（100 行）
  - paragraph: 合成验收数据，不是实际观测。
  - region "图表与下载":
    - heading "图表与数据包" [level=3]
    - paragraph: 基于第 1 轮完整响应。图表只描述交付样本。
    - checkbox "自行散点图"
    - text: 自行散点图
    - checkbox "视差直方图"
    - text: 视差直方图
    - checkbox "观测颜色—星等图"
    - text: 观测颜色—星等图
    - button "生成预览与数据包"
```

# Test source

```ts
  1   | import { test, expect } from '@playwright/test'
  2   | import { mkdirSync } from 'node:fs'
  3   | import path from 'node:path'
  4   | import http from 'node:http'
  5   | 
  6   | test('production build: conversation, follow-up, complete table, preview, download and restore', async ({ page, browserName, browser }, testInfo) => {
  7   |   testInfo.annotations.push({ type: 'browser_version', description: browser.version() })
  8   |   const errors: string[] = []; page.on('pageerror', e => errors.push(e.message))
  9   |   await page.goto('/')
  10  |   await expect(page.getByRole('heading', { name: '天文数据与文献检索' })).toBeVisible()
  11  |   if (process.env.ASTROAGENT_RECORD_DIR) { mkdirSync(process.env.ASTROAGENT_RECORD_DIR, { recursive: true }); await page.screenshot({ path: path.join(process.env.ASTROAGENT_RECORD_DIR, `${testInfo.project.name}-empty.png`) }) }
  12  |   await page.getByRole('button', { name: '新建会话', exact: true }).click()
  13  |   const question = page.getByRole('textbox', { name: '天文问题' })
  14  |   await question.fill('合成验收：查询Gaia圆锥100个位置候选源。')
  15  |   await page.getByRole('button', { name: '发送问题', exact: true }).click()
  16  |   await expect(page.getByText('合成验收结果已返回。', { exact: false })).toBeVisible()
  17  |   await expect(page.getByRole('button', { name: '核查本轮结果与导出' })).toBeVisible()
  18  |   await page.getByRole('button', { name: '核查本轮结果与导出' }).click()
  19  |   await page.getByText('查看完整交付表格（100 行）').click()
  20  |   await expect(page.getByRole('cell', { name: '5853498713190525696', exact: true })).toBeVisible()
  21  |   await page.getByRole('button', { name: '下一页' }).click()
  22  |   await expect(page.getByRole('cell', { name: '5853498713190525716', exact: true })).toBeVisible()
  23  |   await page.getByLabel('自行散点图', { exact: true }).check()
  24  |   await page.getByLabel('视差直方图', { exact: true }).check()
  25  |   await page.getByLabel('观测颜色—星等图', { exact: true }).check()
  26  |   await page.getByRole('button', { name: '生成预览与数据包' }).click()
  27  |   await expect(page.getByRole('img', { name: '自行散点图', exact: true })).toBeVisible()
  28  |   if (process.env.ASTROAGENT_RECORD_DIR) { await page.getByRole('img', { name: '自行散点图', exact: true }).scrollIntoViewIfNeeded(); await page.screenshot({ path: path.join(process.env.ASTROAGENT_RECORD_DIR, `${testInfo.project.name}-preview.png`) }) }
  29  |   const downloadPromise = page.waitForEvent('download')
  30  |   await page.getByRole('button', { name: '下载 ZIP' }).click()
  31  |   const file = await downloadPromise; expect(file.suggestedFilename()).toBe('astroagent-results.zip')
  32  |   if (process.env.ASTROAGENT_RECORD_DIR) await file.saveAs(path.join(process.env.ASTROAGENT_RECORD_DIR, `${testInfo.project.name}-download.zip`))
  33  |   await question.fill('只保留 RUWE≤1.4，其他条件不变，重新查询。')
  34  |   await page.getByRole('button', { name: '发送问题', exact: true }).click()
  35  |   await expect(page.getByText('使用了 1 轮历史上下文')).toBeVisible()
  36  |   const url = page.url(); await page.reload(); await expect(page.getByText('使用了 1 轮历史上下文')).toBeVisible()
  37  |   expect(page.url()).toBe(url)
  38  |   await page.getByRole('button', { name: '核查本轮结果与导出' }).first().click()
  39  |   await expect(page.getByLabel('结果核查').getByText('历史结果', { exact: true })).toBeVisible()
  40  |   if (process.env.ASTROAGENT_RECORD_DIR) await page.screenshot({ path: path.join(process.env.ASTROAGENT_RECORD_DIR, `${testInfo.project.name}-full.png`) })
  41  |   expect(errors).toEqual([]); expect(browserName).toBe('chromium')
  42  | })
  43  | 
  44  | test('IME composition, explicit examples, plain text literature, rename and delete', async ({ page }) => {
  45  |   await page.goto('/'); await page.getByRole('button', { name: '新建会话', exact: true }).click()
  46  |   await page.getByRole('button', { name: 'ADS 文献检索' }).click()
  47  |   const input = page.getByRole('textbox', { name: '天文问题' })
  48  |   await input.dispatchEvent('compositionstart'); await input.dispatchEvent('keydown', { key: 'Enter', isComposing: true })
  49  |   await expect(page.getByText('第 1 轮', { exact: true })).toHaveCount(0)
  50  |   await input.dispatchEvent('compositionend')
  51  |   await page.getByRole('button', { name: '发送问题', exact: true }).click()
  52  |   await expect(page.getByText('合成验收结果已返回。', { exact: false })).toBeVisible()
  53  |   await page.getByRole('tab', { name: /ADS/ }).click()
  54  |   await expect(page.getByRole('heading', { name: '<img src=x onerror="window.syntheticXss=true"> 合成论文标题' })).toBeVisible()
  55  |   expect(await page.evaluate(() => 'syntheticXss' in window)).toBe(false)
  56  |   await page.locator('.conversation-row.selected').getByRole('button', { name: /会话操作：/ }).click()
  57  |   await page.getByRole('menuitem', { name: '重命名' }).click(); await page.getByRole('textbox', { name: '会话名称' }).fill('我的文献核查')
  58  |   await page.getByRole('button', { name: '保存名称', exact: true }).click()
  59  |   await expect(page.getByRole('heading', { name: '我的文献核查' })).toBeVisible()
  60  |   await page.locator('.conversation-row.selected').getByRole('button', { name: /会话操作：/ }).click()
  61  |   await page.getByRole('menuitem', { name: '删除会话' }).click(); await expect(page.getByRole('dialog')).toBeVisible()
  62  |   await page.getByRole('button', { name: '确认删除' }).click(); await expect(page).toHaveURL('http://127.0.0.1:15173/')
  63  | })
  64  | 
  65  | test('narrow viewport has usable panel navigation and no page overflow', async ({ page }, testInfo) => {
  66  |   await page.setViewportSize({ width: 390, height: 844 }); await page.goto('/')
  67  |   await page.getByRole('button', { name: '展开会话列表' }).click(); await page.getByRole('button', { name: '新建会话', exact: true }).click()
  68  |   const input = page.getByRole('textbox', { name: '天文问题' }); await input.fill('合成Gaia圆锥查询')
  69  |   await page.getByRole('button', { name: '发送问题', exact: true }).click()
> 70  |   await expect(page.getByText('合成验收结果已返回。', { exact: false })).toBeVisible()
      |                                                                ^ Error: expect(locator).toBeVisible() failed
  71  |   await page.getByRole('button', { name: '核查本轮结果与导出' }).click(); await expect(page.getByRole('heading', { name: '第 1 轮结果' })).toBeVisible()
  72  |   const width = await page.evaluate(() => ({ body: document.body.scrollWidth, viewport: innerWidth })); expect(width.body).toBeLessThanOrEqual(width.viewport)
  73  |   if (process.env.ASTROAGENT_RECORD_DIR) await page.screenshot({ path: path.join(process.env.ASTROAGENT_RECORD_DIR, `${testInfo.project.name}-mobile.png`) })
  74  | })
  75  | 
  76  | test('backend connection error is explicit', async ({ page }) => {
  77  |   await page.route('**/api/v1/conversations', route => route.abort())
  78  |   await page.goto('/'); await expect(page.getByRole('alert')).toContainText('连接已断开')
  79  | })
  80  | 
  81  | test('a rejected send preserves the question and only retries on explicit action', async ({ page }) => {
  82  |   await page.goto('/'); await page.getByRole('button', { name: '新建会话', exact: true }).click()
  83  |   let calls = 0
  84  |   await page.route('**/api/v1/conversations/*/turns', async route => {
  85  |     calls++
  86  |     if (calls === 1) return route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ error: { code: 'conversation_service_busy', message: '已有两轮正在处理', retryable: true } }) })
  87  |     return route.continue()
  88  |   })
  89  |   const question = page.getByRole('textbox', { name: '天文问题' })
  90  |   await question.fill('合成Gaia查询，验证重试')
  91  |   await page.getByRole('button', { name: '发送问题', exact: true }).click()
  92  |   await expect(page.getByRole('alert')).toContainText('已有两轮正在处理')
  93  |   await expect(question).toHaveValue('合成Gaia查询，验证重试'); expect(calls).toBe(1)
  94  |   await page.getByRole('button', { name: '重新执行（新一轮）' }).click()
  95  |   await expect(page.getByText('合成验收结果已返回。', { exact: false })).toBeVisible(); expect(calls).toBe(2)
  96  | })
  97  | 
  98  | test('a late initial list does not clear a send error after navigation', async ({ page, request }) => {
  99  |   const created = await (await request.post('/api/v1/conversations', { data: { title: '延迟列表测试' } })).json()
  100 |   let release!: () => void, started!: () => void
  101 |   const gate = new Promise<void>(resolve => { release = resolve })
  102 |   const waiting = new Promise<void>(resolve => { started = resolve })
  103 |   await page.route('**/api/v1/conversations', async route => {
  104 |     if (route.request().method() === 'GET') { started(); await gate }
  105 |     await route.continue()
  106 |   }, { times: 1 })
  107 |   try {
  108 |     await page.goto(`/conversations/${created.id}`); await waiting
  109 |     await expect(page).toHaveURL(/conversations\/[0-9a-f-]+/)
  110 |     await page.route('**/api/v1/conversations/*/turns', route => route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ error: { code: 'conversation_service_busy', message: '已有两轮正在处理', retryable: true } }) }))
  111 |     await page.getByRole('textbox', { name: '天文问题' }).fill('测试异步加载')
  112 |     await page.getByRole('button', { name: '发送问题', exact: true }).click()
  113 |     await expect(page.getByRole('alert')).toContainText('已有两轮正在处理')
  114 |     const initialList = page.waitForResponse(response => response.request().method() === 'GET' && response.url().endsWith('/api/v1/conversations'))
  115 |     release()
  116 |     await initialList
  117 |     await expect(page.getByRole('alert')).toContainText('已有两轮正在处理')
  118 |   } finally { release() }
  119 | })
  120 | 
  121 | test('local static proxy keeps its API target and never returns SPA HTML for API errors', async ({ request }) => {
  122 |   const missing = await request.get('/api/v1/nonexistent')
  123 |   expect(missing.status()).toBe(404); expect(missing.headers()['content-type']).toContain('application/json')
  124 |   const response = await new Promise<{status:number;body:string}>(resolve => {
  125 |     http.get({ host: '127.0.0.1', port: 15173, path: '//example.invalid/api/v1/conversations' }, reply => {
  126 |       let body = ''; reply.on('data', chunk => body += chunk); reply.on('end', () => resolve({ status: reply.statusCode || 0, body }))
  127 |     })
  128 |   })
  129 |   expect(response.status).toBe(200); expect(Array.isArray(JSON.parse(response.body))).toBe(true)
  130 | })
  131 | 
```