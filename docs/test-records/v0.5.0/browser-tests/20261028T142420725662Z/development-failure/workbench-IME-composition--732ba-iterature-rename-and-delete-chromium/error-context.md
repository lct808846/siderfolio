# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: workbench.spec.ts >> IME composition, explicit examples, plain text literature, rename and delete
- Location: tests\browser\workbench.spec.ts:42:1

# Error details

```
Error: expect(locator).toBeVisible() failed

Locator: getByRole('heading', { name: '<img src=x onerror="window.syntheticXss=true"> 合成论文标题' })
Expected: visible
Timeout: 5000ms
Error: element(s) not found

Call log:
  - Expect "toBeVisible" getByRole('heading', { name: '<img src=x onerror="window.syntheticXss=true"> 合成论文标题' }) with timeout 5000ms
  - waiting for getByRole('heading', { name: '<img src=x onerror="window.syntheticXss=true"> 合成论文标题' })

```

```yaml
- banner:
  - link "AstroAgent 0.5":
    - /url: /
  - text: 本地科研工作台
  - link "接口文档 ↗":
    - /url: http://127.0.0.1:8000/docs
- complementary "会话列表":
  - text: WORKSPACE 2/20
  - button "新建会话"
  - paragraph: 本地会话
  - navigation:
    - button "新会话 1 轮 · 2026/10/28"
    - button "新会话 2 轮 · 2026/10/28"
  - text: SIMBAD / ADS / Gaia 测量 · 文献 · 可追溯结果
- main:
  - text: RESEARCH NOTEBOOK
  - heading "新会话" [level=1]
  - button "重命名会话": 改名
  - button "删除会话": 删除
  - article:
    - text: 第 1 轮
    - time: 22:21
    - text: 检索2020—2026年双星团相关论文，取3篇，按发表日期降序，给出来源。 AstroAgent 已完成
    - paragraph: 合成验收结果已返回。请在右侧核查完整测量、单位和查询条件；这些不是实际观测。
    - link "Gaia ↗":
      - /url: https://example.invalid/synthetic-gaia
    - button "核查本轮结果与导出"
  - text: 天文问题
  - textbox "天文问题":
    - /placeholder: 输入一个天文问题，或继续追问刚才的结果…
  - text: Enter 发送 · Shift + Enter 换行
  - button "发送" [disabled]
  - paragraph: 模型回答需对照原始数据核查；位置候选源不等于星团成员。
- complementary "结果核查":
  - text: RESULTS / 数据核查
  - heading "第 1 轮结果" [level=2]
  - paragraph:
    - text: 接收时间（UTC）
    - time: 2026-10-28T14:21:49.927023+00:00
  - tablist "数据源":
    - tab "Gaia DR3 1"
    - tab "ADS 0" [selected]
    - tab "SIMBAD 0"
  - paragraph: 本轮未执行 ADS 检索。
  - region "图表与下载":
    - heading "图表与数据包" [level=3]
    - paragraph: 基于第 1 轮完整响应。图表只描述交付样本。
    - checkbox "自行散点图"
    - text: 自行散点图
    - checkbox "视差直方图"
    - text: 视差直方图
    - checkbox "观测颜色—星等图"
    - text: 观测颜色—星等图
    - button "生成预览与数据包"
```

# Test source

