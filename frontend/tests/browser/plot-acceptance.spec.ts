import { expect, test } from '@playwright/test'

test('inline plot reviews the proposal and submits one confirmed isolated run', async ({ page, request }) => {
  const response = await request.post('/api/v1/projects', { data: { name: '合成绘图验收' } })
  expect(response.status()).toBe(201)
  const project = await response.json()
  let freezes = 0, plans = 0, runs = 0
  let datasetId = '', planId = ''
  await page.route('**/api/v1/projects/' + project.id + '/plotting/**', async route => {
    const path = new URL(route.request().url()).pathname
    if (path.endsWith('/turn')) {
      freezes++
      const body = route.request().postDataJSON()
      expect(body.turn_id).toMatch(/^[0-9a-f-]+$/)
      expect(body.query_index).toBe(0)
      datasetId = path.split('/').at(-2)!
      return route.fulfill({ json: { id: datasetId } })
    }
    if (path.endsWith('/custom')) {
      plans++
      const body = route.request().postDataJSON()
      expect(body.dataset_id).toBe(datasetId)
      expect(body.proposal.columns).toEqual(['pmra', 'pmdec'])
      expect(body.proposal.script).toBe('print("synthetic plot fixture")')
      planId = path.split('/').at(-2)!
      return route.fulfill({ json: { id: planId } })
    }
    if (path.includes('/runs/') && route.request().method() === 'PUT') {
      runs++
      expect(route.request().postDataJSON()).toEqual({ plan_id: planId, confirm_execute: true })
      return route.fulfill({ json: { id: path.split('/').at(-1), state: 'completed', files: ['figure.png'] } })
    }
    if (path.endsWith('/figure.png')) {
      return route.fulfill({
        contentType: 'image/png',
        body: Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII=', 'base64'),
      })
    }
    return route.continue()
  })

  await page.goto('/projects/' + project.id + '/plotting')
  await expect(page.getByRole('button', { name: /科研绘图与 N 体实验准备/ })).toBeVisible()
  await page.getByRole('textbox', { name: '天文问题' }).fill('__qa_inline_plot__ 画自行散点图')
  await page.getByRole('button', { name: '发送问题', exact: true }).click()
  const card = page.getByRole('region', { name: '科研绘图方案' })
  await expect(card.getByRole('heading', { name: '合成 Gaia 散点' })).toBeVisible()
  await card.getByText('审阅将执行的 Python 绘图脚本').click()
  await expect(card.getByText('print("synthetic plot fixture")', { exact: true })).toBeVisible()
  expect([freezes, plans, runs]).toEqual([0, 0, 0])
  await card.getByRole('button', { name: '确认执行隔离绘图' }).click()
  await expect(card.getByRole('button', { name: '放大查看科研图形' })).toBeVisible()
  expect([freezes, plans, runs]).toEqual([1, 1, 1])
  await page.setViewportSize({ width: 390, height: 760 })
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
})
