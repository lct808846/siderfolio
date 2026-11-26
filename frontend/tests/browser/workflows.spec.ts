import { test, expect } from '@playwright/test'
import path from 'node:path'

async function expectOutputDownload(page: import('@playwright/test').Page, filename: string) {
  const card = page.locator('article.workflow-output').filter({
    has: page.getByText(filename, { exact: true }),
  })
  const [response, download] = await Promise.all([
    page.waitForResponse(response => /\/workflows\/[^/]+\/outputs\/[^/]+$/.test(new URL(response.url()).pathname) &&
      response.request().resourceType() === 'fetch', { timeout: 10000 }),
    page.waitForEvent('download', { timeout: 15000 }),
    card.getByRole('button', { name: '核对哈希并下载' }).click(),
  ])
  expect(response.ok()).toBe(true)
  expect(download.suggestedFilename()).toBe(filename)
  expect(await download.failure()).toBeNull()
}

test('fixed workflows create, confirm, execute, display outputs and restore after refresh', async ({ page, request }, info) => {
  const project = await (await request.post('/api/v1/projects', { data: { name: '合成流程验收' } })).json()
  try {
    await page.goto(`/projects/${project.id}/workflows`)
    await page.getByLabel('运行名称').fill('合成 Gaia 流程')
    await page.getByLabel('ICRS赤经 / 度 [0,360)').fill('56.75')
    await page.getByLabel('ICRS赤纬 / 度 [-90,90]').fill('24.12')
    await page.getByLabel('圆锥半径 / 角分 (0,30]').fill('5')
    const limit = page.getByLabel('交付行上限 / 1—500')
    await expect(limit).toHaveAttribute('max', '500')
    await limit.fill('10')
    await page.getByRole('button', { name: '创建待执行记录' }).click()
    await expect(page.getByRole('heading', { name: '合成 Gaia 流程' })).toBeVisible()
    await page.getByRole('button', { name: '核对并启动' }).click()
    await expect(page.getByRole('dialog')).toBeVisible()
    await page.getByRole('button', { name: '取消', exact: true }).click()
    await expect(page.getByRole('dialog')).not.toBeVisible()
    await page.getByRole('button', { name: '核对并启动' }).click()
    await page.getByRole('button', { name: '确认执行' }).click()
    await expect(page.getByText('workflow-results.zip', { exact: true })).toBeVisible({ timeout: 30000 })
    await expect(page.getByText('4 / 4 步已完成或跳过')).toBeVisible()
    await test.step('核对并下载 Gaia 归档', () => expectOutputDownload(page, 'workflow-results.zip'))
    await page.reload()
    await expect(page.getByText('workflow-results.zip', { exact: true })).toBeVisible()
    if (process.env.ASTROAGENT_RECORD_DIR) await page.screenshot({ path: path.join(process.env.ASTROAGENT_RECORD_DIR, `${info.project.name}-workflow-desktop.png`) })
    await page.setViewportSize({ width: 390, height: 844 })
    await page.getByRole('button', { name: '参数与记录', exact: true }).click()
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
    if (process.env.ASTROAGENT_RECORD_DIR) await page.screenshot({ path: path.join(process.env.ASTROAGENT_RECORD_DIR, `${info.project.name}-workflow-mobile.png`) })
    await page.setViewportSize({ width: 1440, height: 900 })
    await page.getByRole('button', { name: '新建科研流程', exact: true }).click()
    await expect(page).toHaveURL(/\/workflows$/)
    await page.getByRole('group', { name: '选择固定科研流程模板' }).getByRole('button', { name: /ADS 文献/ }).click()
    await page.getByLabel('运行名称').fill('合成 ADS 证据表')
    await page.getByLabel('实际ADS检索式').fill('synthetic')
    await page.getByRole('button', { name: '创建待执行记录' }).click()
    await expect(page.getByRole('heading', { name: '合成 ADS 证据表' })).toBeVisible()
    await page.getByRole('button', { name: '核对并启动' }).click()
    await page.getByRole('button', { name: '确认执行' }).click()
    await expect(page.getByText('ads-evidence.csv', { exact: true })).toBeVisible({ timeout: 30000 })
    await expect(page.getByText('ads-evidence.json', { exact: true })).toBeVisible()
    await test.step('核对并下载 ADS 证据表', () => expectOutputDownload(page, 'ads-evidence.csv'))
    if (process.env.ASTROAGENT_RECORD_DIR) await page.screenshot({ path: path.join(process.env.ASTROAGENT_RECORD_DIR, `${info.project.name}-workflow-ads.png`) })
  } finally {
    const detail = await (await request.get(`/api/v1/projects/${project.id}`)).json()
    await request.delete(`/api/v1/projects/${project.id}`, { data: { expected_revision: detail.revision, confirm: true } })
  }
})

test('failed workflow resumes only after confirmation and retains attempts', async ({ page, request }, info) => {
  const project = await (await request.post('/api/v1/projects', { data: { name: '合成失败恢复' } })).json()
  try {
    await page.goto(`/projects/${project.id}/workflows`)
    await page.getByLabel('运行名称').fill('合成超时后继续')
    await page.getByLabel('ICRS赤经 / 度 [0,360)').fill(info.project.name === 'edge' ? '12.34568' : '12.34567')
    // Each repeat or retry gets a new worker and its own first-failure sample.
    await page.getByLabel('ICRS赤纬 / 度 [-90,90]').fill((24.12 + info.workerIndex / 1000).toFixed(3))
    await page.getByLabel('圆锥半径 / 角分 (0,30]').fill('5')
    await page.getByLabel('交付行上限 / 1—500').fill('10')
    await page.getByRole('button', { name: '创建待执行记录' }).click()
    await expect(page.getByRole('heading', { name: '合成超时后继续' })).toBeVisible()
    const runId = new URL(page.url()).pathname.split('/').at(-1)!
    await page.getByRole('button', { name: '核对并启动' }).click()
    await page.getByRole('button', { name: '确认执行' }).click()
    await expect(page.getByRole('button', { name: '核对并继续' })).toBeVisible()
    await expect(page.getByText('gaia_timeout', { exact: true }).first()).toBeVisible()
    await page.reload()
    await page.getByRole('button', { name: '核对并继续' }).click()
    await page.getByRole('button', { name: '取消', exact: true }).click()
    const before = await (await request.get(`/api/v1/projects/${project.id}/workflows/${runId}`)).json()
    expect(before.state).toBe('failed')
    await page.getByRole('button', { name: '核对并继续' }).click()
    await page.getByRole('button', { name: '确认执行' }).click()
    await expect(page.getByText('workflow-results.zip', { exact: true })).toBeVisible()
    const after = await (await request.get(`/api/v1/projects/${project.id}/workflows/${runId}`)).json()
    expect(after.state).toBe('succeeded')
    const query = after.steps.find((step: { id: string }) => step.id === 'query_gaia')
    expect(query.attempts).toHaveLength(2)
    expect(query.attempts.map((attempt: { state: string }) => attempt.state)).toEqual(['failed', 'succeeded'])
  } finally {
    const detail = await (await request.get(`/api/v1/projects/${project.id}`)).json()
    await request.delete(`/api/v1/projects/${project.id}`, { data: { expected_revision: detail.revision, confirm: true } })
  }
})
