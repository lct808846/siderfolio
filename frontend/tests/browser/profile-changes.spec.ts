import { test, expect, type Page } from '@playwright/test'
import { mkdirSync } from 'node:fs'
import path from 'node:path'

const png = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a1iEAAAAASUVORK5CYII=', 'base64')

async function profileFixture(page: Page) {
  const user = { id: 'synthetic-profile-user', email: 'observer@example.org', username: 'Synthetic Observer', avatar_url: '', admin: false, totp_enabled: false, mfa_verified: false }
  const state = { failRead: false, failUpload: false, uploads: 0, writes: 0 }
  const summary = () => ({ account: { ...user, created_at: '2026-11-16T00:00:00Z', last_login: '2026-11-16T01:00:00Z', active_sessions: 1 }, total_model_calls: 4, distinct_models_count: 2, known_total_tokens: 5,
    models: [{ model: 'synthetic-chat', label: 'Synthetic chat', calls: 3, succeeded: 2, failed: 1, chat_calls: 3, plot_calls: 0, rag_calls: 0, local_calls: 0, input_tokens: null, output_tokens: null, total_tokens: null }, { model: 'synthetic-plot', label: 'Synthetic plot', calls: 1, succeeded: 1, failed: 0, chat_calls: 0, plot_calls: 1, rag_calls: 0, local_calls: 0, input_tokens: null, output_tokens: 5, total_tokens: 5 }],
    workspace: { conversations_count: 1, turns_count: 3, completed_turns: 2, failed_turns: 1, projects_count: 1, snapshots_count: 1, workflows_count: 0, knowledge_documents_count: 1, plot_datasets_count: 1, plot_operations_count: 1, rag_answers_count: 0, local_tasks_count: 0, simbad_queries: 1, ads_queries: 0, gaia_queries: 0, used_bytes: 1024, budget_bytes: 1048576, storage_ready: true } })
  await page.route('**/api/v1/**', async route => {
    const url = new URL(route.request().url()).pathname, method = route.request().method()
    const json = (body: unknown, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) })
    if (url.endsWith('/auth/session')) return json({ user, csrf_token: 'synthetic-csrf', idle_seconds: 1000, absolute_seconds: 2000 })
    if (url.endsWith('/auth/csrf')) return json({ csrf_token: 'synthetic-csrf' })
    if (url.endsWith('/auth/profile')) { state.writes++; user.username = route.request().postDataJSON().username; return json({ message: '用户名已更新。', username: user.username }) }
    if (url.endsWith('/auth/avatar')) return route.fulfill({ contentType: 'image/png', body: png })
    if (url.endsWith('/profile/summary')) return state.failRead ? json({ error: { code: 'synthetic_error', message: 'Synthetic profile read failed' } }, 503) : json(summary())
    if (url.endsWith('/profile/avatar')) {
      state.uploads++
      if (state.failUpload) return json({ error: { code: 'invalid_avatar_image', message: 'Synthetic image rejected' } }, 422)
      user.avatar_url = method === 'DELETE' ? '' : '/api/v1/auth/avatar?v=' + state.uploads
      return json({ message: method === 'DELETE' ? '已恢复默认头像。' : '头像已更新。', avatar_url: user.avatar_url })
    }
    return route.continue()
  })
  return { user, state }
}

test('profile name editing, avatar change/removal and missing usage stay accurate', async ({ page }, info) => {
  const { user, state } = await profileFixture(page)
  await page.goto('/profile')
  await expect(page.getByRole('heading', { name: '个人资料', exact: true })).toBeVisible()
  await expect(page.getByRole('cell', { name: '输入 — / 输出 5', exact: false })).toBeVisible()
  await page.getByRole('button', { name: '点击编辑用户名', exact: true }).click()
  await page.getByRole('textbox', { name: '编辑用户名', exact: true }).fill('Canceled observer')
  await page.keyboard.press('Escape')
  expect(state.writes).toBe(0)
  await page.getByRole('button', { name: '点击编辑用户名', exact: true }).click()
  await page.getByRole('textbox', { name: '编辑用户名', exact: true }).fill('New Synthetic Observer')
  await page.keyboard.press('Enter')
  await expect(page.getByRole('button', { name: '点击编辑用户名', exact: true })).toHaveText('New Synthetic Observer')
  expect(user.username).toBe('New Synthetic Observer')
  await expect(page.locator('.sidebar-user-card')).toContainText('New Synthetic Observer')
  await page.getByLabel('选择头像图片', { exact: true }).setInputFiles({ name: 'synthetic.png', mimeType: 'image/png', buffer: png })
  await expect(page.getByAltText('当前用户头像', { exact: true })).toBeVisible()
  await expect.poll(() => page.getByAltText('当前用户头像', { exact: true }).evaluate(el => (el as HTMLImageElement).naturalWidth)).toBeGreaterThan(0)
  expect(state.uploads).toBe(1)
  if (process.env.ASTROAGENT_RECORD_DIR) {
    mkdirSync(process.env.ASTROAGENT_RECORD_DIR, { recursive: true })
    await page.screenshot({ animations: 'disabled', path: path.join(process.env.ASTROAGENT_RECORD_DIR, info.project.name + '-profile-desktop.png') })
  }
  await page.getByRole('button', { name: '移除头像', exact: true }).click()
  await expect(page.getByAltText('当前用户头像', { exact: true })).toHaveCount(0)
  expect(state.uploads).toBe(2)
})

