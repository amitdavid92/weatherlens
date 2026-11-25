import type { Band, HazardKey } from './api/types'

// Labels only. No scores are computed or rounded here: score strings come from the backend.

export const HAZARDS: { key: HazardKey; label: string; short: string }[] = [
  { key: 'winter', label: 'Winter weather', short: 'Winter' },
  { key: 'hurricane', label: 'Hurricane', short: 'Hurricane' },
  { key: 'flood', label: 'Flooding', short: 'Flood' },
  { key: 'severe_convective', label: 'Severe convective storms', short: 'Severe storms' },
  { key: 'extreme_heat', label: 'Extreme heat', short: 'Heat' },
]

export const hazardLabel = (k: string | null | undefined): string =>
  HAZARDS.find((h) => h.key === k)?.label ?? (k ? k.replace(/_/g, ' ') : '—')

export const bandClass = (band: Band | null | undefined): string =>
  band ? `band-${band.toLowerCase()}` : 'band-none'

export const FRESHNESS_LABEL: Record<string, string> = {
  live: 'Live',
  cache: 'Cached',
  stale_cache: 'Stale cache',
  snapshot: 'Snapshot',
}

export const SOURCE_LABEL: Record<string, string> = {
  noaa_ghcn_daily: 'NOAA GHCN-Daily',
  open_meteo_archive: 'Open-Meteo ERA5',
  fema_nri: 'FEMA National Risk Index',
}

export const METRIC_LABEL: Record<string, string> = {
  snow_days_measurable: 'Measurable snowfall days',
  snow_days_trace_inclusive: 'Snowfall days incl. trace',
  heavy_snow_days: 'Heavy-snow days (≥ 4 in)',
  freezing_days: 'Freezing days',
  extreme_heat_days: 'Extreme-heat days (≥ 95 °F)',
}

export const INDICATOR_LABEL: Record<string, string> = {
  snow_days_measurable: 'Measurable snow days / yr',
  heavy_snow_days: 'Heavy-snow days / yr',
  freezing_days: 'Freezing days / yr',
  extreme_heat_days: 'Days ≥ 95 °F / yr',
  nri_winter_weather: 'FEMA winter weather',
  nri_ice_storm: 'FEMA ice storm',
  nri_cold_wave: 'FEMA cold wave',
  nri_hurricane: 'FEMA hurricane',
  nri_coastal_flooding: 'FEMA coastal flooding',
  nri_inland_flooding: 'FEMA inland flooding',
  nri_tornado: 'FEMA tornado',
  nri_hail: 'FEMA hail',
  nri_strong_wind: 'FEMA strong wind',
  nri_heat_wave: 'FEMA heat wave',
}

export const indicatorLabel = (id: string) => INDICATOR_LABEL[id] ?? id.replace(/_/g, ' ')

/** Readable wording for backend reason strings (identifiers → labels; values untouched). */
export const humanizeReason = (text: string | null | undefined): string =>
  (text ?? '')
    .replace(/\b(nri_[a-z_]+|snow_days_measurable|heavy_snow_days|freezing_days|extreme_heat_days)\b/g, (id) => indicatorLabel(id))
    .replace(/\(insufficient_coverage\)/g, '(too few valid observations)')
    .replace(/\(insufficient_data\)/g, '(no FEMA data)')
    .replace(/\bsevere_convective\b/g, 'severe convective storms')
    .replace(/\bextreme_heat\b/g, 'extreme heat')

/** Display-only formatting of raw (non-score) values the backend sends as numbers. */
export const fmtFreq = (v: number | null | undefined) =>
  v == null ? '—' : `${Number(v.toPrecision(3))} / yr`

export const fmtPct = (v: number) => `${(v * 100).toFixed(1)}%`

export const shortName = (displayName: string) => displayName.replace(/ Hub$/, '')
