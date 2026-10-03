# Decision layer

Package: `src/portfolio_cockpit/decision_layer/`. It sits next to the Fundamental Quality engine and changes none of its hashed files (`CONFIG_FILES`/`CODE_FILES` in `scoring/pipeline.py`). Everything here is analytical: no module can place, modify or cancel an order, every output carries `execution_effect: NONE`, and decision output is asserted free of `side`, `quantity`, `limit_price` and `order_id`.

```
baselines + observations ─► QUALITY DRIFT ─┐
market data + references ─► VALUATION ─────┤
existing target confidence ► DATA CONFIDENCE ┼─► DECISION ENGINE ─► dashboard
positions + scenarios ────► PORTFOLIO RISK ─┤        │
Fundamental Quality ──────── context only ──┘        └─► dry-run simulator + signal log
```

## Commands

| Command | Output |
|---|---|
| `cockpit-check-inputs [--json] [--strict]` | Lists exactly which owner inputs are missing or invalid. |
| `cockpit-drift [--write] [--as-of D]` | `data/drift/quality_drift_<D>[_rN].json` + `current.json` |
| `cockpit-valuation [--write] [--as-of D]` | `data/valuation/valuation_<D>[_rN].json` + `current.json` |
| `cockpit-decide [--write] [--as-of D]` | `data/decisions/decisions_<D>[_rN].json` + `current.json`, and appends `data/signal_log/<D>.jsonl` |
| `cockpit-simulate [--portfolio-value V]` | Dry-run simulation from the current decisions (stdout). |
| `cockpit-evaluate-signals --horizon 90d` | Forward return per decision state versus the portfolio mean (stdout). |
| `python scripts/build_dashboard.py` | `out/dashboard.html` (git-ignored). |
| `python scripts/list_baseline_metrics.py` | All `component.metric` paths per company type in `data/baselines/**`. |
| `python scripts/make_input_templates.py` | Empty owner-input templates in `data/templates/`. |

Without `--write` every builder prints JSON and writes nothing. `--as-of` defaults to today (UTC). The workflow `rebuild-decision-layer.yml` runs the builders with `--write` when inputs change. Decisions are only built there once `positions.yaml` and `thesis_status.yaml` are complete.

## Storage and immutability

There is no database. Outputs use the same write-once pattern as `data/scoring/` (`decision_layer/io.py`, copied rather than imported):

- a file is never overwritten; a changed result becomes `_r2`, `_r3`, …;
- a run with the same `reproducibility_hash` reuses the existing file, so a no-op rebuild is byte-stable;
- `current.json` points to the latest revision.

The reproducibility hash covers `as_of`, the config and code hashes, and the hashes of all input files. The signal log is append-only and idempotent per decision snapshot.

## Quality Drift

Measures change versus the company's own immutable baseline. It is exactly **50.0** at the baseline and never reads price or valuation; an AST test enforces that.

```
per slot:  delta = (raw − baseline) / |baseline|   (mode relative: amounts, per-share values)
                 = raw − baseline                  (mode absolute: percentages and ratios; direct: −1..+1 or boolean)
           signal = clamp(delta / full_scale, −1, 1), 0 when |delta| ≤ dead_band, sign flipped for lower_is_better
component: weighted mean of the slot signals; slot weights renormalize over observed slots (needs ≥ 0.50 slot coverage)
drift    = clamp(50 + 50 · Σ w_c · s_c / Σ w_c(available), 0, 100)
contribution_points per metric = 50 · (w_c / Σ w_c available) · (w_s / Σ w_s observed) · signal
```

Profiles live in `config/quality_drift.yaml`, one per company type. They were built from the real metric names in the 23 baselines.

