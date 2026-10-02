# Implementation prompt for coding agent

Use this repository as the starting point for Phase 1 of Portfolio Cockpit.

## Objective

Implement a fundamental portfolio-monitoring engine. Do not implement intraday trading or live broker orders.

## Non-negotiable concepts

Create five separate concerns:

1. Fundamental Quality
2. Quality Drift
3. Valuation
4. Data Confidence
5. Portfolio Risk

Never use a single variable for multiple meanings.

### Fundamental Quality
- Scale: 0–100.
- 50 = median of relevant peer/company-type group.
- Sector/company-type normalized.
- Market-price changes alone never change this score.

### Quality Drift
- Every company receives an immutable starting baseline.
- Score at baseline is exactly 50.0.
- >50 = fundamental improvement versus its own baseline.
- <50 = fundamental deterioration versus its own baseline.
- Market-price changes alone never change this score.

### Valuation
- Scale: 0–100.
- Higher score = more attractive valuation.
- Independent of Fundamental Quality.
- Price changes may change Valuation.

### Data Confidence
- Scale: 0–100.
- Track completeness, source quality, freshness and consistency.
- If below 80, downstream decision state must be DATA_CHECK.

### Portfolio Risk
- Separate from fundamental scores.
- Support configurable scenario shocks.

## Company-type profiles

Implement at least:
- GENERAL_OPERATING_COMPANY
- INSURER
- CYCLICAL_MINING
- PRE_REVENUE_DEVELOPMENT
- FINANCIAL_SERVICES

Read weights and metrics from `config/company_types.yaml`.
Do not hardcode company-type weights inside scoring functions.

## Phase 1 validation tickers

Validate only:
- WKL
- ASR
- OKLO

Do not roll portfolio-wide until the three profiles are reviewed.

## Required modules

Implement:

```text
src/portfolio_cockpit/
  domain/
    models.py
  scoring/
    quality.py
    drift.py
    valuation.py
    confidence.py
    portfolio_risk.py
  adapters/
    fundamentals.py
    portfolio.py
  future/
    ibkr.py
    trading.py
    order_manager.py
```

The `future/` modules are interfaces/stubs only.

## Provenance

Every input must support:
- source
- source_type
- as_of_date / source_date
- retrieved_at
- period
- raw_value
- unit
- currency
- calculation_method
- confidence

No final displayed metric may exist without reconstructable provenance.

## Warnings

Support at least:
- STALE_DATA
- SOURCE_CONFLICT
- UNSUITABLE_METRIC
- MISSING_DATA
- CALCULATION_ANOMALY

## Historical data

Do not overwrite:
- baselines
- fundamental snapshots
- score snapshots

Every score change must be auditable.

## Minimum tests

1. Baseline Quality Drift is exactly 50.
2. Price-only changes do not change Quality Drift.
3. Price-only changes do not change Fundamental Quality.
4. Price changes may change Valuation.
5. Insurer profile does not use industrial FCF/EV-EBITDA logic as primary quality inputs.
6. Pre-revenue profile does not interpret negative P/E as cheap.
7. Missing critical data can produce DATA_CHECK.
8. Stale data lowers Data Confidence.
9. 5% position with -30% shock produces -1.5 percentage-point impact.
10. Baseline cannot be overwritten.
11. Score history is append-only.
12. No Phase 1 module can place a broker order.

## Workflow

Before editing:
1. inventory current files,
2. state planned changes,
3. state migrations/schema changes,
4. state preserved behavior,
5. list tests.

Then implement incrementally.
