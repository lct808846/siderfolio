# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: workbench.spec.ts >> a rejected send preserves the question and only retries on explicit action
- Location: tests\browser\workbench.spec.ts:83:1

# Error details

```
Test timeout of 60000ms exceeded.
```

```
Error: locator.click: Test timeout of 60000ms exceeded.
Call log:
  - waiting for getByRole('button', { name: '重新执行（新一轮）' })

```

# Page snapshot

```yaml
- generic [active] [ref=e1]:
  - generic [ref=e3]:
    - banner [ref=e4]:
      - generic [ref=e5]:
        - button "AstroAgent：新建会话" [ref=e6] [cursor=pointer]:
          - generic [ref=e11]: AstroAgent
          - generic [ref=e12]: 1.6 开发版
        - navigation "全局导航" [ref=e13]:
          - link "查询工作台" [ref=e14] [cursor=pointer]:
            - /url: /
          - link "项目归档" [ref=e15] [cursor=pointer]:
            - /url: /projects
          - link "本地助手" [ref=e16] [cursor=pointer]:
            - /url: /local-assistant
          - link "接口定义 ↗" [ref=e17] [cursor=pointer]:
            - /url: /openapi.json
    - complementary "会话列表" [ref=e18]:
      - button "新建会话" [ref=e20] [cursor=pointer]:
        - generic [aria-hidden] [ref=e21]: ＋
        - text: 新建会话
      - generic "滚动浏览会话" [ref=e23]:
        - generic [ref=e24]:
          - generic [ref=e25]:
            - paragraph [ref=e26]: 本地会话
            - button "多选管理会话" [ref=e27] [cursor=pointer]
          - navigation "本地会话" [ref=e33]:
            - generic [ref=e34]:
              - checkbox [disabled]
              - button "新会话 0 轮 · 2026/11/15" [ref=e35] [cursor=pointer]:
                - generic [ref=e36]:
                  - generic [ref=e37]: 新会话
                  - generic [ref=e38]: 0 轮 · 2026/11/15
              - button "会话操作：新会话" [ref=e40] [cursor=pointer]: ⋯
            - generic [ref=e41]:
              - checkbox [disabled]
              - button "合成Gaia圆锥查询 1 轮 · 2026/11/15" [ref=e42] [cursor=pointer]:
                - generic [ref=e43]:
                  - generic [ref=e44]: 合成Gaia圆锥查询
                  - generic [ref=e45]: 1 轮 · 2026/11/15
              - button "会话操作：合成Gaia圆锥查询" [ref=e47] [cursor=pointer]: ⋯
            - generic [ref=e48]:
              - checkbox [disabled]
              - button "合成验收：查询Gaia圆锥100个… 2 轮 · 2026/11/15" [ref=e49] [cursor=pointer]:
                - generic [ref=e50]:
                  - generic [ref=e51]: 合成验收：查询Gaia圆锥100个…
                  - generic [ref=e52]: 2 轮 · 2026/11/15
              - button "会话操作：合成验收：查询Gaia圆锥100个…" [ref=e54] [cursor=pointer]: ⋯
            - generic [ref=e55]:
              - checkbox [disabled]
              - button "第一条合成查询 2 轮 · 2026/11/15" [ref=e56] [cursor=pointer]:
                - generic [ref=e57]:
                  - generic [ref=e58]: 第一条合成查询
                  - generic [ref=e59]: 2 轮 · 2026/11/15
              - button "会话操作：第一条合成查询" [ref=e61] [cursor=pointer]: ⋯
      - button "fixture 管理员" [ref=e64] [cursor=pointer]:
        - generic [aria-hidden] [ref=e65]: FI
        - generic [ref=e66]:
          - generic [ref=e67]: fixture
          - generic [ref=e68]: 管理员
    - main [ref=e69]:
      - generic [ref=e70]:
        - button "收起会话列表" [expanded] [ref=e71] [cursor=pointer]
        - heading "新会话" [level=1] [ref=e75]
        - button "打开结果栏" [ref=e76] [cursor=pointer]
      - alert [ref=e80]:
        - generic [ref=e85]:
          - paragraph [ref=e86]: 本次操作未完成
          - paragraph [ref=e87]: 已有两轮正在处理
          - generic [ref=e88]:
            - button "刷新状态" [ref=e89] [cursor=pointer]
            - button "重新发送" [ref=e92] [cursor=pointer]
          - group [ref=e96]:
            - generic "技术详情" [ref=e97] [cursor=pointer]
      - generic [ref=e99]:
        - generic [ref=e100]: 天文问题
        - textbox "天文问题" [ref=e101]:
          - /placeholder: 输入一个天文问题，或继续追问刚才的结果…
          - text: 合成Gaia查询，验证重试
        - generic [ref=e102]:
          - generic [ref=e103]:
            - button "科研绘图" [ref=e104] [cursor=pointer]
            - button "N 体模拟 待开放" [ref=e109] [cursor=pointer]:
              - generic [ref=e115]: N 体模拟
              - generic [ref=e116]: 待开放
          - button "回答模型：synthetic-model" [ref=e119] [cursor=pointer]:
            - generic [ref=e120]: synthetic-model
          - button "选择附件" [ref=e123]
          - button "添加附件" [ref=e124] [cursor=pointer]
          - button "发送问题" [ref=e127] [cursor=pointer]
        - paragraph [ref=e130]: 模型回答需对照原始数据核查；位置候选源不等于星团成员。
  - tooltip "发送问题及附件；Enter 发送，Shift + Enter 换行" [ref=e131]
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
  62  |   await page.getByRole('button', { name: '确认删除' }).click(); await expect(page).toHaveURL(new URL('/', page.url()).href)
  63  | })
  64  | 
  65  | test('narrow viewport has usable panel navigation and no page overflow', async ({ page }, testInfo) => {
  66  |   await page.setViewportSize({ width: 390, height: 844 }); await page.goto('/')
  67  |   await page.getByRole('button', { name: '展开会话列表' }).click(); await page.getByRole('button', { name: '新建会话', exact: true }).click()
  68  |   const input = page.getByRole('textbox', { name: '天文问题' }); await input.fill('合成Gaia圆锥查询')
  69  |   await page.getByRole('button', { name: '发送问题', exact: true }).click()
  70  |   await expect(page.getByRole('heading', { name: '第 1 轮结果' })).toBeVisible()
  71  |   await page.getByRole('button', { name: '收起结果面板' }).click()
  72  |   await expect(page.getByText('合成验收结果已返回。', { exact: false })).toBeVisible()
  73  |   await page.getByRole('button', { name: '核查本轮结果与导出' }).click(); await expect(page.getByRole('heading', { name: '第 1 轮结果' })).toBeVisible()
  74  |   const width = await page.evaluate(() => ({ body: document.body.scrollWidth, viewport: innerWidth })); expect(width.body).toBeLessThanOrEqual(width.viewport)
  75  |   if (process.env.ASTROAGENT_RECORD_DIR) await page.screenshot({ path: path.join(process.env.ASTROAGENT_RECORD_DIR, `${testInfo.project.name}-mobile.png`) })
  76  | })
  77  | 
  78  | test('backend connection error is explicit', async ({ page }) => {
  79  |   await page.route('**/api/v1/conversations', route => route.abort())
  80  |   await page.goto('/'); await expect(page.getByRole('alert')).toContainText('连接已断开')
  81  | })
  82  | 
  83  | test('a rejected send preserves the question and only retries on explicit action', async ({ page }) => {
  84  |   await page.goto('/'); await page.getByRole('button', { name: '新建会话', exact: true }).click()
  85  |   let calls = 0
  86  |   await page.route('**/api/v1/conversations/*/turns', async route => {
  87  |     calls++
  88  |     if (calls === 1) return route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ error: { code: 'conversation_service_busy', message: '已有两轮正在处理', retryable: true } }) })
  89  |     return route.continue()
  90  |   })
  91  |   const question = page.getByRole('textbox', { name: '天文问题' })
  92  |   await question.fill('合成Gaia查询，验证重试')
  93  |   await page.getByRole('button', { name: '发送问题', exact: true }).click()
  94  |   await expect(page.getByRole('alert')).toContainText('已有两轮正在处理')
  95  |   await expect(question).toHaveValue('合成Gaia查询，验证重试'); expect(calls).toBe(1)
> 96  |   await page.getByRole('button', { name: '重新执行（新一轮）' }).click()
      |                                                         ^ Error: locator.click: Test timeout of 60000ms exceeded.
  97  |   await expect(page.getByText('合成验收结果已返回。', { exact: false })).toBeVisible(); expect(calls).toBe(2)
  98  | })
  99  | 
  100 | test('a late initial list does not clear a send error after navigation', async ({ page, request }) => {
  101 |   const created = await (await request.post('/api/v1/conversations', { data: { title: '延迟列表测试' } })).json()
  102 |   let release!: () => void, started!: () => void
  103 |   const gate = new Promise<void>(resolve => { release = resolve })
  104 |   const waiting = new Promise<void>(resolve => { started = resolve })
  105 |   await page.route('**/api/v1/conversations', async route => {
  106 |     if (route.request().method() === 'GET') { started(); await gate }
  107 |     await route.continue()
  108 |   }, { times: 1 })
  109 |   try {
  110 |     await page.goto(`/conversations/${created.id}`); await waiting
  111 |     await expect(page).toHaveURL(/conversations\/[0-9a-f-]+/)
  112 |     await page.route('**/api/v1/conversations/*/turns', route => route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ error: { code: 'conversation_service_busy', message: '已有两轮正在处理', retryable: true } }) }))
  113 |     await page.getByRole('textbox', { name: '天文问题' }).fill('测试异步加载')
  114 |     await page.getByRole('button', { name: '发送问题', exact: true }).click()
  115 |     await expect(page.getByRole('alert')).toContainText('已有两轮正在处理')
  116 |     const initialList = page.waitForResponse(response => response.request().method() === 'GET' && response.url().endsWith('/api/v1/conversations'))
  117 |     release()
  118 |     await initialList
  119 |     await expect(page.getByRole('alert')).toContainText('已有两轮正在处理')
  120 |   } finally { release() }
  121 | })
  122 | 
  123 | test('local static proxy keeps its API target and never returns SPA HTML for API errors', async ({ request, baseURL }) => {
  124 |   const missing = await request.get('/api/v1/nonexistent')
  125 |   expect(missing.status()).toBe(404); expect(missing.headers()['content-type']).toContain('application/json')
  126 |   const response = await new Promise<{status:number;body:string}>(resolve => {
  127 |     http.get({ host: '127.0.0.1', port: Number(new URL(baseURL!).port), path: '//example.invalid/api/v1/conversations' }, reply => {
  128 |       let body = ''; reply.on('data', chunk => body += chunk); reply.on('end', () => resolve({ status: reply.statusCode || 0, body }))
  129 |     })
  130 |   })
  131 |   expect(response.status).toBe(200); expect(Array.isArray(JSON.parse(response.body))).toBe(true)
  132 | })
  133 | 
```