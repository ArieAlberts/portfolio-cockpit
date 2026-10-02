# Fundamental Quality scoring method

## Objective

The Fundamental Quality score answers:

> How strong are the current fundamentals of this company relative to a relevant peer universe?

It does **not** answer whether the stock is cheap and it does **not** measure the change since the portfolio baseline.

## Inspiration and adaptation

The approach is inspired by established quality-factor methodology that standardizes fundamental variables using z-scores and reverses the sign for variables where lower is better, such as leverage.

MSCI's Sector Neutral Quality framework is a useful reference because it explicitly evaluates quality relative to peers within the same sector and uses high profitability, low leverage and low earnings variability as quality descriptors.

Portfolio Cockpit extends the concept with business-model-specific variables, while preserving the same core principles:

- standardize comparable metrics;
- invert adverse metrics;
- control outliers;
- combine standardized signals;
- block a score when critical data coverage is inadequate.

Reference:
- MSCI World Sector Neutral Quality Index: https://www.msci.com/indexes/index/705169/msci-world-sector-neutral-quality-index
- MSCI Quality Indexes Methodology: https://www.msci.com/indexes/documents/methodology/2_MSCI_Quality_Indexes_Methodology_20220519.pdf

## Reference distribution

Portfolio Cockpit uses the **peer companies only** to create the reference distribution.

For metric x:

```text
z = (target - peer_mean) / peer_standard_deviation
```

For a metric where lower is better:

```text
z = -((target - peer_mean) / peer_standard_deviation)
```

The z-score is clipped at the configured limit (default +/-3).

## Score conversion

After weighting valid z-scores:

```text
Fundamental Quality = clamp(50 + 25 * weighted_z, 0, 100)
```

Interpretation:

- 50: approximately neutral versus the peer reference distribution
- 75: approximately +1 weighted standard deviation
- 25: approximately -1 weighted standard deviation
- 100 / 0: capped extreme values

This is a relative score. It must always be displayed together with:
- peer universe
- metric coverage
- peer-confidence flag
- Data Confidence

## Missing data

The system does not silently turn missing information into zero.

Metrics with missing or invalid data are omitted and weights are re-normalized only if minimum weighted coverage is achieved.

Default:

```text
minimum weighted metric coverage = 70%
```

Below that threshold:

```text
fundamental_quality_score = null
status = PEER_DATA_CHECK
```

## Important separation

A price change:
- may change Valuation;
- may not change Fundamental Quality;
- may not change Quality Drift.

A new company report:
- may change Fundamental Quality;
- may change Quality Drift;
- may change Valuation if earnings/cash-flow inputs change.
