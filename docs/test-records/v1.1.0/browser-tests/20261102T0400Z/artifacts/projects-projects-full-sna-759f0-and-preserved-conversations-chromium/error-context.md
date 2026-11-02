# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: projects.spec.ts >> projects: full snapshots, explicit rerun, compare, ZIP recovery and preserved conversations
- Location: tests\browser\projects.spec.ts:5:1

# Error details

```
Error: expect(locator).toContainText(expected) failed

Locator: getByRole('alert')
Expected substring: "项目包校验失败"
Timeout: 5000ms
Error: element(s) not found

Call log:
  - Expect "toContainText" getByRole('alert') with timeout 5000ms
  - waiting for getByRole('alert')

```

```yaml
- banner:
  - link "AstroAgent 查询工作台":
    - /url: /
    - text: AstroAgent 1.1.0
  - navigation "全局导航":
    - link "查询工作台":
      - /url: /
    - link "项目归档":
      - /url: /projects
    - link "本机设置":
      - /url: /settings
    - link "接口文档 ↗":
      - /url: http://127.0.0.1:8000/docs
  - navigation "当前项目导航":
    - link "项目记录":
      - /url: /projects/
    - link "来源关联":
      - /url: /projects//overview
    - link "科研流程":
      - /url: /projects//workflows
    - link "本地知识库":
      - /url: /projects//knowledge
    - link "文献问答":
      - /url: /projects//rag
- navigation "项目面板":
  - button "项目列表" [pressed]
  - button "项目记录"
  - button "快照结果"
- complementary "项目列表":
  - paragraph: RESEARCH PROJECTS · 1/20
  - link "候选源复核项目 本机项目 · r4":
    - /url: /projects/cda01d55-8ff2-4e9f-8bf2-5422b9afad94
  - heading "新建项目" [level=2]
  - text: 项目名称
  - textbox "项目名称"
  - text: 项目说明（可选）
  - textbox "项目说明（可选）"
  - button "创建项目" [disabled]
  - text: 导入项目 ZIP
  - button "导入项目 ZIP"
  - paragraph: 最多32 MiB；恢复为新副本。
  - heading "未归档会话 · 2" [level=3]
  - link "直接重跑 · gaia":
    - /url: /conversations/39059721-a0b9-4d7e-8985-51dc94aa7fd6
  - link "项目验收100行":
    - /url: /conversations/a3507e85-0a45-4f1c-9743-32d0f451d10b
```

# Test source

