# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: overview.spec.ts >> project overview creates and removes an explicit evidence link
- Location: frontend\tests\browser\overview.spec.ts:4:1

# Error details

```
Error: expect(locator).toBeVisible() failed

Locator:  getByText('已解除关联')
Expected: visible
Received: hidden
Timeout:  5000ms

Call log:
  - Expect "toBeVisible" getByText('已解除关联') with timeout 5000ms
  - waiting for getByText('已解除关联')
    12 × locator resolved to <p role="status" class="notice">已解除关联。结果、证据、文档和原回答保留。原创建请求的历史不会再次建立此关联。</p>
       - unexpected value "hidden"

```

```yaml
- banner:
  - link "AstroAgent 0.9":
    - /url: /
  - link "管理项目 ↗":
    - /url: /projects/dbe867bc-9dbd-4a1a-b10b-c2b0c2699279
- navigation "总览面板":
  - button "项目来源"
  - button "建立与管理关联"
  - button "核对两端"
- complementary "来源核对":
  - paragraph: VERIFY / 精确来源
  - heading "关联测试 · 第1轮" [level=2]
  - paragraph: 会话轮次 · completed
  - link "打开完整结果 →":
    - /url: /conversations/08b8cc5f-4965-473d-bfcc-274bf3174dae?turn=87d458d8-6702-4d4b-ab65-c6ebb18a0197
  - paragraph: 先选择原文证据，再核对并确认建立用户引用。
  - group: 结果版本、软件与时间
  - heading "原结果中记录的来源" [level=3]
  - article:
    - text: 数据库测量
    - paragraph: Gaia · success
    - time: 2026-10-31T02:16:04.269826Z
    - link "https://example.invalid/synthetic-gaia":
      - /url: https://example.invalid/synthetic-gaia
  - article:
    - text: 原回答或程序说明
    - paragraph: 保存的回答或程序说明（不新增引用） · success
```

# Test source

```ts
  1  | import { test, expect } from '@playwright/test'
  2  | import path from 'node:path'
  3  | 
  4  | test('project overview creates and removes an explicit evidence link', async ({ page, request }, info) => {
  5  |   const projectResponse = await request.post('/api/v1/projects', { data: { name: '合成关联验收' } })
  6  |   expect(projectResponse.status()).toBe(201)
  7  |   const project = await projectResponse.json()
  8  |   const conversation = await (await request.post('/api/v1/conversations', { data: { title: '关联测试' } })).json()
  9  |   try {
  10 |     const turn = await request.post(`/api/v1/conversations/${conversation.id}/turns`, { data: { message: '合成数据', expected_revision: 0, client_request_id: crypto.randomUUID() } })
  11 |     expect(turn.ok()).toBeTruthy()
  12 |     const current = await (await request.get(`/api/v1/conversations/${conversation.id}`)).json()
  13 |     const membership = await request.put(`/api/v1/projects/${project.id}/conversations/${conversation.id}`, { data: { expected_revision: 0, expected_conversation_revision: current.revision, expected_metadata_revision: current.metadata_revision, expected_source_project_id: null } })
  14 |     expect(membership.ok(), await membership.text()).toBeTruthy()
  15 |     await page.goto(`/projects/${project.id}/knowledge`)
  16 |     await page.getByLabel('选择文件（断线后可重选同一文件核对）').setInputFiles({ name: 'synthetic.md', mimeType: 'text/markdown', buffer: Buffer.from('# 合成文献\n银河潮汐 synthetic evidence\n') })
  17 |     await page.getByRole('button', { name: '保存文件并本地解析' }).click()
  18 |     await expect(page.getByRole('heading', { name: 'synthetic.md', exact: true })).toBeVisible({ timeout: 30000 })
  19 |     await page.getByLabel('问题中的明确关键词').fill('银河潮汐')
  20 |     await page.getByRole('button', { name: '检索原文证据' }).click()
  21 |     await page.getByRole('button', { name: '核对引用与原始版本' }).first().click()
  22 |     await page.getByRole('link', { name: '关联此原文与项目结果' }).click()
  23 |     await expect(page.getByRole('heading', { name: '把结果与原文放在一起核对' })).toBeVisible()
  24 |     const target = page.getByLabel('同项目结果')
  25 |     await expect(target.locator('option')).toHaveCount(2)
  26 |     await target.selectOption({ index: 1 })
  27 |     await page.getByLabel('用户备注（可选，最多1000字）').fill('合成备注')
  28 |     const create = page.getByRole('button', { name: '核对后建立关联' })
  29 |     await expect(create).toBeEnabled()
  30 |     await create.click()
  31 |     await expect(page.getByRole('dialog')).toContainText('合成备注')
  32 |     await page.getByRole('dialog').getByRole('button', { name: '取消' }).click()
  33 |     await expect(page.getByText('项目关联 · 0/1000')).toBeVisible()
  34 |     await create.click()
  35 |     await page.getByRole('dialog').getByRole('button', { name: '确认关联这两项' }).click()
  36 |     await expect(page.getByText('已建立用户引用关系', { exact: false })).toBeVisible()
  37 |     await expect(page.getByLabel('来源核对').getByText('银河潮汐 synthetic evidence', { exact: false })).toBeVisible()
  38 |     if (process.env.ASTROAGENT_RECORD_DIR) await page.screenshot({ path: path.join(process.env.ASTROAGENT_RECORD_DIR, `${info.project.name}-overview.png`) })
  39 |     await page.setViewportSize({ width: 390, height: 844 })
  40 |     await page.getByRole('button', { name: '核对两端' }).click()
  41 |     expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  42 |     await page.getByRole('button', { name: '仅解除关联' }).click()
  43 |     await page.getByRole('dialog').getByRole('button', { name: '确认只解除关联' }).click()
> 44 |     await expect(page.getByText('已解除关联', { exact: false })).toBeVisible()
     |                                                             ^ Error: expect(locator).toBeVisible() failed
  45 |   } finally {
  46 |     const detail = await (await request.get(`/api/v1/projects/${project.id}`)).json()
  47 |     await request.delete(`/api/v1/projects/${project.id}`, { data: { expected_revision: detail.revision, confirm: true } })
  48 |     const latest = await (await request.get(`/api/v1/conversations/${conversation.id}`)).json()
  49 |     await request.delete(`/api/v1/conversations/${conversation.id}`, { data: { expected_revision: latest.revision, confirm: true } })
  50 |   }
  51 | })
  52 | 
```