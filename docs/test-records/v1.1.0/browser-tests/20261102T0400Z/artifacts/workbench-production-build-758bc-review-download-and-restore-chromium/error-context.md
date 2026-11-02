# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: workbench.spec.ts >> production build: conversation, follow-up, complete table, preview, download and restore
- Location: tests\browser\workbench.spec.ts:6:1

# Error details

```
Error: expect(locator).toBeVisible() failed

Locator: getByRole('heading', { name: '观测与文献，从这里开始' })
Expected: visible
Timeout: 5000ms
Error: element(s) not found

Call log:
  - Expect "toBeVisible" getByRole('heading', { name: '观测与文献，从这里开始' }) with timeout 5000ms
  - waiting for getByRole('heading', { name: '观测与文献，从这里开始' })

```

```yaml
- banner:
  - link "AstroAgent 查询工作台":
    - /url: /
    - text: AstroAgent 1.1.0
  - text: 本地科研工作台
  - navigation "全局导航":
    - link "查询工作台":
      - /url: /
    - link "项目归档":
      - /url: /projects
    - link "本机设置":
      - /url: /settings
    - link "接口文档 ↗":
      - /url: http://127.0.0.1:8000/docs
- complementary "会话列表":
  - text: WORKSPACE 0/20
  - button "新建会话"
  - paragraph: 本地会话
  - navigation
  - paragraph: 会话保存在本机， 从一个问题开始。
  - text: SIMBAD / ADS / Gaia 测量 · 文献 · 可追溯结果
- main:
  - text: 科研工作台 / 对话
  - heading "新会话" [level=1]
  - text: 查询工作区 SIMBAD / ADS / GAIA
  - paragraph: 开始查询
  - heading "天文数据与文献检索" [level=2]
  - paragraph: 输入问题，查询天体信息、Gaia 数据或相关文献。 查询结果保留来源、条件和时间，便于核查。
  - text: 示例查询 点击填入输入框
  - button "01 坐标圆锥查询"
  - button "02 指定 DR3 编号"
  - button "03 ADS 文献检索"
  - text: 天文问题
  - textbox "天文问题":
    - /placeholder: 输入一个天文问题，或继续追问刚才的结果…
  - text: Enter 发送 · Shift + Enter 换行
  - button "发送" [disabled]
  - paragraph: 模型回答需对照原始数据核查；位置候选源不等于星团成员。
- complementary "结果核查":
  - text: RESULTS / 数据核查
  - heading "查询结果" [level=2]
  - heading "暂无查询结果" [level=3]
  - paragraph: 提交查询后，可在此查看数据、检索条件、来源与导出选项。
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
> 10  |   await expect(page.getByRole('heading', { name: '观测与文献，从这里开始' })).toBeVisible()
      |                                                                    ^ Error: expect(locator).toBeVisible() failed
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
  61  |   await page.getByRole('button', { name: '确认删除' }).click(); await expect(page).toHaveURL('http://127.0.0.1:15173/')
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
  82  |   await expect(page).toHaveURL(/conversations\/[0-9a-f-]+/)
  83  |   let calls = 0
  84  |   await page.route('**/api/v1/conversations/*/turns', async route => {
  85  |     calls++
  86  |     if (calls === 1) return route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ error: { code: 'conversation_service_busy', message: '已有两轮正在处理', retryable: true } }) })
  87  |     return route.continue()
  88  |   })
  89  |   const question = page.getByRole('textbox', { name: '天文问题' })
  90  |   await question.fill('合成Gaia查询，验证重试')
  91  |   await page.getByRole('button', { name: '发送', exact: true }).click()
  92  |   await expect(page.getByRole('alert')).toContainText('已有两轮正在处理')
  93  |   await expect(question).toHaveValue('合成Gaia查询，验证重试'); expect(calls).toBe(1)
  94  |   await page.getByRole('button', { name: '重新执行（新一轮）' }).click()
  95  |   await expect(page.getByText('合成验收结果已返回。', { exact: false })).toBeVisible(); expect(calls).toBe(2)
  96  | })
  97  | 
  98  | test('a late initial list does not clear a send error after navigation', async ({ page }) => {
  99  |   let release!: () => void, started!: () => void
  100 |   const gate = new Promise<void>(resolve => { release = resolve })
  101 |   const waiting = new Promise<void>(resolve => { started = resolve })
  102 |   await page.route('**/api/v1/conversations', async route => {
  103 |     if (route.request().method() === 'GET') { started(); await gate }
  104 |     await route.continue()
  105 |   }, { times: 1 })
  106 |   try {
  107 |     await page.goto('/'); await waiting
  108 |     await page.getByRole('button', { name: '新建会话' }).click()
  109 |     await expect(page).toHaveURL(/conversations\/[0-9a-f-]+/)
  110 |     await page.route('**/api/v1/conversations/*/turns', route => route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ error: { code: 'conversation_service_busy', message: '已有两轮正在处理', retryable: true } }) }))
```