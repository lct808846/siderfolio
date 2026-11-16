# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: remaining-acceptance.spec.ts >> settings refresh failure clears the previous ready status
- Location: tests\browser\remaining-acceptance.spec.ts:86:1

# Error details

```
Test timeout of 60000ms exceeded.
```

```
Error: locator.click: Test timeout of 60000ms exceeded.
Call log:
  - waiting for getByRole('button', { name: '刷新本机状态' })

```

# Page snapshot

```yaml
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
  - main [ref=e18]:
    - complementary "设置导航" [ref=e19]:
      - button "返回应用" [ref=e20] [cursor=pointer]
      - heading "设置" [level=1] [ref=e24]
      - searchbox "搜索设置" [ref=e29]
      - generic [ref=e30]:
        - generic [ref=e31]: 个人资料
        - link "fixture" [ref=e32] [cursor=pointer]:
          - /url: /profile
          - generic [aria-hidden] [ref=e33]: FI
          - generic [aria-hidden] [ref=e35]: ↗
        - generic [ref=e36]: 账户
        - navigation "账户设置" [ref=e37]:
          - button "账户安全与登录" [ref=e38] [cursor=pointer]
          - button "账户" [ref=e42] [cursor=pointer]
        - generic [ref=e46]: 工作台
        - navigation "工作台设置" [ref=e47]:
          - button "概览" [ref=e48] [cursor=pointer]
          - button "模型" [ref=e52] [cursor=pointer]
          - button "本地助手" [ref=e56] [cursor=pointer]
          - button "检索与存储" [ref=e60] [cursor=pointer]
          - button "数据管理" [ref=e64] [cursor=pointer]
      - link "管理员控制台" [ref=e69] [cursor=pointer]:
        - /url: /admin
        - generic [aria-hidden] [ref=e73]: ↗
    - generic [ref=e75]:
      - generic [ref=e76]:
        - heading "概览" [level=2] [ref=e77]
        - paragraph [ref=e78]: 查看当前工作环境与服务状态。
      - generic [ref=e79]:
        - region [ref=e80]:
          - generic [ref=e81]:
            - heading "工作环境" [level=3] [ref=e82]
            - generic [ref=e83]: 业务数据库已就绪
          - generic [ref=e84]:
            - generic [ref=e85]:
              - heading "部署方式" [level=4] [ref=e86]
              - paragraph [ref=e87]: 当前工作台连接的运行环境
            - generic [ref=e88]: 本机部署
          - generic [ref=e89]:
            - generic [ref=e90]:
              - heading "配置状态" [level=4] [ref=e91]
              - paragraph [ref=e92]: 最近读取：2026/11/16 15:30:18（北京时间）
            - generic [ref=e93]: 正常
        - region [ref=e94]:
          - heading "核心服务就绪度" [level=3] [ref=e95]
          - generic [ref=e96]:
            - generic [ref=e97]:
              - heading "回答服务" [level=4] [ref=e98]
              - paragraph [ref=e99]: 工作台对话与文献问答使用的远程或本地大模型
            - generic [ref=e100]: 未配置
          - generic [ref=e101]:
            - generic [ref=e102]:
              - heading "业务数据库" [level=4] [ref=e103]
              - paragraph [ref=e104]: 会话、项目与科研记录持久化存储（PostgreSQL / pgvector）
            - generic [ref=e105]: 已就绪
          - generic [ref=e106]:
            - generic [ref=e107]:
              - heading "语义检索" [level=4] [ref=e108]
              - paragraph [ref=e109]: 本地多语言嵌入模型配置状态
            - generic [ref=e110]: 未配置
          - paragraph [ref=e111]: 配置状态不代表已通过外部服务连通性或回答质量验收；详细参数可在左侧对应分类中查看。
```

# Test source

