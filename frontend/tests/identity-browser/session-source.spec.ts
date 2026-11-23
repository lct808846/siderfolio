import { test, expect } from '@playwright/test'
import { createHmac } from 'node:crypto'

function otp(secret: string): string {
  const alphabet = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ234567'
  const bits = Array.from(secret.replace(/=+$/, '').toUpperCase()).map(c => alphabet.indexOf(c).toString(2).padStart(5, '0')).join('')
  const bytes = Buffer.from(Array.from({ length: Math.floor(bits.length / 8) }, (_, i) => parseInt(bits.slice(i * 8, i * 8 + 8), 2)))
  const counter = Buffer.alloc(8); counter.writeBigUInt64BE(BigInt(Math.floor(Date.now() / 30000)))
  const mac = createHmac('sha1', bytes).update(counter).digest(), offset = mac[19]! & 15
  return String((mac.readUInt32BE(offset) & 0x7fffffff) % 1000000).padStart(6, '0')
}

test('real container source consistency, profile and TOTP binding survive page navigation', async ({ page, context }, info) => {
  const email = info.project.name + '-source-final@example.org'
  const password = 'Synthetic nebula entropy 2048'
  await page.goto('/login')
  await page.getByLabel('邮箱', { exact: true }).fill(email)
  await page.getByRole('button', { name: '继续', exact: true }).click()
  await page.getByLabel('密码', { exact: true }).fill(password)
  await page.getByRole('button', { name: '继续', exact: true }).click()
  await expect(page).toHaveURL('http://127.0.0.1:5174/')
  const cookie = (await context.cookies()).find(c => c.name === 'astroagent_session')!
  expect(cookie.httpOnly).toBe(true)
  expect(cookie.expires).toBeGreaterThan(Date.now() / 1000)
  for (const route of ['/account', '/projects', '/']) {
    await page.goto(route)
    await expect(page).toHaveURL('http://127.0.0.1:5174' + route)
    expect((await page.request.get('/api/v1/auth/session')).status()).toBe(200)
  }
  const spoof = await page.request.get('/api/v1/auth/session', { headers: {
    'X-Astroagent-Client-Address': '203.0.113.42', 'X-Forwarded-For': '203.0.113.43',
  } })
  expect(spoof.status()).toBe(200)
  await page.goto('/account')
  await page.getByLabel(/^用户名/).fill('QA ' + info.project.name + ' Observer')
  await page.getByRole('button', { name: '保存用户名', exact: true }).click()
  await expect(page.getByRole('status')).toContainText('用户名已更新')
  await page.reload()
  await expect(page.getByLabel(/^用户名/)).toHaveValue('QA ' + info.project.name + ' Observer')
  const enroll = page.locator('.account-2fa-enroll-form')
  await enroll.locator('input[type=password]').fill(password)
  const response = page.waitForResponse(r => r.url().endsWith('/api/v1/auth/totp/enroll') && r.request().method() === 'POST')
  await enroll.getByRole('button', { name: '扫码绑定验证器', exact: true }).click()
  const enrollment = await response
  expect(enrollment.status()).toBe(200)
  const payload = await enrollment.json()
  const uri = new URL(payload.otpauth_uri)
  expect(uri.searchParams.get('secret')).toBe(payload.secret)
  await expect(page.getByRole('img', { name: 'Siderfolio 双因素身份验证绑定二维码' })).toBeVisible()
  await page.getByLabel('6 位动态验证码', { exact: true }).fill(otp(payload.secret))
  await page.getByRole('button', { name: '确认并完成绑定', exact: true }).click()
  await expect(page.locator('.account-recovery-workbench')).toBeVisible()
  expect(await page.locator('.account-recovery-workbench code').count()).toBe(10)
  const user = (await (await page.request.get('/api/v1/auth/session')).json()).user
  expect(user.totp_enabled).toBe(true)
  expect(user.mfa_verified).toBe(true)
  await page.goto('/')
  await expect(page).toHaveURL('http://127.0.0.1:5174/')
  expect((await page.request.get('/api/v1/auth/session')).status()).toBe(200)
})
