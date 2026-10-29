# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: projects.spec.ts >> projects: full snapshots, explicit rerun, compare, ZIP recovery and preserved conversations
- Location: tests\browser\projects.spec.ts:5:1

# Error details

```
Error: expect(locator).toBeVisible() failed

Locator: getByText('查看完整交付表格（100 行）')
Expected: visible
Timeout: 5000ms
Error: element(s) not found

Call log:
  - Expect "toBeVisible" getByText('查看完整交付表格（100 行）') with timeout 5000ms
  - waiting for getByText('查看完整交付表格（100 行）')

```

```yaml
- banner:
  - link "AstroAgent 0.6":
    - /url: /
  - text: 项目与查询归档
  - link "返回对话 ↗":
    - /url: /
- complementary "项目列表":
  - paragraph: RESEARCH PROJECTS · 2/20
  - link "候选源复核项目 导入 · 未认证 · r0":
    - /url: /projects/a62df77b-aec6-4c2d-866f-5b2e65208c1d
  - link "候选源复核项目 本机项目 · r4":
    - /url: /projects/f2ca5759-5eef-4f12-aec6-2014befbe4c3
  - heading "新建项目" [level=2]
  - text: 项目名称
  - textbox "项目名称"
  - text: 项目说明（可选）
  - textbox "项目说明（可选）"
  - button "创建项目" [disabled]
  - text: 导入项目 ZIP
  - button "导入项目 ZIP"
  - paragraph: 最多32 MiB；恢复为新副本。
  - heading "未归档会话 · 0" [level=3]
- main:
  - paragraph: PROJECT / r0
  - heading "候选源复核项目" [level=1]
  - paragraph: 保留条件、来源和完整结果，不推断成员。
  - code: a62df77b-aec6-4c2d-866f-5b2e65208c1d
  - paragraph: 导入来源未经认证。哈希只验证包内完整性；历史数据不会因导入而重新查询。
  - button "导出项目 ZIP"
  - button "删除项目"
  - button "刷新项目"
  - group: 修改项目名称与说明
  - heading "项目会话 2/20" [level=2]
  - link "直接重跑 · gaia · 1轮":
    - /url: /conversations/35e1781d-492c-4366-a970-7d1b3e9b217a
  - button "移出项目"
  - link "项目验收100行 · 1轮":
    - /url: /conversations/cfa95094-8ce2-4c3e-bf2d-63c031dd33e8
  - button "移出项目"
  - text: 选择要加入的会话
  - combobox "选择要加入的会话":
    - option "选择会话加入 / 移动" [selected]
    - option "直接重跑 · gaia（从其他项目移动）"
    - option "项目验收100行（从其他项目移动）"
  - button "加入项目" [disabled]
  - heading "保存命名快照" [level=2]
  - text: 项目内会话
  - combobox "项目内会话":
    - option "选择会话" [selected]
    - option "直接重跑 · gaia"
    - option "项目验收100行"
  - text: 完整响应轮次
  - combobox "完整响应轮次":
    - option "选择可交付轮次" [selected]
  - text: 快照名称
  - textbox "快照名称"
  - button "保存完整快照" [disabled]
  - heading "命名快照 2/100" [level=2]
  - paragraph: 保存完整交付响应，比较与重跑均保留旧结果。
  - button "查看快照 重跑 · gaia": 重跑 · gaia success 2026-10-29T04:22:20.379181+00:00 · a049e572 导入 · 未认证
  - button "查看快照 原始完整样本": 原始完整样本 success 2026-10-29T04:22:18.775561+00:00 · e14f2f3f 导入 · 未认证
  - heading "比较两份快照" [level=2]
  - text: 左侧快照
  - combobox "左侧快照":
    - option "选择快照" [selected]
    - option "重跑 · gaia · a049e572"
    - option "原始完整样本 · e14f2f3f"
  - text: 右侧快照
  - combobox "右侧快照":
    - option "选择快照" [selected]
    - option "重跑 · gaia · a049e572"
    - option "原始完整样本 · e14f2f3f"
  - checkbox "按精确 source_id / bibcode 比较交付编号"
  - text: 按精确 source_id / bibcode 比较交付编号
  - button "比较已存快照" [disabled]
  - heading "直接重跑记录" [level=2]
  - article:
    - text: completed gaia ·
    - time: 2026-10-29T04:22:20.345781+00:00
    - button "查看重跑新快照"
    - group: 实际参数与记录编号
- complementary "结果核查":
  - text: RESULTS / 数据核查
  - heading "选择一份快照" [level=2]
  - heading "让每一个结论有据可查" [level=3]
  - paragraph: 查询后在这里核查测量、检索条件和来源。
  - text: 等待查询数据
```

