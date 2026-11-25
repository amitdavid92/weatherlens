import { AlertTriangle, CheckCircle2, CircleHelp, Info, ShieldAlert } from 'lucide-react'
import Markdown from 'react-markdown'
import type { ChatResponse, Comparison, Explanation, HubProfile, RankingResult, WeatherStat } from '../api/types'
import { fmtFreq, HAZARDS, hazardLabel, humanizeReason, indicatorLabel, METRIC_LABEL, SOURCE_LABEL, shortName } from '../format'
import { BandBadge, Callout, FreshnessChips, PartialTag, ScoreBar } from './ui'

const STATUS_COPY: Partial<Record<ChatResponse['status'], { tone: 'warn' | 'info' | 'error'; title: string }>> = {
  needs_clarification: { tone: 'info', title: 'The analyst needs a clarification' },
  unsupported: { tone: 'warn', title: 'Outside the supported scope' },
  insufficient_data: { tone: 'warn', title: 'Not enough data to answer' },
  fallback: { tone: 'warn', title: 'Verified summary shown instead of the AI narrative' },
  error: { tone: 'error', title: 'No verified answer could be produced' },
}

/** Markdown rendering is safe by default: react-markdown never renders raw HTML from the model. */
function Narrative({ text }: { text: string }) {
  return (
    <div className="prose">
      <Markdown
        skipHtml
        components={{
          a: ({ children }) => <span>{children}</span>, // no outbound links from model text
        }}
      >
        {text.replace(/^\*\*Deterministic summary\*\*[^\n]*\n+/, '')}
      </Markdown>
    </div>
  )
}

