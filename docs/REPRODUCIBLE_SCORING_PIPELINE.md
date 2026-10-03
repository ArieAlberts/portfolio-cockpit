# Reproducible Fundamental Quality pipeline

The canonical score builder is:

`cockpit-score`

It builds Fundamental Quality directly from repository source files rather than from hard-coded score inputs.

## Inputs

For every portfolio company the pipeline reads:

- `config/portfolio.yaml`
- `config/company_types.yaml`
- `config/readiness.yaml`
- `config/scoring.yaml`
- `config/score_metrics.yaml`
- `data/peers/index.json`
- the peer dataset referenced by that index
- the latest dated target-confidence snapshot

## Metric selection

Each quality component is processed in the alias order in `readiness.yaml`.

The first metric that has:
- a score-eligible target value;
- at least four aligned definition-compatible peers;
- an explicit direction;

becomes that component's selected metric.

The result records the exact peer tickers and values used. If the metric-level peer sets overlap by less than 75%, the result carries `PEER_SET_VARIES_BY_METRIC`.

## Gates

A score becomes `DISPLAY_READY` only when all current gates pass:

- >=4 peers per selected metric;
- >=70% weighted component coverage;
- all company-type required components;
- no hard peer-universe block;
- target Data Confidence >=80;
- peer-input confidence >=80;
- leave-one-peer-out stability = `STABLE`.

A candidate score may still be stored diagnostically when publication is blocked. It remains under `blocked[*].diagnostic_candidate` and is not a published score.

## Provenance

Every generated company result stores:

- peer dataset path;
- peer dataset SHA-256;
- target-confidence file path and SHA-256;
- git commit;
- combined config hash;
- exact peer tickers per selected metric.

The top-level snapshot also records the SHA-256 of every scoring config file and the peer-index file.

## Immutability

`cockpit-score --write` never overwrites a different existing score snapshot.

If `fundamental_quality_YYYY-MM-DD.json` already exists with different bytes, the pipeline tries `_r2`, `_r3`, and so on.

If an identical snapshot already exists, it reuses that file.

The current pointer is updated only after a successful write.

## Commands

Dry run:

```
cockpit-score > /tmp/fundamental_quality.json
```

Write immutable snapshot:

```
cockpit-score --write
```

A manual GitHub Action named `rebuild-fundamental-quality` runs the full test suite, builds the immutable snapshot, and commits only generated scoring state.

## Safety

The score pipeline has no brokerage adapter and every result contains:

`execution_effect: NONE`

Fundamental Quality remains analytical information only.


## Semantic reproducibility hash

Pipeline version 2 adds a `reproducibility_hash` based only on scoring-relevant inputs:

- scoring source-code hashes;
- config hashes;
- peer-index hash;
- target-confidence hash;
- every portfolio peer-dataset hash.

The runtime git commit is still recorded as provenance, but a bot-generated score commit does not create a new score revision merely because HEAD changed. If the reproducibility hash is unchanged, the existing immutable score snapshot is reused.

## Dataset-rule consistency

A peer dataset may still contain a historical local `minimum_peer_values_per_metric` setting. The pipeline compares that value with the canonical global production minimum.

A mismatch is recorded as:

`DATASET_MIN_PEERS_MISMATCH:<dataset>!=<global>`

and blocks `DISPLAY_READY`. This prevents an older peer file from silently weakening the production gate.


## No-op rebuilds are byte-stable

When an existing snapshot has the same `reproducibility_hash`, the writer reuses that snapshot and the current pointer is anchored to the immutable snapshot's original provenance. A later workflow HEAD therefore cannot create a meaningless pointer-only commit.
