import { expect, test, type Page } from '@playwright/test'
import path from 'node:path'

const origin = 'http://127.0.0.1:5287'

async function startOrbit(page: Page) {
  await page.getByRole('button', { name: '核对并运行' }).click()
  await expect(page.getByRole('dialog', { name: '确认运行实验' })).toBeVisible()
  await page.getByRole('button', { name: '确认并排队' }).click()
  await expect(page.getByRole('button', { name: '复制为新草稿' })).toBeVisible({ timeout: 20000 })
}

async function saveDraft(page: Page) {
  const invalid = await page.locator('form.compute-form').evaluate(form =>
    [...form.querySelectorAll<HTMLInputElement>('input:invalid')].map(input => ({
      label: input.getAttribute('aria-label') ?? input.labels?.[0]?.textContent,
      value: input.value,
      message: input.validationMessage,
    })),
  )
  expect(invalid).toEqual([])
  const saved = page.waitForResponse(res =>
    /\/compute-tasks(?:\/[^/]+)?$/.test(new URL(res.url()).pathname) &&
    ['POST', 'PATCH'].includes(res.request().method()),
  )
  await page.getByRole('button', { name: '保存草稿' }).click()
  const response = await saved
  expect([200, 201]).toContain(response.status())
  const { id } = await response.json() as { id: string }
  await expect(page).toHaveURL(url => url.pathname.endsWith(`/compute/${id}`))
  await expect(page.getByRole('button', { name: '核对并运行' })).toBeVisible()
  return id
}

async function createProject(page: Page, name: string) {
  await page.route('**/*', route => {
    const url = new URL(route.request().url())
    return url.origin === origin || url.protocol === 'data:' ? route.continue() : route.abort()
  })
  await page.goto('/login')
  await page.getByRole('textbox', { name: '邮箱', exact: true })
    .fill(process.env.ASTROAGENT_COMPUTE_QA_EMAIL || 'compute-first@example.org')
  await page.getByRole('button', { name: '继续', exact: true }).click()
  await page.getByLabel('密码', { exact: true }).fill('Synthetic nebula entropy 2048')
  await page.getByRole('button', { name: '继续', exact: true }).click()
  await expect(page).toHaveURL(origin + '/')
  const csrf = (await (await page.request.get('/api/v1/auth/csrf')).json()).csrf_token
  const created = await page.request.post('/api/v1/projects', {
    data: { name }, headers: { Origin: origin, 'X-CSRF-Token': csrf },
  })
  expect(created.status()).toBe(201)
  return created.json() as Promise<{ id: string }>
}

test('workbench handoff, PeTar run, exports and comparison with REBOUND', async ({ page }, info) => {
  const project = await createProject(page, `Compute QA ${info.project.name} ${Date.now()}`)

  await page.locator('#question').fill('用独立测试项目核对一个圆轨道双体模板。')
  await page.getByRole('button', { name: 'N 体模拟', exact: true }).click()
  await page.getByLabel('保存计算结果的空间').selectOption(project.id)
  await page.getByRole('button', { name: '打开计算任务' }).click()
  await expect(page.getByLabel('实验描述')).toHaveValue('用独立测试项目核对一个圆轨道双体模板。')
  const sidebarTitle = page.getByRole('heading', { name: 'N 体模拟', exact: true })
  await expect(sidebarTitle).toBeVisible()
  expect(await sidebarTitle.evaluate(el => el.scrollWidth <= el.clientWidth)).toBe(true)
  const picker = page.getByRole('group', { name: '选择模拟程序' })
  const rebound = picker.getByRole('button', { name: /REBOUND/ })
  const petar = picker.getByRole('button', { name: /PeTar/ })
  await expect(rebound).toHaveAttribute('aria-pressed', 'true')
  await petar.focus()
  await page.keyboard.press('Space')
  await expect(petar).toHaveAttribute('aria-pressed', 'true')
  await page.getByRole('button', { name: /圆轨道双体模板/ }).click()
  await expect(page.getByLabel('第 1 行质量')).toHaveValue('0.5')
  await expect(petar).toHaveAttribute('aria-pressed', 'true')
  await page.getByLabel('采样点数').fill('100')
  const originalId = await saveDraft(page)
  const originalUrl = page.url()
  await page.getByRole('button', { name: '核对并运行' }).click()
  await expect(page.getByRole('dialog', { name: '确认运行实验' })).toContainText('PeTar')
  await page.keyboard.press('Escape')
  const base = `/api/v1/projects/${project.id}/compute-tasks`
  expect((await (await page.request.get(`${base}/${originalId}`)).json()).state).toBe('draft')

  await startOrbit(page)
  await page.reload()
  await expect(page.getByRole('heading', { name: '运行结果' })).toBeVisible({ timeout: 24000 })
  await expect(page.getByText(/PeTar 1\.0 · Tree \+ Hermite \+ SDAR/)).toBeVisible()
  const plot = page.locator('main .compute-result img').first()
  await expect.poll(() => plot.evaluate(el => (el as HTMLImageElement).naturalWidth)).toBeGreaterThan(0)
  if (process.env.ASTROAGENT_RECORD_DIR) await page.screenshot({ path: path.join(process.env.ASTROAGENT_RECORD_DIR, `${info.project.name}-petar-desktop.png`) })

  await page.getByRole('button', { name: '位置快照', exact: true }).click()
  await page.getByRole('slider').fill('16')
  const [archiveResponse, archive] = await Promise.all([
    page.waitForResponse(res => new URL(res.url()).pathname.endsWith('/archive'), { timeout: 12000 }),
    page.waitForEvent('download', { timeout: 15000 }),
    page.getByRole('button', { name: '下载实验 ZIP' }).click(),
  ])
  expect(archiveResponse.ok()).toBe(true)
  expect(new URL(archiveResponse.url()).searchParams.get('sample')).toBe('16')
  expect(archive.suggestedFilename()).toBe(`astroagent-experiment-${originalId}.zip`)
  expect(await archive.failure()).toBeNull()
  const [csv] = await Promise.all([
    page.waitForEvent('download', { timeout: 15000 }),
    page.getByRole('button', { name: '下载原始快照 CSV' }).click(),
  ])
  expect(csv.suggestedFilename()).toBe(`astroagent-snapshots-${originalId}.csv`)
  expect(await csv.failure()).toBeNull()

  await page.getByRole('button', { name: '复制为新草稿' }).click()
  await expect(page).not.toHaveURL(originalUrl)
  await page.getByRole('button', { name: '编辑条件' }).click()
  await expect(petar).toHaveAttribute('aria-pressed', 'true')
  await rebound.click()
  await saveDraft(page)
  await startOrbit(page)
  await expect(page.getByRole('heading', { name: '运行结果' })).toBeVisible({ timeout: 24000 })
  await expect(page.getByText(/REBOUND 4\.4\.11 · IAS15/)).toBeVisible()
  await page.getByLabel('比较同项目实验').selectOption(originalId)
  await expect(page.getByRole('img', { name: '两次运行的相对能量偏差，横轴为年' })).toBeVisible()
  await page.setViewportSize({ width: 390, height: 844 })
  await expect(page.getByRole('heading', { name: '运行结果' })).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  if (process.env.ASTROAGENT_RECORD_DIR) await page.screenshot({ path: path.join(process.env.ASTROAGENT_RECORD_DIR, `${info.project.name}-compare-mobile.png`) })
  await page.setViewportSize({ width: 1440, height: 900 })
  const space = page.getByRole('main').getByLabel('切换当前科研空间')
  await space.selectOption({ label: '个人空间（默认）' })
  await expect(page).toHaveURL(origin + '/compute')
  await expect(page.getByText('此项目还没有计算任务。')).toBeVisible()
  await space.selectOption(project.id)
  await expect(page).toHaveURL(`${origin}/projects/${project.id}/compute`)
  await expect(page.getByRole('link', { name: /圆轨道双体实验/ }).first()).toBeVisible()
})

