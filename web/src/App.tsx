import { BookOpen, Bot, LayoutDashboard, PanelRightClose, PanelRightOpen } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { api } from './api/client'
import type { Health, Methodology as MethodologyData, Overview as OverviewData } from './api/types'
import { ChatPanel } from './components/ChatPanel'
import { Methodology } from './components/Methodology'
import { Overview } from './components/Overview'
import { FreshnessChips } from './components/ui'
import { useChat } from './hooks/useChat'

type View = 'overview' | 'analyst' | 'methodology'
const VIEWS: { key: View; label: string; icon: typeof LayoutDashboard }[] = [
  { key: 'overview', label: 'Overview', icon: LayoutDashboard },
  { key: 'analyst', label: 'AI Analyst', icon: Bot },
  { key: 'methodology', label: 'Methodology & Data', icon: BookOpen },
]

const viewFromHash = (): View => {
  const v = window.location.hash.replace('#', '') as View
  return VIEWS.some((x) => x.key === v) ? v : 'overview'
}

export default function App() {
  const [view, setView] = useState<View>(viewFromHash)
  const [health, setHealth] = useState<Health | null>(null)
  const [healthError, setHealthError] = useState(false)
  const [overview, setOverview] = useState<OverviewData | null>(null)
  const [overviewError, setOverviewError] = useState<string | null>(null)
  const [methodology, setMethodology] = useState<MethodologyData | null>(null)
  const [methodologyError, setMethodologyError] = useState<string | null>(null)
  const [selected, setSelected] = useState<string | null>(null)
  const [dockOpen, setDockOpen] = useState(false)
  const chat = useChat()

  useEffect(() => {
    api.health().then(setHealth).catch(() => setHealthError(true))
    api.overview().then(setOverview).catch((e) => setOverviewError(e.message))
    api.methodology().then(setMethodology).catch((e) => setMethodologyError(e.message))
    const onHash = () => setView(viewFromHash())
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [])

  const go = (v: View) => {
    window.location.hash = v
    setView(v)
  }

  const hubNames = useMemo(
    () => Object.fromEntries((overview?.hubs ?? []).map((h) => [h.hub_id, h.name.replace(/ Hub$/, '')])),
    [overview],
  )

  const ask = (question: string) => {
    const wide = window.matchMedia?.('(min-width: 1280px)').matches
    if (wide && view === 'overview') setDockOpen(true)
    else go('analyst')
    chat.send(question)
  }

  const dataOk = overview != null && !overviewError
  const llmOk = health?.llm.available ?? false

  return (
    <div className={`app ${dockOpen && view === 'overview' ? 'has-dock' : ''}`}>
      <header className="topbar">
        <div className="brand">
          <svg width="26" height="26" viewBox="0 0 32 32" aria-hidden>
            <rect width="32" height="32" rx="7" fill="#12304d" />
            <circle cx="16" cy="16" r="7.5" fill="none" stroke="#2dd4bf" strokeWidth="2.5" />
            <circle cx="16" cy="16" r="2.6" fill="#f2f5f8" />
          </svg>
          <span className="brand-name">WeatherLens</span>
          <span className="brand-sub">Logistics Weather Risk Intelligence</span>
        </div>
        <nav className="tabs" aria-label="Main">
          {VIEWS.map(({ key, label, icon: Icon }) => (
            <button key={key} className={view === key ? 'is-active' : ''} aria-current={view === key ? 'page' : undefined} onClick={() => go(key)}>
              <Icon size={16} aria-hidden />
              <span>{label}</span>
            </button>
          ))}
        </nav>
        <div className="status" aria-label="System status">
          <span className={`status-pill ${dataOk ? 'ok' : overviewError ? 'bad' : 'wait'}`} title="Deterministic analytics engine">
            <i aria-hidden /> Analytics {dataOk ? 'available' : overviewError ? 'unavailable' : '…'}
          </span>
          <span
            className={`status-pill ${llmOk ? 'ok' : health || healthError ? 'bad' : 'wait'}`}
            title={health?.llm.reason ?? health?.llm.model ?? 'AI agent'}
          >
            <i aria-hidden /> AI agent {llmOk ? 'online' : health || healthError ? 'unavailable' : '…'}
          </span>
          {overview && <FreshnessChips freshness={overview.data_freshness} />}
        </div>
      </header>

      <main className="main">
        {view === 'overview' && (
          <div className="overview-wrap">
            <div className="overview-main">
              <Overview
                overview={overview}
                error={overviewError}
                selected={selected}
                onSelect={setSelected}
                onAsk={ask}
                headerAction={
                  <button className="btn btn-ghost dock-toggle" onClick={() => setDockOpen((o) => !o)} aria-pressed={dockOpen}>
                    {dockOpen ? <PanelRightClose size={16} aria-hidden /> : <PanelRightOpen size={16} aria-hidden />}
                    {dockOpen ? 'Hide AI Analyst' : 'Open AI Analyst alongside'}
                  </button>
                }
              />
            </div>
            {dockOpen && (
              <aside className="dock" aria-label="AI Analyst panel">
                <ChatPanel chat={chat} health={health} hubNames={hubNames} compact />
              </aside>
            )}
          </div>
        )}
        {view === 'analyst' && (
          <div className="page analyst-page">
            <ChatPanel chat={chat} health={health} hubNames={hubNames} />
          </div>
        )}
        {view === 'methodology' && <Methodology m={methodology} overview={overview} error={methodologyError} />}
      </main>
    </div>
  )
}
