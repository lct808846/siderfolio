/**
 * Zero-dependency ISO/IEC 18004 QR Code encoder & SVG generator (Byte mode, EC Level M).
 * Designed for crisp vector rendering of TOTP `otpauth://` URIs in Siderfolio.
 */

interface VersionSpec {
  totalData: number
  ecPerBlock: number
  g1Blocks: number
  g1Data: number
  g2Blocks: number
  g2Data: number
  align: number[]
}

// ISO/IEC 18004 Table 9 & Annex E (Error Correction Level M, Versions 1..14)
const VERSION_SPECS_M: readonly VersionSpec[] = [
  { totalData: 16, ecPerBlock: 10, g1Blocks: 1, g1Data: 16, g2Blocks: 0, g2Data: 0, align: [] },
  { totalData: 28, ecPerBlock: 16, g1Blocks: 1, g1Data: 28, g2Blocks: 0, g2Data: 0, align: [6, 18] },
  { totalData: 44, ecPerBlock: 26, g1Blocks: 1, g1Data: 44, g2Blocks: 0, g2Data: 0, align: [6, 22] },
  { totalData: 64, ecPerBlock: 18, g1Blocks: 2, g1Data: 32, g2Blocks: 0, g2Data: 0, align: [6, 26] },
  { totalData: 86, ecPerBlock: 24, g1Blocks: 2, g1Data: 43, g2Blocks: 0, g2Data: 0, align: [6, 30] },
  { totalData: 108, ecPerBlock: 16, g1Blocks: 4, g1Data: 27, g2Blocks: 0, g2Data: 0, align: [6, 34] },
  { totalData: 124, ecPerBlock: 18, g1Blocks: 4, g1Data: 31, g2Blocks: 0, g2Data: 0, align: [6, 22, 38] },
  { totalData: 154, ecPerBlock: 22, g1Blocks: 2, g1Data: 38, g2Blocks: 2, g2Data: 39, align: [6, 24, 42] },
  { totalData: 182, ecPerBlock: 22, g1Blocks: 3, g1Data: 36, g2Blocks: 2, g2Data: 37, align: [6, 26, 46] },
  { totalData: 216, ecPerBlock: 26, g1Blocks: 4, g1Data: 43, g2Blocks: 1, g2Data: 44, align: [6, 28, 50] },
  { totalData: 254, ecPerBlock: 30, g1Blocks: 1, g1Data: 50, g2Blocks: 4, g2Data: 51, align: [6, 30, 54] },
  { totalData: 290, ecPerBlock: 22, g1Blocks: 6, g1Data: 36, g2Blocks: 2, g2Data: 37, align: [6, 32, 58] },
  { totalData: 334, ecPerBlock: 22, g1Blocks: 8, g1Data: 37, g2Blocks: 1, g2Data: 38, align: [6, 34, 62] },
  { totalData: 365, ecPerBlock: 24, g1Blocks: 4, g1Data: 40, g2Blocks: 5, g2Data: 41, align: [6, 26, 46, 66] },
]

const GF_EXP = new Uint8Array(512)
const GF_LOG = new Uint8Array(256)
;(() => {
  let x = 1
  for (let i = 0; i < 255; i++) {
    GF_EXP[i] = x
    GF_LOG[x] = i
    x = (x << 1) ^ (x & 0x80 ? 0x11d : 0)
  }
  for (let i = 255; i < 512; i++) GF_EXP[i] = GF_EXP[i - 255]
})()

function gfMul(a: number, b: number): number {
  return a === 0 || b === 0 ? 0 : GF_EXP[GF_LOG[a] + GF_LOG[b]]
}

function rsGeneratorPoly(degree: number): Uint8Array {
  let poly = new Uint8Array([1])
  for (let i = 0; i < degree; i++) {
    const next = new Uint8Array(poly.length + 1)
    const root = GF_EXP[i]
    for (let j = 0; j < poly.length; j++) {
      next[j] ^= poly[j]
      next[j + 1] ^= gfMul(poly[j], root)
    }
    poly = next
  }
  return poly
}

function rsComputeRemainder(data: Uint8Array, degree: number): Uint8Array {
  const gen = rsGeneratorPoly(degree)
  const rem = new Uint8Array(degree)
  for (let i = 0; i < data.length; i++) {
    const factor = data[i] ^ rem[0]
    rem.copyWithin(0, 1)
    rem[degree - 1] = 0
    if (factor !== 0) {
      for (let j = 0; j < degree; j++) {
        rem[j] ^= gfMul(gen[j + 1], factor)
      }
    }
  }
  return rem
}