function RankingBlock({ r }: { r: RankingResult }) {
  const title = `${r.hazard ? hazardLabel(r.hazard) : 'Overall exposure'} ranking${r.region ? ` · ${r.region}` : ''}`
  return (
    <figure className="evidence">
      <figcaption>{title}</figcaption>
      <table className="table compact">
        <tbody>
          {r.ranked.map((e) => (
            <tr key={e.hub_id}>
              <td className="col-rank num">{e.rank}</td>
              <td>{shortName(e.display_name)}</td>
              <td className="col-score">
                <ScoreBar score={e.score} display={e.score_display} band={e.band} />
              </td>
              <td>
                <BandBadge band={e.band} />
              </td>
            </tr>
          ))}
          {r.not_ranked.map((e) => (
            <tr key={e.hub_id} className="is-muted" title={humanizeReason(e.exclusion_reason) || undefined}>
              <td className="col-rank">—</td>
              <td>{shortName(e.display_name)}</td>
              <td className="col-score">
                <ScoreBar score={e.score} display={e.score_display} band={e.band} muted />
              </td>
              <td>
                <PartialTag title={humanizeReason(e.exclusion_reason)} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </figure>
  )
}

function ComparisonBlock({ c, names }: { c: Comparison; names: Record<string, string> }) {
  return (
    <figure className="evidence">
      <figcaption>Hub comparison</figcaption>
      <div className="table-scroll">
        <table className="table compact">
          <thead>
            <tr>
              <th>Hazard</th>
              {c.hub_ids.map((h) => (
                <th key={h}>{names[h] ?? h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {c.rows.map((row) => (
              <tr key={row.hazard}>
                <th scope="row">{hazardLabel(row.hazard)}</th>
                {c.hub_ids.map((h) => (
                  <td key={h} className={`num ${row.leader === h ? 'is-leader' : ''}`}>
                    {row.hub_score_display[h] ?? 'n/a'}
                    {row.leader === h && <span className="leader-mark"> highest</span>}
                    {row.hub_status[h] !== 'complete' && <span className="muted"> ({row.hub_status[h]})</span>}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <details className="details">
        <summary>FEMA annualized frequencies (NRI {c.nri_version})</summary>
        <table className="table compact">
          <thead>
            <tr>
              <th>FEMA hazard</th>
              {c.hub_ids.map((h) => (
                <th key={h}>{names[h] ?? h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {Object.keys(c.nri_raw[c.hub_ids[0]] ?? {}).map((code) => (
              <tr key={code}>
                <th scope="row">{code.replace(/_/g, ' ').toLowerCase()}</th>
                {c.hub_ids.map((h) => {
                  const v = c.nri_raw[h]?.[code]
                  return (
                    <td key={h} className="num">
                      {v?.status === 'not_applicable' ? 'not applicable' : fmtFreq(v?.afreq)}
                    </td>
                  )
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </details>
    </figure>
  )
}

function StatBlock({ s, name }: { s: WeatherStat; name: string }) {
  const cov = s.coverage
  return (
    <figure className="evidence stat">
      <figcaption>
        {METRIC_LABEL[s.metric] ?? s.metric} · {name} · {s.period.label}
      </figcaption>
      {s.status === 'ok' ? (
        <div className="stat-row">
          <span className="stat-value num">{s.value_display}</span>
          <span className="stat-denominator">
            <strong className="num">{s.event_days}</strong> of <strong className="num">{cov.valid_days}</strong> valid days
          </span>
        </div>
      ) : (
        <Callout tone="warn" title="Insufficient observation coverage: no value is reported">
          {cov.valid_days} of {cov.expected_days} days have a valid observation ({(cov.coverage * 100).toFixed(1)}%, below the{' '}
          {Math.round(cov.min_coverage * 100)}% minimum). Missing days are never treated as zero.
        </Callout>
      )}
      <dl className="stat-meta">
        <div>
          <dt>Days in period</dt>
          <dd className="num">{cov.expected_days}</dd>
        </div>
        <div>
          <dt>Missing</dt>
          <dd className="num">{cov.missing_days}</dd>
        </div>
        <div>
          <dt>Quality-excluded</dt>
          <dd className="num">{cov.excluded_days}</dd>
        </div>
        <div>
          <dt>Coverage</dt>
          <dd className="num">{(cov.coverage * 100).toFixed(1)}%</dd>
        </div>
        <div>
          <dt>Source</dt>
          <dd>
            {SOURCE_LABEL[s.source_id] ?? s.source_id} · {s.location_id}
            {s.data_kind === 'modeled_reanalysis' ? ' (modeled)' : ''}
          </dd>
        </div>
      </dl>
      <p className="fineprint">Definition: {s.definition}.</p>
    </figure>
  )
}

function ExplanationBlock({ e, name }: { e: Explanation; name: string }) {
  const pc = e.premise_check
  return (
    <figure className="evidence">
      <figcaption>
        {name}: overall exposure drivers
      </figcaption>
      <div className="explain-head">
        <span className="stat-value num">{e.overall_score_display ?? 'n/a'}</span>
        <BandBadge band={e.overall_band} />
        {e.rank_among_catalog != null && (
          <span className="muted">
            Rank #{e.rank_among_catalog} of {e.catalog_size_ranked} ranked hubs
          </span>
        )}
      </div>
      {pc && (
        <p className={`premise ${pc.supported === false ? 'is-false' : ''}`}>
          {pc.supported === false ? <ShieldAlert size={15} aria-hidden /> : <CheckCircle2 size={15} aria-hidden />}
          Claim “{pc.claim}”: {pc.supported === false ? 'not supported' : pc.supported ? 'supported' : 'cannot be evaluated'} by the
          index.
        </p>
      )}
      <table className="table compact">
        <thead>
          <tr>
            <th>Hazard</th>
            <th className="col-score">Hazard score</th>
            <th className="num">Points of overall</th>
          </tr>
        </thead>
        <tbody>
          {e.hazards_by_contribution.map((h) => (
            <tr key={h.hazard} className={h.hazard === e.primary_driver ? 'is-primary' : ''}>
              <th scope="row">
                {hazardLabel(h.hazard)}
                {h.hazard === e.primary_driver && <span className="tag tag-primary">Primary driver</span>}
              </th>
              <td className="col-score">
                <ScoreBar score={h.score} display={h.score_display} band={h.band} />
              </td>
              <td className="num">{h.contribution_to_overall?.toFixed(1) ?? 'n/a'}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {e.not_applicable.length > 0 && (
        <p className="fineprint">
          Not applicable per FEMA (scored 0, weight kept): {e.not_applicable.map((x) => indicatorLabel(x.split('.')[1])).join(', ')}.
        </p>
      )}
    </figure>
  )
}

function ProfileBlock({ p }: { p: HubProfile }) {
  return (
    <figure className="evidence">
      <figcaption>{shortName(p.display_name)}: exposure profile</figcaption>
      <div className="explain-head">
        <span className="stat-value num">{p.overall_score_display ?? 'n/a'}</span>
        <BandBadge band={p.overall_band} />
        {p.overall_status !== 'complete' && <PartialTag title={p.ranking_eligibility.overall?.reason} />}
      </div>
      <table className="table compact">
        <tbody>
          {HAZARDS.map(({ key, label }) => (
            <tr key={key}>
              <th scope="row">{label}</th>
              <td className="col-score">
                <ScoreBar score={p.hazards[key].score} display={p.hazards[key].score_display} band={p.hazards[key].band} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </figure>
  )
}

export function AnswerCard({
  r,
  hubNames,
  onFollowUp,
  disabled,
}: {
  r: ChatResponse
  hubNames: Record<string, string>
  onFollowUp: (q: string) => void
  disabled: boolean
}) {
  const status = STATUS_COPY[r.status]
  const a = r.analysis
  const name = (id: string) => hubNames[id] ?? id
  return (
    <article className="answer" aria-label="AI Analyst answer">
      {status && (
        <Callout tone={status.tone} title={status.title} icon={r.status === 'needs_clarification' ? <CircleHelp size={16} /> : undefined}>
          {r.status === 'fallback' && 'The AI-written answer failed fact validation, so these results come directly from the analytics engine.'}
        </Callout>
      )}
      {r.premise_correction && (
        <div className="premise-banner" role="note">
          <AlertTriangle size={16} aria-hidden />
          <div>
            <strong>Premise check</strong>
            <p>{r.premise_correction}</p>
          </div>
        </div>
      )}
      <Narrative text={r.answer} />

      {(a.rankings.length > 0 || a.comparisons.length > 0 || a.weather_stats.length > 0 || a.explanations.length > 0 || a.profiles.length > 0) && (
        <div className="evidence-list">
          {a.explanations.map((e) => (
            <ExplanationBlock key={`x-${e.hub_id}`} e={e} name={name(e.hub_id)} />
          ))}
          {a.rankings.map((rk, i) => (
            <RankingBlock key={`r-${i}`} r={rk} />
          ))}
          {a.comparisons.map((c, i) => (
            <ComparisonBlock key={`c-${i}`} c={c} names={hubNames} />
          ))}
          {a.weather_stats.map((s, i) => (
            <StatBlock key={`s-${i}`} s={s} name={name(s.hub_id)} />
          ))}
          {a.explanations.length === 0 && a.profiles.map((p) => <ProfileBlock key={`p-${p.hub_id}`} p={p} />)}
        </div>
      )}

      <footer className="answer-foot">
        <div className="answer-meta">
          <FreshnessChips freshness={r.data_freshness} />
          <span className="chip">Index {r.methodology_version}</span>
          <span className={`chip ${r.validation.valid ? 'chip-ok' : 'chip-warn'}`} title={r.validation.issues.join('\n') || undefined}>
            {r.validation.valid ? (
              <>
                <CheckCircle2 size={12} aria-hidden /> Facts verified
                {r.validation.attempts > 1 ? ' after 1 correction' : ''}
              </>
            ) : (
              'Narrative not verified'
            )}
          </span>
        </div>
        <details className="details">
          <summary>
            <Info size={13} aria-hidden /> Sources, assumptions and limitations
          </summary>
          <ul className="sources">
            {r.sources.map((s) => (
              <li key={`${s.source_id}-${s.location_id}`}>
                {SOURCE_LABEL[s.source_id] ?? s.source_id} <span className="muted">· {s.location_id} · {s.freshness}</span>
              </li>
            ))}
          </ul>
          {r.assumptions.length > 0 && (
            <>
              <h4>Assumptions</h4>
              <ul>{r.assumptions.map((x) => <li key={x}>{x}</li>)}</ul>
            </>
          )}
          {r.limitations.length > 0 && (
            <>
              <h4>Limitations</h4>
              <ul>{r.limitations.map((x) => <li key={x}>{x}</li>)}</ul>
            </>
          )}
          <p className="fineprint">
            {r.agent.provider === 'gemini' ? 'Gemini' : r.agent.provider} {r.agent.model_version ?? r.agent.model} ·{' '}
            {(r.agent.latency_ms / 1000).toFixed(1)} s · tools: {r.agent.tool_calls.map((t) => t.name).join(', ') || 'none'}
          </p>
        </details>
        {r.follow_up_suggestions.length > 0 && (
          <div className="followups" aria-label="Suggested follow-up questions">
            {r.follow_up_suggestions.map((q) => (
              <button key={q} className="chip-btn" onClick={() => onFollowUp(q)} disabled={disabled}>
                {q}
              </button>
            ))}
          </div>
        )}
      </footer>
    </article>
  )
}
