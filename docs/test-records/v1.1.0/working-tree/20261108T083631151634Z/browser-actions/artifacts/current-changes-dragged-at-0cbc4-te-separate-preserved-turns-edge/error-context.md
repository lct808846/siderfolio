# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: current-changes.spec.ts >> dragged attachment and edited question create separate preserved turns
- Location: tests\browser\current-changes.spec.ts:28:1

# Error details

```
Error: expect(locator).toBeVisible() failed

Locator: getByText('第一条合成查询', { exact: true })
Expected: visible
Error: strict mode violation: getByText('第一条合成查询', { exact: true }) resolved to 4 elements:
    1) <b>第一条合成查询</b> aka getByRole('button', { name: '第一条合成查询 2 轮 · 2026/11/' }).first()
    2) <b>第一条合成查询</b> aka getByRole('button', { name: '第一条合成查询 2 轮 · 2026/11/' }).nth(1)
    3) <h1 title="第一条合成查询">第一条合成查询</h1> aka getByRole('heading', { name: '第一条合成查询' })
    4) <div class="user-message">第一条合成查询</div> aka locator('div').filter({ hasText: /^第一条合成查询$/ })

Call log:
  - Expect "toBeVisible" getByText('第一条合成查询', { exact: true }) with timeout 5000ms
  - waiting for getByText('第一条合成查询', { exact: true })

```

# Page snapshot

