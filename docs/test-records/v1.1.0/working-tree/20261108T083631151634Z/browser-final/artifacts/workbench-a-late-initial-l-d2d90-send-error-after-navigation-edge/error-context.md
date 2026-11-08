# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: workbench.spec.ts >> a late initial list does not clear a send error after navigation
- Location: tests\browser\workbench.spec.ts:98:1

# Error details

```
Error: locator.click: Error: strict mode violation: getByRole('button', { name: '新建会话' }) resolved to 2 elements:
    1) <button type="button" data-tooltip="" class="brand brand-action" aria-label="AstroAgent：新建会话">…</button> aka getByRole('button', { name: 'AstroAgent：新建会话' })
    2) <button class="new-conversation">…</button> aka getByRole('button', { name: '新建会话', exact: true })

Call log:
  - waiting for getByRole('button', { name: '新建会话' })

```

# Page snapshot

```yaml
- generic [ref=e3]:
  - banner [ref=e4]:
    - generic [ref=e5]:
      - button "AstroAgent：新建会话" [ref=e6] [cursor=pointer]:
        - generic [aria-hidden] [ref=e7]: ✳
        - generic [ref=e8]: AstroAgent
        - generic [ref=e9]: 1.1.0
      - navigation "全局导航" [ref=e10]:
        - link "查询工作台" [ref=e11] [cursor=pointer]:
          - /url: /
        - link "项目归档" [ref=e12] [cursor=pointer]:
          - /url: /projects
        - link "本机设置" [ref=e13] [cursor=pointer]:
          - /url: /settings
        - link "接口文档 ↗" [ref=e14] [cursor=pointer]:
          - /url: http://127.0.0.1:8000/docs
  - complementary "会话列表" [ref=e15]:
    - generic [ref=e16]:
      - generic [ref=e17]: 会话
      - generic [ref=e18]: 2/20
    - button "新建会话" [ref=e19] [cursor=pointer]:
      - generic [aria-hidden] [ref=e20]: ＋
      - text: 新建会话
    - generic [ref=e21]:
      - paragraph [ref=e22]: 本地会话
      - button "多选" [ref=e23] [cursor=pointer]
    - navigation "本地会话" [ref=e24]:
      - generic [ref=e25]:
        - button "流程 · 合成 ADS 证据表 1 轮 · 2026/11/8" [ref=e26] [cursor=pointer]:
          - generic [aria-hidden] [ref=e27]: ◌
          - generic [ref=e28]:
            - generic [ref=e29]: 流程 · 合成 ADS 证据表
            - generic [ref=e30]: 1 轮 · 2026/11/8
        - button "会话操作：流程 · 合成 ADS 证据表" [ref=e31] [cursor=pointer]: ⋯
      - generic [ref=e32]:
        - button "流程 · 合成 Gaia 流程 1 轮 · 2026/11/8" [ref=e33] [cursor=pointer]:
          - generic [aria-hidden] [ref=e34]: ◌
          - generic [ref=e35]:
            - generic [ref=e36]: 流程 · 合成 Gaia 流程
            - generic [ref=e37]: 1 轮 · 2026/11/8
        - button "会话操作：流程 · 合成 Gaia 流程" [ref=e38] [cursor=pointer]: ⋯
    - generic [ref=e39]:
      - text: SIMBAD / ADS / Gaia
      - generic [ref=e40]: 测量 · 文献 · 可追溯结果
  - main [ref=e41]:
    - generic [ref=e42]:
      - button "收起会话列表" [expanded] [ref=e43] [cursor=pointer]
      - heading "新会话" [level=1] [ref=e47]
      - button "打开结果栏" [ref=e48] [cursor=pointer]
    - generic [ref=e53]:
      - generic [ref=e55]:
        - paragraph [ref=e56]: SIMBAD · ADS · Gaia DR3
        - heading "天文数据与文献检索" [level=2] [ref=e57]
        - paragraph [ref=e58]: 查询天体、Gaia 测量和论文，保留每轮来源与结果。
      - generic [ref=e59]:
        - button "坐标圆锥查询" [ref=e60] [cursor=pointer]:
          - generic [aria-hidden] [ref=e62]: ↗
        - button "指定 DR3 编号" [ref=e63] [cursor=pointer]:
          - generic [aria-hidden] [ref=e65]: ↗
        - button "ADS 文献检索" [ref=e66] [cursor=pointer]:
          - generic [aria-hidden] [ref=e68]: ↗
      - paragraph [ref=e69]: 示例仅填入输入框，由你确认发送。
    - generic [ref=e70]:
      - generic [ref=e71]: 天文问题
      - textbox "天文问题" [ref=e72]:
        - /placeholder: 输入一个天文问题，或继续追问刚才的结果…
      - status [ref=e73]:
        - generic [ref=e74]: 服务端尚未配置回答模型。
        - button "刷新模型" [ref=e75] [cursor=pointer]
      - generic [ref=e76]:
        - button "回答模型：deepseek-flash" [disabled] [ref=e79]:
          - generic [ref=e80]: deepseek-flash
        - button "选择附件" [ref=e83]
        - button "添加附件" [ref=e84] [cursor=pointer]
        - button "发送问题" [disabled] [ref=e87]
      - paragraph [ref=e90]: 模型回答需对照原始数据核查；位置候选源不等于星团成员。
```

# Test source

```ts
  8   |   const errors: string[] = []; page.on('pageerror', e => errors.push(e.message))
  9   |   await page.goto('/')
  10  |   await expect(page.getByRole('heading', { name: '天文数据与文献检索' })).toBeVisible()
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
> 108 |     await page.getByRole('button', { name: '新建会话' }).click()
      |                                                      ^ Error: locator.click: Error: strict mode violation: getByRole('button', { name: '新建会话' }) resolved to 2 elements:
  109 |     await expect(page).toHaveURL(/conversations\/[0-9a-f-]+/)
  110 |     await page.route('**/api/v1/conversations/*/turns', route => route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ error: { code: 'conversation_service_busy', message: '已有两轮正在处理', retryable: true } }) }))
  111 |     await page.getByRole('textbox', { name: '天文问题' }).fill('测试异步加载')
  112 |     await page.getByRole('button', { name: '发送', exact: true }).click()
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