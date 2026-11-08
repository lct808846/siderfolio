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
Error: strict mode violation: getByText('第一条合成查询', { exact: true }) resolved to 3 elements:
    1) <b>第一条合成查询</b> aka getByRole('button', { name: '第一条合成查询 2 轮 · 2026/11/' })
    2) <h1 title="第一条合成查询">第一条合成查询</h1> aka getByRole('heading', { name: '第一条合成查询' })
    3) <div class="user-message">第一条合成查询</div> aka locator('div').filter({ hasText: /^第一条合成查询$/ })

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
      - generic [ref=e18]: 1/20
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
      - text: SIMBAD / ADS / Gaia
      - generic [ref=e33]: 测量 · 文献 · 可追溯结果
  - main [ref=e34]:
    - generic [ref=e35]:
      - button "收起会话列表" [expanded] [ref=e36] [cursor=pointer]
      - heading "第一条合成查询" [level=1] [ref=e40]
    - generic [ref=e41]:
      - article [ref=e42]:
        - generic [ref=e43]:
          - generic [ref=e44]: 第 1 轮
          - generic [ref=e45]: synthetic-model
          - time [ref=e46]: 16:42
          - generic [ref=e47]: 历史记录
        - generic [ref=e48]:
          - button "查看附件文本：dragged.txt" [ref=e50] [cursor=pointer]:
            - generic [ref=e53]:
              - generic [ref=e54]: dragged.txt
              - generic [ref=e55]: 6 字符 · 查看文本
          - generic [ref=e56]: 第一条合成查询
          - generic [ref=e57]:
            - button "复制第1轮问题" [ref=e58] [cursor=pointer]
            - button "编辑第1轮问题" [ref=e62] [cursor=pointer]
        - generic [ref=e65]:
          - generic [ref=e66]:
            - generic [aria-hidden] [ref=e67]: ✳
            - generic [ref=e68]: AstroAgent
            - generic [ref=e69]: 已完成
          - paragraph [ref=e71]: 合成验收结果已返回。请在右侧核查完整测量、单位和查询条件；这些不是实际观测。
          - link "Gaia ↗" [ref=e73] [cursor=pointer]:
            - /url: https://example.invalid/synthetic-gaia
          - button "核查本轮结果与导出" [ref=e74] [cursor=pointer]:
            - text: 核查本轮结果与导出
            - generic [aria-hidden] [ref=e75]: →
      - article [ref=e76]:
        - generic [ref=e77]:
          - generic [ref=e78]: 第 2 轮
          - generic [ref=e79]: synthetic-model
          - time [ref=e80]: 16:42
        - generic [ref=e81]:
          - generic [ref=e82]: 编辑后的第二条查询
          - generic [ref=e83]:
            - button "复制第2轮问题" [ref=e84] [cursor=pointer]
            - button "编辑第2轮问题" [ref=e88] [cursor=pointer]
        - generic [ref=e91]:
          - generic [ref=e92]:
            - generic [aria-hidden] [ref=e93]: ✳
            - generic [ref=e94]: AstroAgent
            - generic [ref=e95]: 已完成
          - paragraph [ref=e97]: 合成验收结果已返回。请在右侧核查完整测量、单位和查询条件；这些不是实际观测。
          - group [ref=e98]:
            - generic "使用了 1 轮历史上下文" [ref=e99] [cursor=pointer]
          - link "Gaia ↗" [ref=e101] [cursor=pointer]:
            - /url: https://example.invalid/synthetic-gaia
          - button "核查本轮结果与导出" [ref=e102] [cursor=pointer]:
            - text: 核查本轮结果与导出
            - generic [aria-hidden] [ref=e103]: →
    - generic [ref=e104]:
      - generic [ref=e105]: 天文问题
      - textbox "天文问题" [ref=e106]:
        - /placeholder: 输入一个天文问题，或继续追问刚才的结果…
      - generic [ref=e107]:
        - button "回答模型：synthetic-model" [ref=e110] [cursor=pointer]:
          - generic [ref=e111]: synthetic-model
        - button "选择附件" [ref=e114]
        - button "添加附件" [ref=e115] [cursor=pointer]
        - button "发送问题" [disabled] [ref=e118]
      - paragraph [ref=e121]: 模型回答需对照原始数据核查；位置候选源不等于星团成员。
  - complementary "结果核查" [ref=e122]:
    - generic [ref=e123]:
      - generic [ref=e124]:
        - text: RESULTS / 数据核查
        - heading "第 2 轮结果" [level=2] [ref=e125]
      - button "收起结果面板" [ref=e126] [cursor=pointer]: ×
    - paragraph [ref=e127]:
      - text: 接收时间（UTC）
      - time [ref=e128]: 2026-11-08T08:42:14.085449+00:00
    - tablist "数据源" [ref=e129]:
      - tab "Gaia DR3 1" [selected] [ref=e130] [cursor=pointer]
      - tab "ADS 0" [ref=e131] [cursor=pointer]
      - tab "SIMBAD 0" [ref=e132] [cursor=pointer]
    - generic [ref=e133]:
      - generic [ref=e134]: 本轮 Gaia 查询
      - combobox "本轮 Gaia 查询" [ref=e135]:
        - option "第 1 次 · success · 100 行" [selected]
      - generic [ref=e136]:
        - generic [ref=e137]:
          - generic [ref=e138]: "100"
          - text: 交付行
        - generic [ref=e139]:
          - generic [ref=e140]: 未知
          - text: 总命中数
        - generic [ref=e141]:
          - generic [ref=e142]: 未截断
          - text: 交付范围
      - group [ref=e143]:
        - generic "条件、单位与程序统计" [ref=e144] [cursor=pointer]
      - group [ref=e145]:
        - generic "实际 ADQL" [ref=e146] [cursor=pointer]
      - group [ref=e147]:
        - generic "查看完整交付表格（100 行）" [ref=e148] [cursor=pointer]
      - paragraph [ref=e149]: 合成验收数据，不是实际观测。
    - region "图表与下载" [ref=e150]:
      - heading "图表与数据包" [level=3] [ref=e151]
      - paragraph [ref=e152]: 基于第 2 轮完整响应。图表只描述交付样本。
      - generic [ref=e153]:
        - generic [ref=e154]:
          - checkbox "自行散点图" [ref=e155]
          - text: 自行散点图
        - generic [ref=e156]:
          - checkbox "视差直方图" [ref=e157]
          - text: 视差直方图
        - generic [ref=e158]:
          - checkbox "观测颜色—星等图" [ref=e159]
          - text: 观测颜色—星等图
      - button "生成预览与数据包" [ref=e161] [cursor=pointer]
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