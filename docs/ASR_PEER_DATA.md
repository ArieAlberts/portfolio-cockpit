# ASR insurer peer data review

This dataset standardizes H1 2026 financial observations for ASR and its diversified-insurer peer group.

File:

`data/peers/ASR/2026-10-02.json`

## Strictly score-eligible comparison classes

### Solvency II ratio

Eligible:
- ASR
- NN Group
- Ageas
- Sampo
- Aviva

Zurich is deliberately excluded because its 266% capital ratio is a Swiss Solvency Test (SST) ratio rather than a Solvency II ratio.

### Company-defined operating earnings growth

Eligible:
- ASR
- NN Group
- Ageas
- Sampo
- Aviva
- Zurich

This class is intentionally labeled "company-defined". Operating result, net operating result and business operating profit are not identical accounting measures. The class may be used only as a broad earnings-momentum signal and should receive a lower model weight than capital strength.

### Operating capital generation growth

Eligible:
- ASR
- NN Group
- Ageas
- Aviva

The original company terminology is preserved:
- ASR: organic capital creation
- NN: operating capital generation
- Ageas: operational capital generation
- Aviva: Solvency II operating capital generation

### Non-life combined ratio

Eligible with scope warnings:
- ASR: Non-life excluding Health
- NN: Netherlands Non-life
- Ageas: group Non-Life
- Sampo: group P&C
- Aviva: Group General Insurance
- Zurich: P&C

The ratio is economically related across the cohort, but the business scope differs. It therefore needs a visible comparability warning.

## Stored but currently blocked

ROE values are stored for ASR, Ageas, Aviva and Zurich, but are not score-eligible yet because the definitions differ (operating ROE, shareholder ROE, IFRS ROE and Core ROE).

Dividend growth is stored where available but is not yet sufficiently complete for strict peer normalization.

## Data-quality principle

A regulatory capital ratio from a different regime is not silently treated as equivalent. The same rule applies to ROE and other company-defined metrics.
