# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: overview.spec.ts >> project overview creates and removes an explicit evidence link
- Location: tests\browser\overview.spec.ts:4:1

# Error details

```
Error: expect(locator).toBeVisible() failed

Locator:  getByText('银河潮汐 synthetic evidence').first()
Expected: visible
Received: hidden
Timeout:  5000ms

Call log:
  - Expect "toBeVisible" getByText('银河潮汐 synthetic evidence').first() with timeout 5000ms
  - waiting for getByText('银河潮汐 synthetic evidence').first()
    14 × locator resolved to <pre># 合成文献↵银河潮汐 synthetic evidence↵</pre>
       - unexpected value "hidden"

```

```yaml
- banner:
  - link "AstroAgent 0.9":
    - /url: /
  - text: 项目来源与显式引用
  - link "管理项目 ↗":
    - /url: /projects/86a38b61-62cc-4894-831c-48dd18bd504f
- complementary:
  - paragraph: PROJECT / OVERVIEW
  - heading "合成关联验收" [level=2]
  - paragraph: r5 · 本机项目
  - navigation:
    - link "会话、快照与归档":
      - /url: /projects/86a38b61-62cc-4894-831c-48dd18bd504f
    - link "科研流程 · 0":
      - /url: /projects/86a38b61-62cc-4894-831c-48dd18bd504f/workflows
    - link "本地知识库 · 1":
      - /url: /projects/86a38b61-62cc-4894-831c-48dd18bd504f/knowledge?link_target_type=conversation_turn&link_target_id=0e466004-2ce3-47d8-9720-3f5e8292b7dc
  - heading "会话 · 1" [level=3]
  - group: 关联测试 · 1轮
  - heading "命名快照 · 0" [level=3]
  - heading "科研流程 · 0" [level=3]
  - heading "本地文档 · 1" [level=3]
  - link "synthetic.md ready · 用户文档":
    - /url: /projects/86a38b61-62cc-4894-831c-48dd18bd504f/knowledge/a12d592f-4111-4b1c-b725-dd7330fe5ba7
- main:
  - status: 已建立用户引用关系。原回答、sources和科研统计未改变。
  - button "刷新总览（只读）"
  - paragraph: 总览只读取保存的记录，不查询外部服务、不检索全文、不调用模型。用户备注和手动关联不改写原回答或科研统计。
  - paragraph: USER REFERENCE
  - heading "把结果与原文放在一起核对" [level=1]
  - paragraph: 手动关联仅表示你选择的引用关系。用户备注与文献原文分开保存，不表示科学证明、支持或反驳。
  - text: 同项目结果
  - combobox "同项目结果":
    - option "选择会话轮次、快照或流程"
    - option "会话轮次 · 关联测试 · 第1轮 · completed" [selected]
  - link "在本项目知识库检索并选择原文证据 →":
    - /url: /projects/86a38b61-62cc-4894-831c-48dd18bd504f/knowledge?link_target_type=conversation_turn&link_target_id=0e466004-2ce3-47d8-9720-3f5e8292b7dc
  - text: 已保存证据编号
  - combobox "已保存证据编号": 5936761c-eaed-4369-96ac-a5a54d752a30
  - paragraph: synthetic.md · 原始行1—2 用户文档提取原文；关键词命中不代表支持问题中的命题，PDF复杂排版可能缺漏。
  - group: 待关联的固定原文版本
  - text: 用户备注（可选，最多1000字）
  - textbox "用户备注（可选，最多1000字）": 合成备注
  - button "核对后建立关联"
  - heading "项目关联 · 1/1000" [level=2]
  - text: 目标类型
  - combobox "目标类型":
    - option "全部类型" [selected]
    - option "会话轮次"
    - option "命名快照"
    - option "科研流程"
  - button "读取首页"
  - button "下一页" [disabled]
  - paragraph: 每页最多25条，按不可变关联ID排序；新记录请刷新首页。此筛选共1条。
  - article:
    - text: 当前可核对 会话轮次
    - heading "关联测试 · 第1轮" [level=3]
    - paragraph: 用户备注：合成备注
    - paragraph: UTC 2026-10-31T02:15:12.728847+00:00 · r0 · 本机用户关联
    - button "查看两端与来源 →"
- complementary "来源核对":
  - paragraph: VERIFY / 精确来源
  - heading "当前可核对" [level=2]
  - paragraph: user_reference只表示用户建立的引用关系，不构成支持、反驳或科学证明。
  - heading "关联测试 · 第1轮" [level=3]
  - paragraph: completed · local
  - link "打开关联的结果 →":
    - /url: /conversations/e67df35e-d56b-4713-8d9f-46eda86952ef?turn=0e466004-2ce3-47d8-9720-3f5e8292b7dc
  - heading "用户文档原文" [level=3]
  - paragraph: synthetic.md · 行1—2
  - paragraph: 用户文档提取原文；关键词命中不代表支持问题中的命题，PDF复杂排版可能缺漏。
  - paragraph: 证据保存时间（UTC）：2026-10-31T02:15:12.191304+00:00
  - text: "# 合成文献 银河潮汐 synthetic evidence"
  - link "核对固定原文与文件哈希 →":
    - /url: /projects/86a38b61-62cc-4894-831c-48dd18bd504f/knowledge?evidence_id=5936761c-eaed-4369-96ac-a5a54d752a30
  - heading "用户备注（独立于原文）" [level=3]
  - textbox "修改用户备注": 合成备注
  - button "保存备注"
  - button "仅解除关联"
  - group: 固定版本、哈希及关联身份
  - group: 结果版本、软件与时间
  - heading "原结果中记录的来源" [level=3]
  - article:
    - text: 数据库测量
    - paragraph: Gaia · success
    - time: 2026-10-31T02:15:11.336136Z
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
> 37 |     await expect(page.getByText('银河潮汐 synthetic evidence', { exact: false }).first()).toBeVisible()
     |                                                                                       ^ Error: expect(locator).toBeVisible() failed
  38 |     if (process.env.ASTROAGENT_RECORD_DIR) await page.screenshot({ path: path.join(process.env.ASTROAGENT_RECORD_DIR, `${info.project.name}-overview.png`) })
  39 |     await page.setViewportSize({ width: 390, height: 844 })
  40 |     await page.getByRole('button', { name: '核对两端' }).click()
  41 |     expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  42 |     await page.getByRole('button', { name: '仅解除关联' }).click()
  43 |     await page.getByRole('dialog').getByRole('button', { name: '确认只解除关联' }).click()
  44 |     await expect(page.getByText('已解除关联', { exact: false })).toBeVisible()
  45 |   } finally {
  46 |     const detail = await (await request.get(`/api/v1/projects/${project.id}`)).json()
  47 |     await request.delete(`/api/v1/projects/${project.id}`, { data: { expected_revision: detail.revision, confirm: true } })
  48 |     const latest = await (await request.get(`/api/v1/conversations/${conversation.id}`)).json()
  49 |     await request.delete(`/api/v1/conversations/${conversation.id}`, { data: { expected_revision: latest.revision, confirm: true } })
  50 |   }
  51 | })
  52 | 
```