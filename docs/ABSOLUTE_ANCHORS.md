# Absolute Quality Anchors v1

Absolute anchors are a **context layer beside Fundamental Quality**.

They answer a different question:

> Does the target meet configured absolute economic guardrails, regardless of how exceptional or weak its peer group is?

They do not produce a second 0–100 score.

## Separation from peer scoring

Fundamental Quality remains purely peer-relative:

```text
target metric -> peer z-score -> weighted Fundamental Quality
```

Absolute anchors are evaluated independently on the target's already standardized peer-dataset metrics:

```text
target metric -> configured house threshold -> STRONG / ACCEPTABLE / BELOW_ANCHOR
```

The anchor result:
- does not change Fundamental Quality;
- does not change readiness;
- does not change Decision Engine state;
- never uses market price;
- has no execution effect.

## Pilot calibration

The v1 thresholds in `config/absolute_anchors.yaml` are marked `PILOT`. They are configurable house guardrails, not external industry standards and not statistical estimates.

The central config validator requires every anchor metric to:
- already exist in the canonical metric registry for that company type;
- use the same higher/lower-is-better direction as the canonical registry;
- have internally consistent strong and acceptable thresholds.

## WKL testcase

Wolters Kluwer is the first deliberate testcase because it illustrates why the layer is needed.

The current strict peer model produces a diagnostic relative Fundamental Quality of about **16.5**, while only 50% of weighted components are currently scoreable, so WKL remains `DATA_CHECK`.

At the same time, WKL meets the configured `STRONG` anchor on all seven pilot metrics:
- net debt / EBITDA;
- adjusted operating margin;
- free-cash-flow margin;
- cash conversion;
- organic-like revenue growth;
- adjusted EPS growth;
- share-count change.

That is not a contradiction. It means:

```text
absolute economic guardrails: strong
relative position versus this exceptional peer set: weak
peer-score production coverage: still insufficient
```

The three statements remain separate in the output.

## Expansion rule

Do not copy the general-operating-company thresholds mechanically to insurers, miners, financial services or pre-revenue companies. Add a company-type anchor profile only after economically appropriate metrics and thresholds have been documented.
