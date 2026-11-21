import type { ComputeParameters } from './api/compute'

export type ParticleRow = ComputeParameters['particles'][number]

export const GRAVITATIONAL_CONSTANT = 4 * Math.PI * Math.PI

export interface KeplerBinaryOptions {
  m1: number
  m2: number
  semiMajorAu: number
  eccentricity: number
  inclinationDeg: number
  ascNodeDeg: number
  argPeriapsisDeg: number
  trueAnomalyDeg: number
  orbits: number
}

function round6(value: number) {
  return Math.abs(value) < 1e-12 ? 0 : Number(value.toPrecision(8))
}

export function keplerianBinary(options: KeplerBinaryOptions): {
  particles: ParticleRow[]
  periodYr: number
  durationYr: number
} {
  const m1 = Math.max(1e-9, options.m1)
  const m2 = Math.max(1e-9, options.m2)
  const a = Math.max(1e-4, options.semiMajorAu)
  const e = Math.min(0.98, Math.max(0, options.eccentricity))
  const inc = (options.inclinationDeg * Math.PI) / 180
  const omegaBig = (options.ascNodeDeg * Math.PI) / 180
  const omegaSmall = (options.argPeriapsisDeg * Math.PI) / 180
  const nu = (options.trueAnomalyDeg * Math.PI) / 180

  const totalMass = m1 + m2
  const mu = GRAVITATIONAL_CONSTANT * totalMass
  const p = a * (1 - e * e)
  const r = p / (1 + e * Math.cos(nu))
  const vScale = Math.sqrt(mu / p)

  const xOrb = r * Math.cos(nu)
  const yOrb = r * Math.sin(nu)
  const vxOrb = -vScale * Math.sin(nu)
  const vyOrb = vScale * (e + Math.cos(nu))

  const cO = Math.cos(omegaBig), sO = Math.sin(omegaBig)
  const co = Math.cos(omegaSmall), so = Math.sin(omegaSmall)
  const ci = Math.cos(inc), si = Math.sin(inc)

  const px = cO * co - sO * so * ci
  const py = sO * co + cO * so * ci
  const pz = so * si
  const qx = -cO * so - sO * co * ci
  const qy = -sO * so + cO * co * ci
  const qz = co * si

  const rx = px * xOrb + qx * yOrb
  const ry = py * xOrb + qy * yOrb
  const rz = pz * xOrb + qz * yOrb
  const vx = px * vxOrb + qx * vyOrb
  const vy = py * vxOrb + qy * vyOrb
  const vz = pz * vxOrb + qz * vyOrb

  const f1 = -m2 / totalMass
  const f2 = m1 / totalMass
  const periodYr = Math.sqrt((a * a * a) / totalMass)
  const durationYr = Math.min(10000, Math.max(1e-4, Number((periodYr * Math.max(0.1, options.orbits)).toPrecision(6))))

  return {
    periodYr,
    durationYr,
    particles: [
      { id: 'Star1', mass: round6(m1), position: [round6(f1 * rx), round6(f1 * ry), round6(f1 * rz)], velocity: [round6(f1 * vx), round6(f1 * vy), round6(f1 * vz)] },
      { id: 'Star2', mass: round6(m2), position: [round6(f2 * rx), round6(f2 * ry), round6(f2 * rz)], velocity: [round6(f2 * vx), round6(f2 * vy), round6(f2 * vz)] },
    ],
  }
}

export function hierarchicalTriple(): { particles: ParticleRow[]; durationYr: number } {
  const inner = keplerianBinary({
    m1: 1.0,
    m2: 0.8,
    semiMajorAu: 1.0,
    eccentricity: 0.15,
    inclinationDeg: 0,
    ascNodeDeg: 0,
    argPeriapsisDeg: 0,
    trueAnomalyDeg: 0,
    orbits: 1,
  })
  const mInner = 1.8
  const mOuter = 0.5
  const aOut = 8.0
  const vRel = Math.sqrt((GRAVITATIONAL_CONSTANT * (mInner + mOuter)) / aOut)
  const fIn = -mOuter / (mInner + mOuter)
  const fOut = mInner / (mInner + mOuter)
  const particles: ParticleRow[] = [
    {
      id: 'InnerA',
      mass: inner.particles[0]!.mass,
      position: [round6(inner.particles[0]!.position[0]! + fIn * aOut), round6(inner.particles[0]!.position[1]!), round6(inner.particles[0]!.position[2]!)],
      velocity: [round6(inner.particles[0]!.velocity[0]!), round6(inner.particles[0]!.velocity[1]! + fIn * vRel), round6(inner.particles[0]!.velocity[2]!)],
    },
    {
      id: 'InnerB',
      mass: inner.particles[1]!.mass,
      position: [round6(inner.particles[1]!.position[0]! + fIn * aOut), round6(inner.particles[1]!.position[1]!), round6(inner.particles[1]!.position[2]!)],
      velocity: [round6(inner.particles[1]!.velocity[0]!), round6(inner.particles[1]!.velocity[1]! + fIn * vRel), round6(inner.particles[1]!.velocity[2]!)],
    },
    {
      id: 'OuterC',
      mass: mOuter,
      position: [round6(fOut * aOut), 0, 0],
      velocity: [0, round6(fOut * vRel), 0],
    },
  ]
  return { particles: centerOfMassReset(particles), durationYr: 12 }
}

