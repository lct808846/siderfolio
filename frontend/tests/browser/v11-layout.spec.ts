import { test, expect } from '@playwright/test'

test('responsive panels keep the draft and do not send queries when switched', async ({ page }) => {
  let sends = 0
  page.on('request', request => {
    if (request.method() === 'POST' && /\/turns$|\/rag\/(answers|indexes)$/.test(new URL(request.url()).pathname)) sends++
  })
  await page.goto('/')
  for (const width of [1440, 1201, 1200, 1024, 768, 681, 680, 390, 320]) {
    await page.setViewportSize({ width, height: 740 })
    await expect(page.getByRole('navigation', { name: '全局导航' })).toBeVisible()
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
    if (width <= 1200) {
      const navigation = page.getByRole('navigation', { name: '工作区面板' })
      await navigation.getByRole('button', { name: '对话' }).click()
      await page.getByRole('textbox', { name: '天文问题' }).fill('面板切换保留的测试问题')
      await navigation.getByRole('button', { name: '会话', exact: true }).click()
      await navigation.getByRole('button', { name: '结果', exact: true }).click()
      await navigation.getByRole('button', { name: '对话', exact: true }).click()
      await expect(page.getByRole('textbox', { name: '天文问题' })).toHaveValue('面板切换保留的测试问题')
      await expect(navigation.getByRole('button', { name: '对话', exact: true })).toHaveAttribute('aria-pressed', 'true')
    }
  }
  expect(sends).toBe(0)
  await page.goto('/projects')
  await expect(page.getByRole('navigation', { name: '当前项目导航' })).toHaveCount(0)
})

test('keyboard panel navigation remains available with reduced motion and forced colors', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 700 })
  await page.emulateMedia({ reducedMotion: 'reduce', forcedColors: 'active' })
  await page.goto('/')
  const navigation = page.getByRole('navigation', { name: '工作区面板' })
  const history = navigation.getByRole('button', { name: '会话', exact: true })
  await history.focus()
  await expect(history).toBeFocused()
  await page.keyboard.press('Enter')
  await expect(history).toHaveAttribute('aria-pressed', 'true')
  const chat = navigation.getByRole('button', { name: '对话', exact: true })
  await chat.focus()
  await page.keyboard.press('Space')
  await expect(chat).toHaveAttribute('aria-pressed', 'true')
  await expect(page.getByRole('textbox', { name: '天文问题' })).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
})
