import { test, expect, type Page } from '@playwright/test'

const password = 'Synthetic nebula entropy 2048'
async function login(page: Page, email: string) {
  await page.goto('/login')
  await page.getByRole('textbox', { name: '邮箱', exact: true }).fill(email)
  await page.getByRole('button', { name: '继续', exact: true }).click()
  await page.getByLabel('密码', { exact: true }).fill(password)
  await page.getByRole('button', { name: '继续', exact: true }).click()
  await expect(page).toHaveURL('http://127.0.0.1:5174/')
  await expect(page.getByRole('heading', { name: '天文数据与文献检索' })).toBeVisible()
}

test('anonymous pages, probes and APIs remain closed', async ({ page, request }) => {
  for (const path of ['/', '/projects', '/account', '/settings', '/admin']) {
    await page.goto(path)
    await expect(page.getByRole('heading', { name: '登录 AstroAgent' })).toBeVisible()
    await expect(page).toHaveURL(/\/login/)
  }
  for (const path of ['/api/v1/conversations', '/api/v1/models', '/api/v1/admin/overview', '/openapi.json']) {
    expect((await request.get(path)).status()).toBe(401)
  }
  expect((await request.get('/health')).status()).toBe(404)
  expect((await request.get('/__internal/health')).status()).toBe(404)
  await page.goto('/login?next=https://evil.example.org/')
  await expect(page.getByRole('heading', { name: '登录 AstroAgent' })).toBeVisible()
})

test('login, private conversation, refresh, logout and account switch', async ({ page, context }, info) => {
  await login(page, 'first@example.org')
  const cookie = (await context.cookies()).find(value => value.name === 'astroagent_session')!
  expect(cookie.httpOnly).toBe(true)
  expect(cookie.sameSite).toBe('Lax')
  expect(cookie.expires).toBeGreaterThan(Date.now() / 1000)
  const csrf = (await (await page.request.get('/api/v1/auth/csrf')).json()).csrf_token
  const title = `QA private ${info.project.name} ${Date.now()}`
  const response = await page.request.post('/api/v1/conversations', {
    data: { title }, headers: { Origin: 'http://127.0.0.1:5174', 'X-CSRF-Token': csrf },
  })
  expect(response.status()).toBe(201)
  const conversation = await response.json()
  await page.reload()
  await expect(page.getByText(title, { exact: true })).toBeVisible()
  await page.evaluate(() => { localStorage.setItem('astroagent.qa.draft', 'private draft') })
  await page.goto('/account')
  await expect(page.getByRole('heading', { name: 'first@example.org' })).toBeVisible()
  await page.getByRole('button', { name: '退出登录', exact: true }).click()
  await expect(page.getByRole('heading', { name: '登录 AstroAgent' })).toBeVisible()
  expect(await page.evaluate(() => localStorage.getItem('astroagent.qa.draft'))).toBeNull()
  await login(page, 'second@example.org')
  await expect(page.getByText(title, { exact: true })).toHaveCount(0)
  expect((await page.request.get('/api/v1/conversations/' + conversation.id)).status()).toBe(404)
  await page.goto('/admin')
  await expect(page).toHaveURL('http://127.0.0.1:5174/')
  await page.goto('/account')
  await expect(page.getByRole('heading', { name: 'second@example.org' })).toBeVisible()
})

test('cross-tab logout discards prior private page', async ({ page, context }) => {
  await login(page, 'first@example.org')
  const other = await context.newPage()
  await other.goto('/account')
  await expect(other.getByRole('heading', { name: 'first@example.org' })).toBeVisible()
  await other.getByRole('button', { name: '退出登录', exact: true }).click()
  await expect(other.getByRole('heading', { name: '登录 AstroAgent' })).toBeVisible()
  await expect(page).toHaveURL(/\/login/)
  await expect(page.getByRole('heading', { name: '登录 AstroAgent' })).toBeVisible()
  await other.close()
})
