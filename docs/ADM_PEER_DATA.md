# Admiral peer-data review

The direct listed peer universe is too small for a robust peer-normalized Fundamental Quality score.

## What changed

Saga is now context-only. Its in-house insurer AICL was sold to Ageas on 1 July 2025, so Saga no longer represents the same underwriting business model.

Sabre is the closest listed UK motor-underwriting peer.

Aviva is retained only as a broad comparator after the Direct Line acquisition.

## Result

```text
fundamental_quality_score = null
status = PEER_DATA_CHECK
reason = INSUFFICIENT_DIRECT_PEERS
```

This is deliberate. The repository must prefer no score over a statistically fragile score built from unlike businesses.
