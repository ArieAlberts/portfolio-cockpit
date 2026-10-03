# Scoring method decision — revised 2026-10-03

## Selected method

Portfolio Cockpit uses:

```
clipped_mean_sample_std_zscore
```

For each metric:
- the arithmetic peer mean is the reference point;
- dispersion uses the **sample standard deviation** (n-1);
- the target company is excluded from the peer distribution;
- the directional z-score is clipped to +/-3;
- the unclipped z-score is retained for auditability;
- lower-is-better metrics invert the sign.

A score of 50 therefore means the target equals the **peer mean**, not the median.

## Minimum sample

A score-eligible metric requires at least 4 aligned, definition-compatible peer observations.

## Sensitivity

Every valid score calculation also runs leave-one-peer-out diagnostics per metric. Diagnostic runs may use 3 peers after one omission.

The result records:
- score_low;
- score_high;
- the most influential metric and peer;
- the largest score shift;
- STABLE if the band width is below 10 points;
- PEER_SENSITIVE from 10 up to 25 points;
- UNSTABLE at 25 points or wider.

Only STABLE can become DISPLAY_READY. PEER_SENSITIVE and UNSTABLE remain diagnostic/research outputs.

## Required components

Coverage >=70% is necessary but not sufficient. Each company type also has required components in `config/company_types.yaml`.

For insurers, both are mandatory:
- capital_strength;
- underwriting_quality.

This prevents an insurer from receiving a production quality score while capital strength is missing.

## Robust-method reconsideration

Median/MAD remains deferred while peer groups are small. Reconsider a robust reference distribution when a metric has at least 8 good peers.

## Clipping

Clipping is deliberate information loss. Each MetricScore retains both `unclipped_z_score` and clipped `z_score`, so an extreme signal remains visible even when its contribution is capped.
