# Scoring Methodology: Weather Hazard Exposure Index (v1.1.0)

**What it is:** a deterministic, heuristic 0–100 index of how exposed a distribution hub's location is to five weather hazards, built from public data.

**What it is not:**
- a probability of disruption;
- a loss estimate;
- a scientifically validated risk model.

We have no internal downtime, shipment, asset-vulnerability or financial data, so the index cannot measure *operational* risk.

All parameters live in [`config/scoring.yaml`](../config/scoring.yaml) and are validated at load time. The v1.0.0 parameters were fixed before any hub score was computed. v1.1.0 changed only the FEMA normalization (§3.2), after a sensitivity analysis ([PHASE_2_SENSITIVITY.md](PHASE_2_SENSITIVITY.md)). Its absolute anchors follow one hub-independent return-period rule. Nothing has been tuned to produce particular rankings. The same inputs always give identical outputs, and no LLM is involved.

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

### 3.2 FEMA NRI indicators: hybrid of relative and absolute frequency (v1.1.0)
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
The value above is the **relative** component `s_rel`. Version 1.1.0 blends it with an **absolute** component:

```
s_abs = 100 · clip( log10(x / 0.01) / log10(1 / 0.01), 0, 1 )   # 1-in-100-yr -> 0, 1/yr -> 100
s     = 0.5 · s_rel + 0.5 · s_abs                              # no-exposure tier: 0; unavailable: None
```
**Why:**
- A percentile alone says *how a county compares nationally*. It ranks a ~1-in-87-year hurricane frequency above the 873 no-exposure counties, which gives it a mid-range score.
- The absolute component says *how often, in absolute terms*.
  - The anchors use one rule for every hazard: 0.01/yr → 0 and 1/yr → 100. They are a **heuristic modeling assumption**, loosely inspired by the common "1%-annual-chance" planning convention and by annual occurrence. They are **not a universal scientific standard**, and other defensible anchors would shift magnitudes (not within-hazard rankings).
  - The scale is logarithmic because hazard frequencies span orders of magnitude.
- The two halves are weighted equally, as a transparent default.

**Effects:**
- The hybrid is **monotone in frequency**, so every hub ranking *within* a hazard is identical to percentile-only.
- What changes is magnitude for rare hazards. Hurricane: Dallas 50.8 → 27.0, Chicago 40.4 → 20.2, Miami 98.9 → 86.6. Coastal flooding: Chicago (0.012/yr on Lake Michigan) 88.3 → 46.2.

**Limitations of the absolute half:**
- It saturates at 100 for hazards that occur at least yearly in most counties (winter weather 93%, heat wave 87% and hail 85% of positive counties). For those, the relative half carries the comparison, and the absolute half adds a near-constant offset. As a result, overall *levels* rose in v1.1.0 (§6). Bands are heuristic labels.
- The anchors are the same for all hazards; there are no hazard-specific severity anchors. NRI frequencies count *events* for some hazards and *event-days* for others (winter weather, cold wave, heat wave). So the absolute half measures occurrence frequency, not severity.

**Alternative rejected:** a percentile among positive-frequency counties only, which drops the no-exposure tier. It fixes hurricane but distorts coastal flooding: Miami's coastal score falls to 44.0, because coastal counties are then compared only with each other. See [PHASE_2_SENSITIVITY.md](PHASE_2_SENSITIVITY.md).

