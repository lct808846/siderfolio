const storageKey = 'astroagent.conversations.results-panel.v1'
const limit = 200

export function readResultsPanelStates(): Map<string, boolean> {
  try {
    const saved: unknown = JSON.parse(localStorage.getItem(storageKey) || '[]')
    if (!Array.isArray(saved)) return new Map()
    const entries = saved.filter((entry): entry is [string, boolean] => Array.isArray(entry)
      && entry.length === 2 && typeof entry[0] === 'string' && entry[0].length > 0
      && entry[0].length <= 64 && typeof entry[1] === 'boolean')
    return new Map(entries.slice(-limit))
  } catch { return new Map() }
}

export function saveResultsPanelStates(states: Map<string, boolean>) {
  while (states.size > limit) {
    const oldest = states.keys().next().value
    if (oldest === undefined) break
    states.delete(oldest)
  }
  try { localStorage.setItem(storageKey, JSON.stringify([...states])) }
  catch { /* Browser storage may be unavailable; the in-memory states still work. */ }
}
