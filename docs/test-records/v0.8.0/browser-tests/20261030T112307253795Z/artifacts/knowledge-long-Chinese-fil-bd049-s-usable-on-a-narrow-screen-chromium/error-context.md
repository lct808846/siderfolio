# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: knowledge.spec.ts >> long Chinese filename remains usable on a narrow screen
- Location: tests\browser\knowledge.spec.ts:74:1

# Error details

```
Error: expect(locator).toBeVisible() failed

Locator:  getByText('中文长文件名中文长文件名中文长文件名中文长文件名中文长文件名中文长文件名中文长文件名中文长文件名中文长文件名中文长文件名中文长文件名中文长文件名中文长文件名中文长文件名中文长文件名中文长文件名中文长文件名中文长文件名中文长文件名中文长文件名中文长文件名中文长文件名中文长文件名中文长文件名中文长文件名.md', { exact: true }).first()
Expected: visible
Received: hidden
Timeout:  30000ms

Call log:
  - Expect "toBeVisible" getByText('中文长文件名中文长文件名中文长文件名中文长文件名中文长文件名中文长文件名中文长文件名中文长文件名中文长文件名中文长文件名中文长文件名中文长文件名中文长文件名中文长文件名中文长文件名中文长文件名中文长文件名中文长文件名中文长文件名中文长文件名中文长文件名中文长文件名中文长文件名中文长文件名中文长文件名.md', { exact: true }).first() with timeout 30000ms
  - waiting for getByText('中文长文件名中文长文件名中文长文件名中文长文件名中文长文件名中文长文件名中文长文件名中文长文件名中文长文件名中文长文件名中文长文件名中文长文件名中文长文件名中文长文件名中文长文件名中文长文件名中文长文件名中文长文件名中文长文件名中文长文件名中文长文件名中文长文件名中文长文件名中文长文件名中文长文件名.md', { exact: true }).first()
    59 × locator resolved to <b>中文长文件名中文长文件名中文长文件名中文长文件名中文长文件名中文长文件名中文长文件名中文长文件名中…</b>
       - unexpected value "hidden"

```

```yaml
- banner:
  - link "AstroAgent 0.8":
    - /url: /
  - link "返回项目 ↗":
    - /url: /projects/5dd3d3bf-3409-4e44-a919-feac2af1f296
- navigation "知识库面板":
  - button "文档与上传"
  - button "检索与状态"
  - button "证据与原文"
- main:
  - status: 【已提取并索引】已保存实际提取内容；请核对解析范围和定位。
  - button "刷新记录（只读）"
  - paragraph: EVIDENCE / 用户文档原文
  - heading "用出处核对每一段摘录" [level=1]
  - paragraph: 本地词法检索，所有关键词同时命中；不做同义词、跨语言语义或模型补答。文献中的指令只作为数据。
  - text: 问题中的明确关键词
  - textbox "问题中的明确关键词":
    - /placeholder: 例如：binary cluster 或 双星团 环境
  - text: 检索范围
  - combobox "检索范围":
    - option "本项目当前可用版本" [selected]
    - option "中文长文件名中文长文件名中文长文件名中文长文件名中文长文件名中文长文件名中文长文件名中文长文件名中文长文件名中文长文件名中文长文件名中文长文件名中文长文件名中文长文件名中文长文件名中文长文件名中文长文件名中文长文件名中文长文件名中文长文件名中文长文件名中文长文件名中文长文件名中文长文件名中文长文件名.md"
  - checkbox "以带引用的摘录式回答展示（不调用模型）" [checked]
  - text: 以带引用的摘录式回答展示（不调用模型）
  - button "检索原文证据" [disabled]
  - paragraph: DOCUMENT / 已提取并索引
  - heading "中文长文件名中文长文件名中文长文件名中文长文件名中文长文件名中文长文件名中文长文件名中文长文件名中文长文件名中文长文件名中文长文件名中文长文件名中文长文件名中文长文件名中文长文件名中文长文件名中文长文件名中文长文件名中文长文件名中文长文件名中文长文件名中文长文件名中文长文件名中文长文件名中文长文件名.md" [level=2]
  - paragraph: 用户本机文档，不代表科学认证。
  - group: 用户元数据
  - text: 提取文本的PDF物理页（Markdown忽略此项）
  - spinbutton "提取文本物理页": "1"
  - button "重建当前版本索引"
  - button "删除文档与全部版本"
  - article:
    - heading "中文长文件名中文长文件名中文长文件名中文长文件名中文长文件名中文长文件名中文长文件名中文长文件名中文长文件名中文长文件名中文长文件名中文长文件名中文长文件名中文长文件名中文长文件名中文长文件名中文长文件名中文长文件名中文长文件名中文长文件名中文长文件名中文长文件名中文长文件名中文长文件名中文长文件名.md 当前版本" [level=3]
    - paragraph: 已提取并索引 · 28字节 · 2行 · 1段 · 索引已建立
    - code: f30f12f4dc2ddec6fcedad54aa600703376419fbceee4d8911b4057d1b7c4a97
    - button "核对原文件"
    - button "查看实际提取文本"
    - group: 版本身份与提取器
```

