# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: remaining-acceptance.spec.ts >> rename, pin and export a noncurrent conversation; cancel deletion
- Location: tests\browser\remaining-acceptance.spec.ts:48:1

# Error details

```
Error: locator.click: Error: strict mode violation: getByRole('button', { name: '会话操作：已改名验收会话' }) resolved to 2 elements:
    1) <button disabled data-tooltip="" aria-haspopup="menu" aria-expanded="false" class="conversation-more" aria-label="会话操作：已改名验收会话">⋯</button> aka getByRole('button', { name: '会话操作：已改名验收会话' }).first()
    2) <button disabled data-tooltip="" aria-haspopup="menu" aria-expanded="false" class="conversation-more" aria-label="会话操作：已改名验收会话">⋯</button> aka getByRole('button', { name: '会话操作：已改名验收会话' }).nth(1)

Call log:
  - waiting for getByRole('button', { name: '会话操作：已改名验收会话' })

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
      - generic [ref=e18]: 8/20
    - button "新建会话" [ref=e19] [cursor=pointer]:
      - generic [aria-hidden] [ref=e20]: ＋
      - text: 新建会话
    - generic [ref=e21]:
      - paragraph [ref=e22]: 本地会话
      - button "多选" [ref=e23] [cursor=pointer]
    - status [ref=e24]: 会话已重命名。
    - navigation "本地会话" [ref=e25]:
      - generic [ref=e26]:
        - button "已改名验收会话 0 轮 · 2026/11/8" [ref=e27] [cursor=pointer]:
          - generic [aria-hidden] [ref=e28]: ◌
          - generic [ref=e29]:
            - generic [ref=e30]: 已改名验收会话
            - generic [ref=e31]: 0 轮 · 2026/11/8
        - button "会话操作：已改名验收会话" [ref=e32] [cursor=pointer]: ⋯
      - generic [ref=e33]:
        - button "当前验收会话 0 轮 · 2026/11/8" [ref=e34] [cursor=pointer]:
          - generic [aria-hidden] [ref=e35]: ◌
          - generic [ref=e36]:
            - generic [ref=e37]: 当前验收会话
            - generic [ref=e38]: 0 轮 · 2026/11/8
        - button "会话操作：当前验收会话" [ref=e39] [cursor=pointer]: ⋯
      - generic [ref=e40]:
        - button "合成 Gaia 查询 1 轮 · 2026/11/8" [ref=e41] [cursor=pointer]:
          - generic [aria-hidden] [ref=e42]: ◌
          - generic [ref=e43]:
            - generic [ref=e44]: 合成 Gaia 查询
            - generic [ref=e45]: 1 轮 · 2026/11/8
        - button "会话操作：合成 Gaia 查询" [ref=e46] [cursor=pointer]: ⋯
      - generic [ref=e47]:
        - button "复制验收 1 轮 · 2026/11/8" [ref=e48] [cursor=pointer]:
          - generic [aria-hidden] [ref=e49]: ◌
          - generic [ref=e50]:
            - generic [ref=e51]: 复制验收
            - generic [ref=e52]: 1 轮 · 2026/11/8
        - button "会话操作：复制验收" [ref=e53] [cursor=pointer]: ⋯
      - generic [ref=e54]:
        - button "已改名验收会话 0 轮 · 2026/11/8" [ref=e55] [cursor=pointer]:
          - generic [aria-hidden] [ref=e56]: ◌
          - generic [ref=e57]:
            - generic [ref=e58]: 已改名验收会话
            - generic [ref=e59]: 0 轮 · 2026/11/8
        - button "会话操作：已改名验收会话" [ref=e60] [cursor=pointer]: ⋯
      - generic [ref=e61]:
        - button "当前验收会话 0 轮 · 2026/11/8" [ref=e62] [cursor=pointer]:
          - generic [aria-hidden] [ref=e63]: ◌
          - generic [ref=e64]:
            - generic [ref=e65]: 当前验收会话
            - generic [ref=e66]: 0 轮 · 2026/11/8
        - button "会话操作：当前验收会话" [ref=e67] [cursor=pointer]: ⋯
      - generic [ref=e68]:
        - button "合成 Gaia 查询 1 轮 · 2026/11/8" [ref=e69] [cursor=pointer]:
          - generic [aria-hidden] [ref=e70]: ◌
          - generic [ref=e71]:
            - generic [ref=e72]: 合成 Gaia 查询
            - generic [ref=e73]: 1 轮 · 2026/11/8
        - button "会话操作：合成 Gaia 查询" [ref=e74] [cursor=pointer]: ⋯
      - generic [ref=e75]:
        - button "复制验收 1 轮 · 2026/11/8" [ref=e76] [cursor=pointer]:
          - generic [aria-hidden] [ref=e77]: ◌
          - generic [ref=e78]:
            - generic [ref=e79]: 复制验收
            - generic [ref=e80]: 1 轮 · 2026/11/8
        - button "会话操作：复制验收" [ref=e81] [cursor=pointer]: ⋯
    - generic [ref=e82]:
      - text: SIMBAD / ADS / Gaia
      - generic [ref=e83]: 测量 · 文献 · 可追溯结果
  - main [ref=e84]:
    - generic [ref=e85]:
      - button "收起会话列表" [expanded] [ref=e86] [cursor=pointer]
      - heading "当前验收会话" [level=1] [ref=e90]
      - button "打开结果栏" [ref=e91] [cursor=pointer]
    - generic [ref=e96]:
      - generic [ref=e98]:
        - paragraph [ref=e99]: SIMBAD · ADS · Gaia DR3
        - heading "天文数据与文献检索" [level=2] [ref=e100]
        - paragraph [ref=e101]: 查询天体、Gaia 测量和论文，保留每轮来源与结果。
      - generic [ref=e102]:
        - button "坐标圆锥查询" [ref=e103] [cursor=pointer]:
          - generic [aria-hidden] [ref=e105]: ↗
        - button "指定 DR3 编号" [ref=e106] [cursor=pointer]:
          - generic [aria-hidden] [ref=e108]: ↗
        - button "ADS 文献检索" [ref=e109] [cursor=pointer]:
          - generic [aria-hidden] [ref=e111]: ↗
      - paragraph [ref=e112]: 示例仅填入输入框，由你确认发送。
    - generic [ref=e113]:
      - generic [ref=e114]: 天文问题
      - textbox "天文问题" [ref=e115]:
        - /placeholder: 输入一个天文问题，或继续追问刚才的结果…
      - generic [ref=e116]:
        - button "回答模型：synthetic-model" [ref=e119] [cursor=pointer]:
          - generic [ref=e120]: synthetic-model
        - button "选择附件" [ref=e123]
        - button "添加附件" [ref=e124] [cursor=pointer]
        - button "发送问题" [disabled] [ref=e127]
      - paragraph [ref=e130]: 模型回答需对照原始数据核查；位置候选源不等于星团成员。
```

