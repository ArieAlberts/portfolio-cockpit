# CI policy

The push/pull-request test suite is an offline deterministic gate.

It must not depend on:
- broker connectivity;
- live market data;
- SEC or issuer websites;
- API keys;
- market opening hours;
- an external database unless a database layer is deliberately introduced.

Network calls in ordinary pytest tests are blocked.

Network monitoring belongs to the separate scheduled monitor workflow.

Do not add database service containers merely because they are common in financial systems. Add them only when production code actually depends on a database and create a separate integration-test workflow for that dependency.

The monitoring architecture is short-lived scheduled execution, not a permanent dataframe ingestion loop, so always-on memory-leak and weekend-idle-feed risks are currently out of scope.

The permanent no-live-execution boundary remains mandatory in all CI workflows.
