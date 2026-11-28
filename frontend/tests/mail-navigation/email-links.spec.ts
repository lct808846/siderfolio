import { test, expect } from '@playwright/test'
import http from 'node:http'
import { spawn, type ChildProcess } from 'node:child_process'
import { once } from 'node:events'

const origin = 'http://127.0.0.1:5275'
const token = 'synthetic-mail-link-token-for-acceptance-only'
const csrf = 'synthetic-csrf-not-a-credential'
const posts: { path: string; token?: string }[] = []
let backend: http.Server, mailbox: http.Server, frontend: ChildProcess

test.beforeAll(async () => {
  backend = http.createServer(async (req, res) => {
    res.setHeader('Content-Type', 'application/json')
    if (req.method === 'GET' && req.url === '/api/v1/auth/session') {
      res.writeHead(401); res.end('{"error":{"code":"login_required"}}'); return
    }
    if (req.method === 'GET' && req.url === '/api/v1/auth/csrf') {
      res.setHeader('Set-Cookie', 'astroagent_preauth=fixture; Path=/; HttpOnly; SameSite=Lax')
      res.end(JSON.stringify({ csrf_token: csrf, registration_available: true })); return
    }
    if (req.method === 'POST') {
      if (req.headers.origin !== origin || req.headers['x-csrf-token'] !== csrf) {
        res.writeHead(403); res.end('{}'); return
      }
      const parts: Buffer[] = []
      for await (const part of req) parts.push(Buffer.from(part))
      const body = JSON.parse(Buffer.concat(parts).toString())
      posts.push({ path: req.url!, token: body.token })
      if (req.url === '/api/v1/auth/continue') {
        res.end(JSON.stringify(body.email === 'new@example.org'
          ? { action: 'activate_sent', cooldown: 60, message: 'Synthetic activation sent' }
          : { action: 'login', totp_enabled: body.email === 'mfa@example.org' })); return
      }
      if (req.url === '/api/v1/auth/login') {
        if (body.password !== 'Synthetic nebula entropy 2048') {
          res.writeHead(401)
          res.end(JSON.stringify({ error: { code: 'login_failed', message: '邮箱、密码或验证码不正确，或账号暂不可用。' } }))
          return
        }
        if (body.email === 'mfa@example.org' && !String(body.code || '').trim()) {
          res.end(JSON.stringify({ action: 'totp_required', message: '请输入双因素验证码。' }))
          return
        }
        res.end(JSON.stringify({ message: '登录成功。' }))
        return
      }
      if (req.url === '/api/v1/auth/activate/complete' || req.url === '/api/v1/auth/reset-password') {
        res.end(JSON.stringify({ message: 'Synthetic password saved', email: 'new@example.org', totp_enabled: false })); return
      }
      res.end(JSON.stringify({ setup_token: 'synthetic-one-use-setup-token-for-acceptance' })); return
    }
    res.writeHead(404); res.end('{}')
  })
  mailbox = http.createServer((_req, res) => {
    res.setHeader('Content-Type', 'text/html; charset=utf-8')
    res.end(`<a href="${origin}/activate#token=${token}">Activation email</a><a href="${origin}/reset-password#token=${token}">Password reset email</a><a href="${origin}/">Siderfolio home</a>`)
  })
  backend.listen(8102, '127.0.0.1'); await once(backend, 'listening')
  mailbox.listen(5290, '127.0.0.1'); await once(mailbox, 'listening')
  frontend = spawn(process.execPath, ['server.mjs'], { env: { ...process.env,
    FRONTEND_PORT: '5275', ASTROAGENT_DEPLOYMENT_MODE: 'native',
    ASTROAGENT_API_TARGET: 'http://127.0.0.1:8102', ASTROAGENT_SITE_ORIGIN: origin,
  }, stdio: 'ignore' })
  await expect.poll(async () => {
    try { return (await fetch(origin + '/login')).status } catch { return 0 }
  }).toBe(200)
})

