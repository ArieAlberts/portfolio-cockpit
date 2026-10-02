# Peer financial data standard

## Goal

Peer data must be comparable before it may enter the Fundamental Quality engine.

The repository stores the company's original definition and a standardized comparison class side-by-side. It never silently renames unlike measures as if they were equal.

## Required fields

Every company observation must carry:

- company/ticker
- reporting period and end date
- period alignment
- primary source URL and source type
- raw/source definition
- standardized comparison class
- value
- calculation method when derived
- score eligibility
- comparability notes when needed

## Strict rules

1. Missing data is never converted to zero.
2. H1, quarterly, FY and TTM periods are not mixed in a strict score unless a period-normalization method is explicitly implemented.
3. Adjusted operating margin and adjusted EBITDA margin are different comparison classes.
4. Company-defined "underlying" growth may be stored as organic-like growth, but the original definition must remain visible.
5. A numerator and denominator from different economic bases may not be combined.
6. Pro-forma/recast data must carry the basis in notes.
7. At least three peer values are required for a metric before z-score normalization.
8. A metric can be stored even when it is not score-eligible.

## WKL cohort

The first standardized peer file is:

`data/peers/WKL/2026-10-02.json`

The strict H1 data currently supports at least these comparison classes with three or more aligned peer observations:

- organic-like revenue growth
- adjusted EPS growth
- free-cash-flow margin
- diluted weighted-average share-count change
- adjusted operating margin (with explicit pro-forma caveat for SPGI)

Net-debt/EBITDA and cash conversion do not yet have enough aligned peer observations for a strict peer z-score.

FactSet's latest FY2026 figures are stored but excluded from strict H1 scoring because its fiscal year ended August 31, 2026.

S&P Global's H1 free cash flow is stored as a source fact but is not turned into a FCF margin against post-spin pro-forma revenue, because the economic bases differ.

## Why this is intentionally conservative

The purpose is auditability rather than maximizing metric count. A smaller set of truly comparable metrics is preferable to a larger score built from mismatched accounting definitions.
