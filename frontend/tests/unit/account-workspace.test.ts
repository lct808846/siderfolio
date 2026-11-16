import { describe, expect, it, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import AccountWorkspace from '../../src/views/AccountWorkspace.vue'
import * as identityState from '../../src/identity-state'

vi.mock('../../src/identity-state', async () => {
  const { ref } = await import('vue')
  return {
    identityUser: ref({
      id: 'u-1',
      email: 'observer@example.org',
      username: 'observer',
      admin: true,
      totp_enabled: false,
      mfa_verified: false,
    }),
    sessionPolicy: ref({ idle_seconds: 1800, absolute_seconds: 43200 }),
    identityRequest: vi.fn(),
    refreshIdentity: vi.fn(),
    clearPrivateBrowserData: vi.fn(),
    logout: vi.fn(),
  }
})

describe('AccountWorkspace QR 2FA & Security UI', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    identityState.identityUser.value = {
      id: 'u-1',
      email: 'observer@example.org',
      username: 'observer',
      admin: true,
      totp_enabled: false,
      mfa_verified: false,
    }
    vi.mocked(identityState.identityRequest).mockImplementation(async (path: string) => {
      if (path === 'auth/sessions') {
        return [
          {
            current: true,
            created_at: '2026-11-14T10:00:00Z',
            last_seen: '2026-11-14T10:05:00Z',
            expires_at: '2026-11-14T22:00:00Z',
          },
        ] as never
      }
      if (path === 'auth/totp/enroll') {
        return {
          secret: 'JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP',
          otpauth_uri:
            'otpauth://totp/AstroAgent:observer%40example.org?secret=JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP&issuer=AstroAgent&algorithm=SHA1&digits=6&period=30',
          message: '请使用身份验证器扫描二维码，并输入 6 位动态验证码完成绑定。',
        } as never
      }
      if (path === 'auth/totp/confirm') {
        return {
          recovery_codes: ['code-01', 'code-02', 'code-03'],
          message: '恢复码仅显示一次，请离线保存。',
        } as never
      }
      return { message: 'ok' } as never
    })
  })

  it('renders QR code instead of manual secret text during 2FA enrollment and completes confirmation', async () => {
    Object.defineProperty(HTMLDialogElement.prototype, 'showModal', { configurable: true, value(this: HTMLDialogElement) { this.open = true } })
    Object.defineProperty(HTMLDialogElement.prototype, 'close', { configurable: true, value(this: HTMLDialogElement) { this.open = false } })
    Object.defineProperty(HTMLElement.prototype, 'showPopover', { configurable: true, value() {} })
    Object.defineProperty(HTMLElement.prototype, 'hidePopover', { configurable: true, value() {} })
    const wrapper = mount(AccountWorkspace, {
      global: {
        stubs: {
          RouterLink: { template: '<a><slot /></a>' },
        },
      },
    })
    await flushPromises()

    expect(wrapper.text()).toContain('observer@example.org')
    expect(wrapper.text()).toContain('多因素身份验证 (MFA)')

    // Enter password in the 2FA enroll form and submit
    await wrapper.find('#account-mfa-switch').trigger('change')
    await flushPromises()
    const enrollForm = wrapper.find('dialog form')
    expect(enrollForm.exists()).toBe(true)
    await enrollForm.find('input[type="password"]').setValue('CurrentStrongPass123')
    await enrollForm.trigger('submit')
    await flushPromises()

    // Verify QR Code SVG is rendered and raw secret string is not exposed as manual text
    const qrSvg = wrapper.find('svg[aria-label="身份验证器绑定二维码"]')
    expect(qrSvg.exists()).toBe(true)
    expect(qrSvg.find('path').attributes('d')).toContain('M')
    expect(wrapper.find('.account-manual-key').attributes('open')).toBeUndefined()

    // Enter 6-digit OTP code and confirm
    const otpInput = wrapper.find('#totp-confirm-code')
    expect(otpInput.exists()).toBe(true)
    await otpInput.setValue('123456')
    await wrapper.find('dialog form').trigger('submit')
    await flushPromises()

    // Verify recovery codes grid appears
    expect(wrapper.find('.account-recovery-workbench').exists()).toBe(true)
    expect(wrapper.text()).toContain('code-01')
    expect(wrapper.text()).toContain('code-02')
    wrapper.unmount()
  })
})
