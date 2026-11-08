import { test, expect, type APIRequestContext } from '@playwright/test'
import { readFile } from 'node:fs/promises'

async function conversation(request: APIRequestContext, title: string) {
  const response = await request.post('/api/v1/conversations', { data: { title } })
  expect(response.status()).toBe(201)
  return response.json()
}

test('clipboard preserves the question and reports a denied copy', async ({ page, request }) => {
  const item = await conversation(request, '复制验收')
  const question = '合成查询第一行\n第二行 Gaia 5853498713190525696'
  const turn = await request.post(`/api/v1/conversations/${item.id}/turns`, { data: { message: question, client_request_id: crypto.randomUUID(), expected_revision: 0 } })
  expect(turn.status()).toBe(200)
  await page.addInitScript(() => {
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText: async (value: string) => {
      const state = window as unknown as { copied: string; rejectCopy: boolean }
      if (state.rejectCopy) throw new Error('denied')
      state.copied = value
    } } })
  })
  await page.goto(`/conversations/${item.id}`)
  const bubble = await page.locator('.user-message').boundingBox()
  const container = await page.locator('.user-message-block').boundingBox()
  expect(bubble).not.toBeNull(); expect(container).not.toBeNull()
  expect(Math.abs((bubble!.x + bubble!.width) - (container!.x + container!.width))).toBeLessThan(4)
  await page.getByRole('button', { name: '复制第1轮问题' }).click()
  expect(await page.evaluate(() => (window as unknown as { copied: string }).copied)).toBe(question)
  await page.evaluate(() => { (window as unknown as { rejectCopy: boolean }).rejectCopy = true })
  await page.getByRole('button', { name: '复制第1轮问题' }).click()
  await expect(page.getByRole('alert')).toContainText('复制未完成')
})

test('pending response does not open results and manual close survives refresh', async ({ page }) => {
  let release!: () => void
  const gate = new Promise<void>(resolve => { release = resolve })
  await page.route('**/api/v1/conversations/*/turns', async route => { await gate; await route.continue() }, { times: 1 })
  try {
    await page.goto('/')
    await page.getByRole('textbox', { name: '天文问题' }).fill('合成 Gaia 查询')
    await page.getByRole('button', { name: '发送问题' }).click()
    await expect(page.getByText('正在处理，请稍候…')).toBeVisible()
    await expect(page.locator('.conversation-layout')).toHaveAttribute('data-results-open', 'false')
    release()
    await expect(page.getByRole('button', { name: '收起结果面板' })).toBeVisible()
    await page.getByRole('button', { name: '收起结果面板' }).click()
    await page.reload()
    await expect(page.locator('.conversation-layout')).toHaveAttribute('data-results-open', 'false')
  } finally { release() }
})

test('rename, pin and export a noncurrent conversation; cancel deletion', async ({ page, request }) => {
  const suffix = crypto.randomUUID().slice(0, 8)
  const firstTitle = `当前验收会话-${suffix}`, otherTitle = `其他验收会话-${suffix}`, renamedTitle = `已改名验收会话-${suffix}`
  const first = await conversation(request, firstTitle)
  const other = await conversation(request, otherTitle)
  const otherTurn = await request.post(`/api/v1/conversations/${other.id}/turns`, { data: { message: '导出验收问题', client_request_id: crypto.randomUUID(), expected_revision: 0 } })
  expect(otherTurn.status()).toBe(200)
  await page.goto(`/conversations/${first.id}`)
  await page.getByRole('button', { name: `会话操作：${otherTitle}` }).click()
  await page.getByRole('menuitem', { name: '重命名' }).click()
  await page.getByRole('textbox', { name: '会话名称' }).fill(renamedTitle)
  await page.getByRole('button', { name: '保存名称' }).click()
  await expect(page.getByRole('heading', { name: firstTitle })).toBeVisible()
  await page.getByRole('button', { name: `会话操作：${renamedTitle}` }).click()
  await page.getByRole('menuitem', { name: '置顶', exact: true }).click()
  await expect(page.locator('.conversation-row').first()).toContainText(renamedTitle)
  await page.getByRole('button', { name: `会话操作：${renamedTitle}` }).click()
  await page.getByRole('menuitem', { name: '导出会话 JSON' }).click()
  const downloaded = page.waitForEvent('download')
  await page.getByRole('button', { name: '确认下载 JSON' }).click()
  const file = await downloaded
  const body = JSON.parse(await readFile((await file.path())!, 'utf8'))
  expect(body.conversation.id).toBe(other.id)
  expect(body.conversation.title).toBe(renamedTitle)
  expect(body.turns).toHaveLength(1)
  expect(body.turns[0].message).toBe('导出验收问题')
  await page.getByRole('button', { name: '多选' }).click()
  await page.getByLabel(`选择会话 ${renamedTitle}`).check()
  await page.getByRole('button', { name: '删除所选' }).click()
  await expect(page.getByRole('dialog')).toContainText(renamedTitle)
  await page.getByRole('dialog').getByRole('button', { name: '取消' }).click()
  expect((await request.get(`/api/v1/conversations/${other.id}`)).status()).toBe(200)
})

test('settings refresh failure clears the previous ready status', async ({ page }) => {
  let calls = 0
  await page.route('**/api/v1/setup/status', async route => {
    calls++
    if (calls === 1) await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ configured: true, ready: true, message: '合成数据库已就绪', code: 'ready', database_version: 'test', database_schema: 6, vector_version: 'test' }) })
    else await route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ error: { code: 'database_unavailable', message: '合成读取失败', retryable: true } }) })
  })
  await page.goto('/settings')
  await expect(page.getByText('业务数据库已就绪')).toBeVisible()
  await page.getByRole('button', { name: '刷新本机状态' }).click()
  await expect(page.getByRole('alert')).toContainText('合成读取失败')
  await expect(page.getByText('本机状态未确认', { exact: true })).toBeVisible()
  await expect(page.getByText('业务数据库已就绪')).toHaveCount(0)
})