- **Slots.** A slot uses the first alias present in the baseline. The observation must report that same metric; definitions are never silently swapped.
- **Directions.** Must agree with `score_metrics.yaml: metric_directions` wherever a metric appears there; the validator fails otherwise.
- **Excluded fields.** `*_prior_*`, `prior_year_*` and guidance fields are never drift inputs.
- **Coverage basis.** Coverage is measured against what the baseline can measure; `profile_coverage` reports the share of the profile the baseline covers. This keeps companies with sparse baselines (WSM, LEU) able to drift, while a missing observation still counts against them.
- **Required components.** Only components every baseline of that type can measure are required. For general operating companies these are profitability and growth, because 8 of the 16 baselines have no balance-sheet metric.
- **Period rule (like-for-like).** Each ticker's baseline period basis (H1 or Q) is derived from the source report title, with metric-name overrides (`half_year_`, `quarter_`, `year_to_date_`). An observation metric with a different `period_basis` is excluded with `PERIOD_MISMATCH:<metric>`. Point-in-time slots (balance sheet, capital, share count) skip this check.

| Status | Meaning |
|---|---|
| `NO_NEW_FUNDAMENTALS` | No observation after the baseline yet: drift is exactly 50.0. |
| `OK` | Published drift score. |
| `DRIFT_DATA_CHECK` | A required component is missing or coverage is below 0.70. Only `diagnostic_drift_score` is stored. |

`drift_change_recent` is the score with the latest observation minus the score with the previous observation (or the baseline). This keeps it deterministic from inputs.

**Observations** go in `data/observations/<T>/<date>.json` (template: `data/templates/observation.json`). They are validated: every metric needs `value`, `period`, `period_basis`, `source.{source_type,title,publication_date}` and `retrieved_at`. Corrections are new files, never edits.

## Valuation

Depends on market price; 50 ≈ fair versus reference, higher = more attractive. The metric scores are combined as a weighted mean over the metrics with status `OK`.

| Company type | Metrics (weights) | Not applicable |
|---|---|---|
| General operating | forward P/E .30, EV/EBIT .30, FCF yield .40 | — |
| Insurer, US P&C insurer | P/B .35, P/E .35, shareholder yield .30 | EV/EBITDA, EV/EBIT, FCF yield |
| Pre-revenue | P/NAV .60, market cap / risked NPV .40 | P/E, forward P/E, EV/EBITDA, EV/EBIT, FCF yield |
| Cyclical mining | P/NAV .40, EV / normalized EBITDA .30, FCF yield .30 | P/E, forward P/E |
| Financial services (proposal) | forward P/E .40, P/E .30, P/B .30 | EV/EBITDA, EV/EBIT, FCF yield |

- **Formulas.** Whitelisted in `formulas.py`; there is no `eval`.
- **Reference.** 0.6 × own history + 0.4 × peers, renormalized over the references present.
- **Metric score.** For multiples, `50 − 50·clamp((value/ref − 1)/full_scale)`; for yields the sign is reversed.
- **Labels.** Attractive ≥ 60, Fair ≥ 45, otherwise Expensive.

| Condition | Result |
|---|---|
| Zero or negative denominator, or non-positive numerator for a multiple | `NOT_APPLICABLE`. A negative P/E or EV/EBITDA is never cheap. |
| No reference | `NO_REFERENCE`; no score. |
| Price older than 7 days | `STALE_DATA`; `VALUATION_DATA_CHECK`. |
| Applicable weight with a score below 0.50 | `VALUATION_DATA_CHECK`. |

**Input units.** Amounts in millions of the trading currency, shares in millions, per-share values in the trading-currency unit. Every field carries `as_of_date`, `retrieved_at` and `source`.

## Data Confidence warning contract

`warnings.py` fixes six codes: `STALE_DATA`, `SOURCE_CONFLICT`, `UNSUITABLE_METRIC`, `MISSING_DATA`, `CALCULATION_ANOMALY`, `PERIOD_MISMATCH`. Every raw drift, valuation and confidence warning maps to exactly one of them; an unmapped warning raises.

Target confidence is read from the latest `data/confidence/<date>.json` and its calculation is not changed. Freshness below 100 maps to `STALE_DATA`, completeness below 100 to `MISSING_DATA`, and a cross-check conflict to `SOURCE_CONFLICT`.

Staleness thresholds live in config: a price older than 7 days and fundamentals older than 200 days both give `STALE_DATA`.

