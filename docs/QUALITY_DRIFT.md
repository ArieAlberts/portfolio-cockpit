# Quality Drift v1

Quality Drift measures change versus each company's own immutable baseline.

## Invariants

- Every company starts at exactly **50.0**.
- Daily price movement never changes Quality Drift.
- Only validated evidence from an allowed trigger may update it.
- Component signals are normalized to **-1..+1** upstream.
- Missing components are neutral (0); available components are **not** reweighted.
- Output is analytical only and always has `execution_effect: NONE`.

Formula:

```text
Quality Drift = clamp(50 + 50 * sum(component_weight * component_signal), 0, 100)
```

Allowed triggers are configured in `config/quality_drift.yaml` and currently include official results, official trading updates, regulatory filings, material guidance changes and confirmed thesis events.

## Why normalized component signals first?

The 23 historical baselines are rich but not yet stored in one uniform raw-metric schema. v1 therefore makes the evidence-normalization boundary explicit instead of guessing metric equivalence. A future filing normalizer can produce validated component signals without changing the Drift calculation.

## CLI

```bash
cockpit-drift
cockpit-drift --write
```

Without a validated signal file, a company remains at its immutable baseline score of 50.0 with status `BASELINE`.
