import { api } from './api'
import type { Conversation, ConversationDetail, Turn } from './types'

const pinKey = 'astroagent.conversations.pinned.v1'
export function readPinnedConversations(): string[] {
  try {
    const value: unknown = JSON.parse(localStorage.getItem(pinKey) || '[]')
    return Array.isArray(value) ? [...new Set(value.filter((id): id is string => typeof id === 'string' && id.length <= 64))].slice(0, 20) : []
  } catch { return [] }
}
export function savePinnedConversations(ids: string[]): boolean {
  try { localStorage.setItem(pinKey, JSON.stringify([...new Set(ids)].slice(0, 20))); return true }
  catch { return false }
}
export function orderedConversations(items: Conversation[], pins: string[]): Conversation[] {
  const ranks = new Map(pins.map((id, index) => [id, index]))
  return [...items].sort((a, b) => (ranks.get(a.id) ?? 100) - (ranks.get(b.id) ?? 100))
}

export async function conversationExport(id: string) {
  const conversation = await api.detail(id)
  const turns = await Promise.all(conversation.turns.map(turn => api.turn(id, turn.turn_id)))
  const latest = await api.detail(id)
  if (!sameConversation(conversation, latest) || turns.some((turn, index) => turn.execution_status === 'running' || turn.conversation_id !== id || turn.turn_id !== conversation.turns[index]?.turn_id)) {
    throw new Error('会话正在更新，请等待完成并刷新后再导出。')
  }
  return {
    format: 'astroagent-conversation', format_version: 1,
    exported_at: new Date().toISOString(),
    notice: '本地会话副本，包含问题、回答和保存结果；可能含私人内容。不是项目备份包，不含知识库原文件或模型。',
    conversation, turns,
  }
}
function sameConversation(left: ConversationDetail, right: ConversationDetail) {
  return left.id === right.id && left.revision === right.revision && left.metadata_revision === right.metadata_revision
    && JSON.stringify(left.turns) === JSON.stringify(right.turns)
}
export function saveConversationExport(id: string, value: { conversation: ConversationDetail; turns: Turn[] }) {
  const href = URL.createObjectURL(new Blob([JSON.stringify(value, null, 2)], { type: 'application/json;charset=utf-8' }))
  const anchor = document.createElement('a')
  anchor.href = href; anchor.download = `astroagent-conversation-${id}.json`
  document.body.append(anchor); anchor.click(); anchor.remove()
  setTimeout(() => URL.revokeObjectURL(href), 1000)
}
