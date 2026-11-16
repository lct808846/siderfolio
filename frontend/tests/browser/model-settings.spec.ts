import { test, expect } from '@playwright/test'
import { mkdirSync } from 'node:fs'
import path from 'node:path'

test('provider editor, directory, default, key omission, conflict and removal', async ({ page }, info) => {
  let revision = 0
  let providers: Record<string, unknown>[] = []
  const writes: Record<string, unknown>[] = []
  let defaultModel = ''
  let conflict = false
  const catalog = () => ({ revision, providers, default_model: defaultModel })
  await page.route('**/api/v1/**', async route => {
    const url = new URL(route.request().url()).pathname
    const method = route.request().method()
    const json = (body: unknown, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) })
    if (url.endsWith('/auth/session')) return json({ user: { id: 'synthetic-admin', email: 'admin@example.org', username: 'Synthetic admin', admin: true, totp_enabled: true, mfa_verified: true }, csrf_token: 'synthetic-csrf', idle_seconds: 1000, absolute_seconds: 2000 })
    if (url.endsWith('/auth/csrf')) return json({ csrf_token: 'synthetic-csrf' })
    if (url.endsWith('/setup/status')) return json({ ready: true, configured: true, deployment_mode: 'container', database_version: 'synthetic', vector_version: 'synthetic', database_schema: 16, answering_configured: true })
    if (url === '/api/v1/models') return json({ configured: providers.length > 0, default_model: defaultModel, models: providers.flatMap(p => p.models) })
    if (url.endsWith('/model-providers/discover')) return json({ models: [{ id: 'synthetic-a', label: 'Synthetic A' }, { id: 'synthetic-b', label: 'Synthetic B' }], truncated: true })
    if (url.endsWith('/model-providers/default')) { defaultModel = route.request().postDataJSON().model; revision++; return json(catalog()) }
    if (url.endsWith('/model-providers') && method === 'GET') return json(catalog())
    if (url.endsWith('/model-providers') && method === 'PUT') {
      const body = route.request().postDataJSON()
      writes.push(body)
      if (conflict) { conflict = false; return json({ error: { code: 'provider_revision_changed', message: '配置已被更新，请刷新后重试。' } }, 409) }
      const publicBody = { ...body }
      delete publicBody.api_key
      providers = [{ ...publicBody, key_configured: true, models: body.models.map((m: { id: string }) => ({ ...m, selection_id: m.id })) }]
      defaultModel ||= String(body.models[0]?.id || '')
      revision++
      return json(catalog())
    }
    if (url.includes('/model-providers/') && method === 'DELETE') { providers = []; defaultModel = ''; revision++; return json(catalog()) }
    return route.continue()
  })
  await page.goto('/settings?section=models')
  await page.getByRole('button', { name: '＋ 添加模型服务商', exact: true }).click()
  const editor = page.getByRole('dialog', { name: '添加模型服务商', exact: true })
  await editor.getByLabel('显示名称', { exact: true }).fill('Synthetic provider')
  await editor.getByRole('button', { name: /^API 协议：/ }).click()
  await page.keyboard.press('End')
  await page.keyboard.press('Enter')
  await expect(editor.getByRole('button', { name: 'API 协议：Google Gemini', exact: true })).toBeVisible()
  await editor.getByLabel('API 地址', { exact: true }).fill('https://models.example.org/v1beta')
  await editor.getByLabel('API 密钥', { exact: true }).fill('synthetic-not-a-credential')
  await expect(editor.getByLabel('API 密钥', { exact: true })).toHaveAttribute('autocomplete', 'off')
  expect(await editor.getByLabel('API 密钥', { exact: true }).evaluate(el => getComputedStyle(el).getPropertyValue('-webkit-text-security'))).toBe('disc')
  for (const width of [1440, 1280, 1024, 768, 681, 680, 390, 320]) {
    await page.setViewportSize({ width, height: 900 })
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
    const bounds = (await editor.boundingBox())!
    expect(bounds.x).toBeGreaterThanOrEqual(0)
    expect(bounds.x + bounds.width).toBeLessThanOrEqual(width + 1)
  }
  await page.setViewportSize({ width: 1440, height: 900 })
  await editor.getByRole('button', { name: '获取可用模型', exact: true }).click()
  const picker = page.getByRole('dialog', { name: '选择模型', exact: true })
  await expect(picker).toContainText('本次仅显示已获取的部分')
  await picker.getByLabel('synthetic-a', { exact: true }).check()
  await picker.getByLabel('synthetic-b', { exact: true }).check()
  await picker.getByRole('button', { name: '更新列表', exact: true }).click()
  await editor.getByRole('button', { name: '保存服务商', exact: true }).click()
  await expect(editor).not.toBeVisible()
  await expect(page.locator('.provider-card')).toContainText('Synthetic provider')
  expect(writes[0]?.protocol).toBe('gemini')
  expect(writes[0]?.api_key).toBe('synthetic-not-a-credential')
  await page.locator('.provider-card details').evaluate(el => { (el as HTMLDetailsElement).open = true })
  await page.getByRole('button', { name: '设为默认', exact: true }).click()
  expect(defaultModel).toBe('synthetic-b')
  await page.getByRole('button', { name: '编辑', exact: true }).click()
  const edit = page.getByRole('dialog', { name: '编辑模型服务商', exact: true })
  await expect(edit.getByLabel('API 密钥', { exact: true })).toHaveValue('')
  conflict = true
  await edit.getByRole('button', { name: '保存服务商', exact: true }).click()
  await expect(edit.getByRole('alert')).toContainText('配置已被更新')
  expect(writes[1]).not.toHaveProperty('api_key')
  await edit.getByRole('button', { name: '关闭服务商编辑', exact: true }).click()
  await page.setViewportSize({ width: 390, height: 740 })
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  if (process.env.ASTROAGENT_RECORD_DIR) {
    mkdirSync(process.env.ASTROAGENT_RECORD_DIR, { recursive: true })
    await page.screenshot({ path: path.join(process.env.ASTROAGENT_RECORD_DIR, info.project.name + '-provider-mobile.png'), fullPage: true })
  }
  await page.getByRole('button', { name: '删除', exact: true }).click()
  await page.getByRole('dialog').getByRole('button', { name: '删除服务商', exact: true }).click()
  await expect(page.locator('.provider-card')).toHaveCount(0)
  expect(await page.evaluate(() => JSON.stringify(localStorage) + JSON.stringify(sessionStorage))).not.toContain('synthetic-not-a-credential')
})

