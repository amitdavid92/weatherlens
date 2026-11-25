import { MessageSquareText, X } from 'lucide-react'
import { useEffect, useState } from 'react'
import { api } from '../api/client'
import type { HubProfile, OverviewHub } from '../api/types'
import { FRESHNESS_LABEL, HAZARDS, hazardLabel, humanizeReason, indicatorLabel, SOURCE_LABEL } from '../format'
import { BandBadge, Callout, PartialTag, ScoreBar, Skeleton } from './ui'

export function HubProfilePanel({
  hub,
  onClose,
  onAsk,
}: {
  hub: OverviewHub
  onClose: () => void
  onAsk: (name: string, band: string | null) => void
}) {
  const [result, setResult] = useState<{ id: string; data?: HubProfile; error?: string } | null>(null)
  const profile = result?.id === hub.hub_id ? (result.data ?? null) : null
  const error = result?.id === hub.hub_id ? (result.error ?? null) : null

  useEffect(() => {
    let alive = true
    const id = hub.hub_id
    api
      .hubScores(id)
      .then((data) => alive && setResult({ id, data }))
      .catch((e) => alive && setResult({ id, error: e.message }))
    return () => {
      alive = false
    }
  }, [hub.hub_id])

  const name = hub.name.replace(/ Hub$/, '')
  const climateIndicators = profile
    ? Object.values(profile.hazards).flatMap((h) => h.indicators.filter((i) => i.coverage))
    : []
  const seen = new Set<string>()
  const coverageRows = climateIndicators.filter((i) => {
    const key = i.indicator_id
    if (seen.has(key)) return false
    seen.add(key)
    return true
  })
  const drivers = profile
    ? Object.values(profile.hazards)
        .filter((h) => h.contribution_to_overall != null)
        .sort((a, b) => (b.contribution_to_overall ?? 0) - (a.contribution_to_overall ?? 0))
        .slice(0, 2)
    : []

  return (
    <section className="panel profile" aria-label={`${hub.name} profile`}>
      <header className="profile-head">
        <div>
          <h2>
            {hub.name} <span className="muted">· {hub.city}, {hub.state} · {hub.region}</span>
          </h2>
          <div className="profile-score">
            <span className="profile-score-value num">{hub.overall.score_display ?? 'n/a'}</span>
            <BandBadge band={hub.overall.band} />
            {hub.overall.rank != null ? (
              <span className="muted">Overall rank #{hub.overall.rank}</span>
            ) : (
              <PartialTag title={humanizeReason(hub.overall.exclusion_reason)} />
            )}
          </div>
        </div>
        <div className="profile-actions">
          <button className="btn btn-primary" onClick={() => onAsk(name, hub.overall.band)}>
            <MessageSquareText size={16} aria-hidden /> Ask the AI Analyst
          </button>
          <button className="btn btn-icon" onClick={onClose} aria-label="Close profile">
            <X size={18} />
          </button>
        </div>
      </header>

      {!hub.overall.eligible && hub.overall.exclusion_reason && (
        <Callout tone="warn" title="Overall score is partial: shown, but not ranked">
          {humanizeReason(hub.overall.exclusion_reason)}
        </Callout>
      )}

      {error && <Callout tone="error" title="Profile unavailable">{error}</Callout>}
      {!profile && !error && <Skeleton rows={5} />}

      {profile && (
        <div className="profile-grid">
          <div>
            <h3>Hazard scores</h3>
            <table className="table compact">
              <tbody>
                {HAZARDS.map(({ key, label }) => {
                  const h = profile.hazards[key]
                  return (
                    <tr key={key}>
                      <th scope="row">{label}</th>
                      <td className="col-score">
                        <ScoreBar score={h.score} display={h.score_display} band={h.band} muted={h.status !== 'complete'} />
                      </td>
                      <td>{h.status === 'complete' ? <BandBadge band={h.band} /> : <PartialTag title={h.notes.join(' ')} />}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
            <p className="fineprint">
              Primary drivers (points of the overall index):{' '}
              {drivers.map((d, i) => (
                <span key={d.hazard}>
                  {i > 0 && ', '}
                  <strong>{hazardLabel(d.hazard)}</strong> {d.contribution_to_overall?.toFixed(1)}
                </span>
              ))}
            </p>
          </div>

          <div>
            <h3>Data completeness</h3>
            <table className="table compact">
              <thead>
                <tr>
                  <th>NOAA indicator ({profile.climate_period})</th>
                  <th className="num">Valid days</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {coverageRows.map((i) => (
                  <tr key={i.indicator_id}>
                    <td>{indicatorLabel(i.indicator_id)}</td>
                    <td className="num">{(i.coverage!.coverage * 100).toFixed(1)}%</td>
                    <td>
                      {i.coverage!.status === 'ok' ? (
                        <span className="tag tag-ok">Sufficient</span>
                      ) : (
                        <span className="tag tag-warn">Below {Math.round(i.coverage!.min_coverage * 100)}%</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <h3>Sources</h3>
            <ul className="sources">
              {profile.sources.map((s) => (
                <li key={`${s.source_id}-${s.location_id}`}>
                  <span>{SOURCE_LABEL[s.source_id] ?? s.source_id}</span>
                  <span className="muted"> · {s.location_id}{s.version ? ` · ${s.version}` : ''}</span>
                  <span className={`chip fresh-${s.freshness}`}>{FRESHNESS_LABEL[s.freshness] ?? s.freshness}</span>
                </li>
              ))}
            </ul>
            <p className="fineprint">Methodology {profile.methodology_version}. {profile.fema_period_note}</p>
          </div>
        </div>
      )}
    </section>
  )
}
