# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: workbench.spec.ts >> a rejected send preserves the question and only retries on explicit action
- Location: tests\browser\workbench.spec.ts:80:1

# Error details

```
Error: expect(locator).toContainText(expected) failed

Locator: getByRole('alert')
Expected substring: "已有两轮正在处理"
Timeout: 5000ms
Error: element(s) not found

Call log:
  - Expect "toContainText" getByRole('alert') with timeout 5000ms
  - waiting for getByRole('alert')

```

```yaml
- banner:
  - link "AstroAgent 0.7":
    - /url: /
  - text: 本地科研工作台
  - link "项目归档 →":
    - /url: /projects
  - link "接口文档 ↗":
    - /url: http://127.0.0.1:8000/docs
- complementary "会话列表":
  - text: WORKSPACE 9/20
  - button "新建会话"
  - paragraph: 本地会话
  - navigation:
    - button "新会话 0 轮 · 2026/10/30"
    - button "新会话 0 轮 · 2026/10/30"
    - button "新会话 1 轮 · 2026/10/30"
    - button "新会话 2 轮 · 2026/10/30"
    - button "流程 · 合成 ADS 证据表 1 轮 · 2026/10/30"
    - button "流程 · 合成 Gaia 流程 1 轮 · 2026/10/30"
    - button "新会话 1 轮 · 2026/10/30"
    - button "新会话 1 轮 · 2026/10/30"
    - button "新会话 2 轮 · 2026/10/30"
  - text: SIMBAD / ADS / Gaia 测量 · 文献 · 可追溯结果
- main:
  - text: RESEARCH NOTEBOOK
  - heading "新会话" [level=1]
  - button "重命名会话": 改名
  - button "删除会话": 删除
  - paragraph: ASK. VERIFY. EXPLORE.
  - heading "把问题交给星空， 把依据留在手边。" [level=2]:
    - text: 把问题交给星空，
    - emphasis: 把依据留在手边。
  - paragraph: 查询天体、核查文献、查看 Gaia 测量。 每轮结果独立保存，后续可以继续追问。
  - button "坐标圆锥查询"
  - button "指定 DR3 编号"
  - button "ADS 文献检索"
  - paragraph: 以上为待发送的问题，点击仅填入输入框。
  - text: 天文问题
  - textbox "天文问题":
    - /placeholder: 输入一个天文问题，或继续追问刚才的结果…
    - text: 合成Gaia查询，验证重试
  - text: Enter 发送 · Shift + Enter 换行
  - button "发送"
  - paragraph: 模型回答需对照原始数据核查；位置候选源不等于星团成员。
- complementary "结果核查":
  - text: RESULTS / 数据核查
  - heading "查询结果" [level=2]
  - heading "让每一个结论有据可查" [level=3]
  - paragraph: 查询后在这里核查测量、检索条件和来源。
  - text: 等待查询数据
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
  10  |   await expect(page.getByRole('heading', { name: '观测与文献，从这里开始' })).toBeVisible()
  11  |   if (process.env.ASTROAGENT_RECORD_DIR) { mkdirSync(process.env.ASTROAGENT_RECORD_DIR, { recursive: true }); await page.screenshot({ path: path.join(process.env.ASTROAGENT_RECORD_DIR, `${testInfo.project.name}-empty.png`) }) }
  12  |   await page.getByRole('button', { name: '新建会话' }).click()
  13  |   await expect(page).toHaveURL(/conversations\/[0-9a-f-]+/)
  14  |   const question = page.getByRole('textbox', { name: '天文问题' })
  15  |   await question.fill('合成验收：查询Gaia圆锥100个位置候选源。')
  16  |   await page.getByRole('button', { name: '发送', exact: true }).click()
  17  |   await expect(page.getByText('合成验收结果已返回。', { exact: false })).toBeVisible()
  18  |   await expect(page.getByRole('button', { name: '核查本轮结果与导出' })).toBeVisible()
  19  |   await page.getByRole('button', { name: '核查本轮结果与导出' }).click()
  20  |   await page.getByText('查看完整交付表格（100 行）').click()
  21  |   await expect(page.getByRole('cell', { name: '5853498713190525696', exact: true })).toBeVisible()
  22  |   await page.getByRole('button', { name: '下一页' }).click()
  23  |   await expect(page.getByRole('cell', { name: '5853498713190525716', exact: true })).toBeVisible()
  24  |   await page.getByLabel('自行散点图', { exact: true }).check()
  25  |   await page.getByLabel('视差直方图', { exact: true }).check()
  26  |   await page.getByLabel('观测颜色—星等图', { exact: true }).check()
  27  |   await page.getByRole('button', { name: '生成预览与数据包' }).click()
  28  |   await expect(page.getByRole('img', { name: '自行散点图', exact: true })).toBeVisible()
  29  |   if (process.env.ASTROAGENT_RECORD_DIR) { await page.getByRole('img', { name: '自行散点图', exact: true }).scrollIntoViewIfNeeded(); await page.screenshot({ path: path.join(process.env.ASTROAGENT_RECORD_DIR, `${testInfo.project.name}-preview.png`) }) }
  30  |   const downloadPromise = page.waitForEvent('download')
  31  |   await page.getByRole('button', { name: '下载 ZIP' }).click()
  32  |   const file = await downloadPromise; expect(file.suggestedFilename()).toBe('astroagent-results.zip')
  33  |   if (process.env.ASTROAGENT_RECORD_DIR) await file.saveAs(path.join(process.env.ASTROAGENT_RECORD_DIR, `${testInfo.project.name}-download.zip`))
  34  |   await question.fill('只保留 RUWE≤1.4，其他条件不变，重新查询。')
  35  |   await page.getByRole('button', { name: '发送', exact: true }).click()
  36  |   await expect(page.getByText('使用了 1 轮历史上下文')).toBeVisible()
  37  |   const url = page.url(); await page.reload(); await expect(page.getByText('使用了 1 轮历史上下文')).toBeVisible()
  38  |   expect(page.url()).toBe(url)
  39  |   await page.getByRole('button', { name: '核查本轮结果与导出' }).first().click()
  40  |   await expect(page.getByLabel('结果核查').getByText('历史结果', { exact: true })).toBeVisible()
  41  |   if (process.env.ASTROAGENT_RECORD_DIR) await page.screenshot({ path: path.join(process.env.ASTROAGENT_RECORD_DIR, `${testInfo.project.name}-full.png`) })
  42  |   expect(errors).toEqual([]); expect(browserName).toBe('chromium')
  43  | })
  44  | 
  45  | test('IME composition, explicit examples, plain text literature, rename and delete', async ({ page }) => {
  46  |   await page.goto('/'); await page.getByRole('button', { name: '新建会话' }).click()
  47  |   await page.getByRole('button', { name: 'ADS 文献检索' }).click()
  48  |   const input = page.getByRole('textbox', { name: '天文问题' })
  49  |   await input.dispatchEvent('compositionstart'); await input.dispatchEvent('keydown', { key: 'Enter', isComposing: true })
  50  |   await expect(page.getByText('第 1 轮', { exact: true })).toHaveCount(0)
  51  |   await input.dispatchEvent('compositionend')
  52  |   await page.getByRole('button', { name: '发送', exact: true }).click()
  53  |   await expect(page.getByText('合成验收结果已返回。', { exact: false })).toBeVisible()
  54  |   await page.getByRole('tab', { name: /ADS/ }).click()
  55  |   await expect(page.getByRole('heading', { name: '<img src=x onerror="window.syntheticXss=true"> 合成论文标题' })).toBeVisible()
  56  |   expect(await page.evaluate(() => 'syntheticXss' in window)).toBe(false)
  57  |   await page.getByRole('button', { name: '重命名会话' }).click(); await page.getByRole('textbox', { name: '会话名称' }).fill('我的文献核查')
  58  |   await page.getByRole('button', { name: '保存', exact: true }).click()
  59  |   await expect(page.getByRole('heading', { name: '我的文献核查' })).toBeVisible()
  60  |   await page.getByRole('button', { name: '删除会话' }).click(); await expect(page.getByRole('dialog')).toBeVisible()
  61  |   await page.getByRole('button', { name: '确认删除' }).click(); await expect(page).toHaveURL('http://127.0.0.1:5173/')
  62  | })
  63  | 
  64  | test('narrow viewport has usable panel navigation and no page overflow', async ({ page }, testInfo) => {
  65  |   await page.setViewportSize({ width: 390, height: 844 }); await page.goto('/')
  66  |   await page.getByRole('button', { name: '会话', exact: true }).click(); await page.getByRole('button', { name: '新建会话' }).click()
  67  |   const input = page.getByRole('textbox', { name: '天文问题' }); await input.fill('合成Gaia圆锥查询')
  68  |   await page.getByRole('button', { name: '发送', exact: true }).click()
  69  |   await expect(page.getByText('合成验收结果已返回。', { exact: false })).toBeVisible()
  70  |   await page.getByRole('button', { name: '核查本轮结果与导出' }).click(); await expect(page.getByRole('heading', { name: '第 1 轮结果' })).toBeVisible()
  71  |   const width = await page.evaluate(() => ({ body: document.body.scrollWidth, viewport: innerWidth })); expect(width.body).toBeLessThanOrEqual(width.viewport)
  72  |   if (process.env.ASTROAGENT_RECORD_DIR) await page.screenshot({ path: path.join(process.env.ASTROAGENT_RECORD_DIR, `${testInfo.project.name}-mobile.png`) })
  73  | })
  74  | 
  75  | test('backend connection error is explicit', async ({ page }) => {
  76  |   await page.route('**/api/v1/conversations', route => route.abort())
  77  |   await page.goto('/'); await expect(page.getByRole('alert')).toContainText('连接已断开')
  78  | })
  79  | 
  80  | test('a rejected send preserves the question and only retries on explicit action', async ({ page }) => {
  81  |   await page.goto('/'); await page.getByRole('button', { name: '新建会话' }).click()
  82  |   let calls = 0
  83  |   await page.route('**/api/v1/conversations/*/turns', async route => {
  84  |     calls++
  85  |     if (calls === 1) return route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ error: { code: 'conversation_service_busy', message: '已有两轮正在处理', retryable: true } }) })
  86  |     return route.continue()
  87  |   })
  88  |   const question = page.getByRole('textbox', { name: '天文问题' })
  89  |   await question.fill('合成Gaia查询，验证重试')
  90  |   await page.getByRole('button', { name: '发送', exact: true }).click()
> 91  |   await expect(page.getByRole('alert')).toContainText('已有两轮正在处理')
      |                                         ^ Error: expect(locator).toContainText(expected) failed
  92  |   await expect(question).toHaveValue('合成Gaia查询，验证重试'); expect(calls).toBe(1)
  93  |   await page.getByRole('button', { name: '重新执行（新一轮）' }).click()
  94  |   await expect(page.getByText('合成验收结果已返回。', { exact: false })).toBeVisible(); expect(calls).toBe(2)
  95  | })
  96  | 
  97  | test('local static proxy keeps its API target and never returns SPA HTML for API errors', async ({ request }) => {
  98  |   const missing = await request.get('/api/v1/nonexistent')
  99  |   expect(missing.status()).toBe(404); expect(missing.headers()['content-type']).toContain('application/json')
  100 |   const response = await new Promise<{status:number;body:string}>(resolve => {
  101 |     http.get({ host: '127.0.0.1', port: 5173, path: '//example.invalid/api/v1/conversations' }, reply => {
  102 |       let body = ''; reply.on('data', chunk => body += chunk); reply.on('end', () => resolve({ status: reply.statusCode || 0, body }))
  103 |     })
  104 |   })
  105 |   expect(response.status).toBe(200); expect(Array.isArray(JSON.parse(response.body))).toBe(true)
  106 | })
  107 | 
```