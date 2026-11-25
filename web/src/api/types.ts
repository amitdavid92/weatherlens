// Types mirror the FastAPI response models (weather_risk.api / agent.schema / analytics.models).
// Only fields the UI reads are declared. Every score shown uses the backend `*_display` strings.

export type Band = 'Low' | 'Moderate' | 'High'
export type HazardKey = 'winter' | 'hurricane' | 'flood' | 'severe_convective' | 'extreme_heat'
export type ResultStatus = 'complete' | 'partial' | 'unavailable'

export interface Health {
  status: string
  methodology_version: string
  offline_mode: boolean
  snapshot_entries: number
  llm: { available: boolean; provider: string | null; model: string | null; reason: string | null }
}

export interface OverviewScore {
  score: number | null
  score_display: string | null
  band: Band | null
  status: ResultStatus
  eligible: boolean
  exclusion_reason: string | null
}

export interface OverviewHub {
  hub_id: string
  name: string
  city: string
  state: string
  region: string
  latitude: number
  longitude: number
  overall: OverviewScore & { rank: number | null }
  hazards: Record<HazardKey, OverviewScore>
  primary_driver: HazardKey | null
}

export interface Overview {
  illustrative: boolean
  methodology_version: string
  nri_version: string
  climate_period: string
  counts: { hubs: number; ranked: number; partial: number; unavailable: number; high: number }
  highest: { hub_id: string; name: string; score_display: string; band: Band } | null
  data_freshness: Record<string, string[]>
  snapshot_generated_at: string | null
  hubs: OverviewHub[]
}

export interface RankingEntry {
  rank: number | null
  hub_id: string
  display_name: string
  score: number | null
  score_display: string | null
  band: Band | null
  status: string
  top_contributors: string[]
  eligible: boolean
  exclusion_reason: string | null
}

export interface RankingResult {
  scope: 'overall' | 'hazard'
  hazard: HazardKey | null
  region: string | null
  ranked: RankingEntry[]
  not_ranked: RankingEntry[]
  tie_break: string
  methodology_version: string
  nri_version: string
  climate_period: string
  limitations: string[]
}

export interface CoverageInfo {
  expected_days: number
  valid_days: number
  missing_days: number
  excluded_days: number
  excluded_reasons: Record<string, number>
  coverage: number
  min_coverage: number
  status: 'ok' | 'insufficient_coverage'
}

export interface IndicatorResult {
  indicator_id: string
  hazard: HazardKey
  kind: 'climate_anchor' | 'nri_percentile'
  label: string
  raw_value: number | null
  raw_unit: string
  raw_status: string
  score: number | null
  score_display: string | null
  weight: number
  effective_weight: number
  contribution: number
  normalization: string
  period: string
  coverage: CoverageInfo | null
}

export interface HazardResult {
  hazard: HazardKey
  label: string
  score: number | null
  score_display: string | null
  band: Band | null
  status: ResultStatus
  available_weight_fraction: number
  weight_in_overall: number
  contribution_to_overall: number | null
  indicators: IndicatorResult[]
  notes: string[]
}

export interface SourceRef {
  source_id: string
  dataset: string
  version: string | null
  location_id: string
  freshness: string
  retrieved_at: string
  attribution: string
}

export interface Eligibility {
  scope: string
  eligible: boolean
  status: string
  reason: string | null
}

export interface HubProfile {
  hub_id: string
  display_name: string
  region: string
  methodology_version: string
  nri_version: string
  climate_period: string
  fema_period_note: string
  overall_score: number | null
  overall_score_display: string | null
  overall_band: Band | null
  overall_status: ResultStatus
  hazards: Record<HazardKey, HazardResult>
  ranking_eligibility: Record<string, Eligibility>
  sources: SourceRef[]
  assumptions: string[]
  limitations: string[]
}

