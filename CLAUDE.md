# CLAUDE.md — portfolio-cockpit

Decision-support system for a 23-position dividend/quality portfolio. Owner: Arie Alberts (Dutch-speaking; reply in Dutch, keep code identifiers and repo docs in English).

## Commands

```bash
pip install -e ".[dev]"            # PyYAML, pytest, hypothesis
python -m compileall -q src scripts
pytest -q --tb=short               # must stay fully green
cockpit-score                      # Fundamental Quality dry-run (stdout)
cockpit-score --write              # writes immutable snapshot + data/scoring/current.json (CI does this)
```

Always `git pull` first: the owner works from several machines and other tools also commit to `main`.

## Permanent invariants (never violate)

1. **No live execution.** Nothing in this repo may place, modify or cancel a broker order, or call a live-order endpoint. `future/order_manager.py` only builds non-executable `ProposedOrderTicket`s. New code must not add order fields (`side`, `quantity`, `limit_price`, `order_id`) to decision output, and must not import broker SDKs. Every output carries `"execution_effect": "NONE"`.
2. **Four (soon five) separate axes:**
   - *Fundamental Quality*: peer-relative z-score. 50 = peer **mean**, sample std, clip ±3, at least 4 peers, target excluded from peer stats.
   - *Quality Drift*: change versus the company's own immutable baseline. Exactly 50.0 at the baseline. Never price-driven.
   - *Valuation*: market-price dependent. 50 ≈ fair. Higher means more attractive.
   - *Data Confidence*: below 80 means `DATA_CHECK`, with no valuation conclusion and no portfolio action.
   - *Portfolio Risk*: weights × shocks only.

   Never feed price into Quality or Drift. Never call any score a "percentile"/"percentiel".
3. **Immutability.** `data/baselines/**` is never edited after commit. Score outputs are written as new revisions (`*_rN.json`) via the write-once pattern in `scoring/pipeline.py` (`write_immutable_snapshot`, `update_current_pointer`). No-op rebuilds must be byte-stable.
4. **Only STABLE can be DISPLAY_READY.** PEER_SENSITIVE and UNSTABLE never publish. There is no config switch for this.
5. **Fail-fast config.** Every new YAML gets validation in a loader plus a test that loads the real repo config.

## Fundamental Quality hash scope — read before editing

`scoring/pipeline.py` hashes `CONFIG_FILES` and `CODE_FILES` into `config_hash`, `pipeline_code_hash` and `reproducibility_hash`. Editing any of these files creates a new Fundamental Quality revision on the next CI rebuild:

- `config/portfolio.yaml`, `company_types.yaml`, `readiness.yaml`, `scoring.yaml`, `score_metrics.yaml`, `peer_universes.yaml`
- `src/portfolio_cockpit/config.py` and `scoring/{pipeline,normalization,peer_data,peer_confidence,readiness,quality}.py`

The `rebuild-fundamental-quality` workflow also triggers on any change under `src/portfolio_cockpit/scoring/**`.

Put decision-layer code in its own package (`src/portfolio_cockpit/decision_layer/`) and its config in new files. Only touch FQ-hashed files when the change is genuinely about Fundamental Quality, and say so in the commit message.

## Conventions

- Python ≥3.11, dataclasses, no new runtime dependencies beyond PyYAML without asking.
- All thresholds and weights live in `config/*.yaml`, never as literals in code.
- Provenance on every datapoint: `source`, `source_type`, filing/report id, `as_of_date`, `retrieved_at`, `raw_value`, `currency`, `period`, `calculation_method`.
- Small, single-purpose commits. Keep the full suite green at each commit. Add a CLI smoke-test line to `.github/workflows/tests.yml` for every new CLI.
- Work on a feature branch (e.g. `feature/decision-layer`) and open a PR. Do not push straight to `main` unless the owner says so.
