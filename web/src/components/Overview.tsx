import { MessageSquareText } from 'lucide-react'
import { type ReactNode, useEffect, useState } from 'react'
import { api } from '../api/client'
import type { HazardKey, Overview as OverviewData, RankingResult } from '../api/types'
import { HAZARDS, hazardLabel, humanizeReason } from '../format'
import { HubProfilePanel } from './HubProfilePanel'
import { BandBadge, Callout, PartialTag, ScoreBar, SectionHeader, Skeleton } from './ui'
import { UsMap } from './UsMap'

type Scope = 'overall' | HazardKey
const REGIONS = ['All', 'Midwest', 'South', 'West'] as const

export function Overview({
  overview,
  error,
  selected,
  onSelect,
  onAsk,
  headerAction,
}: {
  headerAction?: ReactNode
  overview: OverviewData | null
  error: string | null
  selected: string | null
  onSelect: (hubId: string | null) => void
  onAsk: (question: string) => void
}) {
  const [scope, setScope] = useState<Scope>('overall')
  const [region, setRegion] = useState<(typeof REGIONS)[number]>('All')
  // Results are keyed by request; a stale key means "loading" (no state reset inside the effect).
  const key = `${scope}|${region}`
  const [result, setResult] = useState<{ key: string; data?: RankingResult; error?: string } | null>(null)
  const ranking = result?.key === key ? (result.data ?? null) : null
  const rankingError = result?.key === key ? (result.error ?? null) : null

  useEffect(() => {
    let alive = true
    api
      .rankings(scope === 'overall' ? null : scope, region === 'All' ? null : region)
      .then((data) => alive && setResult({ key, data }))
      .catch((e) => alive && setResult({ key, error: e.message }))
    return () => {
      alive = false
    }
  }, [key, scope, region])

  if (error) {
    return (
      <div className="page">
        <Callout tone="error" title="Analytical data is unavailable">
          {error}
        </Callout>
      </div>
    )
  }
  if (!overview) {
    return (
      <div className="page">
        <Skeleton rows={6} height={18} />
      </div>
    )
  }

  const c = overview.counts
  const hubsById = Object.fromEntries(overview.hubs.map((h) => [h.hub_id, h]))
  const visibleHubs = region === 'All' ? overview.hubs : overview.hubs.filter((h) => h.region === region)

  const profile =
    selected && hubsById[selected] ? (
      <HubProfilePanel
        hub={hubsById[selected]}
        onClose={() => onSelect(null)}
        onAsk={(name, band) =>
          onAsk(`Explain the ${name} hub's weather exposure${band ? ` (overall band ${band})` : ''}: what are its main drivers?`)
        }
      />
    ) : (
      <p className="hint">
        <MessageSquareText size={15} aria-hidden /> Select a hub on the map or in the ranking to see its profile and ask the AI Analyst about it.
      </p>
    )

  return (
    <div className="page overview">
      <header className="page-head">
        <div>
          <h1>Weather Risk Overview</h1>
          <p className="page-sub">
            Weather-hazard exposure across {c.hubs} distribution hubs, scored from public NOAA and FEMA data to help prioritize
            resilience investment.
          </p>
        </div>
        {headerAction ? <div className="page-head-action">{headerAction}</div> : null}
      </header>
      <section className="kpis" aria-label="Portfolio summary">
        <div className="kpi">
          <span className="kpi-label">Distribution hubs</span>
          <span className="kpi-value num">{c.hubs}</span>
          <span className="kpi-note">Illustrative catalog</span>
        </div>
        <div className="kpi">
          <span className="kpi-label">Ranked · partial</span>
          <span className="kpi-value num">
            {c.ranked} <span className="kpi-sep">·</span> {c.partial}
          </span>
          <span className="kpi-note">Partial hubs are not ranked overall</span>
        </div>
        <div className="kpi">
          <span className="kpi-label">Highest overall exposure</span>
          {overview.highest ? (
            <>
              <span className="kpi-value">
                {overview.highest.name.replace(/ Hub$/, '')} <span className="num kpi-score">{overview.highest.score_display}</span>
              </span>
              <span className="kpi-note">
                <BandBadge band={overview.highest.band} /> among ranked hubs
              </span>
            </>
          ) : (
            <span className="kpi-value">—</span>
          )}
        </div>
        <div className="kpi">
          <span className="kpi-label">High-exposure hubs</span>
          <span className="kpi-value num">{c.high}</span>
          <span className="kpi-note">Overall index ≥ High band</span>
        </div>
      </section>

      <div className="overview-grid">
        <div className="overview-left">
        <section className="panel map-panel" aria-label="Hub map">
          <SectionHeader title={scope === 'overall' ? 'Overall exposure by hub' : `${hazardLabel(scope)} exposure by hub`}>
            <div className="legend" aria-label="Legend">
              <span><i className="dot band-low" /> Low</span>
              <span><i className="dot band-moderate" /> Moderate</span>
              <span><i className="dot band-high" /> High</span>
              <span><i className="dot is-partial-legend" /> Partial</span>
            </div>
          </SectionHeader>
          <UsMap hubs={visibleHubs} scope={scope} selected={selected} onSelect={(id) => onSelect(id)} />
          <p className="fineprint">
            Hubs are illustrative examples, not company facilities. Index {overview.methodology_version} · FEMA NRI{' '}
            {overview.nri_version} · NOAA climate {overview.climate_period}.
          </p>
        </section>
        <div className="profile-slot">{profile}</div>
        </div>

        <section className="panel ranking-panel" aria-label="Exposure ranking">
          <SectionHeader title="Exposure ranking">
            <label className="select">
              <span className="sr-only">Region</span>
              <select value={region} onChange={(e) => setRegion(e.target.value as (typeof REGIONS)[number])}>
                {REGIONS.map((r) => (
                  <option key={r} value={r}>
                    {r === 'All' ? 'All regions' : r}
                  </option>
                ))}
              </select>
            </label>
          </SectionHeader>
          <div className="segmented" role="tablist" aria-label="Hazard">
            {[{ key: 'overall' as Scope, short: 'Overall' }, ...HAZARDS].map((h) => (
              <button key={h.key} role="tab" aria-selected={scope === h.key} className={scope === h.key ? 'is-active' : ''} onClick={() => setScope(h.key)}>
                {h.short}
              </button>
            ))}
          </div>

          {rankingError && <Callout tone="error" title="Ranking unavailable">{rankingError}</Callout>}
          {!ranking && !rankingError && <Skeleton rows={8} />}
          {ranking && (
            <>
              <table className="table ranking-table">
                <thead>
                  <tr>
                    <th className="col-rank">#</th>
                    <th>Hub</th>
                    <th className="col-score">{scope === 'overall' ? 'Overall index' : 'Hazard score'}</th>
                    <th>Band</th>
                  </tr>
                </thead>
                <tbody>
                  {ranking.ranked.map((e) => (
                    <tr
                      key={e.hub_id}
                      className={e.hub_id === selected ? 'is-selected' : ''}
                      aria-selected={e.hub_id === selected}
                      onClick={() => onSelect(e.hub_id)}
                    >
                      <td className="col-rank num">{e.rank}</td>
                      <td>
                        <button className="linklike" onClick={() => onSelect(e.hub_id)}>
                          {e.display_name.replace(/ Hub$/, '')}
                        </button>
                        <span className="cell-sub">{hubsById[e.hub_id]?.region}</span>
                      </td>
                      <td className="col-score">
                        <ScoreBar score={e.score} display={e.score_display} band={e.band} />
                      </td>
                      <td>
                        <BandBadge band={e.band} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {ranking.not_ranked.length > 0 && (
                <div className="not-ranked">
                  <h3>Not ranked: incomplete data</h3>
                  {ranking.not_ranked.map((e) => (
                    <div key={e.hub_id} className={`not-ranked-row ${e.hub_id === selected ? 'is-selected' : ''}`} onClick={() => onSelect(e.hub_id)}>
                      <div className="not-ranked-head">
                        <button className="linklike" onClick={() => onSelect(e.hub_id)}>
                          {e.display_name.replace(/ Hub$/, '')}
                        </button>
                        <PartialTag />
                        <span className="num muted">{e.score_display ?? 'n/a'}</span>
                      </div>
                      <p className="fineprint">{humanizeReason(e.exclusion_reason)}</p>
                    </div>
                  ))}
                </div>
              )}
            </>
          )}
        </section>
      </div>

    </div>
  )
}
