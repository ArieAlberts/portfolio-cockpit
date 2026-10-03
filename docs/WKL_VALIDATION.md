# WKL validation case

## Purpose

Wolters Kluwer is the first validation company for the Phase 1 fundamental model.

The baseline is anchored to the official 2026 Half-Year Results published on 5 August 2026, covering the period ended 30 June 2026.

## Baseline rule

On creation of the first validated snapshot:

```text
Quality Drift = 50.0
```

This is not a quality judgment. It is the neutral starting point for future fundamental change.

## What is stored

The baseline includes:

- net debt and net-debt/EBITDA
- gross debt and available cash/liquidity
- ROIC and adjusted operating margin
- adjusted free cash flow and cash conversion
- organic and recurring revenue growth
- adjusted EPS per share
- diluted share count
- buyback/cancellation information
- full-year guidance

## Source facts captured

The official H1 report states, among other items:

- revenue: EUR 3,033m
- organic revenue growth: 5%
- recurring revenue organic growth: 7%
- adjusted operating margin: 29.4%
- adjusted free cash flow: EUR 533m
- net debt: EUR 4,024m
- net debt / EBITDA: 2.0x
- ROIC: 18.2%
- diluted adjusted EPS: EUR 2.83
- diluted weighted-average shares: 225.3m
- cash conversion: 91%
- net cash available: EUR 1,211m

## Important interpretation

Fundamental Quality is **not** assigned yet.

It requires a validated peer universe and peer normalization. Until that exists:

```text
fundamental_quality_score = null
status = PENDING_PEER_NORMALIZATION
```

This prevents the system from inventing an apparently precise 0–100 quality score without comparative data.

## Next validation step

1. Define the peer universe for WKL.
2. Collect the same comparable metrics for those peers.
3. Normalize metrics within the peer group.
4. Calculate component scores.
5. Calculate WKL Fundamental Quality.
6. Preserve Quality Drift at 50 until a later validated WKL fundamental update is available.

Market-price movement alone must never change Quality Drift.

## Absolute-anchor context

WKL is also the pilot case for the separate absolute-anchor layer.

All seven configured baseline guardrails are currently met: leverage, ROIC, adjusted operating margin, cash conversion, organic revenue growth, recurring-revenue share and diluted share-count change.

This result is explanatory context only. It does not change WKL's peer-relative Fundamental Quality diagnostic, its component-coverage gate or its `DATA_CHECK` status.
