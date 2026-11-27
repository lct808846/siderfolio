import { test, expect } from '@playwright/test'
import { chooseUiOption } from './ui-select'

test('inline N-body review routes a confirmed PeTar task and restores its result on refresh', async ({ page, request }) => {
  const projectResponse = await request.post('/api/v1/projects', { data: { name: '合成计算验收' } })
  expect(projectResponse.status()).toBe(201)
  const project = await projectResponse.json()
  const taskId = '00000000-0000-4000-8000-000000000781'
  const digest = 'b'.repeat(64)
  let created = 0, confirmed = 0
  const ready = { enabled: true, worker_ready: true, engines: ['rebound', 'petar'] }
  const task = { id: taskId, revision: 0, parameter_sha256: digest, sample_count: 129 }
  await page.route('**/api/v1/compute/status', route => route.fulfill({ json: ready }))
  await page.route(new RegExp('/api/v1/projects/' + project.id + '/compute-tasks(?:/|$)'), async route => {
    const req = route.request()
    const pathname = new URL(req.url()).pathname
    if (pathname.endsWith('/compute-tasks') && req.method() === 'POST') {
      created++
      expect(req.postDataJSON()).toMatchObject({
        source: 'conversation',
        parameters: { engine: 'petar', duration: 1, samples: 129 },
      })
      return route.fulfill({ status: 201, json: { ...task, state: 'draft' } })
    }
    if (pathname.endsWith('/confirm')) {
      confirmed++
      expect(req.postDataJSON()).toMatchObject({ expected_revision: 0, parameter_sha256: digest, confirmed: true })
      return route.fulfill({ json: { ...task, state: 'queued', samples_completed: 0 } })
    }
    if (pathname.endsWith('/result')) {
      return route.fulfill({ json: {
        engine: 'petar', integrator: 'Tree + Hermite + SDAR', wall_seconds: 1.02,
        samples: Array.from({ length: 129 }, (_, i) => ({ time: i / 128, energy_relative: 0, angular_relative: 0 })),
      } })
    }
    if (pathname.includes('/plots/')) {
      return route.fulfill({ contentType: 'image/svg+xml', body: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 2 2"><circle cx="1" cy="1" r=".5"/></svg>' })
    }
    if (pathname.endsWith('/' + taskId)) return route.fulfill({ json: { ...task, state: 'succeeded', samples_completed: 129 } })
    return route.continue()
  })
  await page.goto('/?tool=compute&project=' + project.id)
  await expect(page.getByRole('textbox', { name: '天文问题' })).toHaveAttribute('placeholder', /描述 N 体模拟需求/)
  await page.getByRole('textbox', { name: '天文问题' }).fill('__qa_inline_nbody__ 双体圆轨道')
  await page.getByRole('button', { name: '发送问题', exact: true }).click()
  const card = page.getByRole('region', { name: 'N 体模拟参数方案' })
  await expect(card.getByText('合成双体轨道', { exact: true })).toBeVisible()
  await card.getByRole('button', { name: '编辑参数' }).click()
  await chooseUiOption(page, card.getByRole('button', { name: '模拟引擎', exact: true }), /PeTar/i)
  expect([created, confirmed]).toEqual([0, 0])
  await card.getByRole('button', { name: '确认运行模拟' }).click()
  await expect(card.getByText('1.02 s', { exact: true })).toBeVisible()
  await card.getByRole('tab', { name: '位置快照' }).click()
  await expect(card.getByRole('slider')).toHaveValue('128')
  await page.reload()
  await expect(card.getByText('1.02 s', { exact: true })).toBeVisible()
  expect([created, confirmed]).toEqual([1, 1])
})

test('model selection and attachment preview do not send a message', async ({ page }) => {
  let sends = 0
  page.on('request', request => {
    if (request.method() === 'POST' && /\/turns(?:\/stream)?$/.test(new URL(request.url()).pathname)) sends++
  })
  await page.route('**/api/v1/models', route => route.fulfill({
    status: 200, contentType: 'application/json', body: JSON.stringify({
      configured: true, default_model: 'deepseek-test',
      models: [{ id: 'deepseek-test', label: 'DeepSeek' }, { id: 'qwen-test', label: 'Qwen' }],
    }),
  }))
  await page.goto('/')
  await page.getByLabel('选择附件').setInputFiles({ name: 'synthetic.txt', mimeType: 'text/plain', buffer: Buffer.from('合成附件内容') })
  await page.getByRole('button', { name: '查看附件文本：synthetic.txt' }).click()
  await expect(page.getByRole('dialog').getByText('合成附件内容')).toBeVisible()
  await page.getByRole('button', { name: '关闭附件预览' }).click()
  await page.getByRole('button', { name: '回答模型：DeepSeek' }).click()
  await page.getByRole('menuitem', { name: /模型/ }).click()
  await page.getByRole('option', { name: 'Qwen', exact: true }).click()
  await expect(page.getByRole('button', { name: '回答模型：Qwen' })).toBeVisible()
  await page.getByRole('button', { name: '移除附件：synthetic.txt' }).click()
  await expect(page.getByRole('button', { name: '查看附件文本：synthetic.txt' })).toHaveCount(0)
  expect(sends).toBe(0)
})

test('dragged attachment and edited question create separate preserved turns', async ({ page }) => {
  let sends = 0
  page.on('request', request => {
    if (request.method() === 'POST' && /\/turns(?:\/stream)?$/.test(new URL(request.url()).pathname)) sends++
  })
  await page.goto('/')
  const transfer = await page.evaluateHandle(() => {
    const data = new DataTransfer()
    data.items.add(new File(['合成拖放附件'], 'dragged.txt', { type: 'text/plain' }))
    return data
  })
  await page.locator('form.composer').dispatchEvent('drop', { dataTransfer: transfer })
  await expect(page.getByRole('button', { name: '查看附件文本：dragged.txt' })).toBeVisible()
  const input = page.getByRole('textbox', { name: '天文问题' })
  await input.fill('第一条合成查询')
  expect(sends).toBe(0)
  await page.getByRole('button', { name: '发送问题' }).click()
  await expect(page.locator('.turn').first().getByRole('button', { name: '编辑问题', exact: true })).toBeVisible()
  expect(sends).toBe(1)
  await input.fill('保留的草稿')
  await page.locator('.turn').first().getByRole('button', { name: '编辑问题', exact: true }).click()
  await expect(input).toHaveValue('第一条合成查询')
  await page.getByRole('button', { name: '取消编辑' }).click()
  await expect(input).toHaveValue('保留的草稿')
  await page.locator('.turn').first().getByRole('button', { name: '编辑问题', exact: true }).click()
  await input.fill('编辑后的第二条查询')
  expect(sends).toBe(1)
  await page.getByRole('button', { name: '发送问题' }).click()
  await expect(page.locator('.turn').nth(1).getByRole('button', { name: '编辑问题', exact: true })).toBeVisible()
  await expect(page.locator('.user-message').nth(0)).toHaveText('第一条合成查询')
  await expect(page.locator('.user-message').nth(1)).toHaveText('编辑后的第二条查询')
  expect(sends).toBe(2)
})
