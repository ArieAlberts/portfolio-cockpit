# Architecture

## Design principle

The system must not mix business quality, price, data reliability, portfolio risk or execution.

## Permanent no-live-execution invariant

This repository is an analytical and decision-support system.

It may ingest, select, normalize, synthesize and score information, but **no result produced by those processes may directly or indirectly cause a live brokerage order to be placed, changed or cancelled**.

The architecture must enforce a hard boundary:

```text
Research + portfolio data
          ↓
Fundamental Engine
          ↓
Valuation / Quality / Drift
          ↓
Portfolio Cockpit
          ↓
Trading Research
          ↓
Simulation / Paper Trading
          ↓
Proposed Order Ticket
          ↓
HUMAN REVIEW
          ↓
STOP IN THIS REPOSITORY
```

A live broker execution service must not exist in this codebase.

## Hard boundaries

### Fundamental Quality
- Peer/company-type normalized.
- 50 = relevant peer median.
- Must not change from market price alone.

### Quality Drift
- Each company begins at 50.0 at its own immutable baseline.
- Measures change versus its own baseline.
- Must not change from market price alone.

### Valuation
- May change daily with price and consensus/fundamental updates.
- Uses only economically meaningful metrics.

### Data Confidence
- Falls when inputs are stale, incomplete or conflicting.
- If below threshold, downstream decision state must be `DATA_CHECK`.

### Portfolio Risk
- Uses actual position weight and scenario shocks.
- Is analytical only.

## Broker integration boundary

Permitted future interfaces:
- `IBKRReadOnlyPortfolioAdapter`
- `MarketDataAdapter`
- `TradingSignalEngine`
- `RiskEngine`
- `PaperTradingAdapter`
- `ProposedOrderTicketBuilder`

Forbidden:
- live order placement
- live order modification
- live order cancellation
- automatic live execution
- automatic transition from paper to live
