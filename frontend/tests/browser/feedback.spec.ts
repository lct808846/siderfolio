import { expect, test, type Page } from '@playwright/test'
import { mkdirSync } from 'node:fs'
import { join } from 'node:path'

const id = '5b06c950-9744-4c2e-bd94-b20baeabc123'
const created = '2026-11-24T12:00:00Z'
const png = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a1iEAAAAASUVORK5CYII=', 'base64')

async function feedbackFixture(page: Page, admin: boolean) {
  const state = {
    attempts: 0,
    filters: new URLSearchParams(),
    record: {
      id, user_id: 'observer-fixture', category: 'calculation', title: '合成科研反馈',
      description: '<b>这段标记应该按纯文本显示</b>',
      status: 'pending', has_screenshot: true, created_at: created, updated_at: created,
      replies: [] as { id: string; body: string; created_at: string }[],
    },
  }
  await page.route('**/api/v1/**', async route => {
    const url = new URL(route.request().url())
    const method = route.request().method()
    const json = (data: unknown, status = 200) => route.fulfill({ status, json: data })
    if (url.pathname.endsWith('/auth/session')) return json({
      user: { id: admin ? 'admin-fixture' : 'observer-fixture', email: 'fixture@example.org', username: '验收用户',
        admin, totp_enabled: admin, mfa_verified: admin, avatar_url: '' },
      csrf_token: 'synthetic-csrf', idle_seconds: 3600, absolute_seconds: 3600,
    })
    if (url.pathname.endsWith('/auth/csrf')) return json({ csrf_token: 'synthetic-csrf' })
    if (url.pathname.endsWith('/auth/reauthenticate')) return json({ message: '已确认管理员身份。' })
    if (url.pathname.endsWith('/admin/overview')) return json({
      users: { total: 2, pending: 0, disabled: 0, administrators: 1 },
      mail_configured: true, registration_available: true, mail_hour_limit: 100, registration_limit: 10,
    })
    if (url.pathname.endsWith('/admin/capacity')) return json({ enabled: false, worker_ready: false, queued: 0, active: 0 })
    if (url.pathname.endsWith('/screenshot')) return route.fulfill({ contentType: 'image/png', body: png })
    if (url.pathname.endsWith('/feedback')) {
      state.filters = url.searchParams
      if (method === 'POST') {
        state.attempts++
        expect(route.request().postData()).toContain('synthetic.png')
        if (state.attempts === 1) return json({ error: { message: '暂时无法保存反馈。' } }, 503)
        return json(state.record, 201)
      }
      return json({ items: admin || state.attempts > 1 ? [state.record] : [], has_more: false })
    }
    if (url.pathname.endsWith(id)) {
      if (method === 'PATCH') {
        const body = route.request().postDataJSON()
        state.record.status = body.status
        state.record.replies.push({ id, body: body.reply, created_at: created })
      }
      return json(state.record)
    }
    return json([])
  })
  return state
}

async function capture(page: Page, filename: string) {
  const directory = process.env.ASTROAGENT_RECORD_DIR
  if (!directory) return
  mkdirSync(directory, { recursive: true })
  await page.screenshot({ path: join(directory, filename), animations: 'disabled', fullPage: true })
}

test('feedback retries safely and shows history, attachment and literal text on a dark narrow screen', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await page.addInitScript(() => {
    localStorage.setItem('astroagent.appearance.v1', JSON.stringify({ theme: 'obsidian' }))
  })
  const state = await feedbackFixture(page, false)
  await page.goto('/feedback')
  await expect(page.locator('html')).toHaveAttribute('data-theme-mode', 'dark')
  await expect(page.getByRole('heading', { name: '帮助与反馈', exact: true })).toBeVisible()
  await page.getByRole('combobox', { name: '反馈类型', exact: true }).selectOption('calculation')
  await page.getByLabel('标题', { exact: true }).fill(state.record.title)
  await page.getByLabel('详细描述', { exact: true }).fill(state.record.description)
  await page.getByLabel('截图附件（选填）').setInputFiles({ name: 'synthetic.png', mimeType: 'image/png', buffer: png })
  await capture(page, 'feedback-dark-mobile.png')
  await page.getByRole('button', { name: '提交反馈', exact: true }).click()
  await expect(page.getByRole('alert')).toContainText('暂时无法保存反馈')
  await expect(page.getByLabel('标题', { exact: true })).toHaveValue(state.record.title)
  await page.getByRole('button', { name: '提交反馈', exact: true }).click()
  await expect(page.getByText('反馈已提交', { exact: false })).toBeVisible()
  await expect(page.getByAltText('用户上传的截图')).toBeVisible()
  await expect(page.getByText(state.record.description, { exact: true })).toBeVisible()
  await page.getByRole('button', { name: '返回列表', exact: true }).click()
  await expect(page.getByRole('button', { name: /合成科研反馈/ })).toBeVisible()
  expect(await page.locator('html').evaluate(el => el.scrollWidth)).toBeLessThanOrEqual(390)
})

test('admin filters and replies after identity confirmation on a light desktop', async ({ page }) => {
  await page.setViewportSize({ width: 1360, height: 1000 })
  const state = await feedbackFixture(page, true)
  await page.goto('/admin?section=feedback')
  await expect(page.getByRole('button', { name: '用户反馈管理', exact: true })).toBeVisible()
  await page.getByRole('combobox', { name: '类型', exact: true }).selectOption('calculation')
  await page.getByRole('combobox', { name: '状态', exact: true }).selectOption('pending')
  await page.getByLabel('开始日期').fill('2026-11-24')
  await page.getByLabel('结束日期').fill('2026-11-24')
  await page.getByRole('button', { name: '应用筛选' }).click()
  await expect.poll(() => state.filters.get('created_before')).toBeTruthy()
  expect(state.filters.get('category')).toBe('calculation')
  expect(state.filters.get('status')).toBe('pending')
  await page.getByRole('button', { name: /合成科研反馈/ }).click()
  await page.getByRole('combobox', { name: '处理状态', exact: true }).selectOption('resolved')
  await page.getByLabel('给用户的回复').fill('合成验收回复')
  await expect(page.getByRole('button', { name: '保存并回复' })).toBeDisabled()
  await page.getByText('敏感操作重新认证', { exact: false }).click()
  await page.getByPlaceholder('输入管理员密码').fill('synthetic-only')
  await page.getByPlaceholder('6 位动态口令或恢复码').fill('123456')
  await page.getByRole('button', { name: '确认身份', exact: true }).click()
  await page.getByRole('button', { name: '保存并回复' }).click()
  await expect(page.getByText('合成验收回复', { exact: true })).toBeVisible()
  await expect(page.getByRole('heading', { name: '反馈详情' })).toBeVisible()
  await capture(page, 'feedback-admin-light.png')
})
