# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: remaining-acceptance.spec.ts >> settings refresh failure clears the previous ready status
- Location: tests\browser\remaining-acceptance.spec.ts:76:1

# Error details

```
Error: expect(locator).toBeVisible() failed

Locator: getByText('本机状态未确认')
Expected: visible
Error: strict mode violation: getByText('本机状态未确认') resolved to 2 elements:
    1) <span class="tag error">本机状态未确认</span> aka getByText('本机状态未确认', { exact: true })
    2) <p>本机状态未确认，请先读取配置。</p> aka getByText('本机状态未确认，请先读取配置。')

Call log:
  - Expect "toBeVisible" getByText('本机状态未确认') with timeout 5000ms
  - waiting for getByText('本机状态未确认')

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
  - main [ref=e15]:
    - generic [ref=e16]:
      - heading "本机设置" [level=1] [ref=e17]
      - button "刷新本机状态" [ref=e18] [cursor=pointer]
    - generic [ref=e20]:
      - paragraph [ref=e21]: 在这里查看数据库、本地嵌入模型和回答服务的配置状态。配置与密钥由服务端管理。
      - generic [ref=e22]: 本机状态未确认
      - alert [ref=e24]: 合成读取失败
      - generic [ref=e25]:
        - heading "1 · PostgreSQL 数据库" [level=2] [ref=e26]
        - paragraph [ref=e27]:
          - text: 在服务端环境设置
          - code [ref=e28]: ASTROAGENT_DATABASE_URL
          - text: ，连接本机、独立且为空的 PostgreSQL 数据库，然后重启后端。连接示例仅说明格式：
        - generic [ref=e29]: postgresql://astroagent:<服务端密码>@127.0.0.1:5432/astroagent
        - paragraph [ref=e30]: 连接串不能放进 VITE_、浏览器存储、截图或版本仓库。pgvector 和 pg_trgm 需先在数据库服务器安装；初始化账号需有启用扩展及建表权限。
        - paragraph [ref=e31]: 旧 V0.9 SQLite 不会被自动打开或迁移；迁移到独立新库需按维护手册显式执行，旧备份保留。
      - generic [ref=e32]:
        - heading "2 · 本地嵌入模型" [level=2] [ref=e33]
        - paragraph [ref=e34]: 本机状态未确认，请先读取配置。
        - paragraph [ref=e35]: 模型：未确认 · 目标维度 未确认。向量预算 未确认 字节。
        - paragraph [ref=e36]:
          - text: 先检查固定版本的模型来源、许可和下载体积，再用维护工具确认下载或准备离线文件。设置服务端的
          - code [ref=e37]: ASTROAGENT_RAG_MODEL_PATH
          - text: 与
          - code [ref=e38]: ASTROAGENT_RAG_MODEL_SHA256
          - text: 后重启。运行时只加载本地固定文件，不静默换模型。
        - link "查看候选模型来源与许可 ↗" [ref=e39] [cursor=pointer]:
          - /url: https://huggingface.co/sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2
        - paragraph [ref=e40]: 模型与向量各有预算；CPU子进程限120秒、3 GiB。扫描PDF仍不支持OCR，嵌入不能补回缺失文字。
      - generic [ref=e41]:
        - heading "3 · 回答服务与文本发送" [level=2] [ref=e42]
        - paragraph [ref=e43]: 回答服务配置状态未确认，请先读取本机状态。
        - paragraph [ref=e44]: 服务：未确认 · 模型：未确认
        - paragraph [ref=e45]: 已启用：synthetic-model。可在工作台输入区和文献问答中切换。
        - paragraph [ref=e46]: 仅在“知识问答”中看到本次问题、片段及所选历史，并确认后才发送。取消、上传、建索引和旧聊天都不会自动将文献交给回答模型。
      - generic [ref=e47]:
        - heading "4 · 开始使用与保留数据" [level=2] [ref=e48]
        - list [ref=e49]:
          - listitem [ref=e50]: 新建项目，上传文本型PDF或Markdown，核对解析状态和页行。
          - listitem [ref=e51]: 进入知识问答，显式构建本地索引；失败时查看状态，词法检索可单独使用。
          - listitem [ref=e52]: 输入问题，选择文档，核对证据及服务，确认生成，再逐条回查原文。
          - listitem [ref=e53]: 使用含原文的项目格式5包迁移单个项目；整库备份使用PostgreSQL维护工具。
        - paragraph [ref=e54]: 备份可能包含私人原文和问答，请保存在你控制的位置。恢复到全新数据库；卸载程序默认保留数据库、模型和备份。
        - link "打开项目工作区 →" [ref=e55] [cursor=pointer]:
          - /url: /projects
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
  57 |   await page.getByRole('button', { name: '会话操作：已改名验收会话' }).click()
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
> 87 |   await expect(page.getByText('本机状态未确认')).toBeVisible()
     |                                           ^ Error: expect(locator).toBeVisible() failed
  88 |   await expect(page.getByText('业务数据库已就绪')).toHaveCount(0)
  89 | })
  90 | 
```