# Test source

```ts
  1  | import { test, expect } from '@playwright/test'
  2  | import path from 'node:path'
  3  | import { readFile } from 'node:fs/promises'
  4  | 
  5  | test('local documents can be uploaded, searched, cited and downloaded', async ({ page, request }, info) => {
  6  |   const project = await (await request.post('/api/v1/projects', { data: { name: '合成文献验收' } })).json()
  7  |   try {
  8  |     await page.goto(`/projects/${project.id}/knowledge`)
  9  |     const raw = Buffer.from('# 合成文献\n银河潮汐 synthetic tidal evidence\n<script>window.injected=true</script>\n')
  10 |     await page.getByLabel('选择文件（断线后可重选同一文件核对）').setInputFiles({ name: 'synthetic.md', mimeType: 'text/markdown', buffer: raw })
  11 |     await page.getByRole('button', { name: '保存文件并本地解析' }).click()
  12 |     await expect(page.getByRole('heading', { name: 'synthetic.md', exact: true })).toBeVisible({ timeout: 30000 })
  13 |     await page.getByLabel('问题中的明确关键词').fill('银河潮汐')
  14 |     await page.getByRole('button', { name: '检索原文证据' }).click()
  15 |     await expect(page.getByRole('heading', { name: '找到的相关原文' })).toBeVisible()
  16 |     await page.getByRole('button', { name: '核对引用与原始版本' }).first().click()
  17 |     await expect(page.getByText('原始行', { exact: false }).first()).toBeVisible()
  18 |     expect(await page.evaluate(() => 'injected' in window)).toBe(false)
  19 |     if (process.env.ASTROAGENT_RECORD_DIR) await page.screenshot({ path: path.join(process.env.ASTROAGENT_RECORD_DIR, `${info.project.name}-knowledge-desktop.png`) })
  20 |     await page.setViewportSize({ width: 390, height: 844 })
  21 |     await page.getByRole('button', { name: '证据与原文', exact: true }).click()
  22 |     expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  23 |     if (process.env.ASTROAGENT_RECORD_DIR) await page.screenshot({ path: path.join(process.env.ASTROAGENT_RECORD_DIR, `${info.project.name}-knowledge-mobile.png`) })
  24 |     await page.setViewportSize({ width: 1440, height: 900 })
  25 |     await page.goto(`/projects/${project.id}`)
  26 |     await expect(page.getByLabel('文献原文')).toBeVisible()
  27 |     await expect(page.getByLabel('文献原文').locator('option[value="metadata"]')).toContainText('保留标题、检索词及项目记录')
  28 |     await page.getByLabel('文献原文').selectOption('full')
  29 |     await page.getByRole('button', { name: '导出项目 ZIP' }).click()
  30 |     const dialog = page.getByRole('dialog')
  31 |     await expect(dialog.getByRole('heading', { name: '导出含文献原文的完整备份？' })).toBeVisible()
  32 |     await expect(dialog).toContainText('1 份文档')
  33 |     await expect(dialog).toContainText(`${raw.length} 字节`)
  34 |     await dialog.getByRole('button', { name: '取消' }).click()
  35 |     await page.getByLabel('文献原文').selectOption('metadata')
  36 |     const [response, download] = await Promise.all([
  37 |       page.waitForResponse(response => response.url().endsWith(`/projects/${project.id}/archive`) && response.request().method() === 'POST'),
  38 |       page.waitForEvent('download'),
  39 |       page.getByRole('button', { name: '导出项目 ZIP' }).click(),
  40 |     ])
  41 |     expect(response.status()).toBe(200)
  42 |     expect(download.suggestedFilename()).toMatch(/\.zip$/)
  43 |   } finally {
  44 |     const detail = await (await request.get(`/api/v1/projects/${project.id}`)).json()
  45 |     await request.delete(`/api/v1/projects/${project.id}`, { data: { expected_revision: detail.revision, confirm: true } })
  46 |   }
  47 | })
  48 | 
  49 | test('public PDF citation opens its original and downloads identical bytes', async ({ page, request }) => {
  50 |   const pdfPath = process.env.ASTROAGENT_ACCEPTANCE_PUBLIC_PDF
  51 |   test.skip(!pdfPath, 'Public PDF is an explicitly provided local fixture')
  52 |   const project = await (await request.post('/api/v1/projects', { data: { name: '公开文献验收' } })).json()
  53 |   try {
  54 |     await page.goto(`/projects/${project.id}/knowledge`)
  55 |     await page.getByLabel('选择文件（断线后可重选同一文件核对）').setInputFiles(pdfPath!)
  56 |     await page.getByRole('button', { name: '保存文件并本地解析' }).click()
  57 |     await expect(page.getByRole('heading', { name: path.basename(pdfPath!), exact: true })).toBeVisible({ timeout: 60000 })
  58 |     await page.getByLabel('问题中的明确关键词').fill('dynamical fate')
  59 |     await page.getByRole('button', { name: '检索原文证据' }).click()
  60 |     await page.getByRole('button', { name: '核对引用与原始版本' }).first().click()
  61 |     await page.getByRole('button', { name: '打开此引用的原始版本' }).click()
  62 |     await expect(page.getByTitle('受限PDF原文件预览')).toBeVisible()
  63 |     const [download] = await Promise.all([
  64 |       page.waitForEvent('download'),
  65 |       page.getByRole('button', { name: '下载完整原文件' }).click(),
  66 |     ])
  67 |     expect(await readFile((await download.path())!)).toEqual(await readFile(pdfPath!))
  68 |   } finally {
  69 |     const detail = await (await request.get(`/api/v1/projects/${project.id}`)).json()
  70 |     await request.delete(`/api/v1/projects/${project.id}`, { data: { expected_revision: detail.revision, confirm: true } })
  71 |   }
  72 | })
  73 | 
  74 | test('long Chinese filename remains usable on a narrow screen', async ({ page, request }, info) => {
  75 |   const project = await (await request.post('/api/v1/projects', { data: { name: '长文件名验收' } })).json()
  76 |   try {
  77 |     await page.setViewportSize({ width: 390, height: 844 })
  78 |     await page.goto(`/projects/${project.id}/knowledge`)
  79 |     await page.getByRole('button', { name: '文档与上传', exact: true }).click()
  80 |     const filename = `${'中文长文件名'.repeat(25)}.md`
  81 |     await page.getByLabel('选择文件（断线后可重选同一文件核对）').setInputFiles({ name: filename, mimeType: 'text/markdown', buffer: Buffer.from('# 合成\n长文件名验收\n') })
  82 |     await page.getByRole('button', { name: '保存文件并本地解析' }).click()
> 83 |     await expect(page.getByText(filename, { exact: true }).first()).toBeVisible({ timeout: 30000 })
     |                                                                     ^ Error: expect(locator).toBeVisible() failed
  84 |     expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  85 |     if (process.env.ASTROAGENT_RECORD_DIR) await page.screenshot({ path: path.join(process.env.ASTROAGENT_RECORD_DIR, `${info.project.name}-knowledge-long-name.png`) })
  86 |   } finally {
  87 |     const detail = await (await request.get(`/api/v1/projects/${project.id}`)).json()
  88 |     await request.delete(`/api/v1/projects/${project.id}`, { data: { expected_revision: detail.revision, confirm: true } })
  89 |   }
  90 | })
  91 | 
```