# Test source

```ts
  1  | import { test, expect, type APIRequestContext } from '@playwright/test'
  2  | import { readFile } from 'node:fs/promises'
  3  | 
  4  | async function conversation(request: APIRequestContext, title: string) {
  5  |   const response = await request.post('/api/v1/conversations', { data: { title } })
  6  |   expect(response.status()).toBe(201)
  7  |   return response.json()
  8  | }
  9  | 
  10 | test('clipboard preserves the question and reports a denied copy', async ({ page, request }) => {
  11 |   const item = await conversation(request, '复制验收')
  12 |   const question = '合成查询第一行\n第二行 Gaia 5853498713190525696'
  13 |   const turn = await request.post(`/api/v1/conversations/${item.id}/turns`, { data: { message: question, client_request_id: crypto.randomUUID(), expected_revision: 0 } })
  14 |   expect(turn.status()).toBe(200)
  15 |   await page.addInitScript(() => {
  16 |     Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText: async (value: string) => {
  17 |       const state = window as unknown as { copied: string; rejectCopy: boolean }
  18 |       if (state.rejectCopy) throw new Error('denied')
  19 |       state.copied = value
  20 |     } } })
  21 |   })
  22 |   await page.goto(`/conversations/${item.id}`)
  23 |   await page.getByRole('button', { name: '复制第1轮问题' }).click()
  24 |   expect(await page.evaluate(() => (window as unknown as { copied: string }).copied)).toBe(question)
  25 |   await page.evaluate(() => { (window as unknown as { rejectCopy: boolean }).rejectCopy = true })
  26 |   await page.getByRole('button', { name: '复制第1轮问题' }).click()
  27 |   await expect(page.getByRole('alert')).toContainText('复制未完成')
  28 | })
  29 | 
  30 | test('pending response does not open results and manual close survives refresh', async ({ page }) => {
  31 |   let release!: () => void
  32 |   const gate = new Promise<void>(resolve => { release = resolve })
  33 |   await page.route('**/api/v1/conversations/*/turns', async route => { await gate; await route.continue() }, { times: 1 })
  34 |   try {
  35 |     await page.goto('/')
  36 |     await page.getByRole('textbox', { name: '天文问题' }).fill('合成 Gaia 查询')
  37 |     await page.getByRole('button', { name: '发送问题' }).click()
  38 |     await expect(page.getByText('正在处理，请稍候…')).toBeVisible()
  39 |     await expect(page.locator('.conversation-layout')).toHaveAttribute('data-results-open', 'false')
  40 |     release()
  41 |     await expect(page.getByRole('button', { name: '收起结果面板' })).toBeVisible()
  42 |     await page.getByRole('button', { name: '收起结果面板' }).click()
  43 |     await page.reload()
  44 |     await expect(page.locator('.conversation-layout')).toHaveAttribute('data-results-open', 'false')
  45 |   } finally { release() }
  46 | })
  47 | 
  48 | test('rename, pin and export a noncurrent conversation; cancel deletion', async ({ page, request }) => {
  49 |   const first = await conversation(request, '当前验收会话')
  50 |   const other = await conversation(request, '其他验收会话')
  51 |   await page.goto(`/conversations/${first.id}`)
  52 |   await page.getByRole('button', { name: '会话操作：其他验收会话' }).click()
  53 |   await page.getByRole('menuitem', { name: '重命名' }).click()
  54 |   await page.getByRole('textbox', { name: '会话名称' }).fill('已改名验收会话')
  55 |   await page.getByRole('button', { name: '保存名称' }).click()
  56 |   await expect(page.getByRole('heading', { name: '当前验收会话' })).toBeVisible()
> 57 |   await page.getByRole('button', { name: '会话操作：已改名验收会话' }).click()
     |                                                            ^ Error: locator.click: Error: strict mode violation: getByRole('button', { name: '会话操作：已改名验收会话' }) resolved to 2 elements:
  58 |   await page.getByRole('menuitem', { name: '置顶', exact: true }).click()
  59 |   await expect(page.locator('.conversation-row').first()).toContainText('已改名验收会话')
  60 |   await page.getByRole('button', { name: '会话操作：已改名验收会话' }).click()
  61 |   await page.getByRole('menuitem', { name: '导出会话 JSON' }).click()
  62 |   const downloaded = page.waitForEvent('download')
  63 |   await page.getByRole('button', { name: '确认下载 JSON' }).click()
  64 |   const file = await downloaded
  65 |   const body = JSON.parse(await readFile((await file.path())!, 'utf8'))
  66 |   expect(body.conversation.id).toBe(other.id)
  67 |   expect(body.conversation.title).toBe('已改名验收会话')
  68 |   await page.getByRole('button', { name: '多选' }).click()
  69 |   await page.getByLabel('选择会话 已改名验收会话').check()
  70 |   await page.getByRole('button', { name: '删除所选' }).click()
  71 |   await expect(page.getByRole('dialog')).toContainText('已改名验收会话')
  72 |   await page.getByRole('dialog').getByRole('button', { name: '取消' }).click()
  73 |   expect((await request.get(`/api/v1/conversations/${other.id}`)).status()).toBe(200)
  74 | })
  75 | 
  76 | test('settings refresh failure clears the previous ready status', async ({ page }) => {
  77 |   let calls = 0
  78 |   await page.route('**/api/v1/setup/status', async route => {
  79 |     calls++
  80 |     if (calls === 1) await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ configured: true, ready: true, message: '合成数据库已就绪', code: 'ready', database_version: 'test', database_schema: 6, vector_version: 'test' }) })
  81 |     else await route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ error: { code: 'database_unavailable', message: '合成读取失败', retryable: true } }) })
  82 |   })
  83 |   await page.goto('/settings')
  84 |   await expect(page.getByText('业务数据库已就绪')).toBeVisible()
  85 |   await page.getByRole('button', { name: '刷新本机状态' }).click()
  86 |   await expect(page.getByRole('alert')).toContainText('合成读取失败')
  87 |   await expect(page.getByText('本机状态未确认')).toBeVisible()
  88 |   await expect(page.getByText('业务数据库已就绪')).toHaveCount(0)
  89 | })
  90 | 
```