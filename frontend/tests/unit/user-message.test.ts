import { afterEach, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import UserMessage from '../../src/components/UserMessage.vue'

afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks() })

it('copies the original question verbatim, including markup and source IDs', async () => {
  const writeText = vi.fn().mockResolvedValue(undefined)
  vi.stubGlobal('navigator', { clipboard: { writeText } })
  const text = '<b>Gaia</b>\n5853498713190525696'
  const wrapper = mount(UserMessage, { props: { text } })
  expect(wrapper.find('b').exists()).toBe(false)
  await wrapper.get('[aria-label="复制问题"]').trigger('click')
  await flushPromises()
  expect(writeText).toHaveBeenCalledWith(text)
  expect(wrapper.text()).toContain('已复制')
  wrapper.unmount()
})

it('reports clipboard failure without claiming a successful copy', async () => {
  vi.stubGlobal('navigator', { clipboard: { writeText: vi.fn().mockRejectedValue(new Error('denied')) } })
  const wrapper = mount(UserMessage, { props: { text: '问题' } })
  await wrapper.get('[aria-label="复制问题"]').trigger('click')
  await flushPromises()
  expect(wrapper.get('[role="alert"]').text()).toContain('复制未完成')
  expect(wrapper.text()).not.toContain('已复制')
  wrapper.unmount()
})

it('requests editing without changing the original displayed question', async () => {
  const wrapper = mount(UserMessage, { props: { text: '原问题' } })
  await wrapper.get('[aria-label="编辑问题"]').trigger('click')
  expect(wrapper.emitted('edit')).toEqual([['原问题']])
  expect(wrapper.get('.user-message').text()).toBe('原问题')
  wrapper.unmount()
})

it('disables editing while a request is locked', async () => {
  const wrapper = mount(UserMessage, { props: { text: '原问题', disabled: true } })
  await wrapper.get('[aria-label="编辑问题"]').trigger('click')
  expect(wrapper.emitted('edit')).toBeUndefined()
  wrapper.unmount()
})
