# Data Confidence first pass — 2026-10-03

Data Confidence is now separated into four explicit components:

- **Completeness — 30%**
- **Source quality — 30%**
- **Freshness — 20%**
- **Consistency — 20%**

## Current state

For all 23 companies:
- source quality is currently 100 because the baseline is sourced from an official issuer document, regulatory filing or equivalent primary source;
- freshness is currently 100 because the baseline snapshots are less than 120 days old;
- completeness is calculated from weighted company-type component presence;
- consistency remains **PENDING** until an explicit cross-check is recorded.

Because consistency is unknown, the final Data Confidence score remains `null` and status remains `DATA_CHECK`.

The model does **not** treat a missing consistency assessment as zero or as 100.

## Weighted completeness

This is not a simple count of JSON sections. It uses the same component weights as the company type.

Examples:

- a general operating company missing the 25% balance-sheet component receives at most 75 completeness;
- an insurer missing underwriting quality loses the insurer's 25% underwriting weight;
- a pre-revenue company is evaluated on liquidity, dilution, regulatory progress, execution and commercial validation rather than industrial earnings metrics.

## Cross-check standard

A future consistency score should use:

- 100: regulatory filing + primary issuer release cross-checked;
- 90: two primary issuer documents cross-checked;
- 70: internal arithmetic/cross-footing only;
- null: single source not yet explicitly checked;
- 0: material unresolved conflict.

This keeps the confidence score auditable and prevents a single official document from being treated as independently corroborated.
