import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { api } from '../../src/api'
import { conversationExport, orderedConversations, readPinnedConversations, savePinnedConversations } from '../../src/conversation-tools'
import type { ConversationDetail, Turn } from '../../src/types'

beforeEach(() => localStorage.clear())
afterEach(() => vi.restoreAllMocks())

it('sorts pinned entries without changing the unpinned list order or mutating the input', () => {
  const items = ['a', 'b', 'c'].map(id => ({ id, title: id, created_at: '', updated_at: '', revision: 0, metadata_revision: 0 }))
  expect(orderedConversations(items, ['c']).map(item => item.id)).toEqual(['c', 'a', 'b'])
  expect(items.map(item => item.id)).toEqual(['a', 'b', 'c'])
  expect(savePinnedConversations(['c', 'c'])).toBe(true)
  expect(readPinnedConversations()).toEqual(['c'])
})

it('ignores invalid preference JSON', () => {
  localStorage.setItem('astroagent.conversations.pinned.v1', '{invalid')
  expect(readPinnedConversations()).toEqual([])
})

it('refuses an export if the conversation changes while fetching saved turns', async () => {
  const base = { id: 'c', title: '会话', created_at: '', updated_at: '', revision: 0, metadata_revision: 0, turns: [] }
  vi.spyOn(api, 'detail').mockResolvedValueOnce(base).mockResolvedValueOnce({ ...base, revision: 1 })
  await expect(conversationExport('c')).rejects.toThrow('会话正在更新')
})

it('exports an empty saved conversation without invoking an answer service', async () => {
  const base = { id: 'c', title: '会话', created_at: '', updated_at: '', revision: 0, metadata_revision: 0, turns: [] }
  vi.spyOn(api, 'detail').mockResolvedValue(base)
  const submit = vi.spyOn(api, 'submit')
  const result = await conversationExport('c')
  expect(result.format).toBe('astroagent-conversation')
  expect(result.conversation).toEqual(base)
  expect(result.turns).toEqual([])
  expect(submit).not.toHaveBeenCalled()
})

it('refuses export when a saved turn is still running without sending a new request', async () => {
  const summary = { turn_id: 't', revision: 1, message: '合成问题', model: null, execution_status: 'running', received_at: '', completed_at: null, response_status: null }
  const detail: ConversationDetail = { id: 'c', title: '会话', created_at: '', updated_at: '', revision: 1, metadata_revision: 0, turns: [summary] }
  vi.spyOn(api, 'detail').mockResolvedValue(detail)
  vi.spyOn(api, 'turn').mockResolvedValue({ conversation_id: 'c', turn_id: 't', execution_status: 'running' } as Turn)
  const submit = vi.spyOn(api, 'submit')
  await expect(conversationExport('c')).rejects.toThrow('会话正在更新')
  expect(submit).not.toHaveBeenCalled()
})
