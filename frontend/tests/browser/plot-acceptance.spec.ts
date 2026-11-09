import { expect, test } from '@playwright/test'

test('plot workflow requires confirmations before model and execution', async ({ page }) => {
  const projectId = '10000000-0000-4000-8000-000000000001'
  const datasets: Record<string, unknown>[] = []
  const operations: Record<string, unknown>[] = []
  let plans = 0, runs = 0
  const proposal = { engine: 'python', chart: 'scatter', title: '合成散点', columns: ['x', 'y'], axes: { x: 'x', y: 'y' }, filters: [], warnings: [], explanation: '合成测试', script: 'print("synthetic")' }
  await page.route('**/api/v1/**', async route => {
    const request = route.request(), url = new URL(request.url()), path = url.pathname
    const json = (body: unknown) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) })
    if (path === '/api/v1/models') return json({ configured: true, default_model: 'synthetic', models: [{ id: 'synthetic', label: 'synthetic' }] })
    if (path === '/api/v1/setup/plotting') return json({ storage_ready: true, execution_configured: true, message: '合成测试' })
    if (path === `/api/v1/projects/${projectId}`) return json({ id: projectId, name: '合成项目', snapshots: [], revision: 0, conversation_ids: [] })
    if (path.endsWith('/plotting')) return json({ datasets, operations })
    if (path.endsWith('/upload')) {
      const id = path.split('/').at(-2)!
      const value = { id, project_id: projectId, name: 'synthetic.csv', source: 'upload', rows: 2, columns: [{ name: 'x', kind: 'number', missing: 0 }, { name: 'y', kind: 'number', missing: 0 }], warnings: [], provenance: {} }
      datasets.push(value); return json(value)
    }
    if (path.endsWith('/preview')) return json({ dataset_id: path.split('/').at(-2), rows: 2, sample_rows: 2, sample: [['1', '2'], ['2', '4']], columns: datasets[0].columns, warnings: [] })
    if (path.includes('/plans/')) {
      plans++; const payload = request.postDataJSON(); expect(payload.confirm_external_data).toBe(true)
      const value = { id: path.split('/').at(-1), project_id: projectId, dataset_id: payload.dataset_id, kind: 'plan', state: 'completed', proposal, request: payload, files: [], imported: false }
      operations.push(value); return json(value)
    }
    if (path.includes('/runs/') && request.method() === 'PUT') {
      runs++; const payload = request.postDataJSON(); expect(payload.confirm_execute).toBe(true)
      const value = { id: path.split('/').at(-1), project_id: projectId, dataset_id: datasets[0].id, kind: 'run', state: 'completed', proposal, request: payload, files: ['figure.png', 'script.py'], imported: false }
      operations.push(value); return json(value)
    }
    if (path.endsWith('/figure.png')) return route.fulfill({ status: 200, contentType: 'image/png', body: Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII=', 'base64') })
    return route.fulfill({ status: 404, contentType: 'application/json', body: '{}' })
  })
  await page.goto(`/projects/${projectId}/plotting`)
  await page.locator('input[type=file]').setInputFiles({ name: 'synthetic.csv', mimeType: 'text/csv', buffer: Buffer.from('x,y\n1,2\n2,4\n') })
  await expect(page.getByLabel('绘图需求')).toBeVisible()
  await page.getByLabel('绘图需求').fill('绘制散点图')
  await expect(page.getByRole('button', { name: '生成绘图方案' })).toBeDisabled()
  expect(plans).toBe(0)
  await page.getByLabel(/确认将需求、列信息/).check()
  await page.getByRole('button', { name: '生成绘图方案' }).click()
  await expect(page.getByText('实际绘图脚本')).toBeVisible()
  expect(plans).toBe(1)
  await expect(page.getByRole('button', { name: '确认隔离执行' })).toBeDisabled()
  expect(runs).toBe(0)
  await page.getByLabel(/我已核对脚本/).check()
  await page.getByRole('button', { name: '确认隔离执行' }).click()
  await expect(page.getByRole('button', { name: '放大绘图' })).toBeVisible()
  expect(runs).toBe(1)
  await page.setViewportSize({ width: 390, height: 700 })
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
})
