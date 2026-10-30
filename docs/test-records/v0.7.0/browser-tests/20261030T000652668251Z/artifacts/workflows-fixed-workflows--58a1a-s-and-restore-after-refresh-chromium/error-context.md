# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: workflows.spec.ts >> fixed workflows create, confirm, execute, display outputs and restore after refresh
- Location: tests\browser\workflows.spec.ts:4:1

# Error details

```
Error: expect(locator).toBeVisible() failed

Locator: getByText('workflow-results.zip')
Expected: visible
Error: strict mode violation: getByText('workflow-results.zip') resolved to 2 elements:
    1) <b>workflow-results.zip</b> aka getByText('workflow-results.zip', { exact: true })
    2) <pre>{↵  "id": "bce475dc-ede3-4bb0-a1bd-d90e2afa080a",…</pre> aka getByText('{ "id": "bce475dc-ede3-4bb0-')

Call log:
  - Expect "toBeVisible" getByText('workflow-results.zip') with timeout 30000ms
  - waiting for getByText('workflow-results.zip')

```

# Page snapshot

```yaml
- generic [ref=e3]:
  - banner [ref=e4]:
    - link "AstroAgent 0.7" [ref=e5] [cursor=pointer]:
      - /url: /
      - generic [aria-hidden] [ref=e6]: ✳
      - generic [ref=e7]: AstroAgent
      - generic [ref=e8]: "0.7"
    - generic [ref=e9]: 固定科研流程
    - link "返回项目 ↗" [ref=e10] [cursor=pointer]:
      - /url: /projects/db0a0344-e3c5-4207-8146-81d64dad1692
  - complementary "流程列表与新建" [ref=e11]:
    - link [ref=e12] [cursor=pointer]:
      - /url: /projects/db0a0344-e3c5-4207-8146-81d64dad1692/workflows
      - paragraph [ref=e13]: WORKFLOWS · 1/50
      - heading "合成流程验收" [level=2] [ref=e14]
    - link "合成 Gaia 流程 完成 · r8 · 本机" [ref=e15] [cursor=pointer]:
      - /url: /projects/db0a0344-e3c5-4207-8146-81d64dad1692/workflows/971e0aae-7021-4500-a2ea-45b3bd4ae8e6
      - text: 合成 Gaia 流程
      - generic [ref=e16]: 完成 · r8 · 本机
    - generic [ref=e17]:
      - heading "新建运行" [level=2] [ref=e18]
      - paragraph [ref=e19]: 创建只保存参数。执行需另行确认。
      - group [ref=e20]:
        - generic [ref=e21]: 固定模板
        - combobox "固定模板" [ref=e22]:
          - option "Gaia视场候选源 · v1" [selected]
          - option "ADS摘要证据表 · v1"
        - generic [ref=e23]: 运行名称
        - textbox "运行名称" [ref=e24]: 合成 Gaia 流程
        - generic [ref=e25]: 坐标来源（互斥）
        - combobox "坐标来源（互斥）" [ref=e26]:
          - option "明确的ICRS坐标" [selected]
          - option "SIMBAD名称解析"
        - generic [ref=e27]: ICRS赤经 / 度 [0,360)
        - spinbutton "ICRS赤经 / 度 [0,360)" [ref=e28]: "56.75"
        - generic [ref=e29]: ICRS赤纬 / 度 [-90,90]
        - spinbutton "ICRS赤纬 / 度 [-90,90]" [ref=e30]: "24.12"
        - generic [ref=e31]: 圆锥半径 / 角分 (0,30]
        - spinbutton "圆锥半径 / 角分 (0,30]" [ref=e32]: "5"
        - generic [ref=e33]: 交付行上限 / 1—100
        - spinbutton "交付行上限 / 1—100" [ref=e34]: "10"
        - generic [ref=e35]: RUWE上限（可选）
        - spinbutton "RUWE上限（可选）" [ref=e36]
        - generic [ref=e37]: 视差信噪比下限（可选）
        - spinbutton "视差信噪比下限（可选）" [ref=e38]
        - generic [ref=e39]:
          - checkbox "估算高信噪比正视差的近似距离" [ref=e40]
          - text: 估算高信噪比正视差的近似距离
        - generic [ref=e41]:
          - checkbox "自行散点图" [ref=e42]
          - text: 自行散点图
        - generic [ref=e43]:
          - checkbox "视差直方图" [ref=e44]
          - text: 视差直方图
        - generic [ref=e45]:
          - checkbox "观测颜色—星等图" [ref=e46]
          - text: 观测颜色—星等图
        - group [ref=e47]:
          - generic "创建后的固定步骤" [ref=e48] [cursor=pointer]
        - paragraph [ref=e49]: 位置候选源不等于星团成员；未做自行传播。
        - paragraph [ref=e50]: 统计和图表只描述交付样本。
        - paragraph [ref=e51]: 流程不调用模型；启动或继续会按需访问外部科研服务。
        - button "创建待执行记录" [ref=e52] [cursor=pointer]
  - main [ref=e53]:
    - generic [ref=e54]:
      - status [ref=e55]: 本次请求：完成。科学查询和导出状态请分别查看步骤记录。
      - button "刷新记录" [ref=e56] [cursor=pointer]
    - generic [ref=e57]:
      - paragraph [ref=e58]: gaia_field / v1 / r8
      - heading "合成 Gaia 流程" [level=1] [ref=e59]
      - paragraph [ref=e60]: 完成 · 4/4 步已完成或跳过
      - code [ref=e61]: 971e0aae-7021-4500-a2ea-45b3bd4ae8e6
      - generic [ref=e62]:
        - button "复制参数，新建运行" [ref=e63] [cursor=pointer]
        - button "删除流程" [ref=e64] [cursor=pointer]
        - link "查看保存快照 →" [ref=e65] [cursor=pointer]:
          - /url: /projects/db0a0344-e3c5-4207-8146-81d64dad1692?snapshot=22086010-9757-402c-a1de-42d989d145f1
      - group [ref=e66]:
        - generic "保存的明确参数 · 不随继续操作改变" [ref=e67] [cursor=pointer]
        - generic [ref=e68]: "{ \"input_mode\": \"coordinates\", \"object_name\": null, \"ra_deg\": 56.75, \"dec_deg\": 24.12, \"radius_arcmin\": 5, \"limit\": 10, \"ruwe_max\": null, \"parallax_snr_min\": null, \"estimate_distance\": false, \"plots\": [] }"
      - group [ref=e69]:
        - generic "创建时输入与软件版本" [ref=e70] [cursor=pointer]
    - region "步骤与尝试" [ref=e71]:
      - article [ref=e72]:
        - generic [ref=e73]:
          - generic [ref=e74]: "1"
          - heading "解析名称 / 确认ICRS坐标" [level=2] [ref=e75]
          - generic [ref=e76]: 跳过
        - paragraph [ref=e77]: 用户直接指定ICRS坐标，未执行SIMBAD解析。
      - article [ref=e78]:
        - generic [ref=e79]:
          - generic [ref=e80]: "2"
          - heading "查询Gaia与程序统计" [level=2] [ref=e81]
          - generic [ref=e82]: 完成
        - group [ref=e83]:
          - generic "尝试 1/5 · 完成 · 2026-10-30T00:07:16.690204+00:00" [ref=e84] [cursor=pointer]
      - article [ref=e85]:
        - generic [ref=e86]:
          - generic [ref=e87]: "3"
          - heading "保存完整项目快照" [level=2] [ref=e88]
          - generic [ref=e89]: 完成
        - group [ref=e90]:
          - generic "尝试 1/5 · 完成 · 2026-10-30T00:07:16.725690+00:00" [ref=e91] [cursor=pointer]
      - article [ref=e92]:
        - generic [ref=e93]:
          - generic [ref=e94]: "4"
          - heading "生成数据包与所选图表" [level=2] [ref=e95]
          - generic [ref=e96]: 完成
        - group [ref=e97]:
          - generic "尝试 1/5 · 完成 · 2026-10-30T00:07:16.769201+00:00" [ref=e98] [cursor=pointer]
    - group [ref=e99]:
      - generic "执行请求历史（继续会新建请求及失败步骤的尝试）" [ref=e100] [cursor=pointer]
  - region "流程结果与持久输出" [ref=e101]:
    - generic [ref=e102]:
      - paragraph [ref=e103]: DURABLE OUTPUTS
      - heading "保存的输出文件" [level=2] [ref=e104]
      - article [ref=e105]:
        - text: workflow-results.zip
        - paragraph [ref=e106]: 6819 字节 · 本机生成
        - group [ref=e107]:
          - generic "SHA-256与归属" [ref=e108] [cursor=pointer]
        - button "核对哈希并下载" [ref=e109] [cursor=pointer]
      - article [ref=e110]:
        - text: export-manifest.json
        - paragraph [ref=e111]: 4959 字节 · 本机生成
        - group [ref=e112]:
          - generic "SHA-256与归属" [ref=e113] [cursor=pointer]
        - button "核对哈希并下载" [ref=e114] [cursor=pointer]
    - complementary "结果核查" [ref=e115]:
      - generic [ref=e116]:
        - generic [ref=e117]:
          - text: RESULTS / 数据核查
          - heading "本次流程的实际数据" [level=2] [ref=e118]
        - generic [ref=e119]: 历史结果
      - paragraph [ref=e120]:
        - text: 接收时间（UTC）
        - time [ref=e121]: 2026-10-30T00:07:16.357347+00:00
      - tablist "数据源" [ref=e122]:
        - tab "Gaia DR3 1" [selected] [ref=e123] [cursor=pointer]
        - tab "ADS 0" [ref=e124] [cursor=pointer]
        - tab "SIMBAD 0" [ref=e125] [cursor=pointer]
      - generic [ref=e126]:
        - generic [ref=e127]: 本轮 Gaia 查询
        - combobox "本轮 Gaia 查询" [ref=e128]:
          - option "第 1 次 · success · 10 行" [selected]
        - generic [ref=e129]:
          - generic [ref=e130]:
            - generic [ref=e131]: "10"
            - text: 交付行
          - generic [ref=e132]:
            - generic [ref=e133]: 未知
            - text: 总命中数
          - generic [ref=e134]:
            - generic [ref=e135]: 未截断
            - text: 交付范围
        - group [ref=e136]:
          - generic "条件、单位与程序统计" [ref=e137] [cursor=pointer]
        - group [ref=e138]:
          - generic "实际 ADQL" [ref=e139] [cursor=pointer]
        - group [ref=e140]:
          - generic "查看完整交付表格（10 行）" [ref=e141] [cursor=pointer]
        - paragraph [ref=e142]: 合成验收数据，不是实际观测。
```

