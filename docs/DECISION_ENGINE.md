# Decision Engine v1

The Decision Engine combines separate analytical axes without merging them into one score.

States:

- `ADD_CANDIDATE`
- `HOLD`
- `NO_ADD`
- `REVIEW_REDUCE`
- `THESIS_REVIEW`
- `DATA_CHECK`

## Rule priority

1. Data confidence below 80, missing confidence, or missing Quality Drift -> `DATA_CHECK`.
2. Broken thesis -> `THESIS_REVIEW`.
3. Material Quality Drift deterioration -> `REVIEW_REDUCE`.
4. Missing valuation -> configured fallback, currently `HOLD`, with `VALUATION_PENDING`.
5. Strong Quality Drift + attractive valuation -> `ADD_CANDIDATE`.
6. Acceptable Quality Drift + expensive valuation -> `NO_ADD`.
7. Otherwise -> `HOLD`.

Fundamental Quality is optional context until peer-normalized scores are `DISPLAY_READY`. If a score exists, it can block `ADD_CANDIDATE` below the configured floor.

All thresholds are in `config/decision.yaml`.

## Safety boundary

Every result has `execution_effect: NONE`. No decision state can submit, modify or cancel a live broker order.

## CLI

```bash
cockpit-decision
cockpit-decision --write
```

The pipeline reads valuation and thesis snapshots if present. Their absence is explicit in the output rather than silently fabricated.