```yaml
- generic [ref=e3]:
  - banner [ref=e4]:
    - generic [ref=e5]:
      - button "AstroAgent：新建会话" [ref=e6] [cursor=pointer]:
        - generic [aria-hidden] [ref=e7]: ✳
        - generic [ref=e8]: AstroAgent
        - generic [ref=e9]: 1.1.0
      - navigation "全局导航" [ref=e10]:
        - link "查询工作台" [ref=e11] [cursor=pointer]:
          - /url: /
        - link "项目归档" [ref=e12] [cursor=pointer]:
          - /url: /projects
        - link "本机设置" [ref=e13] [cursor=pointer]:
          - /url: /settings
        - link "接口文档 ↗" [ref=e14] [cursor=pointer]:
          - /url: http://127.0.0.1:8000/docs
  - complementary "会话列表" [ref=e15]:
    - generic [ref=e16]:
      - generic [ref=e17]: 会话
      - generic [ref=e18]: 2/20
    - button "新建会话" [ref=e19] [cursor=pointer]:
      - generic [aria-hidden] [ref=e20]: ＋
      - text: 新建会话
    - generic [ref=e21]:
      - paragraph [ref=e22]: 本地会话
      - button "多选" [ref=e23] [cursor=pointer]
    - navigation "本地会话" [ref=e24]:
      - generic [ref=e25]:
        - button "第一条合成查询 2 轮 · 2026/11/8" [ref=e26] [cursor=pointer]:
          - generic [aria-hidden] [ref=e27]: ◌
          - generic [ref=e28]:
            - generic [ref=e29]: 第一条合成查询
            - generic [ref=e30]: 2 轮 · 2026/11/8
        - button "会话操作：第一条合成查询" [ref=e31] [cursor=pointer]: ⋯
      - generic [ref=e32]:
        - button "第一条合成查询 2 轮 · 2026/11/8" [ref=e33] [cursor=pointer]:
          - generic [aria-hidden] [ref=e34]: ◌
          - generic [ref=e35]:
            - generic [ref=e36]: 第一条合成查询
            - generic [ref=e37]: 2 轮 · 2026/11/8
        - button "会话操作：第一条合成查询" [ref=e38] [cursor=pointer]: ⋯
    - generic [ref=e39]:
      - text: SIMBAD / ADS / Gaia
      - generic [ref=e40]: 测量 · 文献 · 可追溯结果
  - main [ref=e41]:
    - generic [ref=e42]:
      - button "收起会话列表" [expanded] [ref=e43] [cursor=pointer]
      - heading "第一条合成查询" [level=1] [ref=e47]
    - generic [ref=e48]:
      - article [ref=e49]:
        - generic [ref=e50]:
          - generic [ref=e51]: 第 1 轮
          - generic [ref=e52]: synthetic-model
          - time [ref=e53]: 16:42
          - generic [ref=e54]: 历史记录
        - generic [ref=e55]:
          - button "查看附件文本：dragged.txt" [ref=e57] [cursor=pointer]:
            - generic [ref=e60]:
              - generic [ref=e61]: dragged.txt
              - generic [ref=e62]: 6 字符 · 查看文本
          - generic [ref=e63]: 第一条合成查询
          - generic [ref=e64]:
            - button "复制第1轮问题" [ref=e65] [cursor=pointer]
            - button "编辑第1轮问题" [ref=e69] [cursor=pointer]
        - generic [ref=e72]:
          - generic [ref=e73]:
            - generic [aria-hidden] [ref=e74]: ✳
            - generic [ref=e75]: AstroAgent
            - generic [ref=e76]: 已完成
          - paragraph [ref=e78]: 合成验收结果已返回。请在右侧核查完整测量、单位和查询条件；这些不是实际观测。
          - link "Gaia ↗" [ref=e80] [cursor=pointer]:
            - /url: https://example.invalid/synthetic-gaia
          - button "核查本轮结果与导出" [ref=e81] [cursor=pointer]:
            - text: 核查本轮结果与导出
            - generic [aria-hidden] [ref=e82]: →
      - article [ref=e83]:
        - generic [ref=e84]:
          - generic [ref=e85]: 第 2 轮
          - generic [ref=e86]: synthetic-model
          - time [ref=e87]: 16:42
        - generic [ref=e88]:
          - generic [ref=e89]: 编辑后的第二条查询
          - generic [ref=e90]:
            - button "复制第2轮问题" [ref=e91] [cursor=pointer]
            - button "编辑第2轮问题" [ref=e95] [cursor=pointer]
        - generic [ref=e98]:
          - generic [ref=e99]:
            - generic [aria-hidden] [ref=e100]: ✳
            - generic [ref=e101]: AstroAgent
            - generic [ref=e102]: 已完成
          - paragraph [ref=e104]: 合成验收结果已返回。请在右侧核查完整测量、单位和查询条件；这些不是实际观测。
          - group [ref=e105]:
            - generic "使用了 1 轮历史上下文" [ref=e106] [cursor=pointer]
          - link "Gaia ↗" [ref=e108] [cursor=pointer]:
            - /url: https://example.invalid/synthetic-gaia
          - button "核查本轮结果与导出" [ref=e109] [cursor=pointer]:
            - text: 核查本轮结果与导出
            - generic [aria-hidden] [ref=e110]: →
    - generic [ref=e111]:
      - generic [ref=e112]: 天文问题
      - textbox "天文问题" [ref=e113]:
        - /placeholder: 输入一个天文问题，或继续追问刚才的结果…
      - generic [ref=e114]:
        - button "回答模型：synthetic-model" [ref=e117] [cursor=pointer]:
          - generic [ref=e118]: synthetic-model
        - button "选择附件" [ref=e121]
        - button "添加附件" [ref=e122] [cursor=pointer]
        - button "发送问题" [disabled] [ref=e125]
      - paragraph [ref=e128]: 模型回答需对照原始数据核查；位置候选源不等于星团成员。
  - complementary "结果核查" [ref=e129]:
    - generic [ref=e130]:
      - generic [ref=e131]:
        - text: RESULTS / 数据核查
        - heading "第 2 轮结果" [level=2] [ref=e132]
      - button "收起结果面板" [ref=e133] [cursor=pointer]: ×
    - paragraph [ref=e134]:
      - text: 接收时间（UTC）
      - time [ref=e135]: 2026-11-08T08:42:18.781978+00:00
    - tablist "数据源" [ref=e136]:
      - tab "Gaia DR3 1" [selected] [ref=e137] [cursor=pointer]
      - tab "ADS 0" [ref=e138] [cursor=pointer]
      - tab "SIMBAD 0" [ref=e139] [cursor=pointer]
    - generic [ref=e140]:
      - generic [ref=e141]: 本轮 Gaia 查询
      - combobox "本轮 Gaia 查询" [ref=e142]:
        - option "第 1 次 · success · 100 行" [selected]
      - generic [ref=e143]:
        - generic [ref=e144]:
          - generic [ref=e145]: "100"
          - text: 交付行
        - generic [ref=e146]:
          - generic [ref=e147]: 未知
          - text: 总命中数
        - generic [ref=e148]:
          - generic [ref=e149]: 未截断
          - text: 交付范围
      - group [ref=e150]:
        - generic "条件、单位与程序统计" [ref=e151] [cursor=pointer]
      - group [ref=e152]:
        - generic "实际 ADQL" [ref=e153] [cursor=pointer]
      - group [ref=e154]:
        - generic "查看完整交付表格（100 行）" [ref=e155] [cursor=pointer]
      - paragraph [ref=e156]: 合成验收数据，不是实际观测。
    - region "图表与下载" [ref=e157]:
      - heading "图表与数据包" [level=3] [ref=e158]
      - paragraph [ref=e159]: 基于第 2 轮完整响应。图表只描述交付样本。
      - generic [ref=e160]:
        - generic [ref=e161]:
          - checkbox "自行散点图" [ref=e162]
          - text: 自行散点图
        - generic [ref=e163]:
          - checkbox "视差直方图" [ref=e164]
          - text: 视差直方图
        - generic [ref=e165]:
          - checkbox "观测颜色—星等图" [ref=e166]
          - text: 观测颜色—星等图
      - button "生成预览与数据包" [ref=e168] [cursor=pointer]
```