test.afterAll(async () => {
  if (frontend && frontend.exitCode === null) {
    frontend.kill(); await once(frontend, 'exit')
  }
  if (mailbox) { mailbox.closeAllConnections(); await new Promise<void>(resolve => mailbox.close(() => resolve())) }
  if (backend) { backend.closeAllConnections(); await new Promise<void>(resolve => backend.close(() => resolve())) }
})

test.beforeEach(() => { posts.length = 0 })

test('real email navigation loads activation without consuming the link until confirmation', async ({ page }) => {
  await page.goto('http://localhost:5290/')
  const navigation = page.waitForRequest(req => req.isNavigationRequest() && req.url().startsWith(origin + '/activate'))
  await page.getByRole('link', { name: 'Activation email', exact: true }).click()
  const request = await navigation
  expect((await request.allHeaders())['sec-fetch-site']).toBe('cross-site')
  await expect(page.getByRole('heading', { name: '确认邮箱', exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: '确认邮箱并继续', exact: true })).toBeEnabled()
  expect(posts).toEqual([])
  expect(page.url()).toBe(origin + '/activate')
  await page.getByRole('button', { name: '确认邮箱并继续', exact: true }).click()
  await expect(page.getByLabel(/^新密码/)).toBeVisible()
  expect(posts).toEqual([{ path: '/api/v1/auth/activate/confirm', token }])
})

test('real email navigation opens reset page without changing a password', async ({ page }) => {
  await page.goto('http://localhost:5290/')
  const navigation = page.waitForRequest(req => req.isNavigationRequest() && req.url().startsWith(origin + '/reset-password'))
  await page.getByRole('link', { name: 'Password reset email', exact: true }).click()
  expect((await (await navigation).allHeaders())['sec-fetch-site']).toBe('cross-site')
  await expect(page.getByRole('heading', { name: '设置新密码', exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: '保存密码', exact: true })).toBeEnabled()
  expect(posts).toEqual([])
})

test('cross-site link to homepage opens the login page', async ({ page, request }) => {
  const navigation = { 'Sec-Fetch-Site': 'cross-site', 'Sec-Fetch-Mode': 'navigate', 'Sec-Fetch-Dest': 'document' }
  for (const method of ['GET', 'HEAD']) {
    const response = await request.fetch('/', { method, headers: navigation, maxRedirects: 0 })
    expect(response.status()).toBe(302)
    expect(response.headers().location).toBe('/login')
  }

  await page.goto('http://localhost:5290/')
  const rootRequest = page.waitForRequest(req => req.isNavigationRequest() && req.url() === origin + '/')
  await page.getByRole('link', { name: 'Siderfolio home' }).click()
  expect((await (await rootRequest).allHeaders())['sec-fetch-site']).toBe('cross-site')
  await expect(page).toHaveURL(origin + '/login')
  await expect(page.getByLabel('邮箱', { exact: true })).toBeVisible()
})

test('cross-site APIs, writes, embeds and private pages stay rejected', async ({ request }) => {
  const navigation = { 'Sec-Fetch-Site': 'cross-site', 'Sec-Fetch-Mode': 'navigate', 'Sec-Fetch-Dest': 'document' }
  for (const path of ['/login', '/register', '/activate', '/resend', '/forgot-password', '/reset-password']) {
    expect((await request.get(path, { headers: navigation })).status()).toBe(200)
    expect((await request.head(path, { headers: navigation })).status()).toBe(200)
  }
  for (const path of ['/api/v1/auth/csrf', '/api/v1/auth/session', '/api/v1/conversations', '/projects', '/admin', '/openapi.json']) {
    expect((await request.get(path, { headers: navigation })).status()).toBe(403)
  }
  for (const [mode, destination] of [['cors', 'empty'], ['navigate', 'iframe'], ['no-cors', 'image']]) {
    for (const path of ['/', '/activate']) {
      expect((await request.get(path, { headers: { ...navigation, 'Sec-Fetch-Mode': mode, 'Sec-Fetch-Dest': destination } })).status()).toBe(403)
    }
  }
  for (const path of ['/', '/activate', '/api/v1/auth/activate/confirm', '/api/v1/auth/reset-password']) {
    expect((await request.post(path, { headers: { ...navigation, Origin: origin, 'X-CSRF-Token': csrf }, data: { token } })).status()).toBe(403)
  }
  expect(posts).toEqual([])
})