# Test source

```ts
  1  | import { test, expect } from '@playwright/test'
  2  | import path from 'node:path'
  3  | 
  4  | test('fixed workflows create, confirm, execute, display outputs and restore after refresh', async ({ page, request }, info) => {
  5  |   const project = await (await request.post('/api/v1/projects', { data: { name: '合成流程验收' } })).json()
  6  |   try {
  7  |     await page.goto(`/projects/${project.id}/workflows`)
  8  |     await page.getByLabel('运行名称').fill('合成 Gaia 流程')
  9  |     await page.getByLabel('ICRS赤经 / 度 [0,360)').fill('56.75')
  10 |     await page.getByLabel('ICRS赤纬 / 度 [-90,90]').fill('24.12')
  11 |     await page.getByLabel('圆锥半径 / 角分 (0,30]').fill('5')
  12 |     await page.getByLabel('交付行上限 / 1—100').fill('10')
  13 |     await page.getByRole('button', { name: '创建待执行记录' }).click()
  14 |     await expect(page.getByRole('heading', { name: '合成 Gaia 流程' })).toBeVisible()
  15 |     await page.getByRole('button', { name: '核对并启动' }).click()
  16 |     await expect(page.getByRole('dialog')).toBeVisible()
  17 |     await page.getByRole('button', { name: '取消', exact: true }).click()
  18 |     await expect(page.getByRole('dialog')).not.toBeVisible()
  19 |     await page.getByRole('button', { name: '核对并启动' }).click()
  20 |     await page.getByRole('button', { name: '确认执行' }).click()
> 21 |     await expect(page.getByText('workflow-results.zip')).toBeVisible({ timeout: 30000 })
     |                                                          ^ Error: expect(locator).toBeVisible() failed
  22 |     await expect(page.getByText('4/4 步已完成或跳过')).toBeVisible()
  23 |     await page.reload()
  24 |     await expect(page.getByText('workflow-results.zip')).toBeVisible()
  25 |     if (process.env.ASTROAGENT_RECORD_DIR) await page.screenshot({ path: path.join(process.env.ASTROAGENT_RECORD_DIR, `${info.project.name}-workflow-desktop.png`) })
  26 |     await page.setViewportSize({ width: 390, height: 844 })
  27 |     await page.getByRole('button', { name: '执行记录' }).click()
  28 |     expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  29 |     if (process.env.ASTROAGENT_RECORD_DIR) await page.screenshot({ path: path.join(process.env.ASTROAGENT_RECORD_DIR, `${info.project.name}-workflow-mobile.png`) })
  30 |   } finally {
  31 |     const detail = await (await request.get(`/api/v1/projects/${project.id}`)).json()
  32 |     await request.delete(`/api/v1/projects/${project.id}`, { data: { expected_revision: detail.revision, confirm: true } })
  33 |   }
  34 | })
  35 | 
```