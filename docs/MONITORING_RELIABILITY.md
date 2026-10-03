# Monitoring reliability

Portfolio Cockpit uses short-lived scheduled monitoring rather than a permanent 24/7 Python ingestion loop.

## Transport resilience

Official-source requests use bounded exponential retry for transient failures:

- 429
- 500
- 502
- 503
- 504
- network/timeout errors

Defaults are configured in the target and peer monitoring YAML files.

The prior validated fingerprint/data are retained when a request fails.

## Soft circuit breaker

Each target source and peer source tracks consecutive failures.

After the configured threshold, the source moves to an OPEN circuit/degraded state. The next scheduled run still performs one recovery probe; a successful probe resets the circuit to CLOSED.

A degraded source does not delete previously validated fundamentals and does not authorize scoring with missing new-period evidence.

## Idempotent source events

Source-event identity is derived from:

- entity/ticker;
- source ID;
- previous fingerprint;
- new fingerprint.

The same fingerprint transition therefore resolves to the same immutable event path. Re-running a workflow cannot create a duplicate event with a different timestamp.

Target events are stored under:

`data/source_events/<ticker>/<source>/<event-id>.json`

Peer events use:

`data/peer_source_events/<peer>/primary/<event-id>.json`

## HTML noise reduction

HTML investor-relations sources fingerprint relevant result/report links by default rather than the entire visible page. This reduces false positives from banners, footer dates and rotating content.

## CI protection

Every push now checks:

- `python -m compileall src scripts`;
- CLI `--help` smoke tests for operational scripts;
- the deterministic offline pytest suite.

This prevents an operational script from being syntactically broken while unit tests remain green.

## Git concurrency

The monitoring bot rebases on the current `main` before pushing its state/event commit.

## Optional dead-man switch

The scheduled workflow can ping an external heartbeat endpoint after a fully successful run.

Configure the repository secret:

`COCKPIT_HEARTBEAT_URL`

with a Healthchecks.io/Uptime Kuma-compatible ping URL.

No heartbeat is sent if the workflow fails or does not run, so the external service can alert on silence.

## SEC contact identity

For SEC polling, configure:

`COCKPIT_USER_AGENT`

as a repository secret containing a descriptive user agent with a real contact email.

Example shape:

`PortfolioCockpit/0.1 contact@example.com`

The source code falls back to the YAML value, but SEC monitoring should not be considered production-ready until the secret is configured.

## Storage decision

Git remains the audit store for configuration, validated baselines and low-frequency fundamental snapshots.

A runtime database such as DuckDB/SQLite/TimescaleDB is intentionally deferred until high-frequency price, telemetry or ingestion history makes repository-file storage materially inefficient.
