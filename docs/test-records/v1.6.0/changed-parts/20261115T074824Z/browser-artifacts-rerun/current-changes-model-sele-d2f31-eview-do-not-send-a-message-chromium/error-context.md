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
        - paragraph [ref=e26]: 本地会话
        - navigation "本地会话"
        - paragraph [ref=e27]: 会话保存在本机，从一个问题开始。
    - button "fixture 管理员" [ref=e30] [cursor=pointer]:
      - generic [aria-hidden] [ref=e31]: FI
      - generic [ref=e32]:
        - generic [ref=e33]: fixture
        - generic [ref=e34]: 管理员
  - main [ref=e35]:
    - generic [ref=e36]:
      - button "收起会话列表" [expanded] [ref=e37] [cursor=pointer]
      - heading "新会话" [level=1] [ref=e41]
      - button "打开结果栏" [ref=e42] [cursor=pointer]
    - generic [ref=e47]:
      - generic [ref=e49]:
        - paragraph [ref=e50]: SIMBAD · ADS · Gaia DR3
        - heading "天文数据与文献检索" [level=2] [ref=e51]
        - paragraph [ref=e52]: 查询天体、Gaia 测量和论文，保留每轮来源与结果。
      - generic [ref=e53]:
        - button "坐标圆锥查询" [ref=e54] [cursor=pointer]:
          - generic [aria-hidden] [ref=e56]: ↗
        - button "指定 DR3 编号" [ref=e57] [cursor=pointer]:
          - generic [aria-hidden] [ref=e59]: ↗
        - button "ADS 文献检索" [ref=e60] [cursor=pointer]:
          - generic [aria-hidden] [ref=e62]: ↗
      - paragraph [ref=e63]: 示例仅填入输入框，由你确认发送。
    - generic [ref=e64]:
      - generic [ref=e67]:
        - button "查看附件文本：synthetic.txt" [active] [ref=e68] [cursor=pointer]:
          - generic [ref=e71]:
            - generic [ref=e72]: synthetic.txt
            - generic [ref=e73]: 6 字符 · 查看文本
        - button "移除附件：synthetic.txt" [ref=e74] [cursor=pointer]: ×
      - generic [ref=e75]: 天文问题
      - textbox "天文问题" [ref=e76]:
        - /placeholder: 输入一个天文问题，或继续追问刚才的结果…
      - generic [ref=e77]:
        - generic [ref=e78]:
          - button "科研绘图" [ref=e79] [cursor=pointer]
          - button "N 体模拟 待开放" [ref=e84] [cursor=pointer]:
            - generic [ref=e90]: N 体模拟
            - generic [ref=e91]: 待开放
        - button "回答模型：DeepSeek" [ref=e94] [cursor=pointer]:
          - generic [ref=e95]: DeepSeek
        - button "选择附件" [ref=e98]
        - button "添加附件" [ref=e99] [cursor=pointer]
        - button "发送问题" [ref=e102] [cursor=pointer]
      - paragraph [ref=e105]: 模型回答需对照原始数据核查；位置候选源不等于星团成员。
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
> 19 |   await page.getByRole('button', { name: '回答模型：deepseek-test' }).click()
     |                                                                  ^ Error: locator.click: Test timeout of 60000ms exceeded.
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
  57 |   await expect(page.locator('.user-message').nth(0)).toHaveText('第一条合成查询')
  58 |   await expect(page.locator('.user-message').nth(1)).toHaveText('编辑后的第二条查询')
  59 |   expect(sends).toBe(2)
  60 | })
  61 | 
```