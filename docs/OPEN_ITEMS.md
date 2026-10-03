# Portfolio Cockpit — feedback status and open items

Updated: 2026-10-03 (main @ `19c3605`, score snapshot r9: 23 companies, 0 DISPLAY_READY, 23 DATA_CHECK)

## Incorporated

- Sample standard deviation, minimum four production peers and +/-3 clipping with raw z retained.
- Leave-one-out sensitivity with STABLE, PEER_SENSITIVE and UNSTABLE classes; only STABLE can publish.
- Required components by company type, separate US P&C insurer model and weighted metric slots inside components.
- Reproducible `cockpit-score` pipeline with exact peer tickers, SHA-256 provenance, semantic reproducibility hash and immutable snapshots.
- Central metric aliases, directions and kinds in `config/score_metrics.yaml`.
- Central config validation, now including peer-universe method and minimum consistency.
- Hypothesis properties for mean=50, monotonicity, clipping and minimum peer count.
- Compile/smoke CI plus a local pytest compile guard.
- Target/peer monitoring, retries, degraded-source state, idempotent events, PENDING_PEERS and the permanent no-live-execution boundary.

## Implementation status per axis

The five axes are separated **conceptually** (README, ARCHITECTURE). Their **implementation maturity** differs strongly:

| Axis | Status |
|---|---|
| Fundamental Quality (peer-relative) | Implemented. Full pipeline, gates, provenance and immutable revisions. |
| Quality Drift (vs own baseline, 50 at inclusion) | **Stub.** Only `drift_from_weighted_signals()`. Baselines exist for all 23 companies; there are no observations, no drift profiles and no output history. |
| Valuation | **Stub.** Only `valuation_score_from_weighted_z()`. There are no market inputs, metric profiles, NOT_APPLICABLE rules or output. |
| Data Confidence | Implemented for targets and peer inputs (threshold 80 gives DATA_CHECK). Warning codes are not yet a fixed contract. |
| Portfolio Risk | **Stub.** Only `portfolio_impact()`. There are no scenarios, sector weights or current position weights. |
| Decision Engine | **Missing.** |
| Dashboard | **Missing.** |
| Dry-run rebalance simulator and signal log | **Missing** (only `ProposedOrderTicketBuilder` and the execution boundary exist). |

## Open — high priority

### Decision layer (parallel track; independent of peer data)
Build according to `docs/HANDOFF_DECISION_LAYER.md`, steps 1–9, in package `src/portfolio_cockpit/decision_layer/` without touching FQ-hashed files:

1. Package skeleton, config loader and immutable-revision writer.
2. Quality Drift engine (baselines + `data/observations/`, drift profiles per company type, like-for-like periods).
3. Valuation engine (`data/market/`, `data/valuation_refs/`, NOT_APPLICABLE rules; negative P/E or EV/EBITDA never counts as cheap).
4. Data Confidence warning contract (STALE_DATA, SOURCE_CONFLICT, UNSUITABLE_METRIC, MISSING_DATA, CALCULATION_ANOMALY, PERIOD_MISMATCH).
5. Portfolio Risk: `PORTFOLIO IMPACT -30%`, sector weights, market/sector/single-stock/combined scenarios.
6. Decision Engine: ADD_CANDIDATE / HOLD / NO_ADD / REVIEW_REDUCE / THESIS_REVIEW / DATA_CHECK. Driven by Quality Drift; Fundamental Quality is context only when DISPLAY_READY.
7. Static dashboard with separate Drift, Fundamental Quality and Valuation blocks, plus drill-down.
8. Dry-run simulator and append-only signal log with forward-return evaluation.
9. CI smoke tests and documentation.

Owner inputs required (templates and validators are generated first; no invented numbers):

- `config/positions.yaml`: current weights, sector, optional beta.
- `config/thesis_status.yaml`: INTACT / WATCH / BROKEN per ticker.
- `data/market/<date>.json` and `data/valuation_refs/<ticker>.json`.
- `data/observations/<ticker>/<date>.json`: first fundamental update after each baseline.

