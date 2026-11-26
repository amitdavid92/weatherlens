import type {
  ChatResponse,
  Health,
  HubProfile,
  Methodology,
  Overview,
  RankingResult,
  SessionHistory,
} from './types'

/** Error with the backend's structured fields ({error, detail, retryable}). */
export class ApiError extends Error {
  readonly status: number
  readonly code: string
  readonly retryable: boolean

  constructor(status: number, code: string, detail: string, retryable: boolean) {
    super(detail)
    this.status = status
    this.code = code
    this.retryable = retryable
  }
}

export const BACKEND_UNREACHABLE =
  'The WeatherLens API server is not reachable. Start it with “make api” (or the full stack with “make dev”), then reload.'

const CHAT_TIMEOUT_MS = 120_000 // real Gemini turns take 5–45 s; backend bounds its own retries
const READ_TIMEOUT_MS = 30_000

async function request<T>(path: string, init: RequestInit = {}, timeoutMs = READ_TIMEOUT_MS): Promise<T> {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), timeoutMs)
  let res: Response
  try {
    res = await fetch(path, {
      ...init,
      signal: controller.signal,
      headers: { 'Content-Type': 'application/json', ...(init.headers ?? {}) },
    })
  } catch (e) {
    const aborted = e instanceof DOMException && e.name === 'AbortError'
    throw new ApiError(
      0,
      aborted ? 'client_timeout' : 'network_error',
      aborted
        ? 'The request took longer than expected and was stopped.'
        : BACKEND_UNREACHABLE,
      true,
    )
  } finally {
    clearTimeout(timer)
  }
  if (!res.ok) {
    let body: { error?: string; detail?: string; retryable?: boolean } = {}
    try {
      body = await res.json()
    } catch {
      /* non-JSON error body */
    }
    // A gateway error without the backend's structured body means the dev proxy could not reach
    // FastAPI (server not running); backend-originated 503s always carry {error, detail}.
    if (!body.error && [502, 503, 504].includes(res.status)) {
      throw new ApiError(res.status, 'backend_unreachable', BACKEND_UNREACHABLE, true)
    }
    throw new ApiError(res.status, body.error ?? 'http_error', body.detail ?? res.statusText, body.retryable ?? res.status >= 500)
  }
  return (await res.json()) as T
}

export const api = {
  health: () => request<Health>('/api/health'),
  overview: () => request<Overview>('/api/overview'),
  rankings: (hazard?: string | null, region?: string | null) => {
    const q = new URLSearchParams()
    if (hazard) q.set('hazard', hazard)
    if (region) q.set('region', region)
    const qs = q.toString()
    return request<RankingResult>(`/api/rankings${qs ? `?${qs}` : ''}`)
  },
  hubScores: (hubId: string) => request<HubProfile>(`/api/hubs/${encodeURIComponent(hubId)}/scores`),
  methodology: () => request<Methodology>('/api/methodology'),
  chat: (message: string, sessionId: string | null) =>
    request<ChatResponse>(
      '/api/chat',
      { method: 'POST', body: JSON.stringify(sessionId ? { message, session_id: sessionId } : { message }) },
      CHAT_TIMEOUT_MS,
    ),
  session: (sessionId: string) => request<SessionHistory>(`/api/sessions/${encodeURIComponent(sessionId)}`),
}

/** Human, actionable copy for chat failures. */
export function describeChatError(e: unknown): { title: string; detail: string; retryable: boolean } {
  if (!(e instanceof ApiError)) {
    return { title: 'Something went wrong', detail: 'An unexpected error occurred.', retryable: true }
  }
  switch (e.code) {
    case 'llm_quota_exceeded':
      return {
        title: 'The AI provider is rate-limiting requests',
        detail: 'Gemini’s per-minute quota was reached. Wait about a minute, then retry.',
        retryable: true,
      }
    case 'rate_limited':
      return { title: 'Too many questions in a short time', detail: e.message, retryable: true }
    case 'daily_limit_reached':
      return { title: 'Daily AI question limit reached', detail: e.message, retryable: false }
    case 'busy':
      return { title: 'The AI Analyst is busy', detail: e.message, retryable: true }
    case 'llm_timeout':
      return { title: 'The AI provider timed out', detail: 'Gemini did not answer in time. Retry the question.', retryable: true }
    case 'llm_unavailable':
    case 'llm_auth_error':
    case 'llm_error':
      return {
        title: 'The AI Analyst is unavailable',
        detail: /still work/.test(e.message) ? e.message : `${e.message} The Overview and Methodology views still work.`,
        retryable: e.retryable,
      }
    case 'unknown_session':
      return { title: 'This conversation has expired', detail: 'Start a new conversation to continue.', retryable: false }
    case 'backend_unreachable':
      return { title: 'The WeatherLens server is not reachable', detail: e.message, retryable: true }
    case 'client_timeout':
    case 'network_error':
      return { title: e.code === 'client_timeout' ? 'No answer yet' : 'Connection problem', detail: e.message, retryable: true }
    default:
      return { title: `Request failed (${e.status || 'network'})`, detail: e.message, retryable: e.retryable }
  }
}