test('current two-step email flow opens password and optional verification step', async ({ page }) => {
  for (const email of ['observer@example.org', 'mfa@example.org']) {
    await page.goto('/login')
    await page.getByLabel('邮箱', { exact: true }).fill(email)
    await expect(page.locator('input[type=password]')).toHaveCount(0)
    await page.getByRole('button', { name: '继续', exact: true }).click()
    await expect(page.getByLabel('密码', { exact: true })).toBeVisible()
    await expect(page.locator('input[autocomplete="one-time-code"]')).toHaveCount(0)
    if (email === 'mfa@example.org') {
      await page.getByLabel('密码', { exact: true }).fill('wrong-password')
      await page.getByRole('button', { name: '继续', exact: true }).click()
      await expect(page.locator('input[autocomplete="one-time-code"]')).toHaveCount(0)
      await expect(page.getByRole('alert')).toContainText('密码')
      await page.getByLabel('密码', { exact: true }).fill('Synthetic nebula entropy 2048')
      await page.getByRole('button', { name: '继续', exact: true }).click()
      await expect(page.locator('input[type=password]')).toHaveCount(0)
      await expect(page.locator('input[autocomplete="one-time-code"]')).toBeVisible()
    } else {
      expect(posts.filter(value => value.path === '/api/v1/auth/login')).toHaveLength(0)
    }
  }
})

test('new email continuation displays activation notice and resend cooldown', async ({ page }) => {
  await page.goto('/login')
  await page.getByLabel('邮箱', { exact: true }).fill('new@example.org')
  await page.getByRole('button', { name: '继续', exact: true }).click()
  await expect(page.getByRole('heading', { name: '检查收件箱', exact: true })).toBeVisible()
  await expect(page.getByRole('status')).toContainText('new@example.org')
  await expect(page.getByRole('button', { name: /^重新发送/ })).toBeDisabled()
  expect(posts.filter(value => value.path === '/api/v1/auth/continue')).toHaveLength(1)
})

test('activation username and password confirmation notify the waiting login tab', async ({ page, context }) => {
  await page.goto('/login')
  await page.getByLabel('邮箱', { exact: true }).fill('new@example.org')
  await page.getByRole('button', { name: '继续', exact: true }).click()
  await expect(page.getByRole('heading', { name: '检查收件箱', exact: true })).toBeVisible()
  const activation = await context.newPage()
  await activation.goto('/activate#token=' + token)
  await activation.getByRole('button', { name: '确认邮箱并继续', exact: true }).click()
  await activation.getByLabel('用户名', { exact: true }).fill('Synthetic observer')
  await activation.getByLabel('新密码', { exact: true }).fill('Synthetic nebula entropy 2048')
  await activation.getByLabel('确认密码', { exact: true }).fill('Mismatch synthetic password')
  await activation.getByRole('button', { name: '保存密码', exact: true }).click()
  await expect(activation.getByRole('alert')).toContainText('两次密码不一致')
  expect(posts.filter(value => value.path === '/api/v1/auth/activate/complete')).toHaveLength(0)
  await activation.getByLabel('确认密码', { exact: true }).fill('Synthetic nebula entropy 2048')
  await activation.getByRole('button', { name: '保存密码', exact: true }).click()
  await expect(page.getByLabel('密码', { exact: true })).toBeVisible()
  await expect(page.getByLabel('密码', { exact: true })).toBeFocused()
  expect(posts.filter(value => value.path === '/api/v1/auth/activate/complete')).toHaveLength(1)
  expect(posts.filter(value => value.path === '/api/v1/auth/login')).toHaveLength(0)
})