### ASR
- Capital strength now has four EU Solvency-II peers, but total weighted component coverage is still only 55%.
- Harmonize insurer ROE definitions so profitability can become scoreable.
- Expand value-per-share evidence where definitions are sufficiently consistent.

### PLMR
- Add a comparable US statutory capital metric across at least four specialty-P&C peers. Start with net-written-premium-to-surplus (broader disclosure) and add RBC as a second alias where available.
- Fix the period basis (FY/TTM) before collecting data; statutory capital data is mainly annual.
- Prefer TTM/full-year underwriting and profitability evidence where H1 seasonality materially distorts comparison.

### WKL and ESI required components
- WKL: four comparable peers for leverage and for profitability/capital efficiency.
- ESI: four comparable balance-sheet peers; then re-assess sensitivity.

### Peer and period rigor
- Define a stable core peer set per company where practical.
- Keep PEER_SET_VARIES_BY_METRIC visible when overlap is weak.
- Add preferred reporting period and seasonal-exposure metadata by company type.

### Calculation provenance
- Standardize machine-readable calculation formulas (whitelisted formula registry, no `eval`).
- Recalculate stored values from formulas and block CALCULATION_MISMATCH above tolerance.

## Open — medium priority

### Absolute anchors
Add absolute company-type quality thresholds beside relative peer scores, e.g. insurer combined ratio/ROE and operating-company ROIC/leverage. WKL (diagnostic FQ ≈16.5 and STABLE against an elite information-services peer set) is the first test case: a low relative score must not be read as "weak company" without absolute context.

### Presentation
Generate score class, sensitivity band, peer count, component coverage, confidence and deterministic display text from the pipeline.

### Monitoring production setup
Configure SEC-compliant COCKPIT_USER_AGENT and optional COCKPIT_HEARTBEAT_URL, then inspect the first complete production poll and false-positive rate. All 23 targets are still `NOT_YET_POLLED`.

### Automatic standardization
Detected filings should eventually create a draft normalized snapshot, but validation must remain mandatory before scoring. These drafts can also feed `data/observations/` for Quality Drift after validation.

### Documentation hygiene
- `docs/ARCHITECTURE.md` says "50 = relevant peer median"; the implementation uses the peer **mean**. Correct the text.
- Add `CHANGELOG.md` for method decisions and material score changes.
- Move `docs/IMPLEMENTATION_PROMPT.md` to `docs/process/` once the build phase ends; remove `reference/` after decision-layer step 9.

## Phase 1 — definition of done

Phase 1 is complete only when **all** of the following hold:

- The monitor has completed a first target and peer poll, and fingerprints are persisted.
- At least one company earns DISPLAY_READY Fundamental Quality under current gates without manual exceptions: required components, at least 4 peers per metric, slot coverage, Data Confidence ≥80, peer-input confidence ≥80, STABLE.
- Every DISPLAY_READY score is reproducible via `cockpit-score` with full provenance and hashes.
- Absolute anchors are shown beside the relative peer score.
- Quality Drift, Valuation and the Decision Engine produce an output for **all 23 positions** with full provenance. DATA_CHECK is a valid output.
- The dashboard shows Drift, Fundamental Quality and Valuation as separate blocks, plus `PORTFOLIO IMPACT -30%` and the decision state.
- No monitoring, scoring or decision route can trigger live execution.

## Decisions recorded

- **Repository visibility:** the repository stays public by owner decision (2026-10-03). This is not an open item.
- **Decision driver:** the Decision Engine is driven by Quality Drift. Fundamental Quality only acts as a floor/context when DISPLAY_READY.
- **Storage:** Git with immutable JSON revisions; no runtime database for now.
- **Tests:** keep the hybrid approach (unit fixtures + real-dataset contract tests + offline integration tests); do not move to mock-only tests.

## Deferred

- Runtime database: retain Git for audited low-frequency fundamentals; consider DuckDB/SQLite/TimescaleDB only for larger telemetry or intraday series.
- Robust median/MAD normalization: reconsider once a metric structurally has about 8 or more good peers.
- Process hygiene: keep model-decision history current (see CHANGELOG item above).
