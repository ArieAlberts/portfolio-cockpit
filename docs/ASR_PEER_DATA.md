# ASR insurer peer data review

This dataset standardizes H1 2026 financial observations for ASR and its diversified-insurer peer group.

File:

`data/peers/ASR/2026-10-03.json`

## Current scoring result

A fresh pipeline rebuild on this dataset makes ASR `DISPLAY_READY` without relaxing any production gate.

- Fundamental Quality: **66.1 / 100**
- weighted component coverage: **75%**
- covered components: capital strength, underwriting quality, profitability
- target data confidence: above the production threshold
- peer-input confidence: above the production threshold
- leave-one-out sensitivity: **STABLE**
- sensitivity band: approximately **63.7–71.9**
- execution effect: **NONE**

The immutable historical `current.json` pointer still references r9, where ASR was DATA_CHECK at 55% coverage. That historical snapshot is intentionally not overwritten; a new immutable scoring revision should be generated after this patch is merged.

## Strictly score-eligible comparison classes

### EU Solvency II ratio

Target and eligible peers:
- ASR
- NN Group
- Ageas
- Sampo
- Generali

Aviva is excluded from this metric because its ratio is Solvency UK. Zurich is excluded because its ratio is Swiss Solvency Test (SST). Neither is silently normalized as EU Solvency II.

### Non-life combined ratio

Eligible with visible scope differences:
- ASR: Non-life excluding Health
- NN Group: Netherlands Non-life
- Ageas: group Non-Life
- Sampo: group P&C
- Aviva: Group General Insurance
- Zurich: P&C
- Generali: P&C

The ratio is economically related across the cohort, but the business scope differs. The peer provenance remains visible.

### Harmonized IFRS common-equity ROE

The old company-defined ROEs remain stored but blocked. Profitability now uses one explicit formula:

```text
annualized H1 IFRS profit available to ordinary shareholders
----------------------------------------------------------------
average opening and closing IFRS common shareholders' equity
```

Claims of non-controlling interests and separately reported equity-hybrid holders are excluded where applicable.

Target and eligible peers:
- ASR: 17.39%
- NN Group: 10.72%
- Ageas: 17.21%
- Sampo: 11.08%
- Aviva: 7.96%
- Generali: 16.01%

This five-peer set is sufficient for production scoring and reduces the leave-one-out score band below the 10-point STABLE threshold.

## Growth stability

Company-defined operating earnings growth is available across a broad peer set, but the metric slots deliberately require enough independent signal weight within the component. The available growth slots do not yet satisfy that component-level metric-coverage rule, so growth stability does not contribute to the current ASR score.

This is intentional: one convenient growth metric is not allowed to carry the whole component automatically.

## Value per share

Weighted-average ordinary share-count change is now available for the target plus at least four peers. The derived IFRS EPS-growth series remains diagnostic only while the exact per-share basis is being revalidated across the cohort.

Because the value-per-share component does not yet reach its internal metric-weight threshold, it is excluded from the production score rather than partially forced in.

## Data-quality principle

A score is published only from comparison classes that are definitionally aligned, sufficiently populated and stable under leave-one-out sensitivity. Regulatory ratios from different regimes and company-defined ROEs are not treated as interchangeable.

No score has an execution effect.