function mulberry32(seed: number) {
  let state = seed >>> 0
  return () => {
    state = (state + 0x6d2b79f5) >>> 0
    let t = Math.imul(state ^ (state >>> 15), 1 | state)
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

export function plummerCluster(count = 12, totalMass = 12, scaleRadiusAu = 50, seed = 45): {
  particles: ParticleRow[]
  durationYr: number
} {
  const n = Math.min(32, Math.max(4, Math.round(count)))
  const rand = mulberry32(seed)
  const m = totalMass / n
  const rows: ParticleRow[] = []

  for (let index = 0; index < n; index++) {
    const u = Math.min(0.95, Math.max(0.05, rand()))
    const radius = scaleRadiusAu / Math.sqrt(Math.pow(u, -2 / 3) - 1)
    const cosTheta = 2 * rand() - 1
    const sinTheta = Math.sqrt(Math.max(0, 1 - cosTheta * cosTheta))
    const phi = 2 * Math.PI * rand()

    const x = radius * sinTheta * Math.cos(phi)
    const y = radius * sinTheta * Math.sin(phi)
    const z = radius * cosTheta

    const vEsc = Math.sqrt((2 * GRAVITATIONAL_CONSTANT * totalMass) / Math.sqrt(radius * radius + scaleRadiusAu * scaleRadiusAu))
    let q = 0.35
    for (let attempt = 0; attempt < 24; attempt++) {
      const candidate = rand()
      const accept = rand() * 0.1
      if (accept < candidate * candidate * Math.pow(1 - candidate * candidate, 3.5)) {
        q = candidate
        break
      }
    }
    const speed = q * vEsc
    const vCos = 2 * rand() - 1
    const vSin = Math.sqrt(Math.max(0, 1 - vCos * vCos))
    const vPhi = 2 * Math.PI * rand()

    rows.push({
      id: `S${index + 1}`,
      mass: round6(m),
      position: [round6(x), round6(y), round6(z)],
      velocity: [round6(speed * vSin * Math.cos(vPhi)), round6(speed * vSin * Math.sin(vPhi)), round6(speed * vCos)],
    })
  }

  const centered = centerOfMassReset(rows)
  const diag = systemDiagnostics(centered)
  if (diag.kinetic > 0 && diag.potential < 0) {
    const scale = Math.sqrt((0.5 * Math.abs(diag.potential)) / diag.kinetic)
    for (const row of centered) {
      row.velocity = [round6(row.velocity[0]! * scale), round6(row.velocity[1]! * scale), round6(row.velocity[2]! * scale)]
    }
  }
  const crossingYr = Math.sqrt((scaleRadiusAu ** 3) / (GRAVITATIONAL_CONSTANT * totalMass)) * 2 * Math.PI
  return { particles: centered, durationYr: Math.min(1000, Math.max(1, Number((crossingYr * 2).toPrecision(4)))) }
}

export function centerOfMassReset(particles: ParticleRow[]): ParticleRow[] {
  const totalMass = particles.reduce((sum, item) => sum + (Number(item.mass) || 0), 0)
  if (totalMass <= 0) return particles.map(item => ({ ...item, position: [...item.position], velocity: [...item.velocity] }))
  const rcm = [0, 0, 0]
  const vcm = [0, 0, 0]
  for (const item of particles) {
    const m = Number(item.mass) || 0
    for (let axis = 0; axis < 3; axis++) {
      rcm[axis]! += m * (Number(item.position[axis]) || 0)
      vcm[axis]! += m * (Number(item.velocity[axis]) || 0)
    }
  }
  for (let axis = 0; axis < 3; axis++) {
    rcm[axis]! /= totalMass
    vcm[axis]! /= totalMass
  }
  return particles.map(item => ({
    ...item,
    position: [
      round6((Number(item.position[0]) || 0) - rcm[0]!),
      round6((Number(item.position[1]) || 0) - rcm[1]!),
      round6((Number(item.position[2]) || 0) - rcm[2]!),
    ],
    velocity: [
      round6((Number(item.velocity[0]) || 0) - vcm[0]!),
      round6((Number(item.velocity[1]) || 0) - vcm[1]!),
      round6((Number(item.velocity[2]) || 0) - vcm[2]!),
    ],
  }))
}

export function systemDiagnostics(particles: ParticleRow[]) {
  let totalMass = 0
  const rcm = [0, 0, 0]
  const vcm = [0, 0, 0]
  let kinetic = 0
  let potential = 0

  for (const item of particles) {
    const m = Number(item.mass) || 0
    totalMass += m
    const vx = Number(item.velocity[0]) || 0
    const vy = Number(item.velocity[1]) || 0
    const vz = Number(item.velocity[2]) || 0
    kinetic += 0.5 * m * (vx * vx + vy * vy + vz * vz)
    for (let axis = 0; axis < 3; axis++) {
      rcm[axis]! += m * (Number(item.position[axis]) || 0)
      vcm[axis]! += m * (Number(item.velocity[axis]) || 0)
    }
  }
  for (let i = 0; i < particles.length; i++) {
    for (let j = i + 1; j < particles.length; j++) {
      const a = particles[i]!, b = particles[j]!
      const dx = (Number(a.position[0]) || 0) - (Number(b.position[0]) || 0)
      const dy = (Number(a.position[1]) || 0) - (Number(b.position[1]) || 0)
      const dz = (Number(a.position[2]) || 0) - (Number(b.position[2]) || 0)
      const dist = Math.hypot(dx, dy, dz)
      if (dist > 1e-12) {
        potential -= (GRAVITATIONAL_CONSTANT * (Number(a.mass) || 0) * (Number(b.mass) || 0)) / dist
      }
    }
  }
  const comPos = totalMass > 0 ? Math.hypot(rcm[0]! / totalMass, rcm[1]! / totalMass, rcm[2]! / totalMass) : 0
  const comSpeed = totalMass > 0 ? Math.hypot(vcm[0]! / totalMass, vcm[1]! / totalMass, vcm[2]! / totalMass) : 0
  const virialRatio = potential < 0 ? (2 * kinetic) / Math.abs(potential) : null

  return {
    totalMass,
    comPos,
    comSpeed,
    kinetic,
    potential,
    totalEnergy: kinetic + potential,
    virialRatio,
  }
}

export function parseParticlesCsv(text: string): ParticleRow[] {
  const lines = text.split(/\r\n|\n|\r/)
  const rows: ParticleRow[] = []
  const seen = new Set<string>()
  let first = true
  for (const [index, rawLine] of lines.entries()) {
    const line = rawLine.trim()
    if (!line || line.startsWith('#')) continue
    const parts = line.split(/[\t,;]/).map(part => part.trim())
    const header = first && parts.join(',').toLowerCase() === 'id,mass,x,y,z,vx,vy,vz'
    first = false
    if (header) continue
    if (parts.length !== 8) {
      throw new Error(`第 ${index + 1} 行需要 8 列：id,mass,x,y,z,vx,vy,vz`)
    }
    const id = parts[0]!
    if (!/^[A-Za-z0-9][A-Za-z0-9_-]{0,31}$/.test(id)) {
      throw new Error(`第 ${index + 1} 行的粒子 ID 无效。请使用 1–32 位字母、数字、下划线或连字符，并以字母或数字开头。`)
    }
    const values = parts.slice(1)
    const nums = values.map(Number)
    if (values.some(value => !value) || nums.some(value => !Number.isFinite(value))) {
      throw new Error(`第 ${index + 1} 行包含空字段或非数值字段。`)
    }
    if (seen.has(id)) throw new Error(`粒子 ID 重复：${id}`)
    if (nums[0]! <= 0) throw new Error(`粒子 ${id} 的质量必须大于 0。`)
    seen.add(id)
    rows.push({
      id,
      mass: nums[0]!,
      position: [nums[1]!, nums[2]!, nums[3]!],
      velocity: [nums[4]!, nums[5]!, nums[6]!],
    })
    if (rows.length > 128) throw new Error('最多导入 128 个粒子。')
  }
  if (rows.length < 2) throw new Error('至少需要 2 行有效粒子数据（格式：id,mass,x,y,z,vx,vy,vz）。')
  return rows
}
