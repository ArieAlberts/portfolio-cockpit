# Portfolio Cockpit — feedback status and open items

Updated: 2026-10-03 (score snapshot r9: 23 companies, 0 DISPLAY_READY, 23 DATA_CHECK; decision layer steps 1–9 built on `feature/decision-layer`)

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
| Quality Drift (vs own baseline, 50 at inclusion) | **Implemented** (`cockpit-drift`). Profiles for all six company types, like-for-like periods, immutable revisions. Exactly 50.0 for all 23 until the first observation arrives. |
| Valuation | **Implemented** (`cockpit-valuation`). Profiles, NOT_APPLICABLE rules, formula registry, own-history/peer references. All 23 are `NO_MARKET_DATA` until market data is supplied. |
| Data Confidence | Implemented for targets and peer inputs (threshold 80 gives DATA_CHECK). Warning codes are now a fixed contract (`decision_layer/warnings.py`). |
| Portfolio Risk | **Implemented.** `PORTFOLIO IMPACT -30%`, sector weights, market/sector/single-stock/combined scenarios. Needs `config/positions.yaml`. |
| Decision Engine | **Implemented** (`cockpit-decide`). Refuses to run until positions and thesis status are filled in. |
| Dashboard | **Implemented** (`scripts/build_dashboard.py` → `out/dashboard.html`). |
| Dry-run rebalance simulator and signal log | **Implemented** (`cockpit-simulate`, `cockpit-evaluate-signals`). |

## Open — high priority

### Decision layer — owner inputs and review
The decision layer (steps 1–9 of `docs/HANDOFF_DECISION_LAYER.md`) is built; see `docs/DECISION_LAYER.md`. Run `cockpit-check-inputs` to see what is still missing. Owner inputs required (templates in `data/templates/`; no invented numbers):

- `config/positions.yaml`: current weights, sector, optional beta. Sector names must match `config/risk_scenarios.yaml` (`Financials`, `Materials`) or the scenarios should be adjusted.
- `config/thesis_status.yaml`: INTACT / WATCH / BROKEN per ticker.
- `data/market/<date>.json` and `data/valuation_refs/<ticker>.json`.
- `data/observations/<ticker>/<date>.json`: first fundamental update after each baseline.

Owner review:

- Confirm the FINANCIAL_SERVICES (ABX) valuation profile: forward P/E 0.4, P/E 0.3, P/B 0.3.
- Confirm decision limits (10% position, 20% overweight band, 30% sector, 3 pp impact, FQ floor 35) and drift full_scale/dead_band values.
- Confirm each baseline's period basis (H1 or Q) in `config/quality_drift.yaml`.

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
- Add `CHANGELOG.md` for method decisions and material score changes.
- Move `docs/IMPLEMENTATION_PROMPT.md` to `docs/process/` once the build phase ends; `reference/` was removed after decision-layer step 9.

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
