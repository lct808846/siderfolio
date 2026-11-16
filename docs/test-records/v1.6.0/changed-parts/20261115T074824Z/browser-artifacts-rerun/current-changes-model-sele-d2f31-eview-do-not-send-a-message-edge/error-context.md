# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: current-changes.spec.ts >> model selection and attachment preview do not send a message
- Location: tests\browser\current-changes.spec.ts:3:1

# Error details

```
Test timeout of 60000ms exceeded.
```

```
Error: locator.click: Test timeout of 60000ms exceeded.
Call log:
  - waiting for getByRole('button', { name: '回答模型：deepseek-test' })

```

# Page snapshot

```yaml
- generic [ref=e3]:
  - banner [ref=e4]:
    - generic [ref=e5]:
      - button "AstroAgent：新建会话" [ref=e6] [cursor=pointer]:
        - generic [ref=e11]: AstroAgent
        - generic [ref=e12]: 1.6 开发版
      - navigation "全局导航" [ref=e13]:
        - link "查询工作台" [ref=e14] [cursor=pointer]:
          - /url: /
        - link "项目归档" [ref=e15] [cursor=pointer]:
          - /url: /projects
        - link "本地助手" [ref=e16] [cursor=pointer]:
          - /url: /local-assistant
        - link "接口定义 ↗" [ref=e17] [cursor=pointer]:
          - /url: /openapi.json
  - complementary "会话列表" [ref=e18]:
    - button "新建会话" [ref=e20] [cursor=pointer]:
      - generic [aria-hidden] [ref=e21]: ＋
      - text: 新建会话
    - generic "滚动浏览会话" [ref=e23]:
      - generic [ref=e24]:
        - generic [ref=e25]:
          - paragraph [ref=e26]: 本地会话
          - button "多选管理会话" [ref=e27] [cursor=pointer]
        - navigation "本地会话" [ref=e33]:
          - generic [ref=e34]:
            - checkbox [disabled]
            - button "流程 · 合成超时后继续 1 轮 · 2026/11/15" [ref=e35] [cursor=pointer]:
              - generic [ref=e36]:
                - generic [ref=e37]: 流程 · 合成超时后继续
                - generic [ref=e38]: 1 轮 · 2026/11/15
            - button "会话操作：流程 · 合成超时后继续" [ref=e40] [cursor=pointer]: ⋯
          - generic [ref=e41]:
            - checkbox [disabled]
            - button "流程 · 合成 ADS 证据表 1 轮 · 2026/11/15" [ref=e42] [cursor=pointer]:
              - generic [ref=e43]:
                - generic [ref=e44]: 流程 · 合成 ADS 证据表
                - generic [ref=e45]: 1 轮 · 2026/11/15
            - button "会话操作：流程 · 合成 ADS 证据表" [ref=e47] [cursor=pointer]: ⋯
          - generic [ref=e48]:
            - checkbox [disabled]
            - button "流程 · 合成 Gaia 流程 1 轮 · 2026/11/15" [ref=e49] [cursor=pointer]:
              - generic [ref=e50]:
                - generic [ref=e51]: 流程 · 合成 Gaia 流程
                - generic [ref=e52]: 1 轮 · 2026/11/15
            - button "会话操作：流程 · 合成 Gaia 流程" [ref=e54] [cursor=pointer]: ⋯
          - generic [ref=e55]:
            - checkbox [disabled]
            - button "延迟列表测试 0 轮 · 2026/11/15" [ref=e56] [cursor=pointer]:
              - generic [ref=e57]:
                - generic [ref=e58]: 延迟列表测试
                - generic [ref=e59]: 0 轮 · 2026/11/15
            - button "会话操作：延迟列表测试" [ref=e61] [cursor=pointer]: ⋯
          - generic [ref=e62]:
            - checkbox [disabled]
            - button "新会话 0 轮 · 2026/11/15" [ref=e63] [cursor=pointer]:
              - generic [ref=e64]:
                - generic [ref=e65]: 新会话
                - generic [ref=e66]: 0 轮 · 2026/11/15
            - button "会话操作：新会话" [ref=e68] [cursor=pointer]: ⋯
          - generic [ref=e69]:
            - checkbox [disabled]
            - button "合成Gaia圆锥查询 1 轮 · 2026/11/15" [ref=e70] [cursor=pointer]:
              - generic [ref=e71]:
                - generic [ref=e72]: 合成Gaia圆锥查询
                - generic [ref=e73]: 1 轮 · 2026/11/15
            - button "会话操作：合成Gaia圆锥查询" [ref=e75] [cursor=pointer]: ⋯
          - generic [ref=e76]:
            - checkbox [disabled]
            - button "合成验收：查询Gaia圆锥100个… 2 轮 · 2026/11/15" [ref=e77] [cursor=pointer]:
              - generic [ref=e78]:
                - generic [ref=e79]: 合成验收：查询Gaia圆锥100个…
                - generic [ref=e80]: 2 轮 · 2026/11/15
            - button "会话操作：合成验收：查询Gaia圆锥100个…" [ref=e82] [cursor=pointer]: ⋯
          - generic [ref=e83]:
            - checkbox [disabled]
            - button "第一条合成查询 2 轮 · 2026/11/15" [ref=e84] [cursor=pointer]:
              - generic [ref=e85]:
                - generic [ref=e86]: 第一条合成查询
                - generic [ref=e87]: 2 轮 · 2026/11/15
            - button "会话操作：第一条合成查询" [ref=e89] [cursor=pointer]: ⋯
    - button "fixture 管理员" [ref=e92] [cursor=pointer]:
      - generic [aria-hidden] [ref=e93]: FI
      - generic [ref=e94]:
        - generic [ref=e95]: fixture
        - generic [ref=e96]: 管理员
  - main [ref=e97]:
    - generic [ref=e98]:
      - button "收起会话列表" [expanded] [ref=e99] [cursor=pointer]
      - heading "新会话" [level=1] [ref=e103]
      - button "打开结果栏" [ref=e104] [cursor=pointer]
    - generic [ref=e109]:
      - generic [ref=e111]:
        - paragraph [ref=e112]: SIMBAD · ADS · Gaia DR3
        - heading "天文数据与文献检索" [level=2] [ref=e113]
        - paragraph [ref=e114]: 查询天体、Gaia 测量和论文，保留每轮来源与结果。
      - generic [ref=e115]:
        - button "坐标圆锥查询" [ref=e116] [cursor=pointer]:
          - generic [aria-hidden] [ref=e118]: ↗
        - button "指定 DR3 编号" [ref=e119] [cursor=pointer]:
          - generic [aria-hidden] [ref=e121]: ↗
        - button "ADS 文献检索" [ref=e122] [cursor=pointer]:
          - generic [aria-hidden] [ref=e124]: ↗
      - paragraph [ref=e125]: 示例仅填入输入框，由你确认发送。
    - generic [ref=e126]:
      - generic [ref=e129]:
        - button "查看附件文本：synthetic.txt" [active] [ref=e130] [cursor=pointer]:
          - generic [ref=e133]:
            - generic [ref=e134]: synthetic.txt
            - generic [ref=e135]: 6 字符 · 查看文本
        - button "移除附件：synthetic.txt" [ref=e136] [cursor=pointer]: ×
      - generic [ref=e137]: 天文问题
      - textbox "天文问题" [ref=e138]:
        - /placeholder: 输入一个天文问题，或继续追问刚才的结果…
      - generic [ref=e139]:
        - generic [ref=e140]:
          - button "科研绘图" [ref=e141] [cursor=pointer]
          - button "N 体模拟 待开放" [ref=e146] [cursor=pointer]:
            - generic [ref=e152]: N 体模拟
            - generic [ref=e153]: 待开放
        - button "回答模型：DeepSeek" [ref=e156] [cursor=pointer]:
          - generic [ref=e157]: DeepSeek
        - button "选择附件" [ref=e160]
        - button "添加附件" [ref=e161] [cursor=pointer]
        - button "发送问题" [ref=e164] [cursor=pointer]
      - paragraph [ref=e167]: 模型回答需对照原始数据核查；位置候选源不等于星团成员。
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
> 19 |   await page.getByRole('button', { name: '回答模型：DeepSeek' }).click()
     |                                                                  ^ Error: locator.click: Test timeout of 60000ms exceeded.
  20 |   await page.getByRole('menuitem', { name: /模型/ }).click()
  21 |   await page.getByRole('option', { name: 'Qwen', exact: true }).click()
  22 |   await expect(page.getByRole('button', { name: '回答模型：Qwen' })).toBeVisible()
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
  57 |   await expect(page.locator('.user-message').nth(0)).toHaveText('第一条合成查询')
  58 |   await expect(page.locator('.user-message').nth(1)).toHaveText('编辑后的第二条查询')
  59 |   expect(sends).toBe(2)
  60 | })
  61 | 
```