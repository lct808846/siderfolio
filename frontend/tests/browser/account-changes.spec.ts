import { test, expect } from '@playwright/test'
import { mkdirSync, readFileSync } from 'node:fs'
import path from 'node:path'

test.beforeEach(async ({ page }) => {
  let signedIn = true
  let otherSession = true
  const user = { id: '00000000-0000-0000-0000-000000000001', email: 'observer@example.org', username: 'Synthetic Observer', admin: false, totp_enabled: false, mfa_verified: false }
  await page.route('**/api/v1/auth/**', async route => {
    const endpoint = new URL(route.request().url()).pathname
    const json = (value: unknown, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(value) })
    if (endpoint.endsWith('/session')) return signedIn ? json({ user, csrf_token: 'synthetic-csrf', idle_seconds: 315360000, absolute_seconds: 315360000 }) : json({ error: { message: 'Login required' } }, 401)
    if (endpoint.endsWith('/csrf')) return json({ csrf_token: 'synthetic-csrf', registration_available: true })
    if (endpoint.endsWith('/sessions')) {
      return json([
        {
          id: 'synthetic-current',
          current: true,
          created_at: '2026-11-14T00:00:00Z',
          last_seen: '2026-11-14T00:00:00Z',
          expires_at: '2036-11-14T00:00:00Z',
          mfa_verified: false,
          login_ip: '198.51.100.10',
          last_ip: '198.51.100.10',
          login_location: '中国 · Shanghai',
          last_location: '中国 · Shanghai',
          device_type: 'desktop',
          device_name: 'Windows 10/11 · Chrome 131',
          browser: 'Chrome 131',
          os: 'Windows 10/11',
          user_agent: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/131.0.0.0',
          is_anomalous: false,
          anomaly_reasons: [],
        },
        ...(otherSession
          ? [
              {
                id: 'synthetic-other',
                current: false,
                created_at: '2026-11-14T00:00:00Z',
                last_seen: '2026-11-14T00:00:00Z',
                expires_at: '2036-11-14T00:00:00Z',
                mfa_verified: false,
                login_ip: '203.0.113.45',
                last_ip: '203.0.113.45',
                login_location: '日本 · Tokyo',
                last_location: '日本 · Tokyo',
                device_type: 'mobile',
                device_name: 'iPhone (iOS 18.1) · Safari 18',
                browser: 'Safari 18',
                os: 'iOS 18.1',
                user_agent: 'Mozilla/5.0 (iPhone; CPU iPhone OS 18_1 like Mac OS X) Safari/604.1',
                is_anomalous: true,
                anomaly_reasons: ['different_location', 'new_device'],
              },
            ]
          : []),
      ])
    }
    if (endpoint.endsWith('/sessions/revoke')) {
      if (route.request().postDataJSON().password !== 'Synthetic password 2048') return json({ error: { message: '当前密码不正确' } }, 403)
      otherSession = false; return json({ message: '所选浏览器会话已退出。' })
    }
    if (endpoint.endsWith('/totp/disable')) {
      if (route.request().postDataJSON().password !== 'Synthetic password 2048') return json({ error: { message: '当前密码不正确' } }, 403)
      user.totp_enabled = false; signedIn = false; return json({ message: '已关闭。' })
    }
    if (endpoint.endsWith('/profile')) { user.username = route.request().postDataJSON().username; return json({ username: user.username, message: '用户名已更新。' }) }
    if (endpoint.endsWith('/totp/enroll')) return json({ secret: 'JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP', otpauth_uri: 'otpauth://totp/AstroAgent:observer%40example.org?secret=JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP&issuer=AstroAgent&algorithm=SHA1&digits=6&period=30', message: 'Synthetic enrollment' })
    if (endpoint.endsWith('/totp/confirm')) {
      if (route.request().postDataJSON().code !== '123456') return json({ error: { message: '验证码不正确' } }, 422)
      user.totp_enabled = true; user.mfa_verified = true
      return json({ recovery_codes: Array.from({ length: 10 }, (_, i) => 'synthetic-recovery-' + String(i + 1).padStart(2, '0')), message: 'Synthetic confirmation' })
    }
    if (endpoint.endsWith('/logout')) { signedIn = false; return json({ message: '已退出。' }) }
    return route.continue()
  })
})

test('account QR enrollment, invalid code, recovery download and narrow layout', async ({ page }, info) => {
  await page.goto('/settings')
  await expect(page.getByRole('heading', { name: '账户安全与登录' })).toBeVisible()
  await page.getByRole('switch', { name: '身份验证器应用', exact: true }).click()
  const enroll = page.getByRole('dialog')
  await enroll.getByLabel('当前密码', { exact: true }).fill('Synthetic password 2048')
  await enroll.getByRole('button', { name: '继续', exact: true }).click()
  const qr = page.getByRole('img', { name: '身份验证器绑定二维码', exact: true })
  await expect(qr).toBeVisible()
  await expect(page.getByText('JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP', { exact: true })).not.toBeVisible()
  await page.setViewportSize({ width: 390, height: 740 })
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  if (process.env.ASTROAGENT_RECORD_DIR) {
    mkdirSync(process.env.ASTROAGENT_RECORD_DIR, { recursive: true })
    await qr.screenshot({ path: path.join(process.env.ASTROAGENT_RECORD_DIR, info.project.name + '-synthetic-qr.png') })
    await page.screenshot({ path: path.join(process.env.ASTROAGENT_RECORD_DIR, info.project.name + '-account-mobile.png'), fullPage: true })
  }
  await page.getByLabel('6 位动态验证码', { exact: true }).fill('000000')
  await page.getByRole('button', { name: '验证并启用', exact: true }).click()
  await expect(page.getByRole('alert')).toContainText('验证码不正确')
  await page.getByLabel('6 位动态验证码', { exact: true }).fill('123456')
  await page.getByRole('button', { name: '验证并启用', exact: true }).click()
  await expect(page.locator('.account-recovery-workbench')).toBeVisible()
  const download = page.waitForEvent('download')
  await page.getByRole('button', { name: '下载恢复码', exact: true }).click()
  const file = await download
  const content = readFileSync((await file.path())!, 'utf8')
  expect(content).toContain('observer@example.org')
  expect(content).toContain('synthetic-recovery-01')
  expect(content).toContain('synthetic-recovery-10')
  await page.getByRole('button', { name: '我已保存', exact: true }).click()
  await expect(page.locator('.account-recovery-workbench')).toHaveCount(0)
})

