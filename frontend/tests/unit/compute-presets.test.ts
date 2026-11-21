import { describe, expect, it } from 'vitest'
import {
  centerOfMassReset,
  GRAVITATIONAL_CONSTANT,
  hierarchicalTriple,
  keplerianBinary,
  parseParticlesCsv,
  plummerCluster,
  systemDiagnostics,
} from '../../src/compute-presets'

describe('N-body initial conditions', () => {
  it('converts an inclined eccentric binary to centered Cartesian coordinates', () => {
    const binary = keplerianBinary({
      m1: 1.4, m2: 0.6, semiMajorAu: 2, eccentricity: 0.3, inclinationDeg: 40,
      ascNodeDeg: 60, argPeriapsisDeg: 0, trueAnomalyDeg: 90, orbits: 2,
    })
    expect(binary.periodYr).toBe(2)
    expect(binary.durationYr).toBe(4)
    const [a, b] = binary.particles
    expect(a).toBeDefined()
    expect(b).toBeDefined()
    const relative = (x: number[], y: number[]) => x.map((value, index) => value - y[index]!)
    const radius = Math.hypot(...relative(b!.position, a!.position))
    const speed = Math.hypot(...relative(b!.velocity, a!.velocity))
    expect(radius).toBeCloseTo(1.82, 7)
    expect(speed ** 2).toBeCloseTo(GRAVITATIONAL_CONSTANT * 2 * (2 / radius - 0.5), 4)
    expect(b!.position[2]).toBeGreaterThan(0)
    const state = systemDiagnostics(binary.particles)
    expect(state.comPos).toBeLessThan(1e-7)
    expect(state.comSpeed).toBeLessThan(1e-7)
    expect(state.totalEnergy).toBeLessThan(0)
  })

  it('builds a centered triple and a repeatable virialized 12-body cluster', () => {
    const triple = hierarchicalTriple()
    expect(triple.particles.map(particle => particle.id)).toEqual(['InnerA', 'InnerB', 'OuterC'])
    expect(systemDiagnostics(triple.particles).comSpeed).toBeLessThan(1e-6)
    const cluster = plummerCluster()
    expect(cluster).toEqual(plummerCluster())
    expect(cluster.particles).toHaveLength(12)
    const state = systemDiagnostics(cluster.particles)
    expect(state.totalMass).toBe(12)
    expect(state.virialRatio).toBeCloseTo(1, 6)
    expect(state.totalEnergy).toBeLessThan(0)
  })

  it('removes only bulk position and velocity when resetting the center of mass', () => {
    const original = parseParticlesCsv('Z9,2,1,0,0,1,0,0\nA1,1,4,0,0,4,0,0')
    const centered = centerOfMassReset(original)
    expect(centered.map(row => row.id)).toEqual(['Z9', 'A1'])
    expect(centered.map(row => row.position[0])).toEqual([-1, 2])
    expect(centered.map(row => row.velocity[0])).toEqual([-1, 2])
    expect(systemDiagnostics(centered).comSpeed).toBe(0)
    expect(original[0]?.position[0]).toBe(1)
  })
})

describe('particle table import', () => {
  const rows = 'Z9,1,-0.5,0,0,0,-3.1416,0\nA1,0.5,0.5,0,0,0,3.1416,0'

  it('preserves particle IDs and numeric data in CSV and TSV', () => {
    const csv = parseParticlesCsv('# synthetic sample\nid,mass,x,y,z,vx,vy,vz\n' + rows)
    const tsv = parseParticlesCsv(rows.replaceAll(',', '\t'))
    expect(csv).toEqual(tsv)
    expect(csv.map(row => row.id)).toEqual(['Z9', 'A1'])
    expect(csv[1]?.velocity).toEqual([0, 3.1416, 0])
  })

  it('rejects a malformed first data row instead of importing a partial particle set', () => {
    expect(() => parseParticlesCsv('Broken,nan,0,0,0,0,0,0\n' + rows)).toThrow(/第 1 行/)
  })

  it('rejects changed identities and misaligned columns', () => {
    expect(() => parseParticlesCsv('A B,1,-0.5,0,0,0,-3,0\n' + rows)).toThrow(/粒子 ID/)
    expect(() => parseParticlesCsv('Extra,1,0,0,0,0,0,0,0\n' + rows)).toThrow(/8 列/)
    expect(() => parseParticlesCsv('Empty,1,2,,0,0,0,0\n' + rows)).toThrow(/第 1 行/)
  })

  it('rejects duplicate IDs, zero masses, and particle counts above 128', () => {
    expect(() => parseParticlesCsv(rows + '\nZ9,1,3,0,0,0,0,0')).toThrow(/重复/)
    expect(() => parseParticlesCsv(rows + '\nP0,0,3,0,0,0,0,0')).toThrow(/质量/)
    const many = Array.from({ length: 129 }, (_, i) => `p${i},1,${i},0,0,0,0,0`).join('\n')
    expect(() => parseParticlesCsv(many)).toThrow(/最多导入 128/)
  })
})
