# Portfolio Cockpit

A repository-ready foundation for a portfolio monitoring system that keeps four concepts strictly separated:

1. **Fundamental Quality (0–100)** — absolute/peer-relative business quality.
2. **Quality Drift (baseline 50)** — deterioration or improvement versus the company's own starting snapshot.
3. **Valuation (0–100)** — current market valuation, independent of business quality.
4. **Data Confidence (0–100)** — reliability, completeness and freshness of the underlying data.

The project intentionally does **not** implement live trading yet. It reserves interfaces for Interactive Brokers, market data, trading signals, risk management and order routing so those can be added after the fundamental model has been validated.

## Phase 1 scope

Phase 1 validates the model on three structurally different companies:

- WKL — general operating company
- ASR — insurer
- OKLO — pre-revenue/development company

Only after these profiles behave correctly should the model be rolled out portfolio-wide.

## Key rules

- Daily price changes must never change Fundamental Quality or Quality Drift.
- Every company starts its own Quality Drift history at exactly **50.0**.
- Fundamental Quality uses sector/company-type appropriate metrics.
- Valuation is separate from quality.
- Missing/stale/conflicting data lowers Data Confidence.
- No automatic order placement in Phase 1.
- Historical snapshots are immutable.
- Every calculated value must be traceable to source, period and formula.

## Repository layout

```text
portfolio-cockpit/
├─ config/
│  ├─ company_types.yaml
│  └─ scoring.yaml
├─ data/
│  └─ examples/
│     └─ wkl_baseline.json
├─ docs/
│  ├─ ARCHITECTURE.md
│  ├─ DATA_MODEL.md
│  ├─ IMPLEMENTATION_PROMPT.md
│  └─ ROADMAP.md
├─ scripts/
│  └─ demo.py
├─ src/
│  └─ portfolio_cockpit/
│     ├─ adapters/
│     ├─ domain/
│     ├─ scoring/
│     └─ future/
├─ tests/
├─ .env.example
├─ .gitignore
└─ pyproject.toml
```

## Local setup

```bash
python -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
pytest
python scripts/demo.py
```

## Future IBKR architecture

```text
Fundamental data
      ↓
Fundamental Engine
      ↓
Portfolio Cockpit
      ↓
Trading Signal Engine
      ↓
Risk Engine
      ↓
Order Manager
      ↓
IBKR Adapter
```

The IBKR adapter is deliberately a stub in Phase 1.
