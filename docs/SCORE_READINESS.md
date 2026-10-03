# Fundamental Quality readiness — 2026-10-03

## Current production state

Two companies currently pass every display gate:

- **ASR — 62.1 / 100**
- **PLMR — 40.2 / 100**

A score requires:
- at least **4 definition-compatible peer observations per metric**;
- at least **70% weighted company-type component coverage**;
- no hard peer-universe block;
- target Data Confidence >=80;
- peer-input confidence >=80.

## WKL progress

WKL has improved from 30% to **50% weighted component coverage**.

Covered components:
- cash-flow quality — H1 free-cash-flow margin now has four aligned peers;
- growth/stability — organic-like revenue growth;
- value per share — adjusted EPS growth.

Still uncovered:
- balance sheet;
- profitability/capital efficiency.

The S&P Global H1 FCF observation is now usable because both parts of the ratio use the same historical H1 basis:

```
H1 free cash flow = $2,249m
H1 as-reported revenue = $8,318m
FCF margin = 27.04%
```

The previous version correctly blocked S&P Global because it would have divided historical FCF including Mobility by pro-forma continuing-operations revenue. That mismatch has been removed rather than ignored.

WKL remains **blocked from a Fundamental Quality score** at 50% versus the required 70%.

## Why no near-period FactSet shortcut yet

FactSet publishes useful adjusted operating-margin data, but its fiscal periods do not exactly match WKL's January-June H1 period. The model will not silently promote a different fiscal period into a strict H1 peer observation merely to cross the 70% threshold.

The next WKL work should therefore focus on either:
- a defensible same-basis balance-sheet/leverage metric across at least four peers; or
- a formally defined near-period policy with an explicit confidence penalty, tested before use.
