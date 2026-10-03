# Scoring method decision — 2026-10-03

The methodology mismatch found in the audit is resolved.

## Selected method

Portfolio Cockpit now uses:

```
clipped_mean_std_zscore
```

For each metric, the peer reference distribution uses:
- arithmetic peer mean;
- population standard deviation;
- the target company is excluded from the reference distribution;
- the resulting z-score is clipped to +/-3;
- lower-is-better metrics have their sign inverted.

This matches the existing implementation and is more stable than median/MAD for the small peer groups currently available.

## Minimum sample

A metric now requires at least **4 aligned peer observations** before it can contribute to Fundamental Quality.

The previous threshold of 3 was too permissive for small peer sets.

## Weighted readiness

A company must also cover at least **70% of its fixed company-type quality components**.

Component weights come from `config/company_types.yaml`.

A component counts as covered only when at least one mapped metric in that component has:
- an eligible target value;
- at least 4 aligned, definition-compatible peer values.

## Production gate

Even if peer/component coverage passes, a production Fundamental Quality score is not published until Data Confidence is populated and is at least 80.

Therefore, current candidate calculations remain research outputs only.