test('bulk deletion preserves the failed item and returns after deleting the current item', async ({ page, request }) => {
  const suffix = crypto.randomUUID().slice(0, 8)
  const currentTitle = `待删当前-${suffix}`, failedTitle = `失败保留-${suffix}`
  const current = await conversation(request, currentTitle)
  const failed = await conversation(request, failedTitle)
  await page.route(`**/api/v1/conversations/${failed.id}`, async route => {
    if (route.request().method() === 'DELETE') await route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ error: { code: 'synthetic_failure', message: '合成删除失败', retryable: true } }) })
    else await route.continue()
  })
  await page.goto(`/conversations/${current.id}`)
  await page.getByRole('button', { name: '多选' }).click()
  await page.getByLabel(`选择会话 ${currentTitle}`).check()
  await page.getByLabel(`选择会话 ${failedTitle}`).check()
  await page.getByRole('button', { name: '删除所选' }).click()
  await expect(page.getByRole('dialog')).toContainText(currentTitle)
  await expect(page.getByRole('dialog')).toContainText(failedTitle)
  await page.getByRole('button', { name: '确认删除' }).click()
  await expect(page).toHaveURL(/\/$/)
  await expect(page.getByRole('alert')).toContainText('合成删除失败')
  await expect(page.getByLabel(`选择会话 ${failedTitle}`)).toBeChecked()
  expect((await request.get(`/api/v1/conversations/${current.id}`)).status()).toBe(404)
  expect((await request.get(`/api/v1/conversations/${failed.id}`)).status()).toBe(200)
})

test('project navigation survives direct load and refresh without sending requests', async ({ page, request }) => {
  const response = await request.post('/api/v1/projects', { data: { name: `导航-${crypto.randomUUID().slice(0, 8)}` } })
  expect(response.status()).toBe(201)
  const project = await response.json()
  let writes = 0
  page.on('request', entry => {
    if (entry.method() === 'POST' && /\/turns$|\/rag\/(answers|indexes)$/.test(new URL(entry.url()).pathname)) writes++
  })
  for (const [suffix, label] of [['', '项目记录'], ['/overview', '来源关联'], ['/workflows', '科研流程'], ['/knowledge', '本地知识库'], ['/rag', '文献问答']]) {
    await page.goto(`/projects/${project.id}${suffix}`)
    const link = page.getByRole('navigation', { name: '当前项目导航' }).getByRole('link', { name: label, exact: true })
    await expect(link).toHaveAttribute('aria-current', 'page')
    await page.reload()
    await expect(link).toHaveAttribute('aria-current', 'page')
  }
  expect(writes).toBe(0)
})

test('low-height compact layout keeps focused controls visible and input scrollable', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 500 })
  await page.emulateMedia({ reducedMotion: 'reduce', forcedColors: 'active' })
  await page.goto('/')
  const input = page.getByRole('textbox', { name: '天文问题' })
  await input.fill(Array.from({ length: 18 }, (_, index) => `合成测试第 ${index + 1} 行`).join('\n'))
  await input.focus()
  await expect(input).toBeFocused()
  const inputState = await input.evaluate(node => ({ height: node.clientHeight, scroll: node.scrollHeight, hidden: !!node.closest('[inert], [aria-hidden="true"]') }))
  expect(inputState.hidden).toBe(false)
  expect(inputState.scroll).toBeGreaterThan(inputState.height)
  await page.getByRole('button', { name: '打开结果栏' }).click()
  const close = page.getByRole('button', { name: '收起结果面板' })
  await expect(close).toBeVisible()
  await close.focus()
  expect(await close.evaluate(node => !!node.closest('[inert], [aria-hidden="true"]'))).toBe(false)
  await page.keyboard.press('Enter')
  await expect(input).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
})

test('reduced transparency disables large background blur', async ({ page }) => {
  const session = await page.context().newCDPSession(page)
  await session.send('Emulation.setEmulatedMedia', { features: [{ name: 'prefers-reduced-transparency', value: 'reduce' }] })
  await page.goto('/')
  expect(await page.evaluate(() => matchMedia('(prefers-reduced-transparency: reduce)').matches)).toBe(true)
  const header = page.locator('.workspace-header')
  const composer = page.locator('.composer')
  await expect(header).toHaveCSS('backdrop-filter', 'none')
  await expect(composer).toHaveCSS('backdrop-filter', 'none')
  await expect(page.getByRole('textbox', { name: '天文问题' })).toBeVisible()
})

test('sidebar toggles across compact and desktop boundaries without losing draft', async ({ page }) => {
  await page.goto('/')
  for (const width of [980, 981, 1439, 1440]) {
    await page.setViewportSize({ width, height: 600 })
    await page.evaluate(() => new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))))
    const input = page.getByRole('textbox', { name: '天文问题' })
    await input.fill('侧栏切换时保留的草稿')
    const toggle = page.locator('.history-toggle')
    const initial = await toggle.getAttribute('aria-expanded')
    await toggle.click()
    await expect(toggle).toHaveAttribute('aria-expanded', initial === 'true' ? 'false' : 'true')
    expect(await page.evaluate(() => !!document.activeElement?.closest('[inert], [aria-hidden="true"]'))).toBe(false)
    await toggle.click()
    await expect(input).toHaveValue('侧栏切换时保留的草稿')
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  }
})