function shouldMask(mask: number, r: number, c: number): boolean {
  switch (mask) {
    case 0: return (r + c) % 2 === 0
    case 1: return r % 2 === 0
    case 2: return c % 3 === 0
    case 3: return (r + c) % 3 === 0
    case 4: return (Math.floor(r / 2) + Math.floor(c / 3)) % 2 === 0
    case 5: return ((r * c) % 2) + ((r * c) % 3) === 0
    case 6: return (((r * c) % 2) + ((r * c) % 3)) % 2 === 0
    default: return (((r + c) % 2) + ((r * c) % 3)) % 2 === 0
  }
}

function writeFormatBits(modules: Uint8Array[], isFunc: boolean[][], size: number, mask: number) {
  // EC Level M indicator is 0b00
  const data = (0b00 << 3) | mask
  let rem = data
  for (let i = 0; i < 10; i++) rem = (rem << 1) ^ ((rem >> 9) * 0x537)
  const bits = ((data << 10) | rem) ^ 0x5412

  for (let i = 0; i <= 5; i++) { modules[i][8] = (bits >> i) & 1; isFunc[i][8] = true }
  modules[7][8] = (bits >> 6) & 1; isFunc[7][8] = true
  modules[8][8] = (bits >> 7) & 1; isFunc[8][8] = true
  modules[8][7] = (bits >> 8) & 1; isFunc[8][7] = true
  for (let i = 9; i < 15; i++) { modules[8][14 - i] = (bits >> i) & 1; isFunc[8][14 - i] = true }

  for (let i = 0; i < 8; i++) { modules[8][size - 1 - i] = (bits >> i) & 1; isFunc[8][size - 1 - i] = true }
  for (let i = 8; i < 15; i++) { modules[size - 15 + i][8] = (bits >> i) & 1; isFunc[size - 15 + i][8] = true }
  modules[size - 8][8] = 1
  isFunc[size - 8][8] = true
}

function writeVersionBits(modules: Uint8Array[], isFunc: boolean[][], size: number, version: number) {
  if (version < 7) return
  let rem = version
  for (let i = 0; i < 12; i++) rem = (rem << 1) ^ ((rem >> 11) * 0x1f25)
  const bits = (version << 12) | rem
  for (let i = 0; i < 18; i++) {
    const bit = (bits >> i) & 1
    const a = Math.floor(i / 3)
    const b = i % 3
    modules[size - 11 + b][a] = bit
    isFunc[size - 11 + b][a] = true
    modules[a][size - 11 + b] = bit
    isFunc[a][size - 11 + b] = true
  }
}

function computePenalty(modules: Uint8Array[], size: number): number {
  let penalty = 0

  // Rule 1: 5+ consecutive modules of same color in row/col
  for (let r = 0; r < size; r++) {
    let runColor = modules[r][0]
    let runLen = 1
    for (let c = 1; c < size; c++) {
      if (modules[r][c] === runColor) {
        runLen++
        if (runLen === 5) penalty += 3
        else if (runLen > 5) penalty += 1
      } else {
        runColor = modules[r][c]
        runLen = 1
      }
    }
  }
  for (let c = 0; c < size; c++) {
    let runColor = modules[0][c]
    let runLen = 1
    for (let r = 1; r < size; r++) {
      if (modules[r][c] === runColor) {
        runLen++
        if (runLen === 5) penalty += 3
        else if (runLen > 5) penalty += 1
      } else {
        runColor = modules[r][c]
        runLen = 1
      }
    }
  }

  // Rule 2: 2x2 blocks of same color
  for (let r = 0; r < size - 1; r++) {
    for (let c = 0; c < size - 1; c++) {
      const val = modules[r][c]
      if (val === modules[r][c + 1] && val === modules[r + 1][c] && val === modules[r + 1][c + 1]) {
        penalty += 3
      }
    }
  }

  // Rule 3: Finder-like 1:1:3:1:1 patterns with 4 light modules on either side
  const matchFinderLike = (line: Uint8Array, i: number) => {
    if (
      line[i] === 1 &&
      line[i + 1] === 0 &&
      line[i + 2] === 1 &&
      line[i + 3] === 1 &&
      line[i + 4] === 1 &&
      line[i + 5] === 0 &&
      line[i + 6] === 1
    ) {
      const leftWhite = i >= 4 && line[i - 1] === 0 && line[i - 2] === 0 && line[i - 3] === 0 && line[i - 4] === 0
      const rightWhite =
        i + 10 < size && line[i + 7] === 0 && line[i + 8] === 0 && line[i + 9] === 0 && line[i + 10] === 0
      return leftWhite || rightWhite
    }
    return false
  }
  const colLine = new Uint8Array(size)
  for (let r = 0; r < size; r++) {
    for (let i = 0; i <= size - 7; i++) {
      if (matchFinderLike(modules[r], i)) penalty += 40
    }
  }
  for (let c = 0; c < size; c++) {
    for (let r = 0; r < size; r++) colLine[r] = modules[r][c]
    for (let i = 0; i <= size - 7; i++) {
      if (matchFinderLike(colLine, i)) penalty += 40
    }
  }

  // Rule 4: Balance of dark and light modules
  let dark = 0
  for (let r = 0; r < size; r++) {
    for (let c = 0; c < size; c++) dark += modules[r][c]
  }
  const total = size * size
  const k = Math.ceil(Math.abs(dark * 20 - total * 10) / total) - 1
  if (k > 0) penalty += k * 10

  return penalty
}