```ts
  1  | import { test, expect } from '@playwright/test'
  2  | import { mkdirSync } from 'node:fs'
  3  | import path from 'node:path'
  4  | 
  5  | test('production build: conversation, follow-up, complete table, preview, download and restore', async ({ page, browserName }, testInfo) => {
  6  |   const errors: string[] = []; page.on('pageerror', e => errors.push(e.message))
  7  |   await page.goto('/')
  8  |   await expect(page.getByRole('heading', { name: '观测与文献，从这里开始' })).toBeVisible()
  9  |   if (process.env.ASTROAGENT_RECORD_DIR) { mkdirSync(process.env.ASTROAGENT_RECORD_DIR, { recursive: true }); await page.screenshot({ path: path.join(process.env.ASTROAGENT_RECORD_DIR, `${testInfo.project.name}-empty.png`) }) }
  10 |   await page.getByRole('button', { name: '新建会话' }).click()
  11 |   await expect(page).toHaveURL(/conversations\/[0-9a-f-]+/)
  12 |   const question = page.getByRole('textbox', { name: '天文问题' })
  13 |   await question.fill('合成验收：查询Gaia圆锥100个位置候选源。')
  14 |   await page.getByRole('button', { name: '发送', exact: true }).click()
  15 |   await expect(page.getByText('合成验收结果已返回。', { exact: false })).toBeVisible()
  16 |   await expect(page.getByRole('button', { name: '核查本轮结果与导出' })).toBeVisible()
  17 |   await page.getByRole('button', { name: '核查本轮结果与导出' }).click()
  18 |   await page.getByText('查看完整交付表格（100 行）').click()
  19 |   await expect(page.getByRole('cell', { name: '5853498713190525696', exact: true })).toBeVisible()
  20 |   await page.getByRole('button', { name: '下一页' }).click()
  21 |   await expect(page.getByRole('cell', { name: '5853498713190525716', exact: true })).toBeVisible()
  22 |   await page.getByLabel('自行散点图', { exact: true }).check()
  23 |   await page.getByLabel('视差直方图', { exact: true }).check()
  24 |   await page.getByLabel('观测颜色—星等图', { exact: true }).check()
  25 |   await page.getByRole('button', { name: '生成预览与数据包' }).click()
  26 |   await expect(page.getByRole('img', { name: '自行散点图', exact: true })).toBeVisible()
  27 |   const downloadPromise = page.waitForEvent('download')
  28 |   await page.getByRole('button', { name: '下载 ZIP' }).click()
  29 |   const file = await downloadPromise; expect(file.suggestedFilename()).toBe('astroagent-results.zip')
  30 |   if (process.env.ASTROAGENT_RECORD_DIR) await file.saveAs(path.join(process.env.ASTROAGENT_RECORD_DIR, `${testInfo.project.name}-download.zip`))
  31 |   await question.fill('只保留 RUWE≤1.4，其他条件不变，重新查询。')
  32 |   await page.getByRole('button', { name: '发送', exact: true }).click()
  33 |   await expect(page.getByText('使用了 1 轮历史上下文')).toBeVisible()
  34 |   const url = page.url(); await page.reload(); await expect(page.getByText('使用了 1 轮历史上下文')).toBeVisible()
  35 |   expect(page.url()).toBe(url)
  36 |   await page.getByRole('button', { name: '核查本轮结果与导出' }).first().click()
  37 |   await expect(page.getByLabel('结果核查').getByText('历史结果', { exact: true })).toBeVisible()
  38 |   if (process.env.ASTROAGENT_RECORD_DIR) await page.screenshot({ path: path.join(process.env.ASTROAGENT_RECORD_DIR, `${testInfo.project.name}-full.png`) })
  39 |   expect(errors).toEqual([]); expect(browserName).toBe('chromium')
  40 | })
  41 | 
  42 | test('IME composition, explicit examples, plain text literature, rename and delete', async ({ page }) => {
  43 |   await page.goto('/'); await page.getByRole('button', { name: '新建会话' }).click()
  44 |   await page.getByRole('button', { name: 'ADS 文献检索' }).click()
  45 |   const input = page.getByRole('textbox', { name: '天文问题' })
  46 |   await input.dispatchEvent('compositionstart'); await input.dispatchEvent('keydown', { key: 'Enter', isComposing: true })
  47 |   await expect(page.getByText('第 1 轮', { exact: true })).toHaveCount(0)
  48 |   await input.dispatchEvent('compositionend')
  49 |   await page.getByRole('button', { name: '发送', exact: true }).click()
  50 |   await expect(page.getByText('合成验收结果已返回。', { exact: false })).toBeVisible()
  51 |   await page.getByRole('tab', { name: /ADS/ }).click()
> 52 |   await expect(page.getByRole('heading', { name: '<img src=x onerror="window.syntheticXss=true"> 合成论文标题' })).toBeVisible()
     |                                                                                                              ^ Error: expect(locator).toBeVisible() failed
  53 |   expect(await page.evaluate(() => 'syntheticXss' in window)).toBe(false)
  54 |   await page.getByRole('button', { name: '重命名会话' }).click(); await page.getByRole('textbox', { name: '会话名称' }).fill('我的文献核查')
  55 |   await page.getByRole('button', { name: '保存', exact: true }).click()
  56 |   await expect(page.getByRole('heading', { name: '我的文献核查' })).toBeVisible()
  57 |   await page.getByRole('button', { name: '删除会话' }).click(); await expect(page.getByRole('dialog')).toBeVisible()
  58 |   await page.getByRole('button', { name: '确认删除' }).click(); await expect(page).toHaveURL('http://127.0.0.1:5173/')
  59 | })
  60 | 
  61 | test('narrow viewport has usable panel navigation and no page overflow', async ({ page }, testInfo) => {
  62 |   await page.setViewportSize({ width: 390, height: 844 }); await page.goto('/')
  63 |   await page.getByRole('button', { name: '会话', exact: true }).click(); await page.getByRole('button', { name: '新建会话' }).click()
  64 |   const input = page.getByRole('textbox', { name: '天文问题' }); await input.fill('合成Gaia圆锥查询')
  65 |   await page.getByRole('button', { name: '发送', exact: true }).click()
  66 |   await expect(page.getByText('合成验收结果已返回。', { exact: false })).toBeVisible()
  67 |   await page.getByRole('button', { name: '核查本轮结果与导出' }).click(); await expect(page.getByRole('heading', { name: '第 1 轮结果' })).toBeVisible()
  68 |   const width = await page.evaluate(() => ({ body: document.body.scrollWidth, viewport: innerWidth })); expect(width.body).toBeLessThanOrEqual(width.viewport)
  69 |   if (process.env.ASTROAGENT_RECORD_DIR) await page.screenshot({ path: path.join(process.env.ASTROAGENT_RECORD_DIR, `${testInfo.project.name}-mobile.png`) })
  70 | })
  71 | 
  72 | test('backend connection error is explicit', async ({ page }) => {
  73 |   await page.route('**/api/v1/conversations', route => route.abort())
  74 |   await page.goto('/'); await expect(page.getByRole('alert')).toContainText('连接已断开')
  75 | })
  76 | 
```