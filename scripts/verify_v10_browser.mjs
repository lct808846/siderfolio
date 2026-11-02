// Browser checks against a disposable real PostgreSQL backend; no external model requests.
import assert from 'node:assert/strict'
import { writeFile } from 'node:fs/promises'
import path from 'node:path'
import { chromium } from '../frontend/node_modules/playwright/index.mjs'

const base = process.env.ASTROAGENT_ACCEPTANCE_ORIGIN
const output = process.env.ASTROAGENT_ACCEPTANCE_RECORD
const results = []
for (const [name, options] of [['chromium', {}], ['edge', { channel: 'msedge' }]]) {
  const browser = await chromium.launch(options)
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })
  let sent = 0
  page.on('request', request => { if (request.method() === 'POST' && request.url().includes('/rag/answers')) sent++ })
  try {
    await page.goto(`${base}/settings`)
    await page.getByRole('heading', { name: '连接数据，准备文献问答' }).waitFor()
    if (name === 'chromium') {
      await page.getByRole('button', { name: '核对后初始化空库' }).click()
      await page.getByRole('dialog').getByRole('button', { name: '确认初始化空库' }).click()
    }
    await page.getByText('PostgreSQL业务服务已就绪', { exact: false }).waitFor({ timeout: 30000 })
    const created = await page.request.post(`${base}/api/v1/projects`, { data: { name: `Browser ${name}` } })
    assert.equal(created.status(), 201)
    const project = await created.json()
    const root = `${base}/api/v1/projects/${project.id}`
    const uploaded = await page.request.post(`${root}/documents`, {
      multipart: {
        file: { name: 'synthetic.md', mimeType: 'text/markdown', buffer: Buffer.from('# Evidence\nBinary cluster synthetic evidence.\n') },
        options: JSON.stringify({ expected_revision: project.revision, client_request_id: crypto.randomUUID() }),
      },
    })
    assert.equal(uploaded.status(), 201)
    await page.goto(`${base}/projects/${project.id}/rag`)
    await page.getByLabel('本次问题').fill('binary cluster')
    const responsePromise = page.waitForResponse(r => r.url().endsWith('/rag/previews') && r.request().method() === 'POST')
    await page.getByRole('button', { name: '检索并预览，不调用回答模型' }).click()
    assert.equal((await responsePromise).status(), 200)
    await page.getByRole('heading', { name: '核对这些片段与服务' }).waitFor()
    await page.getByText('Binary cluster synthetic evidence.', { exact: false }).first().waitFor()
    assert.equal(sent, 0)
    await page.screenshot({ path: path.join(output, `${name}-rag-desktop.png`) })
    await page.setViewportSize({ width: 390, height: 844 })
    await page.getByRole('button', { name: '本次发送预览' }).click()
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true)
    await page.screenshot({ path: path.join(output, `${name}-rag-mobile.png`) })
    const discarded = page.waitForResponse(r => r.url().includes('/rag/previews/') && r.request().method() === 'DELETE')
    await page.getByRole('button', { name: '取消，不发送' }).click()
    assert.equal((await discarded).status(), 204)
    await page.getByText('已取消预览，未向回答服务发送内容。').waitFor()
    assert.equal(sent, 0)
    results.push({ browser: name, passed: true, version: browser.version(), no_answer_requests: true })
  } catch (error) {
    results.push({ browser: name, passed: false, error: String(error) })
    await page.screenshot({ path: path.join(output, `${name}-failure.png`) }).catch(() => {})
  } finally { await browser.close() }
}
await writeFile(path.join(output, 'browser.json'), JSON.stringify({ results, passed: results.every(item => item.passed) }, null, 2))
if (results.some(item => !item.passed)) process.exitCode = 1
