import { expect, test, type Page } from '@playwright/test'
import path from 'node:path'
import { chooseUiOption } from '../browser/ui-select'

const origin = 'http://127.0.0.1:5287'

type CsrfHeaders = {
  Origin: string
  'X-CSRF-Token': string
}

type ComputeTaskResponse = {
  id: string
  name: string
  revision: number
  state: string
  parameter_sha256: string
  parameters: {
    engine: 'rebound' | 'petar'
    duration: number
    samples: number
    particles: Array<{
      id: string
      mass: number
      position: [number, number, number]
      velocity: [number, number, number]
    }>
  }
}

async function loginAndCreateProject(page: Page, name: string) {
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
  const csrf = (await (await page.request.get('/api/v1/auth/csrf')).json()).csrf_token as string
  const headers: CsrfHeaders = { Origin: origin, 'X-CSRF-Token': csrf }
  const created = await page.request.post('/api/v1/projects', {
    data: { name },
    headers,
  })
  expect(created.status()).toBe(201)
  const project = await created.json() as { id: string }
  return { project, headers }
}

async function createExtraProject(page: Page, name: string, headers: CsrfHeaders) {
  const created = await page.request.post('/api/v1/projects', {
    data: { name },
    headers,
  })
  expect(created.status()).toBe(201)
  return created.json() as Promise<{ id: string }>
}

async function createComputeDraft(
  page: Page,
  projectId: string,
  headers: CsrfHeaders,
  body: {
    name: string
    source: 'manual' | 'template' | 'conversation'
    parameters: ComputeTaskResponse['parameters']
  },
) {
  const res = await page.request.post(`/api/v1/projects/${projectId}/compute-tasks`, {
    data: body,
    headers,
  })
  expect(res.status()).toBe(201)
  return res.json() as Promise<ComputeTaskResponse>
}

test('workbench handoff, PeTar run, exports and comparison with REBOUND', async ({ page }, info) => {
  const projectName = `Compute QA ${info.project.name} ${Date.now()}`
  const { project, headers } = await loginAndCreateProject(page, projectName)
  const emptyProject = await createExtraProject(page, `Compute Empty ${info.project.name} ${Date.now()}`, headers)

  // Verify current v2.2 workbench handoff entry (?tool=compute&project=...) activates N-body mode & project context.
  await page.goto(`/?tool=compute&project=${project.id}`)
  const question = page.locator('#question')
  await expect(question).toHaveAttribute('placeholder', /描述 N 体模拟需求/)
  await question.fill('用独立测试项目核对一个圆轨道双体模板。')
  await expect(page.locator('.chat-project-pill-name')).toHaveText(projectName)

  const base = `/api/v1/projects/${project.id}/compute-tasks`
  const templateRes = await page.request.get(`${base}/templates/binary`)
  expect(templateRes.status()).toBe(200)
  const binaryParams = await templateRes.json() as ComputeTaskResponse['parameters']
  expect(binaryParams.particles[0]?.mass).toBe(0.5)

  const petarDraft = await createComputeDraft(page, project.id, headers, {
    name: '圆轨道双体实验（PeTar）',
    source: 'template',
    parameters: {
      ...binaryParams,
      engine: 'petar',
      samples: 100,
    },
  })

  // Legacy /projects/:projectId/compute/:taskId redirects into the workbench result panel.
  await page.goto(`/projects/${project.id}/compute/${petarDraft.id}`)
  const panel = page.locator('#workbench-results')
  const panelTitle = panel.getByRole('heading', { name: '空间 N 体模拟记录', exact: true })
  await expect(panelTitle).toBeVisible()
  expect(await panelTitle.evaluate(el => el.scrollWidth <= el.clientWidth)).toBe(true)
  await expect(panel.getByText('待确认', { exact: true })).toBeVisible()
  await expect(panel.getByRole('button', { name: '确认运行', exact: true })).toBeVisible()
  expect((await (await page.request.get(`${base}/${petarDraft.id}`)).json()).state).toBe('draft')

  await panel.getByRole('button', { name: '确认运行', exact: true }).click()
  await page.goto(`/projects/${project.id}/compute/${petarDraft.id}`)
  await expect(panel.getByText(/PeTar 1\.0 · Tree \+ Hermite \+ SDAR/)).toBeVisible({ timeout: 24000 })
  await expect(panel.getByText('已完成', { exact: true })).toBeVisible()
  const plot = panel.locator('.compute-plot-frame img').first()
  await expect.poll(() => plot.evaluate(el => (el as HTMLImageElement).naturalWidth)).toBeGreaterThan(0)
  if (process.env.ASTROAGENT_RECORD_DIR) {
    await page.screenshot({ path: path.join(process.env.ASTROAGENT_RECORD_DIR, `${info.project.name}-petar-desktop.png`) })
  }

  await panel.getByRole('button', { name: '位置快照', exact: true }).click()
  await panel.getByRole('slider').fill('16')
  const [archiveResponse, archive] = await Promise.all([
    page.waitForResponse(res => new URL(res.url()).pathname.endsWith('/archive'), { timeout: 12000 }),
    page.waitForEvent('download', { timeout: 15000 }),
    panel.getByRole('button', { name: '导出 ZIP', exact: true }).click(),
  ])
  expect(archiveResponse.ok()).toBe(true)
  expect(new URL(archiveResponse.url()).searchParams.get('sample')).toBe('16')
  expect(archive.suggestedFilename()).toBe(`astroagent-experiment-${petarDraft.id}.zip`)
  expect(await archive.failure()).toBeNull()

  const [csv] = await Promise.all([
    page.waitForEvent('download', { timeout: 15000 }),
    panel.getByRole('button', { name: '快照 CSV', exact: true }).click(),
  ])
  expect(csv.suggestedFilename()).toBe(`astroagent-snapshots-${petarDraft.id}.csv`)
  expect(await csv.failure()).toBeNull()

  // Duplicate into a new draft, switch engine to REBOUND, confirm and compare against PeTar.
  const [copyResponse] = await Promise.all([
    page.waitForResponse(res => new URL(res.url()).pathname.endsWith('/copy') && res.request().method() === 'POST', { timeout: 12000 }),
    panel.getByRole('button', { name: '复制', exact: true }).click(),
  ])
  expect(copyResponse.status()).toBe(201)
  const copied = await copyResponse.json() as ComputeTaskResponse
  await expect(panel.getByRole('button', { name: '确认运行', exact: true })).toBeVisible()

  const patched = await page.request.patch(`${base}/${copied.id}`, {
    headers,
    data: {
      expected_revision: copied.revision,
      name: '圆轨道双体实验（REBOUND）',
      source: 'template',
      parameters: {
        ...copied.parameters,
        engine: 'rebound',
      },
    },
  })
  expect(patched.status()).toBe(200)

  await page.goto(`/projects/${project.id}/compute/${copied.id}`)
  await expect(panel.getByRole('button', { name: '确认运行', exact: true })).toBeVisible()
  await panel.getByRole('button', { name: '确认运行', exact: true }).click()
  await expect(panel.getByText(/REBOUND 4\.4\.11 · IAS15/)).toBeVisible({ timeout: 24000 })

  await panel.getByRole('tab', { name: '实验对比', exact: true }).click()
  await chooseUiOption(page, panel.getByRole('button', { name: '选择同空间已完成实验进行对比' }), { index: 1 })
  await expect(panel.getByLabel('相对能量偏差对比曲线')).toBeVisible()

  await panel.getByRole('tab', { name: '数据表与文件', exact: true }).click()
  await expect(panel.getByText('parameters.json')).toBeVisible()

  await page.setViewportSize({ width: 390, height: 844 })
  await expect(panel).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  if (process.env.ASTROAGENT_RECORD_DIR) {
    await page.screenshot({ path: path.join(process.env.ASTROAGENT_RECORD_DIR, `${info.project.name}-compare-mobile.png`) })
  }

  await page.setViewportSize({ width: 1440, height: 900 })
  await page.goto(`/projects/${emptyProject.id}/compute`)
  await expect(panel.getByText('当前空间尚无 N 体模拟记录')).toBeVisible()

  await page.goto(`/projects/${project.id}/compute`)
  const taskSwitcher = panel.getByRole('button', { name: '切换本次对话 N 体模拟记录' })
  await expect(taskSwitcher).toBeVisible()
  await chooseUiOption(page, taskSwitcher, /PeTar/)
  await expect(panel.getByText(/PeTar 1\.0 · Tree \+ Hermite \+ SDAR/)).toBeVisible()
})