test('profile rejects oversized files before upload and displays read/upload errors', async ({ page }, info) => {
  const { state } = await profileFixture(page)
  state.failRead = true
  await page.goto('/profile')
  await expect(page.getByRole('alert')).toContainText('Synthetic profile read failed')
  state.failRead = false
  await page.reload()
  await expect(page.getByRole('heading', { name: '模型使用情况', exact: true })).toBeVisible()
  await page.getByLabel('选择头像图片', { exact: true }).setInputFiles({ name: 'large.png', mimeType: 'image/png', buffer: Buffer.alloc(5 * 1024 * 1024 + 1) })
  await expect(page.getByRole('alert')).toContainText('头像图片不能超过 5 MiB')
  expect(state.uploads).toBe(0)
  state.failUpload = true
  await page.getByLabel('选择头像图片', { exact: true }).setInputFiles({ name: 'bad.png', mimeType: 'image/png', buffer: png })
  await expect(page.getByRole('alert')).toContainText('Synthetic image rejected')
  await expect(page.getByRole('button', { name: '更换用户头像', exact: true })).toBeEnabled()
  if (process.env.ASTROAGENT_RECORD_DIR) {
    mkdirSync(process.env.ASTROAGENT_RECORD_DIR, { recursive: true })
    await page.setViewportSize({ width: 390, height: 900 })
    await page.screenshot({ animations: 'disabled', path: path.join(process.env.ASTROAGENT_RECORD_DIR, info.project.name + '-profile-upload-error.png') })
  }
})

test('profile navigation and responsive sidebar preserve the unsent question', async ({ page }, info) => {
  await profileFixture(page)
  let sends = 0
  page.on('request', value => { if (value.method() === 'POST' && /\/turns$/.test(new URL(value.url()).pathname)) sends++ })
  await page.goto('/')
  await page.getByRole('textbox', { name: '天文问题', exact: true }).fill('Synthetic unsent question')
  await page.locator('.sidebar-user-card').click()
  await page.getByRole('menuitem', { name: '个人资料', exact: true }).click()
  await expect(page).toHaveURL(/\/profile$/)
  await expect(page.getByRole('button', { name: '点击编辑用户名', exact: true })).toBeVisible()
  for (const width of [1440, 1280, 1024, 981, 980, 768, 390, 320]) {
    await page.setViewportSize({ width, height: 900 })
    await page.evaluate(() => new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))))
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
    for (const selector of ['.profile-name-trigger', '.profile-timestamps', '.profile-email']) {
      expect(await page.locator(selector).evaluate(el => {
        const rect = el.getBoundingClientRect(), parent = document.querySelector('.profile-scroll')!.getBoundingClientRect()
        return rect.left >= parent.left && rect.right <= parent.right + 1 && el.scrollWidth <= el.clientWidth + 1
      })).toBe(true)
    }
    const toggle = page.locator('.history-toggle')
    await toggle.click()
    await toggle.click()
  }
  if (process.env.ASTROAGENT_RECORD_DIR) await page.screenshot({ animations: 'disabled', path: path.join(process.env.ASTROAGENT_RECORD_DIR, info.project.name + '-profile-mobile.png') })
  await page.setViewportSize({ width: 1440, height: 900 })
  await page.locator('.sidebar-user-card').click()
  await page.getByRole('menuitem', { name: '个人资料', exact: true }).click()
  await page.getByRole('link', { name: '查询工作台', exact: true }).click()
  await expect(page.getByRole('textbox', { name: '天文问题', exact: true })).toHaveValue('Synthetic unsent question')
  expect(sends).toBe(0)
})