test('ordinary user settings expose only account controls and no admin link', async ({ page }) => {
  let privilegedReads = 0
  await page.route('**/api/v1/**', async route => {
    const url = new URL(route.request().url()).pathname
    const json = (body: unknown) => route.fulfill({ contentType: 'application/json', body: JSON.stringify(body) })
    if (url.endsWith('/auth/session')) return json({ user: { id: 'synthetic-user', email: 'observer@example.org', admin: false, totp_enabled: false, mfa_verified: false }, csrf_token: 'synthetic-csrf' })
    if (url.endsWith('/auth/sessions')) return json([])
    if (url.endsWith('/setup/status') || url.includes('/admin/')) privilegedReads++
    return route.continue()
  })
  await page.goto('/settings?section=models')
  await expect(page.getByRole('heading', { name: '账户安全与登录', exact: true })).toBeVisible()
  await expect(page.getByRole('link', { name: /管理员控制台/ })).toHaveCount(0)
  await expect(page.getByRole('button', { name: '＋ 添加模型服务商', exact: true })).toHaveCount(0)
  expect(privilegedReads).toBe(0)
})

test('RAG and local assistant failures remain readable without starting model jobs', async ({ page, request }, info) => {
  const created = await request.post('/api/v1/projects', { data: { name: 'Synthetic status layout' } })
  expect(created.status()).toBe(201)
  const project = await created.json()
  let jobs = 0
  page.on('request', value => { if (value.method() !== 'GET' && /\/jobs\/|\/rag\/answers/.test(value.url())) jobs++ })
  await page.route('**/api/v1/projects/*/rag/**', route => route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ error: { code: 'synthetic_unavailable', message: 'Synthetic RAG status unavailable' } }) }))
  await page.route('**/api/v1/local-assistant', route => route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ error: { code: 'synthetic_unavailable', message: 'Synthetic local status unavailable' } }) }))
  for (const [url, message] of [[`/projects/${project.id}/rag`, 'Synthetic RAG status unavailable'], ['/local-assistant', 'Synthetic local status unavailable']]) {
    await page.goto(url!)
    await expect(page.getByRole('alert')).toContainText(message!)
    for (const width of [1440, 1024, 768, 390, 320]) {
      await page.setViewportSize({ width, height: 900 })
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
    }
    if (process.env.ASTROAGENT_RECORD_DIR) {
      mkdirSync(process.env.ASTROAGENT_RECORD_DIR, { recursive: true })
      await page.screenshot({ path: path.join(process.env.ASTROAGENT_RECORD_DIR, info.project.name + (url!.includes('/rag') ? '-rag-error.png' : '-assistant-error.png')), fullPage: true })
    }
  }
  expect(jobs).toBe(0)
})

