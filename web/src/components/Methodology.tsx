import type { Methodology as M, Overview } from '../api/types'
import { FRESHNESS_LABEL, HAZARDS, indicatorLabel, SOURCE_LABEL } from '../format'
import { Callout, Skeleton } from './ui'

const pct = (x: number) => `${Math.round(x * 100)}%`

export function Methodology({ m, overview, error }: { m: M | null; overview: Overview | null; error: string | null }) {
  if (error) return <div className="page"><Callout tone="error" title="Methodology unavailable">{error}</Callout></div>
  if (!m) return <div className="page"><Skeleton rows={8} /></div>
  const n = m.nri_normalization
  return (
    <div className="page methodology">
      <article className="read">
        <h1>How the Weather Hazard Exposure Index works</h1>
        <p className="lead">
          WeatherLens scores how exposed each hub’s location is to five weather hazards, on a heuristic 0–100 scale (methodology{' '}
          <strong>{m.methodology_version}</strong>). Every score is computed by a deterministic engine from public data; the AI Analyst only
          explains these results.
        </p>
        <Callout tone="info" title="Exposure, not disruption probability">
          The index says how often and how intensely a location experiences weather hazards. It is not a probability of operational
          disruption or a loss estimate: WeatherLens has no shipment, downtime, asset-vulnerability or cost data, and the index has not been
          validated against outcomes. The hubs are illustrative, not company facilities.
        </Callout>

        <h2>Five hazard dimensions</h2>
        <div className="table-scroll">
          <table className="table">
            <thead>
              <tr>
                <th>Hazard</th>
                <th>Indicators (weight within hazard)</th>
                <th className="num">Weight in index</th>
              </tr>
            </thead>
            <tbody>
              {HAZARDS.map(({ key, label }) => (
                <tr key={key}>
                  <th scope="row">{label}</th>
                  <td>
                    {m.hazards[key].indicators.map((i, idx) => (
                      <span key={i.id}>
                        {idx > 0 && ' · '}
                        {indicatorLabel(i.id)} <span className="muted num">{i.weight.toFixed(2).replace(/0$/, '')}</span>
                      </span>
                    ))}
                  </td>
                  <td className="num">{m.hazard_weights[key].toFixed(2)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p>
          The overall index is the weighted sum of the five hazard scores. Equal weights are a transparent default, not validated operational
          priorities.
        </p>

        <h2>Climate indicators: fixed anchors</h2>
        <p>
          NOAA GHCN-Daily airport-station observations for {m.climate.period.start_year}–{m.climate.period.end_year} give annual averages.
          Each average is scaled linearly between fixed anchors and clipped to 0–100. The anchors are judgment calls, chosen so that adding a
          hub never changes another hub’s score.
        </p>
        <table className="table compact">
          <thead>
            <tr>
              <th>Indicator</th>
              <th className="num">Scores 0 at</th>
              <th className="num">Scores 100 at</th>
            </tr>
          </thead>
          <tbody>
            {Object.values(m.hazards)
              .flatMap((h) => h.indicators)
              .filter((i) => i.anchor)
              .map((i) => (
                <tr key={i.id}>
                  <td>{indicatorLabel(i.id)}</td>
                  <td className="num">{i.anchor!.low}</td>
                  <td className="num">{i.anchor!.high}</td>
                </tr>
              ))}
          </tbody>
        </table>
        <p className="fineprint">
          Thresholds: heavy snow ≥ {m.thresholds.heavy_snow_mm} mm (4 in) per day; freezing day minimum ≤ {m.thresholds.freezing_tmin_c} °C;
          extreme heat maximum ≥ {m.thresholds.extreme_heat_tmax_c} °C (95 °F).
        </p>

        <h2>FEMA frequencies: hybrid normalization</h2>
        <p>
          FEMA National Risk Index ({m.nri_version}) annualized frequencies are scored as{' '}
          <strong>
            {n.relative_weight} × national percentile + {(1 - n.relative_weight).toFixed(1)} × absolute frequency
          </strong>
          .
        </p>
        <ul>
          <li>
            The percentile ranks a county among all counties in the 50 states and DC. Counties with no exposure score 0 and stay in the
            comparison; territories and counties without data are excluded.
          </li>
          <li>
            The absolute part runs on a log scale from {n.absolute_anchor.low} events per year (score 0) to {n.absolute_anchor.high} per year
            (score 100). These anchors are a heuristic modeling assumption, loosely inspired by the “1%-annual-chance” planning convention.
            They are not a scientific standard.
          </li>
          <li>
            Frequencies cover each hazard’s own multi-decade period of record. They are not specific to any calendar year.
          </li>
        </ul>

        <h2>Exposure bands</h2>
        <p>
          {m.bands.map((b, i) => (
            <span key={b.label}>
              {i > 0 && ' · '}
              <span className={`badge band-${b.label.toLowerCase()}`}>{b.label}</span> from {b.min}
            </span>
          ))}
          . Bands are heuristic labels. They are assigned from the unrounded score, and the displayed value never contradicts its band
          (Denver shows 39.98, Low).
        </p>

        <h2>Missing data and ranking eligibility</h2>
        <ul>
          <li>
            Climate statistics need at least {pct(m.climate.min_coverage)} valid observations. Below that, no value is reported. Missing days
            are never counted as zero, and NOAA quality-flagged values are excluded.
          </li>
          <li>
            FEMA “not applicable” (not considered at risk) scores 0 and keeps its weight, so dropping a hazard cannot inflate a score.
            Unknown or insufficient data is never treated as 0.
          </li>
          <li>
            A hazard with at least {pct(m.coverage_policy.min_hazard_weight_fraction)} of its indicator weight available is scored as{' '}
            <em>partial</em>; below that it is unavailable. A partial overall score is shown but{' '}
            {m.coverage_policy.rank_partial_results ? 'ranked with a flag' : 'not ranked'}. The hub still appears in each hazard ranking where
            its data is complete. For example, Miami is unranked overall because its snowfall record is sparse, but it is ranked for hurricane
            and flood.
          </li>
        </ul>

        <h2>Data sources and freshness</h2>
        <table className="table compact">
          <thead>
            <tr>
              <th>Source</th>
              <th>Use</th>
              <th>License</th>
            </tr>
          </thead>
          <tbody>
            {m.sources.map((s) => (
              <tr key={s.source_id}>
                <td>{SOURCE_LABEL[s.source_id] ?? s.source_id}</td>
                <td>
                  {s.source_id === 'noaa_ghcn_daily'
                    ? 'Primary climate observations (stations)'
                    : s.source_id === 'fema_nri'
                      ? 'County hazard frequencies'
                      : 'Alternative modeled reanalysis, never mixed with NOAA'}
                </td>
                <td className="fineprint">{s.license}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <p>
          Data is resolved in this order: fresh cache, then live API, then stale cache, then the committed snapshot (
          {m.snapshot.entries} raw responses
          {m.snapshot.generated_at ? `, generated ${new Date(m.snapshot.generated_at).toISOString().slice(0, 10)}` : ''}). Every result is
          labeled Live, Cached, Stale cache or Snapshot.{' '}
          {overview && (
            <>
              Current data:{' '}
              {Object.entries(overview.data_freshness)
                .map(([k, v]) => `${SOURCE_LABEL[k] ?? k}: ${v.map((x) => FRESHNESS_LABEL[x] ?? x).join(', ')}`)
                .join('; ')}
              .
            </>
          )}
        </p>
      </article>
    </div>
  )
}