## Portfolio Risk

The impact of a −30% move on one position is shown as `PORTFOLIO IMPACT -30%`: `impact_pp = weight × −0.30 × 100`; 7% gives −2.1 pp. It reuses `scoring/portfolio_risk.portfolio_impact` unchanged.

`config/risk_scenarios.yaml` defines the market (beta-aware), sector, single-stock and combined scenarios. Current weights, sector and beta come from `config/positions.yaml`; target weights are only read from `config/portfolio.yaml`.

## Decision Engine

All thresholds are in `config/decision.yaml`. The tree is checked top to bottom:

```
data_confidence < 80, or drift / valuation cannot publish  → DATA_CHECK
thesis_status == BROKEN                                    → THESIS_REVIEW
drift ≤ 40  or  drift_change_recent ≤ −10                  → REVIEW_REDUCE
drift ≥ 55  and valuation ≥ 60                             → ADD_CANDIDATE   (→ HOLD + limit_flags when a limit is hit)
drift ≥ 45  and valuation < 45                             → NO_ADD
otherwise                                                  → HOLD
```

**Limits** (any hit turns `ADD_CANDIDATE` into `HOLD` with `ADD_BLOCKED_BY_LIMIT`):

| Flag | Condition |
|---|---|
| `POSITION_LIMIT` | weight ≥ 10% |
| `ABOVE_TARGET_BAND` | weight ≥ target × 1.20 (an EXIT position with target 0 never becomes ADD) |
| `SECTOR_LIMIT` | sector weight ≥ 30% |
| `IMPACT_LIMIT` | \|impact\| > 3 pp |

**Fundamental Quality** is context only. When it is DISPLAY_READY and below `fq_add_floor` (35), ADD becomes HOLD with `FQ_BELOW_FLOOR`. Otherwise the reason list notes `FQ_NOT_DISPLAY_READY` and FQ has no influence.

**Missing owner inputs.** `cockpit-decide` refuses to run while `positions.yaml` or `thesis_status.yaml` has empty fields, and names each missing field.

## Dashboard

`out/dashboard.html` is one static file with no scripts and no external hosts. Quality Drift (for example "62 (+12 since baseline)"), Fundamental Quality (peer) and Valuation (for example "43 / Expensive") are separate colour blocks. Fundamental Quality is shown only when DISPLAY_READY; otherwise it reads "n.v.t. (DATA_CHECK)" with the diagnostic band as a tooltip. The table also has the `PORTFOLIO IMPACT -30%` column.

Each ticker has a drill-down with:

- drift metrics old against new, with points and source;
- valuation metrics with status, reference and method;
- confidence components;
- the full revision history.

No score is ever called a percentile.

## Simulator and signal log

`DryRunSimulator` refuses `dry_run=False`. It suggests a review direction per ticker:

| Direction | When |
|---|---|
| `REVIEW_UP_TO_TARGET` | ADD_CANDIDATE and below target |
| `REVIEW_DOWN` | REVIEW_REDUCE |
| `REVIEW_THESIS` | THESIS_REVIEW |
| `NONE (DATA_CHECK)` | DATA_CHECK |
| `NONE` | otherwise |

For each ticker it also reports the difference to target, the portfolio impact now and at target, and the sector and cash impact. Base target weights never change.

`cockpit-decide --write` logs every signal (price, state, inputs). `cockpit-evaluate-signals` compares the forward return per state with the mean of all evaluated signals. It uses the first market file dated on or after signal date + horizon, within 7 days.

## Owner inputs

The system never invents numbers. Templates and validators:

| File | Template |
|---|---|
| `config/positions.yaml` | in place (empty values) |
| `config/thesis_status.yaml` | in place (empty values) |
| `data/market/<date>.json` | `data/templates/market.json` |
| `data/valuation_refs/<T>.json` | `data/templates/valuation_refs/<T>.json` |
| `data/observations/<T>/<date>.json` | `data/templates/observation.json` |

Run `cockpit-check-inputs` after editing.