export interface QrCodeSvgResult {
  version: number
  size: number
  viewBoxSize: number
  margin: number
  path: string
  modules: Uint8Array[]
}

export function encodeQrCode(text: string, margin = 4): QrCodeSvgResult {
  const payload = new TextEncoder().encode(text)

  let version = 1
  let spec = VERSION_SPECS_M[0]
  for (let v = 1; v <= VERSION_SPECS_M.length; v++) {
    const candidate = VERSION_SPECS_M[v - 1]
    const countBits = v <= 9 ? 8 : 16
    const maxBytes = Math.floor((candidate.totalData * 8 - 4 - countBits) / 8)
    if (payload.length <= maxBytes) {
      version = v
      spec = candidate
      break
    }
    if (v === VERSION_SPECS_M.length) {
      throw new Error('QR payload exceeds supported capacity')
    }
  }

  // Build bit buffer
  const totalDataBits = spec.totalData * 8
  const bits: number[] = []
  const pushBits = (val: number, len: number) => {
    for (let i = len - 1; i >= 0; i--) bits.push((val >>> i) & 1)
  }

  // Byte mode indicator (0100) + character count
  pushBits(0b0100, 4)
  pushBits(payload.length, version <= 9 ? 8 : 16)
  for (let i = 0; i < payload.length; i++) pushBits(payload[i], 8)

  // Terminator (up to 4 zero bits)
  const terminator = Math.min(4, totalDataBits - bits.length)
  pushBits(0, terminator)
  while (bits.length % 8 !== 0) bits.push(0)

  const dataBytes = new Uint8Array(spec.totalData)
  for (let i = 0; i < bits.length / 8; i++) {
    let b = 0
    for (let j = 0; j < 8; j++) b = (b << 1) | bits[i * 8 + j]
    dataBytes[i] = b
  }
  const padBytes = [0xec, 0x11]
  for (let i = bits.length / 8, p = 0; i < spec.totalData; i++, p ^= 1) {
    dataBytes[i] = padBytes[p]
  }

  // Split into blocks & compute Reed-Solomon EC codewords
  const dataBlocks: Uint8Array[] = []
  const ecBlocks: Uint8Array[] = []
  let offset = 0
  for (let i = 0; i < spec.g1Blocks; i++) {
    const block = dataBytes.subarray(offset, offset + spec.g1Data)
    offset += spec.g1Data
    dataBlocks.push(block)
    ecBlocks.push(rsComputeRemainder(block, spec.ecPerBlock))
  }
  for (let i = 0; i < spec.g2Blocks; i++) {
    const block = dataBytes.subarray(offset, offset + spec.g2Data)
    offset += spec.g2Data
    dataBlocks.push(block)
    ecBlocks.push(rsComputeRemainder(block, spec.ecPerBlock))
  }

  // Interleave data codewords, then EC codewords
  const codewords: number[] = []
  const maxDataLen = Math.max(spec.g1Data, spec.g2Data)
  for (let i = 0; i < maxDataLen; i++) {
    for (const block of dataBlocks) {
      if (i < block.length) codewords.push(block[i])
    }
  }
  for (let i = 0; i < spec.ecPerBlock; i++) {
    for (const block of ecBlocks) {
      codewords.push(block[i])
    }
  }

  // Initialize matrix
  const size = 17 + version * 4
  const baseModules = Array.from({ length: size }, () => new Uint8Array(size))
  const isFunc = Array.from({ length: size }, () => Array<boolean>(size).fill(false))

  const placeFinder = (top: number, left: number) => {
    for (let dy = -1; dy <= 7; dy++) {
      for (let dx = -1; dx <= 7; dx++) {
        const r = top + dy
        const c = left + dx
        if (r < 0 || r >= size || c < 0 || c >= size) continue
        const inOuter = dy >= 0 && dy <= 6 && dx >= 0 && dx <= 6
        const onRing = dy === 0 || dy === 6 || dx === 0 || dx === 6
        const inCenter = dy >= 2 && dy <= 4 && dx >= 2 && dx <= 4
        baseModules[r][c] = inOuter && (onRing || inCenter) ? 1 : 0
        isFunc[r][c] = true
      }
    }
  }
  placeFinder(0, 0)
  placeFinder(0, size - 7)
  placeFinder(size - 7, 0)

  // Timing patterns
  for (let i = 8; i < size - 8; i++) {
    const bit = i % 2 === 0 ? 1 : 0
    baseModules[6][i] = bit
    isFunc[6][i] = true
    baseModules[i][6] = bit
    isFunc[i][6] = true
  }

  // Alignment patterns
  const align = spec.align
  for (let i = 0; i < align.length; i++) {
    for (let j = 0; j < align.length; j++) {
      if (
        (i === 0 && j === 0) ||
        (i === 0 && j === align.length - 1) ||
        (i === align.length - 1 && j === 0)
      ) {
        continue
      }
      const cr = align[i]
      const cc = align[j]
      for (let dy = -2; dy <= 2; dy++) {
        for (let dx = -2; dx <= 2; dx++) {
          const dist = Math.max(Math.abs(dy), Math.abs(dx))
          baseModules[cr + dy][cc + dx] = dist === 2 || dist === 0 ? 1 : 0
          isFunc[cr + dy][cc + dx] = true
        }
      }
    }
  }

  // Reserve format and version areas
  writeFormatBits(baseModules, isFunc, size, 0)
  writeVersionBits(baseModules, isFunc, size, version)

  // Place data bits in 2-column upward/downward zig-zag
  let bitIdx = 0
  const totalCodewordBits = codewords.length * 8
  let upward = true
  for (let right = size - 1; right >= 1; right -= 2) {
    if (right === 6) right = 5 // Skip vertical timing column
    for (let vert = 0; vert < size; vert++) {
      const r = upward ? size - 1 - vert : vert
      for (let j = 0; j < 2; j++) {
        const c = right - j
        if (!isFunc[r][c]) {
          let bit = 0
          if (bitIdx < totalCodewordBits) {
            bit = (codewords[bitIdx >>> 3] >>> (7 - (bitIdx & 7))) & 1
            bitIdx++
          }
          baseModules[r][c] = bit
        }
      }
    }
    upward = !upward
  }

  // Choose optimal mask (0..7)
  let bestMask = 0
  let bestPenalty = Infinity
  let bestModules = baseModules
  for (let mask = 0; mask < 8; mask++) {
    const candidate = baseModules.map(row => new Uint8Array(row))
    for (let r = 0; r < size; r++) {
      for (let c = 0; c < size; c++) {
        if (!isFunc[r][c] && shouldMask(mask, r, c)) {
          candidate[r][c] ^= 1
        }
      }
    }
    writeFormatBits(candidate, isFunc, size, mask)
    const penalty = computePenalty(candidate, size)
    if (penalty < bestPenalty) {
      bestPenalty = penalty
      bestMask = mask
      bestModules = candidate
    }
  }
  void bestMask

  // Build compact SVG path
  const segments: string[] = []
  for (let r = 0; r < size; r++) {
    for (let c = 0; c < size; c++) {
      if (bestModules[r][c] === 1) {
        segments.push(`M${c + margin} ${r + margin}h1v1h-1Z`)
      }
    }
  }

  return {
    version,
    size,
    viewBoxSize: size + margin * 2,
    margin,
    path: segments.join(''),
    modules: bestModules,
  }
}

export function buildOtpAuthUri(
  email: string,
  secret: string,
  issuer = 'Siderfolio',
  imageUrl?: string,
): string {
  const cleanEmail = (email || 'user').trim()
  const label = `${encodeURIComponent(issuer)}:${encodeURIComponent(cleanEmail)}`
  const params = new URLSearchParams({
    secret: secret.trim(),
    issuer,
    algorithm: 'SHA1',
    digits: '6',
    period: '30',
  })
  if (imageUrl && /^https?:\/\//i.test(imageUrl)) {
    params.set('image', imageUrl)
  }
  return `otpauth://totp/${label}?${params.toString()}`
}