```ts
  1   | import { test, expect } from '@playwright/test'
  2   | import { mkdirSync, readFileSync } from 'node:fs'
  3   | import path from 'node:path'
  4   | 
  5   | test('projects: full snapshots, explicit rerun, compare, ZIP recovery and preserved conversations', async ({ page, request, browser }, info) => {
  6   |   info.annotations.push({ type: 'browser_version', description: browser.version() })
  7   |   const errors: string[] = []; page.on('pageerror', e => errors.push(e.message))
  8   |   const ownedProjects = new Set<string>(), ownedConversations = new Set<string>()
  9   |   const screenshot = async (name: string) => { if (process.env.ASTROAGENT_RECORD_DIR) { mkdirSync(process.env.ASTROAGENT_RECORD_DIR, { recursive: true }); await page.screenshot({ path: path.join(process.env.ASTROAGENT_RECORD_DIR, `${info.project.name}-project-${name}.png`) }) } }
  10  |   try {
  11  |     const created = await request.post('/api/v1/conversations', { data: { title: '项目验收100行' } }); const c = await created.json(); ownedConversations.add(c.id)
  12  |     const turn = await request.post(`/api/v1/conversations/${c.id}/turns`, { data: { message: '合成Gaia100行验收，不是实际观测。', expected_revision: 0, client_request_id: crypto.randomUUID() } })
  13  |     expect(turn.ok()).toBeTruthy()
  14  |     await page.goto('/projects')
  15  |     await page.getByLabel('项目名称', { exact: true }).fill('候选源复核项目')
  16  |     await page.getByLabel('项目说明（可选）').fill('保留条件、来源和完整结果，不推断成员。')
  17  |     await page.getByRole('button', { name: '创建项目', exact: true }).click()
  18  |     await expect(page.getByRole('heading', { name: '候选源复核项目', exact: true })).toBeVisible()
  19  |     const id = new URL(page.url()).pathname.split('/').at(-1)!; ownedProjects.add(id)
  20  |     await page.getByLabel('选择要加入的会话').selectOption(c.id)
  21  |     await page.getByRole('button', { name: '加入项目', exact: true }).click()
  22  |     await expect(page.getByRole('button', { name: '移出项目' })).toBeVisible()
  23  |     await page.getByLabel('项目内会话').selectOption(c.id)
  24  |     await expect(page.getByLabel('完整响应轮次').locator('option')).toHaveCount(2)
  25  |     await page.getByLabel('快照名称', { exact: true }).fill('原始完整样本')
  26  |     await page.getByRole('button', { name: '保存完整快照', exact: true }).click()
  27  |     await page.getByRole('button', { name: '查看快照 原始完整样本' }).click()
  28  |     await expect(page.getByText('查看完整交付表格（100 行）')).toBeVisible()
  29  |     await page.getByText('查看完整交付表格（100 行）').click()
  30  |     await expect(page.getByRole('cell', { name: '5853498713190525696', exact: true })).toBeVisible()
  31  |     await page.getByLabel('自行散点图', { exact: true }).check()
  32  |     await page.getByRole('button', { name: '生成预览与数据包' }).click()
  33  |     await expect(page.getByRole('img', { name: '自行散点图', exact: true })).toBeVisible()
  34  |     await page.locator('.project-main').evaluate(el => { el.scrollTop = 0 }); await screenshot('desktop')
  35  |     let rerunRequests = 0; page.on('request', r => { if (r.method() === 'POST' && r.url().endsWith('/reruns')) rerunRequests++ })
  36  |     await page.getByLabel('选择单条工具查询重跑').selectOption('gaia:0')
  37  |     await page.getByRole('button', { name: '核对并重跑单条查询' }).click()
  38  |     await expect(page.getByRole('dialog')).toBeVisible(); expect(rerunRequests).toBe(0)
  39  |     await page.keyboard.press('Escape'); await expect(page.getByRole('dialog')).not.toBeVisible(); expect(rerunRequests).toBe(0)
  40  |     await page.getByRole('button', { name: '核对并重跑单条查询' }).click()
  41  |     await page.getByRole('button', { name: '确认访问数据源并重跑' }).click()
  42  |     await expect(page.getByRole('button', { name: '查看重跑新快照' })).toBeVisible(); expect(rerunRequests).toBe(1)
  43  |     const result = await request.get(`/api/v1/projects/${id}`); const p = await result.json()
  44  |     const original = p.snapshots.find((s: { name: string }) => s.name === '原始完整样本'), newer = p.snapshots.find((s: { name: string }) => s.name === '重跑 · gaia')
  45  |     for (const cid of p.conversation_ids) ownedConversations.add(cid)
  46  |     expect(original.id).not.toBe(newer.id)
  47  |     await page.getByLabel('左侧快照').selectOption(original.id); await page.getByLabel('右侧快照').selectOption(newer.id)
  48  |     await page.getByLabel('按精确 source_id / bibcode 比较交付编号').check()
  49  |     await page.getByRole('button', { name: '比较已存快照' }).click()
  50  |     await expect(page.getByText('仅比较交付样本与查询元数据；不表示总体增减、显著性或成员变化。')).toBeVisible(); await screenshot('comparison')
  51  |     const importControl = page.getByLabel('导入项目 ZIP', { exact: true })
  52  |     await expect(importControl).toBeEnabled()
  53  |     let releaseRefresh!: () => void, observeRefresh!: () => void
  54  |     const refreshGate = new Promise<void>(resolve => { releaseRefresh = resolve })
  55  |     const refreshStarted = new Promise<void>(resolve => { observeRefresh = resolve })
  56  |     await page.route('**/api/v1/projects/memberships', async route => { observeRefresh(); await refreshGate; await route.continue() }, { times: 1 })
  57  |     let file
  58  |     try {
  59  |       const download = page.waitForEvent('download'); await page.getByRole('button', { name: '导出项目 ZIP' }).click()
  60  |       file = await download; expect(file.suggestedFilename()).toBe('astroagent-project.zip')
  61  |       await refreshStarted
  62  |       await expect(importControl).toBeDisabled()
  63  |     } finally { releaseRefresh() }
  64  |     const raw = readFileSync((await file.path())!)
  65  |     if (process.env.ASTROAGENT_RECORD_DIR) await file.saveAs(path.join(process.env.ASTROAGENT_RECORD_DIR, `${info.project.name}-project.zip`))
  66  |     // setInputFiles bypasses disabled-control actionability; wait for the export refresh.
  67  |     await expect(importControl).toBeEnabled()
  68  |     const importedResponse = page.waitForResponse(response => response.request().method() === 'POST' && response.url().endsWith('/api/v1/projects/import'))
  69  |     await importControl.setInputFiles({ name: 'restored.zip', mimeType: 'application/zip', buffer: raw })
  70  |     const upload = await importedResponse
  71  |     expect(upload.status(), await upload.text()).toBe(201)
  72  |     await expect(page).not.toHaveURL(new RegExp(`/projects/${id}`))
  73  |     await expect(page.getByText('导入来源未经认证。哈希只验证包内完整性；历史数据不会因导入而重新查询。')).toBeVisible()
  74  |     const importedId = new URL(page.url()).pathname.split('/').at(-1)!; ownedProjects.add(importedId)
  75  |     const imported = await (await request.get(`/api/v1/projects/${importedId}`)).json()
  76  |     for (const cid of imported.conversation_ids) ownedConversations.add(cid)
  77  |     expect(imported.snapshots).toHaveLength(2)
  78  |     await page.getByRole('button', { name: '查看快照 原始完整样本' }).click()
  79  |     await expect(page).toHaveURL(/snapshot=[0-9a-f-]+/)
  80  |     await expect(page.getByText('查看完整交付表格（100 行）')).toBeVisible()
  81  |     await page.reload(); await expect(page.getByText('查看完整交付表格（100 行）')).toBeVisible()
  82  |     await page.setViewportSize({ width: 390, height: 844 }); await page.getByRole('button', { name: '项目记录', exact: true }).click()
  83  |     await page.locator('.project-main').evaluate(el => { el.scrollTop = 0 }); await screenshot('mobile')
  84  |     expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  85  |     await page.getByRole('button', { name: '删除项目', exact: true }).click()
  86  |     await expect(page.getByRole('dialog')).toContainText('会话及其轮次保留')
  87  |     await page.getByRole('button', { name: '确认删除', exact: true }).click()
  88  |     await expect(page).toHaveURL(/\/projects$/)
  89  |     for (const cid of imported.conversation_ids) expect((await request.get(`/api/v1/conversations/${cid}`)).ok()).toBe(true)
  90  |     await expect(importControl).toBeEnabled()
  91  |     await importControl.setInputFiles({ name: 'broken.zip', mimeType: 'application/zip', buffer: Buffer.from('broken') })
> 92  |     await expect(page.getByRole('alert')).toContainText('项目包校验失败')
      |                                           ^ Error: expect(locator).toContainText(expected) failed
  93  |     expect(errors).toEqual([])
  94  |   } finally {
  95  |     for (const id of ownedProjects) {
  96  |       const response = await request.get(`/api/v1/projects/${id}`)
  97  |       if (response.ok()) { const p = await response.json(); await request.delete(`/api/v1/projects/${id}`, { data: { expected_revision: p.revision, confirm: true } }) }
  98  |     }
  99  |     for (const id of ownedConversations) await request.delete(`/api/v1/conversations/${id}`)
  100 |   }
  101 | })
  102 | 
```