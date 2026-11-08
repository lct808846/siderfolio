# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: remaining-acceptance.spec.ts >> sidebar toggles across compact and desktop boundaries without losing draft
- Location: tests\browser\remaining-acceptance.spec.ts:172:1

# Error details

```
Error: expect(locator).toHaveAttribute(expected) failed

Locator:  locator('.history-toggle')
Expected: "false"
Received: "true"
Timeout:  5000ms

Call log:
  - Expect "toHaveAttribute" locator('.history-toggle') with timeout 5000ms
  - waiting for locator('.history-toggle')
    14 × locator resolved to <button type="button" title="收起会话列表" aria-label="收起会话列表" aria-expanded="true" aria-controls="conversation-history" class="chat-toolbar-button history-toggle">…</button>
       - unexpected value "true"

```

```yaml
- button "收起会话列表" [expanded]
```

# Test source

```ts
  81  | 
  82  | test('settings refresh failure clears the previous ready status', async ({ page }) => {
  83  |   let calls = 0
  84  |   await page.route('**/api/v1/setup/status', async route => {
  85  |     calls++
  86  |     if (calls === 1) await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ configured: true, ready: true, message: '合成数据库已就绪', code: 'ready', database_version: 'test', database_schema: 6, vector_version: 'test' }) })
  87  |     else await route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ error: { code: 'database_unavailable', message: '合成读取失败', retryable: true } }) })
  88  |   })
  89  |   await page.goto('/settings')
  90  |   await expect(page.getByText('业务数据库已就绪')).toBeVisible()
  91  |   await page.getByRole('button', { name: '刷新本机状态' }).click()
  92  |   await expect(page.getByRole('alert')).toContainText('合成读取失败')
  93  |   await expect(page.getByText('本机状态未确认', { exact: true })).toBeVisible()
  94  |   await expect(page.getByText('业务数据库已就绪')).toHaveCount(0)
  95  | })
  96  | 
  97  | test('bulk deletion preserves the failed item and returns after deleting the current item', async ({ page, request }) => {
  98  |   const suffix = crypto.randomUUID().slice(0, 8)
  99  |   const currentTitle = `待删当前-${suffix}`, failedTitle = `失败保留-${suffix}`
  100 |   const current = await conversation(request, currentTitle)
  101 |   const failed = await conversation(request, failedTitle)
  102 |   await page.route(`**/api/v1/conversations/${failed.id}`, async route => {
  103 |     if (route.request().method() === 'DELETE') await route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ error: { code: 'synthetic_failure', message: '合成删除失败', retryable: true } }) })
  104 |     else await route.continue()
  105 |   })
  106 |   await page.goto(`/conversations/${current.id}`)
  107 |   await page.getByRole('button', { name: '多选' }).click()
  108 |   await page.getByLabel(`选择会话 ${currentTitle}`).check()
  109 |   await page.getByLabel(`选择会话 ${failedTitle}`).check()
  110 |   await page.getByRole('button', { name: '删除所选' }).click()
  111 |   await expect(page.getByRole('dialog')).toContainText(currentTitle)
  112 |   await expect(page.getByRole('dialog')).toContainText(failedTitle)
  113 |   await page.getByRole('button', { name: '确认删除' }).click()
  114 |   await expect(page).toHaveURL(/\/$/)
  115 |   await expect(page.getByRole('alert')).toContainText('合成删除失败')
  116 |   await expect(page.getByLabel(`选择会话 ${failedTitle}`)).toBeChecked()
  117 |   expect((await request.get(`/api/v1/conversations/${current.id}`)).status()).toBe(404)
  118 |   expect((await request.get(`/api/v1/conversations/${failed.id}`)).status()).toBe(200)
  119 | })
  120 | 
  121 | test('project navigation survives direct load and refresh without sending requests', async ({ page, request }) => {
  122 |   const response = await request.post('/api/v1/projects', { data: { name: `导航-${crypto.randomUUID().slice(0, 8)}` } })
  123 |   expect(response.status()).toBe(201)
  124 |   const project = await response.json()
  125 |   let writes = 0
  126 |   page.on('request', entry => {
  127 |     if (entry.method() === 'POST' && /\/turns$|\/rag\/(answers|indexes)$/.test(new URL(entry.url()).pathname)) writes++
  128 |   })
  129 |   for (const [suffix, label] of [['', '项目记录'], ['/overview', '来源关联'], ['/workflows', '科研流程'], ['/knowledge', '本地知识库'], ['/rag', '文献问答']]) {
  130 |     await page.goto(`/projects/${project.id}${suffix}`)
  131 |     const link = page.getByRole('navigation', { name: '当前项目导航' }).getByRole('link', { name: label, exact: true })
  132 |     await expect(link).toHaveAttribute('aria-current', 'page')
  133 |     await page.reload()
  134 |     await expect(link).toHaveAttribute('aria-current', 'page')
  135 |   }
  136 |   expect(writes).toBe(0)
  137 | })
  138 | 
  139 | test('low-height compact layout keeps focused controls visible and input scrollable', async ({ page }) => {
  140 |   await page.setViewportSize({ width: 390, height: 500 })
  141 |   await page.emulateMedia({ reducedMotion: 'reduce', forcedColors: 'active' })
  142 |   await page.goto('/')
  143 |   const input = page.getByRole('textbox', { name: '天文问题' })
  144 |   await input.fill(Array.from({ length: 18 }, (_, index) => `合成测试第 ${index + 1} 行`).join('\n'))
  145 |   await input.focus()
  146 |   await expect(input).toBeFocused()
  147 |   const inputState = await input.evaluate(node => ({ height: node.clientHeight, scroll: node.scrollHeight, hidden: !!node.closest('[inert], [aria-hidden="true"]') }))
  148 |   expect(inputState.hidden).toBe(false)
  149 |   expect(inputState.scroll).toBeGreaterThan(inputState.height)
  150 |   await page.getByRole('button', { name: '打开结果栏' }).click()
  151 |   const close = page.getByRole('button', { name: '收起结果面板' })
  152 |   await expect(close).toBeVisible()
  153 |   await close.focus()
  154 |   expect(await close.evaluate(node => !!node.closest('[inert], [aria-hidden="true"]'))).toBe(false)
  155 |   await page.keyboard.press('Enter')
  156 |   await expect(input).toBeVisible()
  157 |   expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  158 | })
  159 | 
  160 | test('reduced transparency disables large background blur', async ({ page }) => {
  161 |   const session = await page.context().newCDPSession(page)
  162 |   await session.send('Emulation.setEmulatedMedia', { features: [{ name: 'prefers-reduced-transparency', value: 'reduce' }] })
  163 |   await page.goto('/')
  164 |   expect(await page.evaluate(() => matchMedia('(prefers-reduced-transparency: reduce)').matches)).toBe(true)
  165 |   const header = page.locator('.workspace-header')
  166 |   const composer = page.locator('.composer')
  167 |   await expect(header).toHaveCSS('backdrop-filter', 'none')
  168 |   await expect(composer).toHaveCSS('backdrop-filter', 'none')
  169 |   await expect(page.getByRole('textbox', { name: '天文问题' })).toBeVisible()
  170 | })
  171 | 
  172 | test('sidebar toggles across compact and desktop boundaries without losing draft', async ({ page }) => {
  173 |   await page.goto('/')
  174 |   for (const width of [980, 981, 1439, 1440]) {
  175 |     await page.setViewportSize({ width, height: 600 })
  176 |     const input = page.getByRole('textbox', { name: '天文问题' })
  177 |     await input.fill('侧栏切换时保留的草稿')
  178 |     const toggle = page.locator('.history-toggle')
  179 |     const initial = await toggle.getAttribute('aria-expanded')
  180 |     await toggle.click()
> 181 |     await expect(toggle).toHaveAttribute('aria-expanded', initial === 'true' ? 'false' : 'true')
      |                          ^ Error: expect(locator).toHaveAttribute(expected) failed
  182 |     expect(await page.evaluate(() => !!document.activeElement?.closest('[inert], [aria-hidden="true"]'))).toBe(false)
  183 |     await toggle.click()
  184 |     await expect(input).toHaveValue('侧栏切换时保留的草稿')
  185 |     expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  186 |   }
  187 | })
  188 | 
```