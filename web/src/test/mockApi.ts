// Fetch router over REAL recorded backend responses (src/test/fixtures, captured from the running
// API; the two chat fixtures are real Gemini answers). Mocked transport, not mocked analytics.
import { vi } from 'vitest'
import chatDenver from './fixtures/chat_denver.json'
import chatMidwest from './fixtures/chat_midwest.json'
import health from './fixtures/health.json'
import hubDenver from './fixtures/hub_denver.json'
import hubMiami from './fixtures/hub_miami.json'
import methodology from './fixtures/methodology.json'
import overview from './fixtures/overview.json'
import rankings from './fixtures/rankings.json'
import rankingsHurricane from './fixtures/rankings_hurricane.json'

export const fixtures = { chatDenver, chatMidwest, health, hubDenver, hubMiami, methodology, overview, rankings, rankingsHurricane }

type ChatHandler = (body: { message: string; session_id?: string }) => Promise<Response> | Response

export const json = (data: unknown, status = 200) =>
  new Response(JSON.stringify(data), { status, headers: { 'Content-Type': 'application/json' } })

export function mockApi(opts: { llmAvailable?: boolean; chat?: ChatHandler } = {}) {
  const calls: { url: string; body?: unknown }[] = []
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    const body = init?.body ? JSON.parse(String(init.body)) : undefined
    calls.push({ url, body })
    if (url === '/api/health') {
      return json(
        opts.llmAvailable === false
          ? { ...health, llm: { available: false, provider: null, model: null, reason: 'GEMINI_API_KEY is not configured' } }
          : health,
      )
    }
    if (url === '/api/overview') return json(overview)
    if (url === '/api/methodology') return json(methodology)
    if (url.startsWith('/api/rankings')) return json(url.includes('hazard=hurricane') ? rankingsHurricane : rankings)
    if (url === '/api/hubs/miami_fl/scores') return json(hubMiami)
    if (url === '/api/hubs/denver_co/scores') return json(hubDenver)
    if (url.startsWith('/api/sessions/')) return json({ error: 'unknown_session', detail: 'not found' }, 404)
    if (url === '/api/chat') {
      if (opts.chat) return opts.chat(body)
      return json(chatDenver)
    }
    return json({ error: 'not_found', detail: url }, 404)
  })
  vi.stubGlobal('fetch', fetchMock)
  return { fetchMock, calls }
}

export function deferred<T>() {
  let resolve!: (v: T) => void
  const promise = new Promise<T>((r) => (resolve = r))
  return { promise, resolve }
}
