import { ArrowUp, Bot, RotateCcw, SquarePen } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import type { Health } from '../api/types'
import { EXAMPLE_QUESTIONS } from '../examples'
import type { ChatController } from '../hooks/useChat'
import { AnswerCard } from './AnswerCard'
import { Callout } from './ui'


const SLOW_AFTER_S = 20

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
            <h2>Ask about weather-hazard exposure across the hubs</h2>
            <p className="muted">
              Answers use only the WeatherLens analytics engine: every number is a verified fact with its source. Try one of the assignment
              questions:
            </p>
            <div className="examples">
              {EXAMPLE_QUESTIONS.map((q) => (
                <button key={q} className="example" onClick={() => submit(q)} disabled={chat.pending || llmDown}>
                  {q}
                </button>
              ))}
            </div>
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
