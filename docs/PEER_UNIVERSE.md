# Peer-universe methodology

## Purpose

Fundamental Quality is a **peer-normalized** 0–100 score.

The portfolio itself is not the comparison set. Each company is compared with publicly listed companies that have a reasonably similar economic business model.

## Important distinction

Peer selection in this repository is **model-curated**. It is not presented as an official peer list chosen by the company.

The peer universe is used only when the economic comparison is defensible.

## Score gate

A Fundamental Quality score may be calculated only when:

1. the peer universe status is not `INSUFFICIENT`;
2. the minimum peer count is met;
3. the same economic metric can be calculated consistently for the target and peers;
4. source periods are sufficiently aligned;
5. Data Confidence is above the configured threshold.

If any gate fails:

```text
fundamental_quality_score = null
fundamental_quality_status = PEER_DATA_CHECK
```

## Normalization

For each eligible metric:

1. collect target + peer observations;
2. normalize accounting definitions;
3. winsorize extreme z-scores at the configured limit;
4. invert metrics where lower is better;
5. calculate a peer-relative z-score;
6. aggregate only the metrics defined for that universe.

Base conversion:

```text
score = clamp(50 + 25 * weighted_z, 0, 100)
```

Therefore:

- 50 = peer median / neutral z-score;
- above 50 = stronger than peer median;
- below 50 = weaker than peer median.

## Confidence

Peer confidence is separate from Data Confidence.

`HIGH` means the business models are relatively comparable.

`MEDIUM` means the peer group is usable but includes broader comparators.

`LOW` means the economic model is unusual and any peer-normalized score requires a visible warning.

## Special cases

### ABX
Direct listed life-settlement peers are too sparse. The score remains blocked until a defensible peer method is created.

### TMDX
Direct transplant-platform public peers are sparse. Broader high-growth medtech comparators may be used only with a low-confidence warning.

### LEU
Centrus combines nuclear-fuel supply with a distinctive enrichment/HALEU model. The peer group is therefore limited.

### OKLO
The company is development-stage. Only development-stage metrics are permitted; earnings multiples are explicitly excluded.

## Evidence used in initial curation

Examples supporting the business-model grouping include:

- WSM / RH / Arhaus are explicitly treated as luxury/premium home-furnishings peers in 2026 SEC proxy materials.
- TXRH is commonly grouped with US casual-dining names such as Darden, Brinker and Cheesecake Factory.
- IMCD competes directly with chemical distributors including Brenntag and Azelis.
- Powell Industries is commonly compared with listed electrical-equipment names such as nVent and Hubbell.

These examples validate the grouping approach, but every peer set remains a model assumption that must be reviewable and versioned.
