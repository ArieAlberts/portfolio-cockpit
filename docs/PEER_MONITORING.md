# Peer monitoring and period alignment

The daily maintenance workflow now monitors both portfolio companies and peer companies.

## How peer monitoring works

The monitor derives peer dependencies from `data/peers/index.json` and the company entries in each peer dataset.

For U.S.-listed peers it resolves the ticker through the SEC company-ticker registry and monitors the SEC submissions feed. This avoids depending on a one-off earnings-release URL.

For non-U.S. peers:
- explicit durable investor-relations discovery pages can be configured in `config/peer_monitoring.yaml`;
- otherwise the source already stored in the peer dataset is used as a fallback;
- fallback/static sources receive a visible warning because they may not discover a future report.

A peer-source change creates an immutable event under:

`data/peer_source_events/YYYY-MM-DD/`

The event contains all dependent portfolio targets.

## Target state after a peer change

A changed peer sets the affected target to:

`PEER_UPDATE_DETECTED`

with:

`peer_review_required = true`

This is a review signal only.

It does not modify:
- Quality Drift;
- Fundamental Quality;
- valuation;
- target portfolio weight;
- any order or proposed live execution.

## PENDING_PEERS after a new target snapshot

When `create_fundamental_snapshot.py` writes a new validated target-company snapshot, it immediately evaluates the available peer period.

If the target snapshot reporting period differs from the current standardized peer dataset period, the target becomes:

`PENDING_PEERS`

and:

`score_recalculation_allowed = false`

When the peer dataset is later updated to the same reference period, `scripts/update_peer_alignment.py` can move it to:

`PEERS_ALIGNED_FOR_SCORING_REVIEW`

That still does not publish a score. The normal metric-coverage, peer-input-confidence and Data Confidence gates must pass afterwards.

## Why this is separate from source detection

A peer may publish a new report before or after the portfolio company. Detecting that publication is not the same as having standardized comparable metrics.

The state machine therefore separates:

```
SOURCE CHANGE
  -> PEER_UPDATE_DETECTED
  -> STANDARDIZE PEER DATA
  -> PERIOD ALIGNMENT CHECK
  -> PEERS_ALIGNED_FOR_SCORING_REVIEW
  -> SCORING GATES
  -> DISPLAY_READY
```

## First poll

As with target sources, the first successful peer poll initializes the fingerprint and does not create a false update event.
