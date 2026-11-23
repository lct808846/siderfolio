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
  const turn: Turn = { conversation_id: 'c', turn_id: 't', revision: 1, client_request_id: 'key', message: '旧问题', execution_status: 'completed', received_at: '', trace_status: 'not_recorded' }
  vi.spyOn(api, 'bundle').mockResolvedValue({
    conversation: { id: 'c', title: '历史', metadata_revision: 0, revision: 1, created_at: '', updated_at: '', turns: [{ turn_id: 't', revision: 1, message: '旧问题', execution_status: 'completed', received_at: '', completed_at: '', response_status: 'success' }] },
    turns: [turn],
  })
  const submit = vi.spyOn(api, 'submitStream')
  const store = useWorkbench(); await store.load('c')
  expect(store.selectedTurn?.message).toBe('旧问题'); expect(submit).not.toHaveBeenCalled()
})
it('retains original request on disconnect and blocks a new charged send', async () => {
  const store = useWorkbench(); store.current = { id: 'c', title: '', created_at: '', updated_at: '', revision: 0, metadata_revision: 0, turns: [] }
  vi.spyOn(api, 'bundle').mockRejectedValue(new ApiError('connection_lost', '断线'))
  const submit = vi.spyOn(api, 'submitStream').mockRejectedValue(new ApiError('connection_lost', '断线'))
  await store.send('问题')
  expect(store.disconnectedRequest?.message).toBe('问题')
  await store.send('重复问题')
  expect(submit).toHaveBeenCalledTimes(1)
})
it('shows empty results and never interprets unsafe answer content as HTML', () => {
  const turn: Turn = { conversation_id: 'c', turn_id: 't', revision: 1, client_request_id: 'key', message: '', received_at: '', execution_status: 'completed', trace_status: 'not_recorded', response: { status: 'success', answer: '', results: [{ object_name: '<img src=x onerror=alert(1)>', status: 'error', source: { name: 'SIMBAD', url: 'javascript:alert(1)', retrieved_at: '' }, error: { code: 'synthetic', message: '未匹配', retryable: false } }] } }
  const wrapper = mount(ResultPanel, { props: { turn, historical: true }, global: { stubs: ['RouterLink'] } })
  expect(wrapper.text()).toContain('历史')
  expect(wrapper.find('img').exists()).toBe(false)
  expect(wrapper.find('a[href^="javascript:"]').exists()).toBe(false)
})

it('does not show a previous conversation after a failed navigation', async () => {
  const store = useWorkbench()
  store.current = { id: 'old', title: '旧会话', created_at: '', updated_at: '', revision: 0, metadata_revision: 0, turns: [] }
  vi.spyOn(api, 'bundle').mockRejectedValue(new ApiError('conversation_not_found', '不存在', 404))
  await store.load('missing')
  expect(store.current).toBeNull()
  expect(store.turns).toEqual([])
})

it('ignores an older response arriving after a newer navigation', async () => {
  const store = useWorkbench()
  let finish: ((value: Awaited<ReturnType<typeof api.bundle>>) => void) | undefined
  const conversation = { id: 'new', title: '新会话', created_at: '', updated_at: '', revision: 0, metadata_revision: 0, turns: [] }
  vi.spyOn(api, 'bundle').mockImplementation(id => id === 'slow' ? new Promise(resolve => { finish = resolve }) : Promise.resolve({ conversation, turns: [] }))
  const slow = store.load('slow'); await store.load('new')
  finish?.({ conversation: { ...conversation, id: 'slow', title: '迟到响应' }, turns: [] }); await slow
  expect(store.current?.id).toBe('new')
})

it('refreshes storage state without an existing conversation and does not submit a question', async () => {
  const store = useWorkbench()
  store.error = '存储暂不可用'; store.errorCode = 'conversation_storage_unavailable'
  const list = vi.spyOn(api, 'list').mockResolvedValue([])
  const submit = vi.spyOn(api, 'submitStream')
  const create = vi.spyOn(api, 'create')
  await store.recover()
  expect(list).toHaveBeenCalledOnce()
  expect(store.error).toBe(''); expect(store.errorCode).toBe('')
  expect(submit).not.toHaveBeenCalled(); expect(create).not.toHaveBeenCalled()
})

it('keeps a storage refresh failure visible without an existing conversation', async () => {
  const store = useWorkbench()
  vi.spyOn(api, 'list').mockRejectedValue(new ApiError('database_unavailable', '数据库仍不可用', 503))
  await store.recover()
  expect(store.errorCode).toBe('database_unavailable')
  expect(store.error).toBe('数据库仍不可用')
})

it('blocks repeated creation while the first request is pending and reuses its empty conversation', async () => {
  const store = useWorkbench()
  const conversation = { id: 'new', title: '新会话', created_at: '', updated_at: '', revision: 0, metadata_revision: 0 }
  let finish: ((value: typeof conversation) => void) | undefined
  const create = vi.spyOn(api, 'create').mockImplementation(() => new Promise(resolve => { finish = resolve }))
  vi.spyOn(api, 'list').mockResolvedValueOnce([]).mockResolvedValue([conversation])
  const first = store.create()
  expect(store.creating).toBe(true)
  expect(await store.create()).toBeUndefined()
  await vi.waitFor(() => expect(create).toHaveBeenCalledTimes(1))
  finish?.(conversation)
  expect(await first).toBe('new')
  expect(store.creating).toBe(false)
  expect(await store.create()).toBe('new')
  expect(create).toHaveBeenCalledTimes(1)
})

it('keeps a confirmed empty conversation when the subsequent list refresh fails', async () => {
  const store = useWorkbench()
  const create = vi.spyOn(api, 'create').mockResolvedValue({ id: 'new', title: '新会话', created_at: '', updated_at: '', revision: 0, metadata_revision: 0 })
  vi.spyOn(api, 'list').mockResolvedValueOnce([]).mockRejectedValue(new ApiError('connection_lost', '断线'))
  expect(await store.create()).toBe('new')
  expect(store.current?.id).toBe('new')
  expect(await store.create()).toBe('new')
  expect(create).toHaveBeenCalledTimes(1)
})

it('does not overwrite a conversation selected during creation', async () => {
  const store = useWorkbench()
  const conversation = { id: 'new', title: '新会话', created_at: '', updated_at: '', revision: 0, metadata_revision: 0 }
  let finish: ((value: typeof conversation) => void) | undefined
  vi.spyOn(api, 'create').mockImplementation(() => new Promise(resolve => { finish = resolve }))
  vi.spyOn(api, 'list').mockResolvedValue([conversation])
  vi.spyOn(api, 'bundle').mockResolvedValue({ conversation: { ...conversation, id: 'other', turns: [] }, turns: [] })
  const pending = store.create()
  await store.load('other')
  finish?.(conversation)
  await pending
  expect(store.current?.id).toBe('other')
})

it('does not send a question to a different conversation after navigation', async () => {
  const store = useWorkbench()
  store.current = { id: 'other', title: '其他会话', created_at: '', updated_at: '', revision: 0, metadata_revision: 0, turns: [] }
  const submit = vi.spyOn(api, 'submitStream')
  await store.send('问题', 'expected')
  expect(submit).not.toHaveBeenCalled()
})