export interface WeatherStat {
  hub_id: string
  metric: string
  definition: string
  period: { start: string; end: string; label: string }
  source_id: string
  data_kind: string
  location_id: string
  status: 'ok' | 'insufficient_coverage'
  value_percent_of_valid_days: number | null
  value_display: string | null
  event_days: number | null
  annual_average_days: number | null
  coverage: CoverageInfo
}

export interface ComparisonRow {
  hazard: HazardKey
  hub_scores: Record<string, number | null>
  hub_score_display: Record<string, string | null>
  hub_status: Record<string, string>
  leader: string | null
  difference: number | null
}

export interface Comparison {
  hub_ids: string[]
  hazards: HazardKey[]
  rows: ComparisonRow[]
  nri_raw: Record<string, Record<string, { afreq: number | null; events: number | null; status: string }>>
  nri_version: string
}

export interface IndicatorContribution {
  hazard: HazardKey
  indicator_id: string
  label: string
  raw_value: number | null
  raw_unit: string
  score: number | null
  contribution_to_overall: number
}

export interface Explanation {
  hub_id: string
  overall_score: number | null
  overall_score_display: string | null
  overall_band: Band | null
  overall_status: string
  rank_among_catalog: number | null
  catalog_size_ranked: number
  primary_driver: HazardKey | null
  hazards_by_contribution: HazardResult[]
  top_indicators: IndicatorContribution[]
  not_applicable: string[]
  unavailable: string[]
  premise_check: { claim: string; supported: boolean | null; reasoning: string } | null
}

export interface VerifiedFact {
  fact_id: string
  label: string
  display: string
  hub_id: string | null
  period: string | null
  source_ids: string[]
}

export type ChatStatus =
  | 'answered'
  | 'needs_clarification'
  | 'unsupported'
  | 'insufficient_data'
  | 'fallback'
  | 'error'

export interface ChatResponse {
  session_id: string
  turn: number
  status: ChatStatus
  intent: string
  answer: string
  narrative_source: 'llm' | 'deterministic_fallback' | 'none'
  premise_correction: string | null
  clarification_question: string | null
  resolved: { hubs: string[]; hazards: string[]; metric: string | null; period: string | null }
  facts: VerifiedFact[]
  analysis: {
    rankings: RankingResult[]
    comparisons: Comparison[]
    weather_stats: WeatherStat[]
    explanations: Explanation[]
    profiles: HubProfile[]
    hubs: unknown[]
  }
  sources: SourceRef[]
  data_freshness: Record<string, string[]>
  methodology_version: string
  assumptions: string[]
  limitations: string[]
  follow_up_suggestions: string[]
  validation: {
    valid: boolean
    attempts: number
    issues: string[]
    retry_reasons: string[]
    fallback_used: boolean
  }
  agent: {
    provider: string
    model: string
    model_version: string | null
    iterations: number
    tool_calls: { name: string; ok: boolean; error_type: string | null }[]
    input_tokens: number
    output_tokens: number
    latency_ms: number
  }
}

export interface SessionHistory {
  session_id: string
  turns: { turn: number; created_at: string; user_message: string; response: ChatResponse }[]
}

export interface Methodology {
  methodology_version: string
  nri_version: string
  climate: { source: string; period: { start_year: number; end_year: number }; min_coverage: number; exclude_quality_flagged: boolean }
  thresholds: { heavy_snow_mm: number; freezing_tmin_c: number; extreme_heat_tmax_c: number }
  coverage_policy: { min_hazard_weight_fraction: number; rank_partial_results: boolean }
  bands: { label: Band; min: number }[]
  hazard_weights: Record<HazardKey, number>
  hazards: Record<
    HazardKey,
    {
      label: string
      indicators: {
        id: string
        kind: string
        weight: number
        metric: string | null
        nri_hazard: string | null
        anchor: { low: number; high: number } | null
        unit: string | null
      }[]
    }
  >
  nri_normalization: { method: string; relative_weight: number; absolute_anchor: { low: number; high: number } }
  sources: { source_id: string; license: string }[]
  snapshot: { entries: number; generated_at: string | null }
  offline_mode: boolean
}
