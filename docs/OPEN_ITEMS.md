# Portfolio Cockpit — feedback status and open items

Updated: 2026-10-03

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

## Open — high priority

### ASR
- Capital strength now has four EU Solvency-II peers, but total weighted component coverage is still only 55%.
- Harmonize insurer ROE definitions so profitability can become scoreable.
- Expand value-per-share evidence where definitions are sufficiently consistent.

### PLMR
- Add a comparable US statutory capital metric across at least four specialty-P&C peers: RBC or net-written-premium-to-surplus.
- Prefer TTM/full-year underwriting and profitability evidence where H1 seasonality materially distorts comparison.

### Peer and period rigor
- Define a stable core peer set per company where practical.
- Keep PEER_SET_VARIES_BY_METRIC visible when overlap is weak.
- Add preferred reporting period and seasonal-exposure metadata by company type.

### Calculation provenance
- Standardize machine-readable calculation formulas.
- Recalculate stored values from formulas and block CALCULATION_MISMATCH above tolerance.

## Open — medium priority

### Absolute anchors
Add absolute company-type quality thresholds beside relative peer scores, e.g. insurer combined ratio/ROE and operating-company ROIC/leverage.

### Presentation
Generate score class, sensitivity band, peer count, component coverage, confidence and deterministic display text from the pipeline.

### Monitoring production setup
Configure SEC-compliant COCKPIT_USER_AGENT and optional COCKPIT_HEARTBEAT_URL, then inspect the first complete production poll and false-positive rate.

### Automatic standardization
Detected filings should eventually create a draft normalized snapshot, but validation must remain mandatory before scoring.

## Deferred

- Runtime database: retain Git for audited low-frequency fundamentals; consider DuckDB/SQLite/TimescaleDB only for larger telemetry or intraday series.
- Repository privacy/process hygiene: keep personal portfolio data appropriately separated and maintain changelog/model-decision history.
