# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: knowledge.spec.ts >> local documents can be uploaded, searched, cited and downloaded
- Location: tests\browser\knowledge.spec.ts:4:1

# Error details

```
Error: expect(locator).toBeVisible() failed

Locator: getByRole('heading', { name: 'synthetic.md' })
Expected: visible
Error: strict mode violation: getByRole('heading', { name: 'synthetic.md' }) resolved to 2 elements:
    1) <h2>synthetic.md</h2> aka getByRole('heading', { name: 'synthetic.md', exact: true })
    2) <h3>…</h3> aka getByRole('heading', { name: 'synthetic.md 当前版本' })

Call log:
  - Expect "toBeVisible" getByRole('heading', { name: 'synthetic.md' }) with timeout 30000ms
  - waiting for getByRole('heading', { name: 'synthetic.md' })

```

# Page snapshot

```yaml
- generic [ref=e3]:
  - banner [ref=e4]:
    - link "AstroAgent 0.8" [ref=e5] [cursor=pointer]:
      - /url: /
      - generic [aria-hidden] [ref=e6]: ✳
      - generic [ref=e7]: AstroAgent
      - generic [ref=e8]: "0.8"
    - generic [ref=e9]: 本地文献与原文证据
    - link "返回项目 ↗" [ref=e10] [cursor=pointer]:
      - /url: /projects/c8a8af57-e320-4c11-b20c-572e9816fc13
  - complementary [ref=e11]:
    - link [ref=e12] [cursor=pointer]:
      - /url: /projects/c8a8af57-e320-4c11-b20c-572e9816fc13/knowledge
      - paragraph [ref=e13]: LOCAL LIBRARY · 1/100
      - heading "合成文献验收" [level=2] [ref=e14]
    - link "synthetic.md 已提取并索引 · 用户本机文档" [ref=e15] [cursor=pointer]:
      - /url: /projects/c8a8af57-e320-4c11-b20c-572e9816fc13/knowledge/faf53b22-f41e-4591-9ac8-8e9918ef18e9
      - text: synthetic.md
      - generic [ref=e16]: 已提取并索引 · 用户本机文档
    - generic [ref=e17]:
      - heading "上传到本机项目" [level=2] [ref=e18]
      - paragraph [ref=e19]: PDF / UTF-8 Markdown，单文件≤20 MiB。副本保存在本机数据库，不发送给模型服务。
      - group [ref=e20]:
        - generic [ref=e21]: 上传方式
        - combobox "上传方式" [ref=e22]:
          - option "新文档" [selected]
          - option "为选中文档新增版本"
          - option "恢复选中文档同哈希原文件"
        - generic [ref=e23]: 标题（可选，不从文件名推断）
        - textbox "标题（可选，不从文件名推断）" [ref=e24]
        - generic [ref=e25]: 作者（可选，分号分隔）
        - textbox "作者（可选，分号分隔）" [ref=e26]
        - generic [ref=e27]: 年份（可选）
        - textbox "年份（可选）" [ref=e28]
        - generic [ref=e29]: DOI（可选）
        - textbox "DOI（可选）" [ref=e30]
        - generic [ref=e31]:
          - checkbox "相同文件也创建独立文档" [ref=e32]
          - text: 相同文件也创建独立文档
        - button "保存文件并本地解析" [ref=e33] [cursor=pointer]
      - generic [ref=e34]: 选择文件（断线后可重选同一文件核对）
      - button "选择文件（断线后可重选同一文件核对）" [ref=e35]
  - main [ref=e36]:
    - status [ref=e37]: 【已提取并索引】已保存实际提取内容；请核对解析范围和定位。
    - button "刷新记录（只读）" [ref=e38] [cursor=pointer]
    - generic [ref=e39]:
      - paragraph [ref=e40]: EVIDENCE / 用户文档原文
      - heading "用出处核对每一段摘录" [level=1] [ref=e41]
      - paragraph [ref=e42]: 本地词法检索，所有关键词同时命中；不做同义词、跨语言语义或模型补答。文献中的指令只作为数据。
      - generic [ref=e43]:
        - generic [ref=e44]: 问题中的明确关键词
        - textbox "问题中的明确关键词" [ref=e45]:
          - /placeholder: 例如：binary cluster 或 双星团 环境
        - generic [ref=e46]: 检索范围
        - combobox "检索范围" [ref=e47]:
          - option "本项目当前可用版本" [selected]
          - option "synthetic.md"
        - generic [ref=e48]:
          - checkbox "以带引用的摘录式回答展示（不调用模型）" [checked] [ref=e49]
          - text: 以带引用的摘录式回答展示（不调用模型）
        - button "检索原文证据" [disabled] [ref=e50]
    - generic [ref=e51]:
      - paragraph [ref=e52]: DOCUMENT / 已提取并索引
      - heading "synthetic.md" [level=2] [ref=e53]
      - paragraph [ref=e54]: 用户本机文档，不代表科学认证。
      - group [ref=e55]:
        - generic "用户元数据" [ref=e56] [cursor=pointer]
      - generic [ref=e57]:
        - text: 提取文本的PDF物理页（Markdown忽略此项）
        - spinbutton "提取文本物理页" [ref=e58]: "1"
      - generic [ref=e59]:
        - button "重建当前版本索引" [ref=e60] [cursor=pointer]
        - button "删除文档与全部版本" [ref=e61] [cursor=pointer]
      - article [ref=e62]:
        - heading "synthetic.md 当前版本" [level=3] [ref=e63]:
          - text: synthetic.md
          - generic [ref=e64]: 当前版本
        - paragraph [ref=e65]: 已提取并索引 · 91字节 · 3行 · 1段 · 索引已建立
        - code [ref=e66]: e91a019316b00397527ece2c658d162be6dbcbf84f77ce29f0b4370fd87a96ab
        - generic [ref=e67]:
          - button "核对原文件" [ref=e68] [cursor=pointer]
          - button "查看实际提取文本" [ref=e69] [cursor=pointer]
        - group [ref=e70]:
          - generic "版本身份与提取器" [ref=e71] [cursor=pointer]
  - complementary "引用与原文件核对" [ref=e72]:
    - paragraph [ref=e73]: SOURCE / 来源核对
    - heading "引用与原始位置" [level=2] [ref=e74]
    - paragraph [ref=e75]: 与ADS摘要、数据库测量和模型回答分开标识。
    - generic [ref=e76]:
      - heading "最近保存的引用 · 0/最多显示50" [level=3] [ref=e77]
      - paragraph [ref=e78]: 检索后在此保存可回查的引用编号。
```

