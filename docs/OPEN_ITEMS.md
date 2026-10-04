# Portfolio Cockpit — feedback status and open items

Updated: 2026-10-04 (score snapshot r12: 23 companies, 1 DISPLAY_READY (ASR), 22 DATA_CHECK; decision layer steps 1–9 merged in #6/#7)

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
- ASR EU Solvency-II capital strength plus harmonized IFRS common-equity ROE; company-defined ROE remains blocked.
- Calculation validation (#10): stored `calculation` strings are recomputed with a safe AST evaluator; a score-eligible `CALCULATION_MISMATCH` blocks publication.
- Context-only absolute anchors (#8) beside the peer score for general operating companies.
- PLMR capital strength locked to the FY2025 US statutory basis (#4).

## Implementation status per axis

The five axes are separated **conceptually** (README, ARCHITECTURE). Their **implementation maturity** differs strongly:

| Axis | Status |
|---|---|
| Fundamental Quality (peer-relative) | Implemented. Full pipeline, gates, provenance, calculation validation and immutable revisions. First DISPLAY_READY: ASR 66.1 (STABLE, 75% coverage) in r12. |
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
- **DISPLAY_READY** in r12: Fundamental Quality 66.1, STABLE, 75% weighted component coverage (harmonized H1 IFRS common-equity ROE for ASR plus five peers).
- Value-per-share remains partial; share-count coverage is usable but insufficient by itself to carry the component.

### PLMR
- Period basis fixed: capital strength uses FY2025 statutory data (#4). Net-written-premium-to-surplus is collected, but `capital_strength` still lacks four comparable peers, so PLMR stays DATA_CHECK (`MISSING_REQUIRED_COMPONENT:capital_strength`). Add peers, and RBC as a second alias where available.
- Prefer TTM/full-year underwriting and profitability evidence where H1 seasonality materially distorts comparison.

### WKL and ESI required components
- WKL: four comparable peers for leverage and for profitability/capital efficiency.
- ESI: four comparable balance-sheet peers; then re-assess sensitivity.

### Peer and period rigor
- Define a stable core peer set per company where practical.
- Keep PEER_SET_VARIES_BY_METRIC visible when overlap is weak.
- Add preferred reporting period and seasonal-exposure metadata by company type.

### Calculation provenance
- Done for peer datasets (#10) and for valuation formulas (whitelisted registry in `decision_layer/formulas.py`). Keep new peer data in recomputable `calculation` form; a value taken directly from a report records that value (e.g. `0.88 * 100`) and keeps the underlying amounts in `notes`.

## Open — medium priority

### Absolute anchors
Implemented for GENERAL_OPERATING_COMPANY as context only (#8, `config/absolute_anchors.yaml`, PILOT thresholds). WKL meets all seven anchors (STRONG) while its relative diagnostic FQ is ≈16.5. Open:
- Most other GOCs still show MISSING for most anchor metrics; fill the canonical metrics in their peer datasets.
- Add economically appropriate profiles for insurers, miners, financial services and pre-revenue companies; do not copy GOC thresholds.
- Show anchors in the decision-layer dashboard next to the FQ block.

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

Phase 1 is complete only when **all** of the following hold (status 2026-10-04 in brackets):

- The monitor has completed a first target and peer poll, and fingerprints are persisted. [open: still NOT_YET_POLLED]
- At least one company earns DISPLAY_READY Fundamental Quality under current gates without manual exceptions: required components, at least 4 peers per metric, slot coverage, Data Confidence ≥80, peer-input confidence ≥80, STABLE. [done: ASR]
- Every DISPLAY_READY score is reproducible via `cockpit-score` with full provenance and hashes. [done]
- Absolute anchors are shown beside the relative peer score. [done in the FQ snapshot for GOCs; not yet on the dashboard]
- Quality Drift, Valuation and the Decision Engine produce an output for **all 23 positions** with full provenance. DATA_CHECK is a valid output. [drift and valuation yes; decisions wait for `positions.yaml` and `thesis_status.yaml`]
- The dashboard shows Drift, Fundamental Quality and Valuation as separate blocks, plus `PORTFOLIO IMPACT -30%` and the decision state. [done; impact and state fill in once owner inputs exist]
- No monitoring, scoring or decision route can trigger live execution. [done; enforced by tests]

## Decisions recorded

- **Repository visibility:** the repository stays public by owner decision (2026-10-03). This is not an open item.
- **Decision driver:** the Decision Engine is driven by Quality Drift. Fundamental Quality only acts as a floor/context when DISPLAY_READY.
- **Current weights:** `config/positions.yaml` holds only actual current positions and cash from a broker export (owner decision 2026-10-04). Target weights are never used as current weights; until the export exists the Decision Engine refuses to run.
- **Score-adjusted target:** decisions compare current weight with `score_adjusted_target_pct` (base × Quality Drift multiplier, gated and capped; `config/target_adjustment.yaml`), not with base. Base targets change only by the owner; a deliberate base change may add a new baseline file (`rebaseline_of`), never an edit.
- **Storage:** Git with immutable JSON revisions; no runtime database for now.
- **Tests:** keep the hybrid approach (unit fixtures + real-dataset contract tests + offline integration tests); do not move to mock-only tests.

## Deferred

- Runtime database: retain Git for audited low-frequency fundamentals; consider DuckDB/SQLite/TimescaleDB only for larger telemetry or intraday series.
- Robust median/MAD normalization: reconsider once a metric structurally has about 8 or more good peers.
- Process hygiene: keep model-decision history current (see CHANGELOG item above).
