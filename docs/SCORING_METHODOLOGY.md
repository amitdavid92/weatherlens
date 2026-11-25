# Scoring Methodology: Weather Hazard Exposure Index (v1.0.0)

**What it is:** a deterministic, heuristic 0–100 index of how exposed a distribution hub's location is to five weather hazards, built from public data.

**What it is not:**
- a probability of disruption;
- a loss estimate;
- a scientifically validated risk model.

We have no internal downtime, shipment, asset-vulnerability or financial data, so the index cannot measure *operational* risk.

All parameters live in [`config/scoring.yaml`](../config/scoring.yaml) and are validated at load time. They were fixed before any hub score was computed and have **not** been tuned to produce particular rankings. The same inputs always give identical outputs, and no LLM is involved.

---

## 1. Inputs
| Input | Source | Resolution | Period |
|---|---|---|---|
| Daily SNOW, TMIN, TMAX | NOAA GHCN-Daily, airport station per hub (primary climate source) | Station | 2016–2025 climatology (configurable); any completed calendar year or range for ad-hoc statistics |
| Annualized frequency (`AFREQ`) for 10 hazards | FEMA National Risk Index, Dec 2025 (v1.20) | County containing the hub's city reference point | Each hazard's **own multi-decade period of record**. *Not* specific to any user-selected year. |
| Daily ERA5 reanalysis | Open-Meteo (`models=era5`) | ~0.25° grid cell | Alternative, labeled as modeled. Never mixed with NOAA and not used in scores. |

---

## 2. Historical statistics (`analytics/stats.py`)
For one dataset (one source, one location), one element and one period:

| Quantity | Definition |
|---|---|
| expected days | Calendar days in the period (leap-aware) |
| missing | No reported value |
| excluded | Reported, but NOAA quality flag is non-empty (reason kept as `quality_flag:<Q>`) |
| valid | expected − missing − excluded |
| coverage | valid / expected |
| event days | Valid days satisfying the metric predicate |
| % of valid days | 100 · event / valid |
| annual average | (event / valid) · (expected / n_years). This is observed-rate scaling: missing days are assumed to resemble observed ones, **never set to zero**. |

| Metric | Predicate |
|---|---|
| `snow_days_measurable` | SNOW reported > 0 (trace excluded) |
| `snow_days_trace_inclusive` | SNOW > 0 **or** trace flag "T" |
| `heavy_snow_days` | SNOW ≥ 101.6 mm (4.0 in) |
| `freezing_days` | TMIN ≤ 0 °C |
| `extreme_heat_days` | TMAX ≥ 35 °C (95 °F) |

**Coverage gate:** if coverage is below **90%** (configurable), the statistic is returned with status `insufficient_coverage` and **no value**. Counts are still reported. Trace and zero semantics apply only to snow; for temperatures, negative values and 0 °C are ordinary measurements.

---

## 3. Indicator normalization (0–100)

### 3.1 Climate indicators: fixed anchors
`s = 100 · clip((x − low) / (high − low), 0, 1)`, where x is the 2016–2025 annual average.

| Indicator | low → 0 | high → 100 | Rationale |
|---|---|---|---|
| Measurable snow days/yr | 0 | 60 | 60 is roughly the frequency of the snowiest large US metros; most hubs fall well inside the scale |
| Heavy-snow days/yr (≥ 4 in) | 0 | 6 | A 4-inch day is a common operational-disruption trigger; 6+ per year is exceptional for major cities |
| Freezing days/yr | 0 | 180 | About half the year below freezing, as on the northern plains and upper Midwest |
| Extreme-heat days/yr (≥ 95 °F) | 0 | 100 | Desert-Southwest metros approach this; most Sunbelt hubs sit mid-scale |

Fixed anchors, unlike min-max over the catalog, mean that adding or removing a hub never changes another hub's score. The anchors are judgment calls, stated openly.

### 3.2 FEMA NRI indicators: national mid-rank percentiles
For each hazard h, the **eligible reference population** is defined as follows:
- **Start:** NRI county records for the 50 states + DC (3,144).
- **Excluded:** territories (88: PR, GU, AS, MP, VI), plus counties whose hazard status is `insufficient_data` or `unknown`. Example: 30 Alaska counties for heat wave.
- **No-exposure tier (Z), kept in the population:** counties with status `observed_zero` or `not_applicable`. FEMA defines "Not Applicable" as *not considered at risk*.

```
county in no-exposure tier       -> s = 0                 (never percentile-ranked)
county with positive AFREQ x     -> s = 100 · (Z + L + ½E) / N
                                    N = eligible count, L = eligible positives < x,
                                    E = eligible positives == x (ties share the mid-rank)
insufficient_data / unknown      -> unavailable (None), never 0
```
**Properties:** 0 ≤ s < 100. The calculation is deterministic (exact comparison of published values). A mass of zero-frequency counties scores 0; it cannot pull zero counties up.

**Version guard:** a county record and the reference population must share one `NRI_VER`. If they don't, the engine uses the reference table's own row; if that is still inconsistent, it raises.

| Hazard | N eligible | Positive | Observed zero | Not applicable | Excluded (unavailable) |
|---|---|---|---|---|---|
| HRCN hurricane | 3144 | 2271 | 126 | 747 | 0 |
| CFLD coastal flooding | 3144 | 465 | 35 | 2644 | 0 |
| IFLD inland flooding | 3144 | 3141 | 3 | 0 | 0 |
| WNTW winter weather | 3144 | 3108 | 34 | 2 | 0 |
| ISTM ice storm | 3144 | 3001 | 0 | 143 | 0 |
| CWAV cold wave | 3144 | 3078 | 66 | 0 | 0 |
| TRND tornado | 3144 | 3144 | 0 | 0 | 0 |
| HAIL hail | 3144 | 3127 | 17 | 0 | 0 |
| SWND strong wind | 3144 | 3121 | 23 | 0 | 0 |
| HWAV heat wave | 3114 | 3062 | 52 | 0 | 30 |

