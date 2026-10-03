# Target baseline consistency — 2026-10-03

All 23 target-company baselines now have an explicit source-consistency check.

The scale is deliberately conservative:
- 100: full metric-level regulatory cross-check;
- 95: regulatory package with financial statements, MD&A and release;
- 90: regulatory plus issuer headline cross-check, or auditor-reviewed interim primary document;
- 85: two issuer primary documents checked at headline level;
- 70: internal arithmetic/cross-foot only.

All 23 target baseline Data Confidence scores now clear 80.

This does **not** unlock production Fundamental Quality scores. A peer-normalized score depends on the target data and on the peer observations. The readiness engine now requires a separate peer-input confidence score of at least 80.

Peer-input confidence remains pending.
