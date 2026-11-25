import { useCallback, useEffect, useRef, useState } from 'react'
import { api, ApiError, describeChatError } from '../api/client'
import type { ChatResponse } from '../api/types'

export type ChatEntry =
  | { id: string; role: 'user'; text: string; state: 'sent' | 'pending' | 'failed'; error?: ReturnType<typeof describeChatError> }
  | { id: string; role: 'assistant'; response: ChatResponse }

const SESSION_KEY = 'weatherlens.session'
let counter = 0
const nextId = () => `m${Date.now().toString(36)}${(counter++).toString(36)}`

/**
 * Conversation state shared by the full-page Analyst and the docked panel.
 * - The user's message is shown immediately; a second submit is refused while one is pending.
 * - The backend stores a turn only after a successful answer, so retrying a failed request
 *   re-sends the same message once and never duplicates a turn.
 */
export function useChat() {
  const [entries, setEntries] = useState<ChatEntry[]>([])
  const [sessionId, setSessionId] = useState<string | null>(() => localStorage.getItem(SESSION_KEY))
  const [pending, setPending] = useState(false)
  const [startedAt, setStartedAt] = useState<number | null>(null)
  const [restoring, setRestoring] = useState(false)
  const inFlight = useRef(false)

  // Restore the previous conversation (if the backend still has it).
  useEffect(() => {
    const sid = localStorage.getItem(SESSION_KEY)
    if (!sid) return
    setRestoring(true)
    api
      .session(sid)
      .then((h) => {
        const restored: ChatEntry[] = []
        for (const t of h.turns) {
          restored.push({ id: nextId(), role: 'user', text: t.user_message, state: 'sent' })
          restored.push({ id: nextId(), role: 'assistant', response: t.response })
        }
        setEntries(restored)
      })
      .catch((e) => {
        if (e instanceof ApiError && e.status === 404) {
          localStorage.removeItem(SESSION_KEY)
          setSessionId(null)
        }
      })
      .finally(() => setRestoring(false))
  }, [])

  const run = useCallback(
    async (userEntryId: string, text: string) => {
      inFlight.current = true
      setPending(true)
      setStartedAt(Date.now())
      try {
        const res = await api.chat(text, sessionId)
        setSessionId(res.session_id)
        localStorage.setItem(SESSION_KEY, res.session_id)
        setEntries((prev) => [
          ...prev.map((e) => (e.id === userEntryId && e.role === 'user' ? { ...e, state: 'sent' as const, error: undefined } : e)),
          { id: nextId(), role: 'assistant', response: res },
        ])
      } catch (err) {
        if (err instanceof ApiError && err.code === 'unknown_session') {
          localStorage.removeItem(SESSION_KEY)
          setSessionId(null)
        }
        setEntries((prev) =>
          prev.map((e) =>
            e.id === userEntryId && e.role === 'user' ? { ...e, state: 'failed' as const, error: describeChatError(err) } : e,
          ),
        )
      } finally {
        inFlight.current = false
        setPending(false)
        setStartedAt(null)
      }
    },
    [sessionId],
  )

  const send = useCallback(
    (raw: string) => {
      const text = raw.trim()
      if (!text || inFlight.current) return false
      const id = nextId()
      setEntries((prev) => [...prev, { id, role: 'user', text, state: 'pending' }])
      void run(id, text)
      return true
    },
    [run],
  )

  const retry = useCallback(
    (entryId: string) => {
      if (inFlight.current) return
      const entry = entries.find((e) => e.id === entryId)
      if (!entry || entry.role !== 'user') return
      setEntries((prev) => prev.map((e) => (e.id === entryId && e.role === 'user' ? { ...e, state: 'pending' as const, error: undefined } : e)))
      void run(entryId, entry.text)
    },
    [entries, run],
  )

  const reset = useCallback(() => {
    if (inFlight.current) return
    localStorage.removeItem(SESSION_KEY)
    setSessionId(null)
    setEntries([])
  }, [])

  return { entries, sessionId, pending, startedAt, restoring, send, retry, reset }
}

export type ChatController = ReturnType<typeof useChat>
