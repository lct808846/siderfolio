# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: axe-acceptance.spec.ts >> automated accessibility audit of workbench, project and settings
- Location: tests\browser\axe-acceptance.spec.ts:4:1

# Error details

```
Error: page.addScriptTag: Executing inline script violates the following Content Security Policy directive 'script-src 'self''. Either the 'unsafe-inline' keyword, a hash ('sha256-ci58rsVFdB5X+St8VZlEZXT1ryZVc7TaRl/fed6foGw='), or a nonce ('nonce-...') is required to enable inline execution. The action has been blocked.
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
      - generic [ref=e18]: 0/20
    - button "新建会话" [ref=e19] [cursor=pointer]:
      - generic [aria-hidden] [ref=e20]: ＋
      - text: 新建会话
    - paragraph [ref=e22]: 本地会话
    - navigation "本地会话"
    - paragraph [ref=e23]: 会话保存在本机，从一个问题开始。
    - generic [ref=e24]:
      - text: SIMBAD / ADS / Gaia
      - generic [ref=e25]: 测量 · 文献 · 可追溯结果
  - main [ref=e26]:
    - generic [ref=e27]:
      - button "收起会话列表" [expanded] [ref=e28] [cursor=pointer]
      - heading "新会话" [level=1] [ref=e32]
      - button "打开结果栏" [ref=e33] [cursor=pointer]
    - generic [ref=e38]:
      - generic [ref=e40]:
        - paragraph [ref=e41]: SIMBAD · ADS · Gaia DR3
        - heading "天文数据与文献检索" [level=2] [ref=e42]
        - paragraph [ref=e43]: 查询天体、Gaia 测量和论文，保留每轮来源与结果。
      - generic [ref=e44]:
        - button "坐标圆锥查询" [ref=e45] [cursor=pointer]:
          - generic [aria-hidden] [ref=e47]: ↗
        - button "指定 DR3 编号" [ref=e48] [cursor=pointer]:
          - generic [aria-hidden] [ref=e50]: ↗
        - button "ADS 文献检索" [ref=e51] [cursor=pointer]:
          - generic [aria-hidden] [ref=e53]: ↗
      - paragraph [ref=e54]: 示例仅填入输入框，由你确认发送。
    - generic [ref=e55]:
      - generic [ref=e56]: 天文问题
      - textbox "天文问题" [ref=e57]:
        - /placeholder: 输入一个天文问题，或继续追问刚才的结果…
      - generic [ref=e58]:
        - button "回答模型：synthetic-model" [ref=e61] [cursor=pointer]:
          - generic [ref=e62]: synthetic-model
        - button "选择附件" [ref=e65]
        - button "添加附件" [ref=e66] [cursor=pointer]
        - button "发送问题" [disabled] [ref=e69]
      - paragraph [ref=e72]: 模型回答需对照原始数据核查；位置候选源不等于星团成员。
```

# Test source

```ts
  1  | import { test, expect } from '@playwright/test'
  2  | import path from 'node:path'
  3  | 
  4  | test('automated accessibility audit of workbench, project and settings', async ({ page, request }, info) => {
  5  |   const project = await (await request.post('/api/v1/projects', { data: { name: `无障碍-${crypto.randomUUID().slice(0, 8)}` } })).json()
  6  |   for (const route of ['/', `/projects/${project.id}`, '/settings']) {
  7  |     await page.goto(route)
> 8  |     await page.addScriptTag({ path: path.resolve('node_modules/axe-core/axe.min.js') })
     |     ^ Error: page.addScriptTag: Executing inline script violates the following Content Security Policy directive 'script-src 'self''. Either the 'unsafe-inline' keyword, a hash ('sha256-ci58rsVFdB5X+St8VZlEZXT1ryZVc7TaRl/fed6foGw='), or a nonce ('nonce-...') is required to enable inline execution. The action has been blocked.
  9  |     const result = await page.evaluate(async () => {
  10 |       const axe = (window as unknown as { axe: { run: (root: Document, options: object) => Promise<{ violations: { id: string; impact: string; nodes: unknown[] }[] }> } }).axe
  11 |       const output = await axe.run(document, { runOnly: { type: 'tag', values: ['wcag2a', 'wcag2aa'] } })
  12 |       return output.violations.map(item => ({ id: item.id, impact: item.impact, count: item.nodes.length }))
  13 |     })
  14 |     info.annotations.push({ type: 'accessibility', description: `${route}: ${JSON.stringify(result)}` })
  15 |     expect(result, `${route} accessibility violations`).toEqual([])
  16 |   }
  17 | })
  18 | 
```