# Automatic fundamental maintenance

Portfolio Cockpit uses an event-driven daily monitor.

The monitor is deliberately short-lived: GitHub Actions starts it, it polls official sources, records only changed state/events, and exits. It is not a permanent intraday process.

Key safeguards:

- transient network failures use bounded retry/backoff;
- repeated failures open a per-source degraded circuit state;
- previous validated data are retained on source failure;
- HTML sources fingerprint relevant financial links to reduce cosmetic noise;
- source events are fingerprint-derived and idempotent;
- source changes never directly alter Fundamental Quality or Quality Drift;
- live brokerage execution is permanently outside the repository.

See `docs/MONITORING_RELIABILITY.md` for operational details.

After validated new target data are standardized, peer-period alignment and all scoring gates must still pass before a score can become display-ready.
