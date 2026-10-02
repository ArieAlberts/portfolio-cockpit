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

No live trading.

## Phase 2 — Portfolio integration
Deliver:
- current positions
- target weights
- sector exposure
- cash exposure
- portfolio stress scenarios
- dry-run rebalance simulator
- read-only IBKR position/account adapter

Still no automated order placement.

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

## Phase 4 — IBKR execution
Only after validated Phase 3 results.

Deliver:
- IB Gateway/TWS API adapter
- order manager
- idempotent order state
- circuit breakers
- daily loss limits
- position limits
- disconnect/reconnect handling
- paper account first
- explicit switch for live account

The Fundamental Engine must remain independent from execution.
