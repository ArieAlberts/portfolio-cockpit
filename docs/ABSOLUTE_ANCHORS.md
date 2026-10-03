# Absolute quality anchors v1

Absolute anchors are a **separate diagnostic layer** beside peer-relative Fundamental Quality.

They answer a different question:

- Fundamental Quality: how does the company compare with relevant peers?
- Absolute anchors: do selected raw fundamentals clear preconfigured minimum quality guardrails?

The two outputs are intentionally not blended.

## Hard boundaries

Absolute anchors:

- do not change the 0-100 Fundamental Quality score;
- do not change Fundamental Quality readiness;
- are not a Decision Engine gate in v1;
- do not use share price or valuation inputs;
- have no execution effect.

The policy is enforced in `config/absolute_anchors.yaml`.

## WKL pilot

Wolters Kluwer is the first calibrated pilot profile: `PROFESSIONAL_INFORMATION_SERVICES`.

The anchors are read from the immutable WKL baseline, not from peer rankings.

Configured guardrails:

| Metric | Direction | Threshold | WKL baseline |
| --- | --- | ---: | ---: |
| Net debt / EBITDA | lower is better | <= 3.0x | 2.0x |
| ROIC | higher is better | >= 10% | 18.2% |
| Adjusted operating margin | higher is better | >= 20% | 29.4% |
| Cash conversion | higher is better | >= 80% | 91% |
| Organic revenue growth | higher is better | >= 3% | 5% |
| Recurring revenue share | higher is better | >= 70% | 85% |
| Diluted share-count change | lower is better | <= 2% | -3.7% |

WKL therefore meets all seven configured pilot anchors.

This does **not** override its peer-relative result. The current relative diagnostic candidate remains about **16.5**, with only 50% weighted component coverage and therefore `DATA_CHECK`.

That contrast is the purpose of the layer: WKL can be absolutely healthy on selected fundamentals while still ranking weakly against an unusually strong peer cohort.

## CLI

```bash
cockpit-anchors
cockpit-anchors --write
```

The pipeline creates its own immutable analytical snapshot under `data/anchors/` when run with `--write`.

No live-order capability exists or is implied.
