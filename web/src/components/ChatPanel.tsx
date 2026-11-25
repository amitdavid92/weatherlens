import { ArrowLeftRight, ArrowUp, Bot, CalendarRange, Layers, RotateCcw, ShieldCheck, Snowflake, SquarePen } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import type { Health } from '../api/types'
import { EXAMPLES } from '../examples'
import type { ChatController } from '../hooks/useChat'
import { AnswerCard } from './AnswerCard'
import { Callout } from './ui'


const SLOW_AFTER_S = 20

const EXAMPLE_ICONS = { winter: Snowflake, compare: ArrowLeftRight, history: CalendarRange, drivers: Layers }

/** WeatherLens Analyst mark: the brand lens with an insight spark (authored SVG). */
export function AnalystMark({ size = 56 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 56 56" aria-hidden className="analyst-mark">
      <rect width="56" height="56" rx="14" fill="#12304d" />
      <circle cx="25" cy="29" r="12" fill="none" stroke="#2dd4bf" strokeWidth="3.5" />
      <path d="M33.5 37.5 L41 45" stroke="#2dd4bf" strokeWidth="3.5" strokeLinecap="round" />
      <path d="M20 31 l3.2 -4.4 3.4 2.6 4 -6" fill="none" stroke="#f2f5f8" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M41.5 9.5 l1.6 3.9 3.9 1.6 -3.9 1.6 -1.6 3.9 -1.6 -3.9 -3.9 -1.6 3.9 -1.6 z" fill="#f2c35a" />
    </svg>
  )
}

function Waiting({ startedAt }: { startedAt: number }) {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(t)
  }, [])
  const s = Math.max(0, Math.floor((now - startedAt) / 1000))
  return (
    <div className="waiting" role="status" aria-live="polite">
      <span className="waiting-pulse" aria-hidden />
      <div>
        <strong>The AI Analyst is working on your question</strong>
        <span className="muted num"> · {s}s</span>
        <p className="fineprint">
          {s < SLOW_AFTER_S
            ? 'Answers are not streamed; the full, fact-checked answer appears when it is ready.'
            : 'This is taking longer than usual. Real AI responses take about 5–45 seconds, depending on provider load.'}
        </p>
      </div>
    </div>
  )
}

export function ChatPanel({
  chat,
  health,
  hubNames,
  compact = false,
}: {
  chat: ChatController
  health: Health | null
  hubNames: Record<string, string>
  compact?: boolean
}) {
  const [draft, setDraft] = useState('')
  const endRef = useRef<HTMLDivElement>(null)
  const llmDown = health != null && !health.llm.available

  useEffect(() => {
    // only follow the conversation; never scroll the empty state away from its heading
    if (chat.entries.length === 0 && !chat.pending) return
    endRef.current?.scrollIntoView?.({ block: 'end', behavior: 'smooth' })
  }, [chat.entries.length, chat.pending])

  const submit = (text: string) => {
    if (chat.send(text)) setDraft('')
  }

  return (
    <div className={`chat ${compact ? 'is-compact' : ''}`}>
      <div className="chat-toolbar">
        <span className="chat-title">
          <Bot size={16} aria-hidden /> AI Analyst
          {health?.llm.available && !compact && <span className="muted"> · {health.llm.model}</span>}
        </span>
        <button className="btn btn-ghost" aria-label="New conversation" onClick={chat.reset} disabled={chat.pending || chat.entries.length === 0}>
          <SquarePen size={15} aria-hidden /> {compact ? 'New' : 'New conversation'}
        </button>
      </div>

      <div className="chat-log" aria-live="polite">
        {llmDown && (
          <Callout tone="warn" title="AI Analyst unavailable">
            {health?.llm.reason ?? 'The language model is not configured.'} The Overview and Methodology views use the deterministic engine and
            keep working.
          </Callout>
        )}

        {chat.entries.length === 0 && !chat.restoring && (
          <div className="chat-empty">
            <AnalystMark size={compact ? 44 : 56} />
            <h2>Your AI Weather Risk Analyst</h2>
            <p className="chat-empty-lead">
              Rank hubs by exposure, compare locations hazard by hazard, look up historical weather statistics and understand what drives a
              hub’s score. Every answer is grounded in the WeatherLens analytics engine.
            </p>
            <div className="examples">
              {EXAMPLES.map((ex) => {
                const Icon = EXAMPLE_ICONS[ex.key]
                return (
                  <button
                    key={ex.key}
                    className="example"
                    onClick={() => submit(ex.question)}
                    disabled={chat.pending || llmDown}
                  >
                    <span className="example-icon" aria-hidden>
                      <Icon size={18} />
                    </span>
                    <span className="example-text">
                      <strong>{ex.title}</strong>
                      <span>{ex.question}</span>
                    </span>
                  </button>
                )
              })}
            </div>
            <p className="trust">
              <ShieldCheck size={15} aria-hidden />
              Public NOAA and FEMA data · Deterministic scoring · Every number checked against verified facts
            </p>
          </div>
        )}

        {chat.entries.map((e) =>
          e.role === 'user' ? (
            <div key={e.id} className={`msg-user ${e.state}`}>
              <p>{e.text}</p>
              {e.state === 'failed' && e.error && (
                <div className="msg-error" role="alert">
                  <strong>{e.error.title}.</strong> {e.error.detail}
                  {e.error.retryable && (
                    <button className="btn btn-ghost" onClick={() => chat.retry(e.id)} disabled={chat.pending}>
                      <RotateCcw size={14} aria-hidden /> Retry
                    </button>
                  )}
                </div>
              )}
            </div>
          ) : (
            <AnswerCard key={e.id} r={e.response} hubNames={hubNames} onFollowUp={submit} disabled={chat.pending || llmDown} />
          ),
        )}
        {chat.pending && chat.startedAt && <Waiting startedAt={chat.startedAt} />}
        <div ref={endRef} />
      </div>

      <form
        className="composer"
        onSubmit={(ev) => {
          ev.preventDefault()
          submit(draft)
        }}
      >
        <label className="sr-only" htmlFor={compact ? 'composer-dock' : 'composer-main'}>
          Ask the AI Analyst
        </label>
        <textarea
          id={compact ? 'composer-dock' : 'composer-main'}
          value={draft}
          maxLength={2000}
          rows={compact ? 2 : 2}
          placeholder={llmDown ? 'AI Analyst unavailable' : 'Ask about hubs, hazards, rankings or historical weather…'}
          disabled={llmDown}
          onChange={(ev) => setDraft(ev.target.value)}
          onKeyDown={(ev) => {
            if (ev.key === 'Enter' && !ev.shiftKey) {
              ev.preventDefault()
              submit(draft)
            }
          }}
        />
        <button className="btn btn-primary btn-send" type="submit" disabled={chat.pending || llmDown || !draft.trim()} aria-label="Send question">
          <ArrowUp size={18} aria-hidden />
        </button>
      </form>
    </div>
  )
}