test('multi-body PeTar draft, parameter disclosure and two-step delete lifecycle', async ({ page }, info) => {
  const { project, headers } = await loginAndCreateProject(page, `Presets QA ${info.project.name} ${Date.now()}`)
  const draft = await createComputeDraft(page, project.id, headers, {
    name: '合成质心系双体草稿',
    source: 'manual',
    parameters: {
      engine: 'petar',
      duration: 2,
      samples: 65,
      particles: [
        { id: 'Z9', mass: 2, position: [-1, 0, 0], velocity: [0, -1, 0] },
        { id: 'A1', mass: 1, position: [2, 0, 0], velocity: [0, 2, 0] },
      ],
    },
  })

  await page.goto(`/projects/${project.id}/compute/${draft.id}`)
  const panel = page.locator('#workbench-results')
  await expect(panel.getByText('合成质心系双体草稿')).toBeVisible()
  await panel.getByText(/初始条件与执行时间线/).click()
  await expect(panel.locator('.compute-json')).toContainText('"engine": "petar"')
  await expect(panel.locator('.compute-json')).toContainText('"id": "Z9"')
  await expect(panel.locator('.compute-json')).toContainText('"id": "A1"')
  await expect(panel.locator('.compute-sha')).toContainText(draft.parameter_sha256)

  await page.setViewportSize({ width: 390, height: 844 })
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  if (process.env.ASTROAGENT_RECORD_DIR) {
    await page.screenshot({ path: path.join(process.env.ASTROAGENT_RECORD_DIR, `${info.project.name}-picker-mobile.png`) })
  }

  await page.setViewportSize({ width: 1440, height: 900 })
  await panel.getByRole('button', { name: '移除', exact: true }).click()
  await panel.getByRole('button', { name: '确认移除', exact: true }).click()
  await expect(panel.getByText('当前空间尚无 N 体模拟记录')).toBeVisible()
  const removed = await page.request.get(`/api/v1/projects/${project.id}/compute-tasks/${draft.id}`)
  expect(removed.status()).toBe(404)
})