---

## 4. Hazard scores and weights
`H = Σ_available w_i · s_i / Σ_available w_i`. The hazard is computed only if the available indicator weight is ≥ **60%**.

| Hazard | Indicators (weight within hazard) | Why |
|---|---|---|
| Winter | measurable snow days 0.20 · heavy-snow days 0.10 · freezing days 0.20 · NRI winter weather 0.20 · NRI ice storm 0.20 · NRI cold wave 0.10 | Half observed station climate, half FEMA long-record frequency. Ice storms are weighted like snow because ice disproportionately disrupts roads and power. |
| Hurricane | NRI hurricane 1.0 | FEMA modeled hurricane frequency. Observed wind speeds are *not* used as a proxy. |
| Flood | NRI coastal flooding 0.5 · NRI inland flooding 0.5 | Two flood channels, equally weighted. Rainfall is *not* used as a proxy. |
| Severe convective | NRI tornado 0.334 · hail 0.333 · strong wind 0.333 | Equal thirds |
| Extreme heat | days ≥ 95 °F 0.5 · NRI heat wave 0.5 | Observed heat days plus FEMA heat-wave frequency |

**Overall index:** `O = Σ_h W_h · H_h`, with **equal hazard weights W_h = 0.2**. Equal weights are a transparent default, not validated operational priorities.

**Contributions:**
- indicator → hazard: `w_i_eff · s_i`;
- hazard → overall: `W_h · H_h`;
- indicator → overall: `W_h · w_i_eff · s_i`.

They sum exactly to the scores (tested).

**Bands (heuristic labels):** Low < 40 ≤ Moderate < 70 ≤ High.

---

## 5. Missing-data and not-applicable policies
| Situation | Treatment | Effect |
|---|---|---|
| FEMA `not_applicable` (e.g. hurricane in Denver, coastal flood in Dallas) | Indicator scored **0** and **kept in every denominator** | No inflation from dropping the indicator. Dallas flood = ½·97.8 + ½·0 = 48.9, not 97.8. |
| FEMA `observed_zero` | Indicator scored 0 | — |
| FEMA `insufficient_data` / `unknown` | Indicator **unavailable**; never 0 | Hazard is renormalized over available indicators and marked `partial`, or `unavailable` if under 60% of its weight is available |
| Climate coverage < 90% | Statistic withheld; indicator unavailable | Miami snow (20.5% coverage) makes Miami winter `partial` (70% of weight available) |
| Any hazard `unavailable` | Overall = **None**, status `unavailable` | No silent renormalization across hazards |
| Any hazard `partial` | Overall computed, status `partial` | **Not ranked** by default (`rank_partial_results: false`); listed separately with its score |
| Rankings | Require one NRI version, one climate source and one climate period across hubs | Otherwise rejected as not comparable |
| Ties | Score descending; exact ties share a rank; listed by `hub_id` | Deterministic |

---

## 6. Worked example: Dallas (actual output, methodology 1.0.0)
| Hazard | Indicator: raw → score (effective weight) | Hazard score | × 0.2 |
|---|---|---|---|
| Severe convective | tornado 0.928/yr → 96.3 (0.334); hail 8.92/yr → 96.9 (0.333); strong wind 4.36/yr → 75.8 (0.333) | **89.7** | 17.93 |
| Extreme heat | 65.0 days ≥ 95 °F/yr → 65.0 (0.5); heat wave 19.1/yr → 96.7 (0.5) | **80.9** | 16.17 |
| Hurricane | 0.0115/yr (≈ 1 per 87 yr) → 50.8 (1.0) | **50.8** | 10.17 |
| Flood | coastal: not applicable → 0 (0.5); inland 4.61/yr → 97.8 (0.5) | **48.9** | 9.78 |
| Winter | snow 1.1 d/yr → 1.8; heavy 0.1 → 1.7; freezing 23.2 → 12.9; NRI winter weather 4.05 → 21.5; ice storm 1.23 → 88.2; cold wave 0.95 → 32.1 | **28.3** | 5.65 |
| **Overall** | | | **59.7 (Moderate)** |

Check: 0.2 × (89.675 + 80.854 + 50.843 + 48.895 + 28.253) = 59.70.

---

## 7. Limitations (stated with every result)
1. **Exposure ≠ disruption risk.** The index has no vulnerability, redundancy or financial dimension and has not been validated against outcomes.
2. **Percentiles exaggerate small differences near the no-exposure tier.** Hubs with tiny but positive modeled frequencies score mid-range:
   - Hurricane: Dallas ≈ 1 event per 87 years scores 50.8; Chicago ≈ 1 per 108 years scores 40.4.
   - Coastal flooding: with 2,644 counties not applicable, any coastal county scores ≥ ~85.

   See `docs/PHASE_2_VALIDATION.md` → *Methodology diagnostics*. This is a known property of the approved method and is flagged for review; it was not tuned.
3. **Geography.** County-level FEMA data and airport-station climate data are not site-specific. Three hubs (Chicago, Kansas City, Atlanta) use a station outside the hazard county.
4. **Periods.** The climate window is 10 years, short for rare events. FEMA frequencies cover different, hazard-specific periods of record and are not year-specific.
5. **Weights and anchors are judgment calls.** The overall ranking is sensitive to equal hazard weighting.
6. **Station data quality.** NOAA quality-flagged values are excluded. Miami's snow record is too sparse to score (reported as partial, not as zero).
