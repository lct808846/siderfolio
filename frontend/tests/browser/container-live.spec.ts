import { expect, test } from '@playwright/test'

test('isolated container plot history works on desktop and narrow screens', async ({ page, request }, info) => {
  test.skip(process.env.ASTROAGENT_CONTAINER_LIVE !== '1', 'Requires a separately prepared synthetic container deployment')
  const response = await request.get('/api/v1/projects')
  expect(response.ok()).toBe(true)
  const projects = await response.json() as { id: string; name: string }[]
  let project: { id: string; name: string } | undefined
  for (const candidate of projects.filter(value => value.name.startsWith('容器验收合成项目'))) {
    const records = await (await request.get(`/api/v1/projects/${candidate.id}/plotting`)).json()
    if (records.operations?.some((op: { kind: string; state: string }) => op.kind === 'run' && op.state === 'completed')) {
      project = candidate
      break
    }
  }
  expect(project).toBeDefined()
  for (const [name, width] of [['desktop', 1440], ['mobile', 390]] as const) {
    await page.setViewportSize({ width, height: 800 })
    await page.goto(`/projects/${project!.id}/plotting`)
    await page.getByRole('button', { name: '展开绘图列表' }).click()
    const run = page.locator('.plot-record').filter({ hasText: '运行 · 已完成' }).first()
    await expect(run).toBeVisible()
    await run.click()
    await expect(page.getByRole('button', { name: '放大绘图' })).toBeVisible()
    await expect(page.getByRole('button', { name: '保存所选文件 ZIP' })).toBeVisible()
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
    await info.attach(`container-${name}`, {
      body: await page.screenshot({ mask: [page.locator('.conversation-list'), page.locator('.workbench-plot-context')] }),
      contentType: 'image/png',
    })
  }
})