**Properties:** 0 ≤ s ≤ 100. The calculation is deterministic (exact comparison of published values). A mass of zero-frequency counties scores 0; it cannot pull zero counties up.

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
| Ranking eligibility (per scope) | Every profile exposes `ranking_eligibility` for `overall` and each hazard, with an explicit reason. A hazard ranking includes every hub whose *hazard* is complete. | Miami is excluded from the overall and winter rankings (partial snow data) but ranked in hurricane (#1) and flood (#2) |
| Ties | Score descending; exact ties share a rank; listed by `hub_id` | Deterministic |

---

## 6. Worked example: Dallas (actual output, methodology 1.1.0)
| Hazard | Indicator: raw → score (effective weight) | Hazard score | × 0.2 |
|---|---|---|---|
| Severe convective | tornado 0.928/yr → 97.3 (0.334); hail 8.92/yr → 98.4 (0.333); strong wind 4.36/yr → 87.9 (0.333) | **94.6** | 18.91 |
| Extreme heat | 65.0 days ≥ 95 °F/yr → 65.0 (0.5); heat wave 19.1/yr → 98.4 (0.5) | **81.7** | 16.34 |
| Flood | coastal: not applicable → 0 (0.5); inland 4.61/yr → 98.9 (0.5) | **49.4** | 9.89 |
| Winter | snow 1.1 d/yr → 1.8; heavy 0.1 → 1.7; freezing 23.2 → 12.9; NRI winter weather 4.05 → 60.8; ice storm 1.23 → 94.1; cold wave 0.95 → 65.5 | **40.6** | 8.12 |
| Hurricane | 0.0115/yr (≈ 1 per 87 yr): relative 50.8, absolute 3.1 → 27.0 (1.0) | **27.0** | 5.39 |
| **Overall** | | | **58.7 (Moderate)** |

**Two contribution levels:**
- **Hazard level:** `W_h·H_h`. This is the primary explanation; Dallas's primary driver is severe convective storms.
- **Indicator level:** `W_h·w_i·s_i`. These also sum to the overall score. But a single-indicator hazard (hurricane) concentrates its whole weight in one indicator, so indicator lists must not be read as hazard rankings. In v1.0.0 the hurricane indicator was Dallas's largest *single indicator* (10.2 points) while ranking only third as a hazard. `explain_hub_score` now reports `primary_driver`, both contribution levels, and a note.

### v1.0.0 → v1.1.0 (overall)
| Hub | v1.0.0 | v1.1.0 | Rank change |
|---|---|---|---|
| Houston | 68.3 (#1) | 73.6 (#1, High) | — |
| Dallas | 59.7 (#2) | 58.7 (#2) | — |
| Chicago | 58.5 (#3) | 56.7 (#3) | — |
| Detroit | 57.2 (#4) | 56.2 (#4) | — |
| Memphis | 51.7 (#5) | 54.0 (#5) | — |
| Atlanta | 45.3 (#7) | 50.7 (#6) | ↑1 |
| Kansas City | 46.3 (#6) | 49.5 (#7) | ↓1 |
| Minneapolis | 43.2 (#9) | 49.3 (#8) | ↑1 |
| Indianapolis | 44.2 (#8) | 47.9 (#9) | ↓1 |
| Columbus | 39.2 (#10) | 45.6 (#10) | — |
| Denver | 28.1 (#11) | 40.0 (#11) | — |
| Miami | 55.5 (partial) | 61.3 (partial) | not ranked |

## 7. Limitations (stated with every result)
1. **Exposure ≠ disruption risk.** The index has no vulnerability, redundancy or financial dimension and has not been validated against outcomes.
2. **FEMA scores mean relative and absolute *frequency*, not likelihood of a damaging event or its severity.** The v1.1.0 hybrid reduces, but doesn't remove, the percentile's compression near the no-exposure tier.
   - Hurricane: Dallas ≈ 1 event per 87 years now scores 27.0 (was 50.8).
   - The absolute half saturates for hazards that occur at least yearly.
3. **Geography.** County-level FEMA data and airport-station climate data are not site-specific. Three hubs (Chicago, Kansas City, Atlanta) use a station outside the hazard county.
4. **Periods.** The climate window is 10 years, short for rare events. FEMA frequencies cover different, hazard-specific periods of record and are not year-specific.
5. **Weights and anchors are judgment calls.** The overall ranking is sensitive to equal hazard weighting.
6. **Station data quality.** NOAA quality-flagged values are excluded. Miami's snow record is too sparse to score (reported as partial, not as zero).
