# Fundamental Quality results — current status

## No DISPLAY_READY scores

The earlier ASR 62.1 and PLMR 40.2 outputs are retained only as historical research snapshots. They are superseded by `data/scoring/fundamental_quality_2026-10-03_r2.json`.

### ASR

Current status: **DATA_CHECK**.

Why:
- Aviva is now labelled `SOLVENCY_UK_RATIO`, not EU `SOLVENCY_II_RATIO`;
- Aviva is therefore excluded from the Solvency II score under the existing cross-regime rule;
- only three eligible Solvency II peers remain, below the minimum of four;
- operating earnings growth is now growth/stability, not profitability;
- ASR's ROE remains blocked until insurer ROE definitions are harmonized.

Current weighted component coverage is 35%: underwriting quality plus growth/stability. Required capital strength is missing.

### PLMR

Current status: **DATA_CHECK**.

Palomar still reaches 70% weighted non-capital component coverage, but insurers now require both:
- capital strength;
- underwriting quality.

PLMR has underwriting coverage but no standardized comparable capital-strength metric. Therefore the earlier 40.2 score is no longer display-ready.

## Statistical method

Future scores use sample standard deviation and include leave-one-peer-out sensitivity. A `PEER_SENSITIVE` result cannot be DISPLAY_READY.

All outputs remain research/monitoring data only and have no execution effect.
