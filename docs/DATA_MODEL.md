# Data model

## FundamentalSnapshot

Immutable snapshot of company fundamentals at a specific reporting point.

Required fields:

- ticker
- company_type
- observation_date
- metric_name
- raw_value
- normalized_value
- unit
- currency
- period
- source
- source_type
- source_date
- retrieved_at
- filing_or_report_id
- calculation_method
- confidence

## CompanyBaseline

Immutable baseline for Quality Drift.

- ticker
- baseline_date
- company_type
- quality_drift_score = 50.0
- snapshot_ids
- created_at

A baseline must never be overwritten.

## ScoreSnapshot

- ticker
- calculated_at
- fundamental_quality_score
- quality_drift_score
- valuation_score
- data_confidence_score
- thesis_status
- score_explanation

## EventRecord

Events between reporting periods are stored independently.

- ticker
- event_date
- event_type
- source
- description
- confidence
- potential_direction
- confirmed_in_financials

Events do not automatically change Quality Drift.

## PortfolioPosition

- ticker
- current_weight
- base_target_weight
- market_value
- currency
- as_of

## PortfolioShock

```text
portfolio_impact = current_weight * shock
```

Example:

```text
current_weight = 0.05
shock = -0.30
portfolio_impact = -0.015
```

This equals -1.5 percentage points.