test('administrator layout keeps masked metadata, tabs and current-account protection', async ({ page }, info) => {
  await page.route('**/api/v1/**', async route => {
    const url = new URL(route.request().url()).pathname
    const json = (body: unknown) => route.fulfill({ contentType: 'application/json', body: JSON.stringify(body) })
    if (url.endsWith('/auth/session')) return json({ user: { id: 'synthetic-admin', email: 'admin@example.org', admin: true, totp_enabled: true, mfa_verified: true }, csrf_token: 'synthetic-csrf' })
    if (url.endsWith('/admin/overview')) return json({ users: { total: 2, pending: 0, disabled: 0, administrators: 1 }, mail_configured: false, registration_available: false, mail_hour_limit: 30, registration_limit: 30 })
    if (url.endsWith('/admin/users')) return json([{ id: 'synthetic-admin', email: 'a***@example.org', active: true, admin: true }, { id: 'synthetic-user', email: 'o***@example.org', active: true, admin: false }])
    if (url.endsWith('/admin/mail') || url.endsWith('/admin/audit')) return json([])
    return route.continue()
  })
  await page.goto('/admin')
  await expect(page.getByRole('heading', { name: '账号与服务状态', exact: true })).toBeVisible()
  const current = page.getByRole('row').filter({ hasText: 'a***@example.org' })
  await expect(current.getByText('当前账号', { exact: true })).toBeVisible()
  await expect(current.getByRole('button')).toHaveCount(0)
  await expect(page.getByRole('button', { name: '下一页', exact: true })).toHaveCount(0)
  for (const width of [1440, 1024, 768, 390, 320]) {
    await page.setViewportSize({ width, height: 900 })
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  }
  if (process.env.ASTROAGENT_RECORD_DIR) {
    mkdirSync(process.env.ASTROAGENT_RECORD_DIR, { recursive: true })
    await page.screenshot({ path: path.join(process.env.ASTROAGENT_RECORD_DIR, info.project.name + '-admin-mobile.png'), fullPage: true })
  }
  await page.getByRole('button', { name: '邮件状态', exact: true }).click()
  await expect(page.getByRole('cell', { name: '暂无邮件发送队列记录', exact: true })).toBeVisible()
  await page.getByRole('button', { name: '审计日志', exact: true }).click()
  await expect(page.getByRole('cell', { name: '暂无安全审计日志', exact: true })).toBeVisible()
})