test('username propagates to sidebar, menu closes and logout clears private browser state', async ({ page }) => {
  await page.goto('/account')
  await page.locator('.settings-row').filter({ has: page.getByRole('heading', { name: '用户名', exact: true }) }).getByRole('button').click()
  await page.getByLabel(/^用户名/).fill('New Synthetic Observer')
  await page.getByRole('button', { name: '保存用户名', exact: true }).click()
  await expect(page.getByRole('status')).toContainText('用户名已更新')
  await expect(page.getByRole('status').filter({ hasText: '用户名已更新' })).not.toBeVisible({ timeout: 5000 })
  await page.goto('/')
  const trigger = page.locator('.sidebar-user-card')
  await expect(trigger).toContainText('New Synthetic Observer')
  await trigger.click()
  await expect(page.getByRole('menu', { name: '账号菜单' })).toBeVisible()
  await trigger.press('Escape')
  await expect(page.getByRole('menu', { name: '账号菜单' })).toHaveCount(0)
  await trigger.click()
  await page.getByRole('textbox', { name: '天文问题' }).click()
  await expect(page.getByRole('menu', { name: '账号菜单' })).toHaveCount(0)
  await page.setViewportSize({ width: 390, height: 740 })
  await page.getByRole('button', { name: '展开会话列表', exact: true }).click()
  await trigger.click()
  const menu = page.getByRole('menu', { name: '账号菜单' })
  const bounds = (await menu.boundingBox())!
  expect(bounds.x).toBeGreaterThanOrEqual(0)
  expect(bounds.y).toBeGreaterThanOrEqual(0)
  expect(bounds.x + bounds.width).toBeLessThanOrEqual(391)
  await page.evaluate(() => localStorage.setItem('astroagent.synthetic.draft', 'private fixture'))
  await menu.getByRole('menuitem', { name: '退出登录', exact: true }).click()
  await expect(page).toHaveURL(/\/login/)
  expect(await page.evaluate(() => localStorage.getItem('astroagent.synthetic.draft'))).toBeNull()
})

test('activity dialog only revokes the selected other browser after password confirmation', async ({ page }) => {
  await page.goto('/settings?section=security')
  await page.getByRole('button', { name: /2 台设备/ }).click()
  const dialog = page.getByRole('dialog')
  await expect(dialog.getByText('当前设备', { exact: true })).toBeVisible()
  await expect(dialog.getByText('iPhone (iOS 18.1) · Safari 18')).toBeVisible()
  await expect(dialog.getByText('异地登录', { exact: true })).toBeVisible()
  const revokeButton = dialog.getByRole('button', { name: '强制退出 iPhone (iOS 18.1) · Safari 18', exact: true })
  await expect(revokeButton).toHaveCount(1)
  await revokeButton.click()
  await dialog.getByLabel('当前密码', { exact: true }).fill('wrong-password')
  await dialog.getByRole('button', { name: '确认强制退出', exact: true }).click()
  await expect(dialog.getByRole('alert')).toContainText('密码不正确')
  await dialog.getByLabel('当前密码', { exact: true }).fill('Synthetic password 2048')
  await dialog.getByRole('button', { name: '确认强制退出', exact: true }).click()
  await expect(dialog.getByText('当前设备', { exact: true })).toBeVisible()
  await expect(revokeButton).toHaveCount(0)
  await expect(page).toHaveURL(/section=security/)
})

test('MFA switch waits for confirmation and disabling requires proof', async ({ page }) => {
  await page.goto('/settings?section=security')
  const toggle = page.getByRole('switch', { name: '身份验证器应用', exact: true })
  await toggle.click()
  const dialog = page.getByRole('dialog')
  await expect(toggle).not.toBeChecked()
  await dialog.getByLabel('当前密码', { exact: true }).fill('Synthetic password 2048')
  await dialog.getByRole('button', { name: '继续', exact: true }).click()
  await dialog.getByLabel('6 位动态验证码', { exact: true }).fill('123456')
  await dialog.getByRole('button', { name: '验证并启用', exact: true }).click()
  await dialog.getByRole('button', { name: '我已保存', exact: true }).click()
  await expect(toggle).toBeChecked()
  await toggle.click()
  await dialog.getByLabel('当前密码', { exact: true }).fill('wrong-password')
  await dialog.getByLabel('验证码或恢复码', { exact: true }).fill('synthetic-recovery-01')
  await dialog.getByRole('button', { name: '关闭 MFA 并退出', exact: true }).click()
  await expect(dialog.getByRole('alert')).toContainText('密码不正确')
  await dialog.getByLabel('当前密码', { exact: true }).fill('Synthetic password 2048')
  await dialog.getByRole('button', { name: '关闭 MFA 并退出', exact: true }).click()
  await expect(page).toHaveURL(/\/login/)
})