# Test source

```ts
  1  | import { test, expect } from '@playwright/test'
  2  | import { mkdirSync, readFileSync } from 'node:fs'
  3  | import path from 'node:path'
  4  | 
  5  | test('projects: full snapshots, explicit rerun, compare, ZIP recovery and preserved conversations', async ({ page, request, browser }, info) => {
  6  |   info.annotations.push({ type: 'browser_version', description: browser.version() })
  7  |   const errors: string[] = []; page.on('pageerror', e => errors.push(e.message))
  8  |   const ownedProjects = new Set<string>(), ownedConversations = new Set<string>()
  9  |   const screenshot = async (name: string) => { if (process.env.ASTROAGENT_RECORD_DIR) { mkdirSync(process.env.ASTROAGENT_RECORD_DIR, { recursive: true }); await page.screenshot({ path: path.join(process.env.ASTROAGENT_RECORD_DIR, `${info.project.name}-project-${name}.png`) }) } }
  10 |   try {
  11 |     const created = await request.post('/api/v1/conversations', { data: { title: '项目验收100行' } }); const c = await created.json(); ownedConversations.add(c.id)
  12 |     const turn = await request.post(`/api/v1/conversations/${c.id}/turns`, { data: { message: '合成Gaia100行验收，不是实际观测。', expected_revision: 0, client_request_id: crypto.randomUUID() } })
  13 |     expect(turn.ok()).toBeTruthy()
  14 |     await page.goto('/projects')
  15 |     await page.getByLabel('项目名称', { exact: true }).fill('候选源复核项目')
  16 |     await page.getByLabel('项目说明（可选）').fill('保留条件、来源和完整结果，不推断成员。')
  17 |     await page.getByRole('button', { name: '创建项目', exact: true }).click()
  18 |     await expect(page.getByRole('heading', { name: '候选源复核项目', exact: true })).toBeVisible()
  19 |     const id = new URL(page.url()).pathname.split('/').at(-1)!; ownedProjects.add(id)
  20 |     await page.getByLabel('选择要加入的会话').selectOption(c.id)
  21 |     await page.getByRole('button', { name: '加入项目', exact: true }).click()
  22 |     await expect(page.getByRole('button', { name: '移出项目' })).toBeVisible()
  23 |     await page.getByLabel('项目内会话').selectOption(c.id)
  24 |     await expect(page.getByLabel('完整响应轮次').locator('option')).toHaveCount(2)
  25 |     await page.getByLabel('快照名称', { exact: true }).fill('原始完整样本')
  26 |     await page.getByRole('button', { name: '保存完整快照', exact: true }).click()
  27 |     await page.getByRole('button', { name: '查看快照 原始完整样本' }).click()
  28 |     await expect(page.getByText('查看完整交付表格（100 行）')).toBeVisible()
  29 |     await page.getByText('查看完整交付表格（100 行）').click()
  30 |     await expect(page.getByRole('cell', { name: '5853498713190525696', exact: true })).toBeVisible()
  31 |     await page.getByLabel('自行散点图', { exact: true }).check()
  32 |     await page.getByRole('button', { name: '生成预览与数据包' }).click()
  33 |     await expect(page.getByRole('img', { name: '自行散点图', exact: true })).toBeVisible()
  34 |     await page.locator('.project-main').evaluate(el => { el.scrollTop = 0 }); await screenshot('desktop')
  35 |     let rerunRequests = 0; page.on('request', r => { if (r.method() === 'POST' && r.url().endsWith('/reruns')) rerunRequests++ })
  36 |     await page.getByLabel('选择单条工具查询重跑').selectOption('gaia:0')
  37 |     await page.getByRole('button', { name: '核对并重跑单条查询' }).click()
  38 |     await expect(page.getByRole('dialog')).toBeVisible(); expect(rerunRequests).toBe(0)
  39 |     await page.getByRole('button', { name: '确认访问数据源并重跑' }).click()
  40 |     await expect(page.getByRole('button', { name: '查看重跑新快照' })).toBeVisible(); expect(rerunRequests).toBe(1)
  41 |     const result = await request.get(`/api/v1/projects/${id}`); const p = await result.json()
  42 |     const original = p.snapshots.find((s: { name: string }) => s.name === '原始完整样本'), newer = p.snapshots.find((s: { name: string }) => s.name === '重跑 · gaia')
  43 |     for (const cid of p.conversation_ids) ownedConversations.add(cid)
  44 |     expect(original.id).not.toBe(newer.id)
  45 |     await page.getByLabel('左侧快照').selectOption(original.id); await page.getByLabel('右侧快照').selectOption(newer.id)
  46 |     await page.getByLabel('按精确 source_id / bibcode 比较交付编号').check()
  47 |     await page.getByRole('button', { name: '比较已存快照' }).click()
  48 |     await expect(page.getByText('仅比较交付样本与查询元数据；不表示总体增减、显著性或成员变化。')).toBeVisible(); await screenshot('comparison')
  49 |     const download = page.waitForEvent('download'); await page.getByRole('button', { name: '导出项目 ZIP' }).click()
  50 |     const file = await download; expect(file.suggestedFilename()).toBe('astroagent-project.zip')
  51 |     const raw = readFileSync((await file.path())!)
  52 |     if (process.env.ASTROAGENT_RECORD_DIR) await file.saveAs(path.join(process.env.ASTROAGENT_RECORD_DIR, `${info.project.name}-project.zip`))
  53 |     await page.getByLabel('导入项目 ZIP', { exact: true }).setInputFiles({ name: 'restored.zip', mimeType: 'application/zip', buffer: raw })
  54 |     await expect(page).not.toHaveURL(new RegExp(`/projects/${id}`))
  55 |     await expect(page.getByText('导入来源未经认证。哈希只验证包内完整性；历史数据不会因导入而重新查询。')).toBeVisible()
  56 |     const importedId = new URL(page.url()).pathname.split('/').at(-1)!; ownedProjects.add(importedId)
  57 |     const imported = await (await request.get(`/api/v1/projects/${importedId}`)).json()
  58 |     for (const cid of imported.conversation_ids) ownedConversations.add(cid)
  59 |     expect(imported.snapshots).toHaveLength(2)
  60 |     await page.getByRole('button', { name: '查看快照 原始完整样本' }).click()
> 61 |     await page.reload(); await expect(page.getByText('查看完整交付表格（100 行）')).toBeVisible()
     |                                                                          ^ Error: expect(locator).toBeVisible() failed
  62 |     await page.setViewportSize({ width: 390, height: 844 }); await page.getByRole('button', { name: '项目记录', exact: true }).click()
  63 |     await page.locator('.project-main').evaluate(el => { el.scrollTop = 0 }); await screenshot('mobile')
  64 |     expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  65 |     await page.getByRole('button', { name: '删除项目', exact: true }).click()
  66 |     await expect(page.getByRole('dialog')).toContainText('会话及其轮次保留')
  67 |     await page.getByRole('button', { name: '确认删除', exact: true }).click()
  68 |     await expect(page).toHaveURL(/\/projects$/)
  69 |     for (const cid of imported.conversation_ids) expect((await request.get(`/api/v1/conversations/${cid}`)).ok()).toBe(true)
  70 |     await page.getByLabel('导入项目 ZIP', { exact: true }).setInputFiles({ name: 'broken.zip', mimeType: 'application/zip', buffer: Buffer.from('broken') })
  71 |     await expect(page.getByRole('alert')).toContainText('项目包校验失败')
  72 |     expect(errors).toEqual([])
  73 |   } finally {
  74 |     for (const id of ownedProjects) {
  75 |       const response = await request.get(`/api/v1/projects/${id}`)
  76 |       if (response.ok()) { const p = await response.json(); await request.delete(`/api/v1/projects/${id}`, { data: { expected_revision: p.revision, confirm: true } }) }
  77 |     }
  78 |     for (const id of ownedConversations) await request.delete(`/api/v1/conversations/${id}`)
  79 |   }
  80 | })
  81 | 
```