# Test source

```ts
  1  | import { test, expect } from '@playwright/test'
  2  | 
  3  | test('model selection and attachment preview do not send a message', async ({ page }) => {
  4  |   let sends = 0
  5  |   page.on('request', request => {
  6  |     if (request.method() === 'POST' && /\/turns$/.test(new URL(request.url()).pathname)) sends++
  7  |   })
  8  |   await page.route('**/api/v1/models', route => route.fulfill({
  9  |     status: 200, contentType: 'application/json', body: JSON.stringify({
  10 |       configured: true, default_model: 'deepseek-test',
  11 |       models: [{ id: 'deepseek-test', label: 'DeepSeek' }, { id: 'qwen-test', label: 'Qwen' }],
  12 |     }),
  13 |   }))
  14 |   await page.goto('/')
  15 |   await page.getByLabel('选择附件').setInputFiles({ name: 'synthetic.txt', mimeType: 'text/plain', buffer: Buffer.from('合成附件内容') })
  16 |   await page.getByRole('button', { name: '查看附件文本：synthetic.txt' }).click()
  17 |   await expect(page.getByRole('dialog').getByText('合成附件内容')).toBeVisible()
  18 |   await page.getByRole('button', { name: '关闭附件预览' }).click()
  19 |   await page.getByRole('button', { name: '回答模型：deepseek-test' }).click()
  20 |   await page.getByRole('menuitem', { name: /模型/ }).click()
  21 |   await page.getByRole('option', { name: 'qwen-test' }).click()
  22 |   await expect(page.getByRole('button', { name: '回答模型：qwen-test' })).toBeVisible()
  23 |   await page.getByRole('button', { name: '移除附件：synthetic.txt' }).click()
  24 |   await expect(page.getByRole('button', { name: '查看附件文本：synthetic.txt' })).toHaveCount(0)
  25 |   expect(sends).toBe(0)
  26 | })
  27 | 
  28 | test('dragged attachment and edited question create separate preserved turns', async ({ page }) => {
  29 |   let sends = 0
  30 |   page.on('request', request => {
  31 |     if (request.method() === 'POST' && /\/turns$/.test(new URL(request.url()).pathname)) sends++
  32 |   })
  33 |   await page.goto('/')
  34 |   const transfer = await page.evaluateHandle(() => {
  35 |     const data = new DataTransfer()
  36 |     data.items.add(new File(['合成拖放附件'], 'dragged.txt', { type: 'text/plain' }))
  37 |     return data
  38 |   })
  39 |   await page.locator('form.composer').dispatchEvent('drop', { dataTransfer: transfer })
  40 |   await expect(page.getByRole('button', { name: '查看附件文本：dragged.txt' })).toBeVisible()
  41 |   const input = page.getByRole('textbox', { name: '天文问题' })
  42 |   await input.fill('第一条合成查询')
  43 |   expect(sends).toBe(0)
  44 |   await page.getByRole('button', { name: '发送问题' }).click()
  45 |   await expect(page.getByRole('button', { name: '编辑第1轮问题' })).toBeVisible()
  46 |   expect(sends).toBe(1)
  47 |   await input.fill('保留的草稿')
  48 |   await page.getByRole('button', { name: '编辑第1轮问题' }).click()
  49 |   await expect(input).toHaveValue('第一条合成查询')
  50 |   await page.getByRole('button', { name: '取消编辑' }).click()
  51 |   await expect(input).toHaveValue('保留的草稿')
  52 |   await page.getByRole('button', { name: '编辑第1轮问题' }).click()
  53 |   await input.fill('编辑后的第二条查询')
  54 |   expect(sends).toBe(1)
  55 |   await page.getByRole('button', { name: '发送问题' }).click()
  56 |   await expect(page.getByRole('button', { name: '编辑第2轮问题' })).toBeVisible()
> 57 |   await expect(page.getByText('第一条合成查询', { exact: true })).toBeVisible()
     |                                                            ^ Error: expect(locator).toBeVisible() failed
  58 |   await expect(page.getByText('编辑后的第二条查询', { exact: true })).toBeVisible()
  59 |   expect(sends).toBe(2)
  60 | })
  61 | 
```