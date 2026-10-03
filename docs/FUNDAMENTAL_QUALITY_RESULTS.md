# Fundamental Quality results — current and next validated state

## Immutable current snapshot

`data/scoring/current.json` still points to the immutable 2026-10-03 r9 snapshot. That historical snapshot has **0 DISPLAY_READY** scores and is not rewritten when methodology or peer data improve.

## ASR — validated rebuild candidate

With the harmonized H1 IFRS common-equity ROE series added, a fresh deterministic rebuild now passes the production gates for ASR:

- required capital strength: covered with four EU Solvency II peers;
- underwriting quality: covered;
- profitability: covered by `annualized_ifrs_common_equity_roe_pct`;
- weighted component coverage: **75%**;
- target data confidence: above the 80 threshold;
- peer-input confidence: above the 80 threshold;
- leave-one-peer-out sensitivity: **STABLE**;
- dry-run Fundamental Quality score: **66.1**.

The score uses only the three covered components. Value-per-share remains partial and growth/stability does not yet meet its metric-slot coverage threshold.

Company-defined ROE values are not mixed into the harmonized ROE class. Aviva remains excluded from EU Solvency II capital strength and Zurich remains excluded under its SST regime.

After this data patch is merged, the next immutable score rebuild may publish ASR as the first `DISPLAY_READY` company if the same gates remain satisfied.

## PLMR

Current status remains **DATA_CHECK**.

Palomar has strong non-capital peer coverage, but its required `capital_strength` component still lacks target plus four homogeneous FY2025 U.S. statutory observations. Premium-to-surplus is locked to a same-period statutory basis and RBC remains an exact-ratio fallback.

## Statistical method

Production scores use sample standard deviation, +/-3 z clipping with unclipped z retained, weighted metric slots and leave-one-peer-out sensitivity. Only `STABLE` results may be `DISPLAY_READY`.

All outputs are research/monitoring data only and have `execution_effect: NONE`.
