# ASR insurer peer data review

This dataset standardizes H1 2026 observations for ASR and its diversified-insurer peer group.

File:

`data/peers/ASR/2026-10-03.json`

## Score-eligible comparison classes

### EU Solvency II capital strength

Target: ASR.

Eligible peers:
- NN Group
- Ageas
- Sampo
- Generali

Aviva is deliberately excluded because its 176% ratio is a **Solvency UK** shareholder-cover ratio. Zurich is excluded because its 266% ratio is a **Swiss Solvency Test** ratio. Neither is silently substituted for EU Solvency II.

### Non-life combined ratio

Eligible with visible scope differences:
- ASR: Non-life excluding Health
- NN: Netherlands Non-life
- Ageas: group Non-Life
- Sampo: group P&C
- Aviva: Group General Insurance
- Zurich: P&C
- Generali: P&C

This remains an economically related but not perfectly scope-identical class.

### Harmonized IFRS common-equity ROE

The company-defined ROE labels remain stored but blocked. Production scoring instead uses one explicit formula:

```text
annualized H1 IFRS profit available to ordinary shareholders
----------------------------------------------------------------
average opening and closing common shareholders' equity
```

Equity-instrument coupons and non-controlling interests are excluded where separately reported.

Target:
- ASR: 17.390315%

Eligible peers:
- NN Group: 10.716895%
- Ageas: 17.209113%
- Sampo: 11.076337%
- Aviva: 7.955278%
- Generali: 16.010640%

The canonical metric is `annualized_ifrs_common_equity_roe_pct`. It is deliberately distinct from `reported_roe_pct` and other company-defined ROE aliases.

### Weighted-average share-count change

Target:
- ASR: -1.695736%

Eligible peers:
- NN Group: -1.838649%
- Sampo: -1.374953%
- Aviva: +13.701201%
- Generali: -0.913613%

Ageas is excluded from this series because the prior-period weighted-average share basis was not sufficiently aligned in the source pass.

Share count alone represents only 25% of the value-per-share component slot weight, so it does **not** make that component scoreable by itself.

## Deliberately blocked

Derived H1 IFRS EPS-growth observations are retained as audit/research data but are not score-eligible yet. Their source alignment is not sufficiently homogeneous across target plus four peers.

Company-defined ROE values also remain blocked; the pipeline uses only the harmonized metric above.

## Rebuild consequence

The immutable current r9 snapshot is not rewritten. A fresh pipeline rebuild on this dataset covers:
- capital strength: 30%
- underwriting quality: 25%
- profitability: 20%

Total weighted component coverage is therefore **75%**. The leave-one-peer-out result is **STABLE** and the dry-run Fundamental Quality score is approximately **66.1**.

The value-per-share and growth/stability components remain outside the production score until their own metric-slot coverage gates are met.
