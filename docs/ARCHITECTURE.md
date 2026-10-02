# Architecture

## Design principle

The system must not mix business quality, price, data reliability and portfolio risk.

```text
                    ┌─────────────────────┐
                    │ Fundamental Sources │
                    └──────────┬──────────┘
                               │
                      provenance + snapshots
                               │
                 ┌─────────────▼─────────────┐
                 │   Fundamental Engine      │
                 │                           │
                 │ Fundamental Quality       │
                 │ Quality Drift             │
                 │ Data Confidence           │
                 └─────────────┬─────────────┘
                               │
                 ┌─────────────▼─────────────┐
                 │     Valuation Engine      │
                 └─────────────┬─────────────┘
                               │
                 ┌─────────────▼─────────────┐
                 │    Portfolio Cockpit      │
                 └─────────────┬─────────────┘
                               │
                 ┌─────────────▼─────────────┐
                 │ Future Trading Layer      │
                 │ (not Phase 1)             │
                 └───────────────────────────┘
```

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
- Example: 5% weight × -30% shock = -1.5 percentage-point portfolio impact.

## Future interfaces

The codebase reserves interfaces for:

- `IBKRPortfolioAdapter`
- `MarketDataAdapter`
- `TradingSignalEngine`
- `RiskEngine`
- `OrderManager`

They must remain non-live during Phase 1.
