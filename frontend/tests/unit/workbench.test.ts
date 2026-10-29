import { beforeEach, afterEach, it, expect, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { mount } from '@vue/test-utils'
import { api, ApiError } from '../../src/api'
import { useWorkbench } from '../../src/stores/workbench'
import ResultPanel from '../../src/components/ResultPanel.vue'
import type { Turn } from '../../src/types'

beforeEach(() => setActivePinia(createPinia()))
afterEach(() => vi.restoreAllMocks())
it('restores saved turns without invoking the model', async () => {
  vi.spyOn(api, 'detail').mockResolvedValue({ id: 'c', title: '历史', metadata_revision: 0, revision: 1, created_at: '', updated_at: '', turns: [{ turn_id: 't', revision: 1, message: '旧问题', execution_status: 'completed', received_at: '', completed_at: '', response_status: 'success' }] })
  vi.spyOn(api, 'turn').mockResolvedValue({ conversation_id: 'c', turn_id: 't', revision: 1, client_request_id: 'key', message: '旧问题', execution_status: 'completed', received_at: '' })
  const submit = vi.spyOn(api, 'submit')
  const store = useWorkbench(); await store.load('c')
  expect(store.selectedTurn?.message).toBe('旧问题'); expect(submit).not.toHaveBeenCalled()
})
it('retains original request on disconnect and blocks a new charged send', async () => {
  const store = useWorkbench(); store.current = { id: 'c', title: '', created_at: '', updated_at: '', revision: 0, metadata_revision: 0, turns: [] }
  vi.spyOn(api, 'detail').mockRejectedValue(new ApiError('connection_lost', '断线'))
  const submit = vi.spyOn(api, 'submit').mockRejectedValue(new ApiError('connection_lost', '断线'))
  await store.send('问题')
  expect(store.disconnectedRequest?.message).toBe('问题')
  await store.send('重复问题')
  expect(submit).toHaveBeenCalledTimes(1)
})
it('shows empty results and never interprets unsafe answer content as HTML', () => {
  const turn: Turn = { conversation_id: 'c', turn_id: 't', revision: 1, client_request_id: 'key', message: '', received_at: '', execution_status: 'completed', response: { status: 'success', answer: '', results: [{ object_name: '<img src=x onerror=alert(1)>', status: 'error', source: { name: 'SIMBAD', url: 'javascript:alert(1)', retrieved_at: '' }, error: { code: 'synthetic', message: '未匹配', retryable: false } }] } }
  const wrapper = mount(ResultPanel, { props: { turn, historical: true } })
  expect(wrapper.text()).toContain('历史结果')
  expect(wrapper.find('img').exists()).toBe(false)
  expect(wrapper.find('a[href^="javascript:"]').exists()).toBe(false)
})

it('does not show a previous conversation after a failed navigation', async () => {
  const store = useWorkbench()
  store.current = { id: 'old', title: '旧会话', created_at: '', updated_at: '', revision: 0, metadata_revision: 0, turns: [] }
  vi.spyOn(api, 'detail').mockRejectedValue(new ApiError('conversation_not_found', '不存在', 404))
  await store.load('missing')
  expect(store.current).toBeNull()
  expect(store.turns).toEqual([])
})

it('ignores an older response arriving after a newer navigation', async () => {
  const store = useWorkbench()
  let finish: ((value: Awaited<ReturnType<typeof api.detail>>) => void) | undefined
  vi.spyOn(api, 'detail').mockImplementation(id => id === 'slow' ? new Promise(resolve => { finish = resolve }) : Promise.resolve({ id: 'new', title: '新会话', created_at: '', updated_at: '', revision: 0, metadata_revision: 0, turns: [] }))
  const slow = store.load('slow'); await store.load('new')
  finish?.({ id: 'slow', title: '迟到响应', created_at: '', updated_at: '', revision: 0, metadata_revision: 0, turns: [] }); await slow
  expect(store.current?.id).toBe('new')
})