```ts
  1   | import { test, expect, type APIRequestContext } from '@playwright/test'
  2   | import { readFile } from 'node:fs/promises'
  3   | 
  4   | async function conversation(request: APIRequestContext, title: string) {
  5   |   const response = await request.post('/api/v1/conversations', { data: { title } })
  6   |   expect(response.status()).toBe(201)
  7   |   return response.json()
  8   | }
  9   | 
  10  | test('clipboard preserves the question and reports a denied copy', async ({ page, request }) => {
  11  |   const item = await conversation(request, '复制验收')
  12  |   const question = '合成查询第一行\n第二行 Gaia 5853498713190525696'
  13  |   const turn = await request.post(`/api/v1/conversations/${item.id}/turns`, { data: { message: question, client_request_id: crypto.randomUUID(), expected_revision: 0 } })
  14  |   expect(turn.status()).toBe(200)
  15  |   await page.addInitScript(() => {
  16  |     Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText: async (value: string) => {
  17  |       const state = window as unknown as { copied: string; rejectCopy: boolean }
  18  |       if (state.rejectCopy) throw new Error('denied')
  19  |       state.copied = value
  20  |     } } })
  21  |   })
  22  |   await page.goto(`/conversations/${item.id}`)
  23  |   const bubble = await page.locator('.user-message').boundingBox()
  24  |   const container = await page.locator('.user-message-block').boundingBox()
  25  |   expect(bubble).not.toBeNull(); expect(container).not.toBeNull()
  26  |   expect(Math.abs((bubble!.x + bubble!.width) - (container!.x + container!.width))).toBeLessThan(4)
  27  |   await page.getByRole('button', { name: '复制第1轮问题' }).click()
  28  |   expect(await page.evaluate(() => (window as unknown as { copied: string }).copied)).toBe(question)
  29  |   await page.evaluate(() => { (window as unknown as { rejectCopy: boolean }).rejectCopy = true })
  30  |   await page.getByRole('button', { name: '复制第1轮问题' }).click()
  31  |   await expect(page.getByRole('alert')).toContainText('复制未完成')
  32  | })
  33  | 
  34  | test('pending response does not open results and manual close survives refresh', async ({ page }) => {
  35  |   let release!: () => void
  36  |   const gate = new Promise<void>(resolve => { release = resolve })
  37  |   await page.route('**/api/v1/conversations/*/turns', async route => { await gate; await route.continue() }, { times: 1 })
  38  |   try {
  39  |     await page.goto('/')
  40  |     await page.getByRole('textbox', { name: '天文问题' }).fill('合成 Gaia 查询')
  41  |     await page.getByRole('button', { name: '发送问题' }).click()
  42  |     await expect(page.getByText('正在处理，请稍候…')).toBeVisible()
  43  |     await expect(page.locator('.conversation-layout')).toHaveAttribute('data-results-open', 'false')
  44  |     release()
  45  |     await expect(page.getByRole('button', { name: '收起结果面板' })).toBeVisible()
  46  |     await page.getByRole('button', { name: '收起结果面板' }).click()
  47  |     await page.reload()
  48  |     await expect(page.locator('.conversation-layout')).toHaveAttribute('data-results-open', 'false')
  49  |   } finally { release() }
  50  | })
  51  | 
  52  | test('rename, pin and export a noncurrent conversation; cancel deletion', async ({ page, request }) => {
  53  |   const suffix = crypto.randomUUID().slice(0, 8)
  54  |   const firstTitle = `当前验收会话-${suffix}`, otherTitle = `其他验收会话-${suffix}`, renamedTitle = `已改名验收会话-${suffix}`
  55  |   const first = await conversation(request, firstTitle)
  56  |   const other = await conversation(request, otherTitle)
  57  |   const otherTurn = await request.post(`/api/v1/conversations/${other.id}/turns`, { data: { message: '导出验收问题', client_request_id: crypto.randomUUID(), expected_revision: 0 } })
  58  |   expect(otherTurn.status()).toBe(200)
  59  |   await page.goto(`/conversations/${first.id}`)
  60  |   await page.getByRole('button', { name: `会话操作：${otherTitle}` }).click()
  61  |   await page.getByRole('menuitem', { name: '重命名' }).click()
  62  |   await page.getByRole('textbox', { name: '会话名称' }).fill(renamedTitle)
  63  |   await page.getByRole('button', { name: '保存名称' }).click()
  64  |   await expect(page.getByRole('heading', { name: firstTitle })).toBeVisible()
  65  |   await page.getByRole('button', { name: `会话操作：${renamedTitle}` }).click()
  66  |   await page.getByRole('menuitem', { name: '置顶', exact: true }).click()
  67  |   await expect(page.locator('.conversation-row').first()).toContainText(renamedTitle)
  68  |   await page.getByRole('button', { name: `会话操作：${renamedTitle}` }).click()
  69  |   await page.getByRole('menuitem', { name: '导出会话 JSON' }).click()
  70  |   const downloaded = page.waitForEvent('download')
  71  |   await page.getByRole('button', { name: '确认下载 JSON' }).click()
  72  |   const file = await downloaded
  73  |   const body = JSON.parse(await readFile((await file.path())!, 'utf8'))
  74  |   expect(body.conversation.id).toBe(other.id)
  75  |   expect(body.conversation.title).toBe(renamedTitle)
  76  |   expect(body.turns).toHaveLength(1)
  77  |   expect(body.turns[0].message).toBe('导出验收问题')
  78  |   await page.getByRole('button', { name: '多选' }).click()
  79  |   await page.getByLabel(`选择会话 ${renamedTitle}`).check()
  80  |   await page.getByRole('button', { name: '删除所选' }).click()
  81  |   await expect(page.getByRole('dialog')).toContainText(renamedTitle)
  82  |   await page.getByRole('dialog').getByRole('button', { name: '取消' }).click()
  83  |   expect((await request.get(`/api/v1/conversations/${other.id}`)).status()).toBe(200)
  84  | })
  85  | 
  86  | test('settings refresh failure clears the previous ready status', async ({ page }) => {
  87  |   let calls = 0
  88  |   await page.route('**/api/v1/setup/status', async route => {
  89  |     calls++
  90  |     if (calls === 1) await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ configured: true, ready: true, message: '合成数据库已就绪', code: 'ready', database_version: 'test', database_schema: 6, vector_version: 'test' }) })
  91  |     else await route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ error: { code: 'database_unavailable', message: '合成读取失败', retryable: true } }) })
  92  |   })
  93  |   await page.goto('/settings?section=general')
  94  |   await expect(page.getByText('业务数据库已就绪')).toBeVisible()
> 95  |   await page.getByRole('button', { name: '刷新本机状态' }).click()
      |                                                      ^ Error: locator.click: Test timeout of 60000ms exceeded.
  96  |   await expect(page.getByRole('alert')).toContainText('合成读取失败')
  97  |   await expect(page.getByText('本机状态未确认', { exact: true })).toBeVisible()
  98  |   await expect(page.getByText('业务数据库已就绪')).toHaveCount(0)
  99  | })
  100 | 
  101 | test('bulk deletion preserves the failed item and returns after deleting the current item', async ({ page, request }) => {
  102 |   const suffix = crypto.randomUUID().slice(0, 8)
  103 |   const currentTitle = `待删当前-${suffix}`, failedTitle = `失败保留-${suffix}`
  104 |   const current = await conversation(request, currentTitle)
  105 |   const failed = await conversation(request, failedTitle)
  106 |   await page.route(`**/api/v1/conversations/${failed.id}`, async route => {
  107 |     if (route.request().method() === 'DELETE') await route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ error: { code: 'synthetic_failure', message: '合成删除失败', retryable: true } }) })
  108 |     else await route.continue()
  109 |   })
  110 |   await page.goto(`/conversations/${current.id}`)
  111 |   await page.getByRole('button', { name: '多选' }).click()
  112 |   await page.getByLabel(`选择会话 ${currentTitle}`).check()
  113 |   await page.getByLabel(`选择会话 ${failedTitle}`).check()
  114 |   await page.getByRole('button', { name: '删除所选' }).click()
  115 |   await expect(page.getByRole('dialog')).toContainText(currentTitle)
  116 |   await expect(page.getByRole('dialog')).toContainText(failedTitle)
  117 |   await page.getByRole('button', { name: '确认删除' }).click()
  118 |   await expect(page).toHaveURL(/\/$/)
  119 |   await expect(page.getByRole('alert')).toContainText('合成删除失败')
  120 |   await expect(page.getByLabel(`选择会话 ${failedTitle}`)).toBeChecked()
  121 |   expect((await request.get(`/api/v1/conversations/${current.id}`)).status()).toBe(404)
  122 |   expect((await request.get(`/api/v1/conversations/${failed.id}`)).status()).toBe(200)
  123 | })
  124 | 
  125 | test('project navigation survives direct load and refresh without sending requests', async ({ page, request }) => {
  126 |   const response = await request.post('/api/v1/projects', { data: { name: `导航-${crypto.randomUUID().slice(0, 8)}` } })
  127 |   expect(response.status()).toBe(201)
  128 |   const project = await response.json()
  129 |   let writes = 0
  130 |   page.on('request', entry => {
  131 |     if (entry.method() === 'POST' && /\/turns$|\/rag\/(answers|indexes)$/.test(new URL(entry.url()).pathname)) writes++
  132 |   })
  133 |   for (const [suffix, label] of [['', '项目记录'], ['/overview', '来源关联'], ['/workflows', '科研流程'], ['/knowledge', '本地知识库'], ['/rag', '文献问答']]) {
  134 |     await page.goto(`/projects/${project.id}${suffix}`)
  135 |     const link = page.getByRole('navigation', { name: '当前项目导航' }).getByRole('link', { name: label, exact: true })
  136 |     await expect(link).toHaveAttribute('aria-current', 'page')
  137 |     await page.reload()
  138 |     await expect(link).toHaveAttribute('aria-current', 'page')
  139 |   }
  140 |   expect(writes).toBe(0)
  141 | })
  142 | 
  143 | test('low-height compact layout keeps focused controls visible and input scrollable', async ({ page }) => {
  144 |   await page.setViewportSize({ width: 390, height: 500 })
  145 |   await page.emulateMedia({ reducedMotion: 'reduce', forcedColors: 'active' })
  146 |   await page.goto('/')
  147 |   const input = page.getByRole('textbox', { name: '天文问题' })
  148 |   await input.fill(Array.from({ length: 18 }, (_, index) => `合成测试第 ${index + 1} 行`).join('\n'))
  149 |   await input.focus()
  150 |   await expect(input).toBeFocused()
  151 |   const inputState = await input.evaluate(node => ({ height: node.clientHeight, scroll: node.scrollHeight, hidden: !!node.closest('[inert], [aria-hidden="true"]') }))
  152 |   expect(inputState.hidden).toBe(false)
  153 |   expect(inputState.scroll).toBeGreaterThan(inputState.height)
  154 |   await page.getByRole('button', { name: '打开结果栏' }).click()
  155 |   const close = page.getByRole('button', { name: '收起结果面板' })
  156 |   await expect(close).toBeVisible()
  157 |   await close.focus()
  158 |   expect(await close.evaluate(node => !!node.closest('[inert], [aria-hidden="true"]'))).toBe(false)
  159 |   await page.keyboard.press('Enter')
  160 |   await expect(input).toBeVisible()
  161 |   expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  162 | })
  163 | 
  164 | test('reduced transparency disables large background blur', async ({ page }) => {
  165 |   const session = await page.context().newCDPSession(page)
  166 |   await session.send('Emulation.setEmulatedMedia', { features: [{ name: 'prefers-reduced-transparency', value: 'reduce' }] })
  167 |   await page.goto('/')
  168 |   expect(await page.evaluate(() => matchMedia('(prefers-reduced-transparency: reduce)').matches)).toBe(true)
  169 |   const header = page.locator('.workspace-header')
  170 |   const composer = page.locator('.composer')
  171 |   await expect(header).toHaveCSS('backdrop-filter', 'none')
  172 |   await expect(composer).toHaveCSS('backdrop-filter', 'none')
  173 |   await expect(page.getByRole('textbox', { name: '天文问题' })).toBeVisible()
  174 | })
  175 | 
  176 | test('sidebar toggles across compact and desktop boundaries without losing draft', async ({ page }) => {
  177 |   await page.goto('/')
  178 |   for (const width of [980, 981, 1439, 1440]) {
  179 |     await page.setViewportSize({ width, height: 600 })
  180 |     await page.evaluate(() => new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))))
  181 |     const input = page.getByRole('textbox', { name: '天文问题' })
  182 |     await input.fill('侧栏切换时保留的草稿')
  183 |     const toggle = page.locator('.history-toggle')
  184 |     const initial = await toggle.getAttribute('aria-expanded')
  185 |     await toggle.click()
  186 |     await expect(toggle).toHaveAttribute('aria-expanded', initial === 'true' ? 'false' : 'true')
  187 |     expect(await page.evaluate(() => !!document.activeElement?.closest('[inert], [aria-hidden="true"]'))).toBe(false)
  188 |     await toggle.click()
  189 |     await expect(input).toHaveValue('侧栏切换时保留的草稿')
  190 |     expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  191 |   }
  192 | })
  193 | 
```