# Test source

```ts
  1  | import { test, expect } from '@playwright/test'
  2  | import path from 'node:path'
  3  | 
  4  | test('local documents can be uploaded, searched, cited and downloaded', async ({ page, request }, info) => {
  5  |   const project = await (await request.post('/api/v1/projects', { data: { name: '合成文献验收' } })).json()
  6  |   try {
  7  |     await page.goto(`/projects/${project.id}/knowledge`)
  8  |     const raw = Buffer.from('# 合成文献\n银河潮汐 synthetic tidal evidence\n<script>window.injected=true</script>\n')
  9  |     await page.getByLabel('选择文件（断线后可重选同一文件核对）').setInputFiles({ name: 'synthetic.md', mimeType: 'text/markdown', buffer: raw })
  10 |     await page.getByRole('button', { name: '保存文件并本地解析' }).click()
> 11 |     await expect(page.getByRole('heading', { name: 'synthetic.md' })).toBeVisible({ timeout: 30000 })
     |                                                                       ^ Error: expect(locator).toBeVisible() failed
  12 |     await page.getByLabel('问题中的明确关键词').fill('银河潮汐')
  13 |     await page.getByRole('button', { name: '检索原文证据' }).click()
  14 |     await expect(page.getByRole('heading', { name: '找到的相关原文' })).toBeVisible()
  15 |     await page.getByRole('button', { name: '核对引用与原始版本' }).first().click()
  16 |     await expect(page.getByText('原始行', { exact: false }).first()).toBeVisible()
  17 |     expect(await page.evaluate(() => 'injected' in window)).toBe(false)
  18 |     if (process.env.ASTROAGENT_RECORD_DIR) await page.screenshot({ path: path.join(process.env.ASTROAGENT_RECORD_DIR, `${info.project.name}-knowledge-desktop.png`) })
  19 |     await page.setViewportSize({ width: 390, height: 844 })
  20 |     await page.getByRole('button', { name: '证据与原文', exact: true }).click()
  21 |     expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  22 |     if (process.env.ASTROAGENT_RECORD_DIR) await page.screenshot({ path: path.join(process.env.ASTROAGENT_RECORD_DIR, `${info.project.name}-knowledge-mobile.png`) })
  23 |   } finally {
  24 |     const detail = await (await request.get(`/api/v1/projects/${project.id}`)).json()
  25 |     await request.delete(`/api/v1/projects/${project.id}`, { data: { expected_revision: detail.revision, confirm: true } })
  26 |   }
  27 | })
  28 | 
```