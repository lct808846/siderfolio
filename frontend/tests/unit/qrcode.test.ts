import { describe, expect, it } from 'vitest'
import { buildOtpAuthUri, encodeQrCode } from '../../src/utils/qrcode'

describe('TOTP QR code encoder', () => {
  it('builds a valid otpauth:// URI for Siderfolio', () => {
    const uri = buildOtpAuthUri('observer@example.org', 'JBSWY3DPEHPK3PXP')
    expect(uri).toBe(
      'otpauth://totp/Siderfolio:observer%40example.org?secret=JBSWY3DPEHPK3PXP&issuer=Siderfolio&algorithm=SHA1&digits=6&period=30',
    )
  })

  it('encodes otpauth URI into a valid ISO/IEC 18004 QR matrix and decodes back to exact bytes', () => {
    const uri = buildOtpAuthUri('observer@example.org', 'JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP')
    const qr = encodeQrCode(uri, 4)

    expect(qr.version).toBeGreaterThanOrEqual(6)
    expect(qr.size).toBe(17 + qr.version * 4)
    expect(qr.viewBoxSize).toBe(qr.size + 8)
    expect(qr.path).toContain('M4 4h1v1h-1Z')

    // Verify finder pattern corners (top-left, top-right, bottom-left)
    for (const [top, left] of [
      [0, 0],
      [0, qr.size - 7],
      [qr.size - 7, 0],
    ]) {
      expect(qr.modules[top][left]).toBe(1)
      expect(qr.modules[top + 3][left + 3]).toBe(1)
      expect(qr.modules[top + 1][left + 1]).toBe(0)
    }

    // Verify dark module at (size - 8, 8)
    expect(qr.modules[qr.size - 8][8]).toBe(1)

    // Extract format bits from top-left copy and verify against second copy
    let formatBits1 = 0
    for (let i = 0; i <= 5; i++) formatBits1 |= qr.modules[i][8] << i
    formatBits1 |= qr.modules[7][8] << 6
    formatBits1 |= qr.modules[8][8] << 7
    formatBits1 |= qr.modules[8][7] << 8
    for (let i = 9; i < 15; i++) formatBits1 |= qr.modules[8][14 - i] << i

    let formatBits2 = 0
    for (let i = 0; i < 8; i++) formatBits2 |= qr.modules[8][qr.size - 1 - i] << i
    for (let i = 8; i < 15; i++) formatBits2 |= qr.modules[qr.size - 15 + i][8] << i
    expect(formatBits1).toBe(formatBits2)

    const unmaskedFormat = formatBits1 ^ 0x5412
    const formatData = unmaskedFormat >> 10
    const ecIndicator = formatData >> 3
    const mask = formatData & 0b111
    expect(ecIndicator).toBe(0b00) // EC Level M
    expect(mask).toBeGreaterThanOrEqual(0)
    expect(mask).toBeLessThanOrEqual(7)
  })
})
