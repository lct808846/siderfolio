import { test, expect } from '@playwright/test'

test('model selection and attachment preview do not send a message', async ({ page }) => {
  let sends = 0
  page.on('request', request => {
    if (request.method() === 'POST' && /\/turns$/.test(new URL(request.url()).pathname)) sends++
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
  await page.getByRole('button', { name: '回答模型：deepseek-test' }).click()
  await page.getByRole('menuitem', { name: /模型/ }).click()
  await page.getByRole('option', { name: 'qwen-test' }).click()
  await expect(page.getByRole('button', { name: '回答模型：qwen-test' })).toBeVisible()
  await page.getByRole('button', { name: '移除附件：synthetic.txt' }).click()
  await expect(page.getByRole('button', { name: '查看附件文本：synthetic.txt' })).toHaveCount(0)
  expect(sends).toBe(0)
})

test('dragged attachment and edited question create separate preserved turns', async ({ page }) => {
  let sends = 0
  page.on('request', request => {
    if (request.method() === 'POST' && /\/turns$/.test(new URL(request.url()).pathname)) sends++
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
  await expect(page.getByRole('button', { name: '编辑第1轮问题' })).toBeVisible()
  expect(sends).toBe(1)
  await input.fill('保留的草稿')
  await page.getByRole('button', { name: '编辑第1轮问题' }).click()
  await expect(input).toHaveValue('第一条合成查询')
  await page.getByRole('button', { name: '取消编辑' }).click()
  await expect(input).toHaveValue('保留的草稿')
  await page.getByRole('button', { name: '编辑第1轮问题' }).click()
  await input.fill('编辑后的第二条查询')
  expect(sends).toBe(1)
  await page.getByRole('button', { name: '发送问题' }).click()
  await expect(page.getByRole('button', { name: '编辑第2轮问题' })).toBeVisible()
  await expect(page.locator('.user-message').nth(0)).toHaveText('第一条合成查询')
  await expect(page.locator('.user-message').nth(1)).toHaveText('编辑后的第二条查询')
  expect(sends).toBe(2)
})
