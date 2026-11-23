import { test, expect } from '@playwright/test'

test('responsive panels preserve drafts without sending', async ({ page }) => {
  let sends = 0
  page.on('request', request => { if (request.method() === 'POST' && /\/turns$|\/rag\/(answers|indexes)$/.test(new URL(request.url()).pathname)) sends++ })
  await page.goto('/')
  for (const width of [1440, 1439, 1200, 1024, 981, 980, 768, 681, 680, 390, 320]) {
    await page.setViewportSize({ width, height: 740 })
    await expect(page.getByRole('navigation', { name: '全局导航' })).toBeVisible()
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
    const question = page.getByRole('textbox', { name: '天文问题' })
    await question.fill('面板切换保留的测试问题')
    await page.getByRole('button', { name: '打开结果栏' }).click()
    await expect(page.getByRole('complementary', { name: '结果与文件' })).toBeVisible()
    await page.getByRole('button', { name: '收起结果面板' }).click()
    await expect(question).toHaveValue('面板切换保留的测试问题')
  }
  expect(sends).toBe(0)
  await page.goto('/projects')
  await expect(page.getByRole('navigation', { name: '当前项目导航' })).toHaveCount(0)
})

test('keyboard controls work with reduced motion and forced colors', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 700 })
  await page.emulateMedia({ reducedMotion: 'reduce', forcedColors: 'active' })
  await page.goto('/')
  const open = page.getByRole('button', { name: '打开结果栏' })
  await open.focus()
  await expect(open).toBeFocused()
  await page.keyboard.press('Enter')
  const close = page.getByRole('button', { name: '收起结果面板' })
  await expect(close).toBeVisible()
  await close.focus()
  await page.keyboard.press('Space')
  await expect(page.getByRole('textbox', { name: '天文问题' })).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
})
