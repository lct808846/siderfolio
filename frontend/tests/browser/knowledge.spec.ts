import { test, expect } from '@playwright/test'
import path from 'node:path'
import { readFile } from 'node:fs/promises'
import { chooseUiOption } from './ui-select'

test('local documents can be uploaded, searched, cited and downloaded', async ({ page, request }, info) => {
  const project = await (await request.post('/api/v1/projects', { data: { name: '合成文献验收' } })).json()
  try {
    await page.goto(`/projects/${project.id}/knowledge`)
    const raw = Buffer.from('# 合成文献\n银河潮汐 synthetic tidal evidence\n<script>window.injected=true</script>\n')
    await page.getByLabel('选择文件（断线后可重选同一文件核对）').setInputFiles({ name: 'synthetic.md', mimeType: 'text/markdown', buffer: raw })
    await page.getByRole('button', { name: '保存文件并本地解析' }).click()
    await expect(page.getByRole('heading', { name: 'synthetic.md', exact: true, level: 3 })).toBeVisible({ timeout: 30000 })
    await page.getByLabel('问题中的明确关键词').fill('银河潮汐')
    await page.getByRole('button', { name: '检索原文证据' }).click()
    await expect(page.getByRole('heading', { name: '找到的相关原文' })).toBeVisible()
    await page.getByRole('button', { name: '核对引用与原始版本' }).first().click()
    await expect(page.getByText('原始行', { exact: false }).first()).toBeVisible()
    expect(await page.evaluate(() => 'injected' in window)).toBe(false)
    if (process.env.ASTROAGENT_RECORD_DIR) await page.screenshot({ path: path.join(process.env.ASTROAGENT_RECORD_DIR, `${info.project.name}-knowledge-desktop.png`) })
    await page.setViewportSize({ width: 390, height: 844 })
    await page.getByRole('button', { name: '证据与原文', exact: true }).click()
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
    if (process.env.ASTROAGENT_RECORD_DIR) await page.screenshot({ path: path.join(process.env.ASTROAGENT_RECORD_DIR, `${info.project.name}-knowledge-mobile.png`) })
    await page.setViewportSize({ width: 1440, height: 900 })
    await page.goto(`/?project=${project.id}&manage=manage`)
    await expect(page.getByRole('heading', { name: '导出项目备份包（ZIP 迁移格式）' })).toBeVisible()
    const knowledgeMode = page.getByRole('button', { name: '文献原文备份方式', exact: true })
    await expect(knowledgeMode).toBeVisible()
    await expect(knowledgeMode).toContainText('保留标题、检索词及记录')
    await chooseUiOption(page, knowledgeMode, /完整备份/)
    await page.getByRole('button', { name: '导出项目备份 ZIP' }).click()
    const dialog = page.getByRole('dialog').filter({ has: page.getByRole('heading', { name: '导出含文献原文的完整备份？' }) })
    await expect(dialog.getByRole('heading', { name: '导出含文献原文的完整备份？' })).toBeVisible()
    await expect(dialog).toContainText('1 份文档')
    await expect(dialog).toContainText(`${raw.length} 字节`)
    await dialog.getByRole('button', { name: '取消' }).click()
    await chooseUiOption(page, knowledgeMode, /仅元数据/)
    const [response, download] = await Promise.all([
      page.waitForResponse(response => response.url().endsWith(`/projects/${project.id}/archive`) && response.request().method() === 'POST'),
      page.waitForEvent('download'),
      page.getByRole('button', { name: '导出项目备份 ZIP' }).click(),
    ])
    expect(response.status()).toBe(200)
    expect(download.suggestedFilename()).toMatch(/\.zip$/)
  } finally {
    const detail = await (await request.get(`/api/v1/projects/${project.id}`)).json()
    await request.delete(`/api/v1/projects/${project.id}`, { data: { expected_revision: detail.revision, confirm: true } })
  }
})

test('public PDF citation opens its original and downloads identical bytes', async ({ page, request }) => {
  const pdfPath = process.env.ASTROAGENT_ACCEPTANCE_PUBLIC_PDF
  test.skip(!pdfPath, 'Public PDF is an explicitly provided local fixture')
  const project = await (await request.post('/api/v1/projects', { data: { name: '公开文献验收' } })).json()
  try {
    await page.goto(`/projects/${project.id}/knowledge`)
    await page.getByLabel('选择文件（断线后可重选同一文件核对）').setInputFiles(pdfPath!)
    await page.getByRole('button', { name: '保存文件并本地解析' }).click()
    await expect(page.getByRole('heading', { name: path.basename(pdfPath!), exact: true, level: 3 })).toBeVisible({ timeout: 60000 })
    await page.getByLabel('问题中的明确关键词').fill('dynamical fate')
    await page.getByRole('button', { name: '检索原文证据' }).click()
    await page.getByRole('button', { name: '核对引用与原始版本' }).first().click()
    await page.getByRole('button', { name: '打开此引用的原始版本' }).click()
    await expect(page.getByTitle('受限PDF原文件预览')).toBeVisible()
    const [download] = await Promise.all([
      page.waitForEvent('download'),
      page.getByRole('button', { name: '下载完整原文件' }).click(),
    ])
    expect(await readFile((await download.path())!)).toEqual(await readFile(pdfPath!))
  } finally {
    const detail = await (await request.get(`/api/v1/projects/${project.id}`)).json()
    await request.delete(`/api/v1/projects/${project.id}`, { data: { expected_revision: detail.revision, confirm: true } })
  }
})

test('long Chinese filename remains usable on a narrow screen', async ({ page, request }, info) => {
  const project = await (await request.post('/api/v1/projects', { data: { name: '长文件名验收' } })).json()
  try {
    await page.setViewportSize({ width: 390, height: 844 })
    await page.goto(`/projects/${project.id}/knowledge`)
    await page.getByRole('button', { name: '文档与上传', exact: true }).click()
    const filename = `${'中文长文件名'.repeat(25)}.md`
    await page.getByLabel('选择文件（断线后可重选同一文件核对）').setInputFiles({ name: filename, mimeType: 'text/markdown', buffer: Buffer.from('# 合成\n长文件名验收\n') })
    await page.getByRole('button', { name: '保存文件并本地解析' }).click()
    await expect(page.getByRole('status')).toContainText('已提取并索引', { timeout: 30000 })
    await page.getByRole('button', { name: '文档与上传', exact: true }).click()
    await expect(page.getByText(filename, { exact: true }).first()).toBeVisible({ timeout: 30000 })
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
    if (process.env.ASTROAGENT_RECORD_DIR) await page.screenshot({ path: path.join(process.env.ASTROAGENT_RECORD_DIR, `${info.project.name}-knowledge-long-name.png`) })
  } finally {
    const detail = await (await request.get(`/api/v1/projects/${project.id}`)).json()
    await request.delete(`/api/v1/projects/${project.id}`, { data: { expected_revision: detail.revision, confirm: true } })
  }
})
