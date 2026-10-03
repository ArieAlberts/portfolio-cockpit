# Portfolio Cockpit

A portfolio-monitoring and research system that keeps four concepts strictly separated:

1. **Fundamental Quality (0–100)** — absolute/peer-relative business quality.
2. **Quality Drift (baseline 50)** — deterioration or improvement versus the company's own starting snapshot.
3. **Valuation (0–100)** — current market valuation, independent of business quality.
4. **Data Confidence (0–100)** — reliability, completeness and freshness of the underlying data.

## Permanent execution boundary

**This repository is decision-support only. It must never place, route, submit, modify or cancel live brokerage orders.**

No data selected, synthesized, scored or inferred by this repository may directly trigger execution in an Interactive Brokers account or any other broker.

The repository may later:
- read broker positions and account data,
- calculate portfolio exposures,
- generate research signals,
- simulate trades,
- backtest strategies,
- produce paper-trading instructions,
- produce a proposed order ticket for human review.

The repository must never:
- call a live-order endpoint,
- submit or cancel an order,
- switch itself from paper to live,
- infer approval from a score or signal,
- execute because a threshold was crossed.

Any real trade must be initiated separately by a human outside this repository.

## Phase 1 scope

Phase 1 validates the model on:
- WKL — general operating company
- ASR — insurer
- OKLO — pre-revenue/development company

## Key rules

- Daily price changes must never change Fundamental Quality or Quality Drift.
- Every company starts its own Quality Drift history at exactly **50.0**.
- Fundamental Quality uses sector/company-type appropriate metrics.
- Valuation is separate from quality.
- Missing/stale/conflicting data lowers Data Confidence.
- Historical snapshots are immutable.
- Every calculated value must be traceable to source, period and formula.
- **Live brokerage execution is permanently out of scope.**

## Intended architecture

```text
Fundamental data
      ↓
Fundamental Engine
      ↓
Portfolio Cockpit
      ↓
Trading Research / Signal Engine
      ↓
Risk & Simulation Engine
      ↓
Human-reviewed proposed order ticket
      ↓
STOP — no live broker execution in this repo
```

A future IBKR adapter may be read-only for positions/account/market data or paper-trading only.

## Decision layer

Quality Drift, Valuation, the Data Confidence warning contract, Portfolio Risk, the Decision Engine, a static dashboard and a dry-run simulator live in `src/portfolio_cockpit/decision_layer/`. See `docs/DECISION_LAYER.md` for commands, formulas and statuses. Start with `cockpit-check-inputs` to see which owner inputs are still missing.

## Automatic source monitoring

The repository includes a daily event-driven source monitor for all 23 portfolio companies. It detects changes in official issuer/SEC sources, records review events, and supports immutable versioned fundamental snapshots.

See `docs/AUTOMATIC_MAINTENANCE.md`.

A detected source change can never directly change a score or place an order.
