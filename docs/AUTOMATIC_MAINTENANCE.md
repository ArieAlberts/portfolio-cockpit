# Automatic fundamental maintenance

Portfolio Cockpit now has an event-driven maintenance layer.

## Daily source monitor

`.github/workflows/daily-source-monitor.yml` runs daily at 04:17 UTC and can also be started manually from GitHub Actions.

The monitor reads `config/source_registry.yaml`.

For U.S./SEC filers it fingerprints the most recent financial filings from the SEC submissions feed. For European issuers it fingerprints normalized visible text and links on the official investor/results page.

A changed source creates an immutable source event under:

`data/source_events/YYYY-MM-DD/`

A source event **never** changes Fundamental Quality, Quality Drift, valuation, portfolio weights, or an order.

It only changes the company status to:

`NEW_DATA_DETECTED`

and sets:

`review_required = true`

## First observation

The first successful poll initializes a fingerprint and sets the company to `CURRENT`. It does not create a fake "new data" event.

## Stale-data gate

Each company has a `stale_after_days` threshold. If the validated baseline ages beyond that threshold without a validated replacement, the status can move to `STALE_DATA`.

This is a warning, not a score change.

## Immutable fundamental snapshots

After new information has been standardized and validated, the snapshot engine can create a new immutable record:

`python scripts/create_fundamental_snapshot.py ...`

Snapshots form a chain using `previous_snapshot_id`. Existing snapshot bytes are never overwritten.

The snapshot payload contains:

- reporting period;
- observation timestamp;
- source event IDs;
- normalized fundamentals;
- previous snapshot ID;
- content hash.

Every snapshot explicitly contains:

`score_update_allowed: false`

and

`execution_effect: NONE`

Scoring remains a separate, gated step after peer alignment and confidence checks.

## No daily commit noise

The workflow commits only when the stored source state, company status, or source-event history changes. A successful poll with no detected source change creates no repository commit.

## Limitations

HTML investor pages can change for reasons unrelated to financial results. Such a change only creates a review event; it cannot automatically become a fundamental update.

Peer-company monitoring is intentionally separate from the first target-company monitor. When a target publishes a new period, the downstream scoring workflow must wait for enough aligned peer data before publishing a new peer-normalized Fundamental Quality score.

## Execution boundary

This monitoring system has no brokerage adapter and no order submission path. Source changes and snapshots can never place, modify, or cancel live orders.