test('presets, Kepler elements, CSV import and center-of-mass reset', async ({ page }, info) => {
  const project = await createProject(page, `Presets QA ${info.project.name} ${Date.now()}`)
  await page.goto(`/projects/${project.id}/compute`)
  await page.getByRole('button', { name: '新建草稿' }).click()
  await page.getByRole('button', { name: /层级三星系统/ }).click()
  await expect(page.getByLabel('第 3 行粒子 ID')).toHaveValue('OuterC')
  await page.getByRole('button', { name: /Plummer 模型星团/ }).click()
  await expect(page.getByLabel('第 12 行粒子 ID')).toHaveValue('S12')
  await expect(page.getByText('1.000', { exact: true })).toBeVisible()

  await page.getByText(/双体开普勒轨道根数生成器/).click()
  await page.getByLabel(/主星质量/).fill('1.4')
  await page.getByLabel(/伴星质量/).fill('0.6')
  await page.getByLabel(/半长轴 a/).fill('2')
  await page.getByLabel(/轨道倾角 i/).fill('40')
  await page.getByLabel(/初始真近点角/).fill('90')
  await page.getByRole('button', { name: '生成并填入粒子表' }).click()
  await expect(page.getByLabel('模拟时长（yr）')).toHaveValue('4')
  await expect(page.getByLabel('第 1 行粒子 ID')).toHaveValue('Star1')
  await expect(page.getByLabel('第 2 行位置 Z')).not.toHaveValue('0')

  await page.getByText(/批量导入粒子表/).click()
  const csv = page.locator('details').filter({ hasText: '批量导入粒子表' })
  const valid = 'Z9,2,1,0,0,1,0,0\nA1,1,4,0,0,4,0,0'
  await csv.locator('textarea').fill('Broken,nan,0,0,0,0,0,0\n' + valid)
  await page.getByRole('button', { name: '解析并填入粒子表' }).click()
  await expect(csv.getByRole('alert')).toContainText('第 1 行')
  await expect(page.getByLabel('第 1 行粒子 ID')).toHaveValue('Star1')
  await csv.locator('input[type=file]').setInputFiles({
    name: 'synthetic.tsv', mimeType: 'text/tab-separated-values', buffer: Buffer.from(valid.replaceAll(',', '\t')),
  })
  await expect(page.getByLabel('第 1 行粒子 ID')).toHaveValue('Z9')
  await expect(csv.getByRole('alert')).toHaveCount(0)
  await page.getByRole('button', { name: /质心系归零/ }).click()
  await expect(page.getByLabel('第 1 行位置 X')).toHaveValue('-1')
  await expect(page.getByLabel('第 2 行速度 Vx')).toHaveValue('2')
  const picker = page.getByRole('group', { name: '选择模拟程序' })
  await picker.getByRole('button', { name: /PeTar/ }).click()
  await page.setViewportSize({ width: 390, height: 844 })
  await picker.scrollIntoViewIfNeeded()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  if (process.env.ASTROAGENT_RECORD_DIR) await page.screenshot({ path: path.join(process.env.ASTROAGENT_RECORD_DIR, `${info.project.name}-picker-mobile.png`) })
  const id = await saveDraft(page)
  const task = await page.request.get(`/api/v1/projects/${project.id}/compute-tasks/${id}`)
  expect(task.status()).toBe(200)
  const params = (await task.json()).parameters
  expect(params.engine).toBe('petar')
  expect(params.particles.map((item: { id: string }) => item.id)).toEqual(['Z9', 'A1'])
})
