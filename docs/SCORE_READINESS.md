# Fundamental Quality readiness — 2026-10-03

## Result

All 23 portfolio companies now have peer datasets, but **none is production-ready for a published Fundamental Quality score yet**.

The stricter scoring gate now requires:
- at least **4 aligned peer observations per metric**;
- at least **70% weighted company-type component coverage**;
- no hard peer-universe block;
- Data Confidence of at least **80**.

## Current coverage

| Ticker | Weighted component coverage | Peer gate |
|---|---:|---|
| ASR | 75% | PASS |
| ADM.L | 0% | HARD BLOCK |
| WKL | 30% | DATA CHECK |
| CAP.PA | 0% | DATA CHECK |
| IMCD | 0% | DATA CHECK |
| CRDA.L | 0% | HARD BLOCK |
| ROR.L | 0% | DATA CHECK |
| EMN | 15% | DATA CHECK |
| WSM | 0% | DATA CHECK |
| DKS | 0% | HARD BLOCK |
| TXRH | 0% | DATA CHECK |
| SNA | 15% | DATA CHECK |
| MSM | 0% | HARD BLOCK |
| PLMR | 50% | DATA CHECK |
| MOD | 15% | DATA CHECK |
| FUL | 0% | HARD BLOCK |
| POWL | 15% | DATA CHECK |
| ESI | 25% | DATA CHECK |
| ABX | 0% | HARD BLOCK |
| ERO | 0% | HARD BLOCK |
| TMDX | 0% | DATA CHECK |
| LEU | 0% | DATA CHECK |
| OKLO | 0% | DATA CHECK |

Only **ASR** currently clears the 70% peer/component coverage gate, at 75%.

That does **not** make ASR production-ready, because Data Confidence is still pending.

## ASR research candidate

Using only the three components that currently pass the stricter four-peer rule:

- Solvency II ratio — capital strength
- combined ratio — underwriting quality
- operating earnings growth — profitability

the current clipped mean/std peer z-score model produces a **research-only candidate score of about 62.1**.

This value is deliberately **not written into the ASR baseline as Fundamental Quality**.

Reasons:
- Data Confidence has not been validated;
- 25% of the configured insurer component weight is not covered;
- company-defined operating earnings remain less standardized than regulatory capital and combined ratio.

## Why WKL is not yet score-ready

Under the old three-peer rule, several WKL metrics appeared usable. With the stricter four-peer minimum:
- organic-like revenue growth remains usable;
- adjusted EPS growth remains usable;
- margin, FCF margin and share-count change do not yet have four aligned peer observations;
- leverage also lacks enough aligned peers.

Weighted coverage therefore falls to 30%.

This is intentional. A smaller number of trustworthy inputs is preferable to a precise-looking score built on a thin reference distribution.

## Next task

Populate Data Confidence deterministically and expand high-priority peer datasets until more companies cross the 70% component-coverage threshold.
