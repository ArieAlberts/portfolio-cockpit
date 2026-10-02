# Roadmap

## Phase 1 — Fundamental cockpit
Status: current

Deliver:
- company-type profiles
- Fundamental Quality
- Quality Drift
- Valuation
- Data Confidence
- immutable history
- audit trail
- WKL / ASR / OKLO validation
- portfolio shock calculation

## Phase 2 — Portfolio integration

Deliver:
- current positions
- target weights
- sector exposure
- cash exposure
- portfolio stress scenarios
- dry-run rebalance simulator
- read-only IBKR account/position adapter

No order placement.

## Phase 3 — Trading research

Deliver:
- VWAP
- standard-deviation bands
- mean-reversion/trend regime detection
- trading sleeve
- position sizing
- transaction-cost model
- backtest engine
- paper-trading engine

No live order placement.

## Phase 4 — Human-reviewed trade preparation

Deliver:
- proposed order tickets
- expected size, limit, stop and rationale
- risk impact before/after proposed trade
- explicit paper-trading support
- read-only IBKR reconciliation after the user trades manually

## Permanent rule

There is no phase for automated live execution.

The repository must never submit, modify or cancel a live brokerage order based on selected, synthesized, scored or inferred information.
