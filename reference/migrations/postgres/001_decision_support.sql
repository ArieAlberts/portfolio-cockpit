-- Portfolio Cockpit v2 — PostgreSQL-migratie (productie, Docker Compose + FastAPI).
-- Additief: raakt bestaande tabellen niet aan. Zie docs/INTEGRATIE.md voor het
-- koppelen aan het bestaande schema (holdings/thesis-ledger).

BEGIN;

CREATE TABLE IF NOT EXISTS securities (
    ticker              TEXT PRIMARY KEY,
    company_name        TEXT NOT NULL,
    company_type        TEXT NOT NULL CHECK (company_type IN
                         ('GENERAL_OPERATING_COMPANY','INSURER','DEVELOPMENT_PRE_REVENUE','CYCLICAL_MINING')),
    sector              TEXT NOT NULL,
    beta                NUMERIC,
    base_target_weight  NUMERIC NOT NULL,
    thesis_status       TEXT NOT NULL DEFAULT 'INTACT' CHECK (thesis_status IN ('INTACT','WATCH','BROKEN')),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS positions (
    ticker      TEXT PRIMARY KEY REFERENCES securities(ticker),
    weight      NUMERIC NOT NULL,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS baseline_snapshot (
    id              BIGSERIAL PRIMARY KEY,
    ticker          TEXT NOT NULL REFERENCES securities(ticker),
    company_name    TEXT NOT NULL,
    company_type    TEXT NOT NULL,
    baseline_date   DATE NOT NULL,
    metric_name     TEXT NOT NULL,
    baseline_value  NUMERIC NOT NULL,
    source          TEXT NOT NULL,
    source_date     DATE NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (ticker, metric_name)
);

CREATE TABLE IF NOT EXISTS datapoints (
    id                  BIGSERIAL PRIMARY KEY,
    ticker              TEXT NOT NULL REFERENCES securities(ticker),
    metric_name         TEXT NOT NULL,
    kind                TEXT NOT NULL CHECK (kind IN ('FUNDAMENTAL','MARKET','ASSESSMENT')),
    raw_value           NUMERIC NOT NULL,
    currency            TEXT,
    period              TEXT,
    source              TEXT NOT NULL,
    source_type         TEXT NOT NULL,
    filing_id           TEXT,
    as_of_date          DATE NOT NULL,
    retrieved_at        TIMESTAMPTZ NOT NULL,
    calculation_method  TEXT
);
CREATE INDEX IF NOT EXISTS ix_dp_ticker_metric ON datapoints (ticker, metric_name, as_of_date);

CREATE TABLE IF NOT EXISTS valuation_references (
    id          BIGSERIAL PRIMARY KEY,
    ticker      TEXT NOT NULL REFERENCES securities(ticker),
    metric_name TEXT NOT NULL,
    ref_type    TEXT NOT NULL CHECK (ref_type IN ('own_history','peers')),
    value       NUMERIC NOT NULL,
    source      TEXT NOT NULL,
    as_of_date  DATE NOT NULL,
    method      TEXT
);

CREATE TABLE IF NOT EXISTS quality_observations (
    id                  BIGSERIAL PRIMARY KEY,
    run_id              TEXT NOT NULL,
    ticker              TEXT NOT NULL,
    observation_date    DATE NOT NULL,
    metric_name         TEXT NOT NULL,
    raw_value           NUMERIC,
    source              TEXT,
    source_date         DATE,
    confidence          NUMERIC,
    delta_vs_baseline   NUMERIC,
    normalized_signal   NUMERIC NOT NULL CHECK (normalized_signal BETWEEN -1 AND 1),
    metric_weight       NUMERIC NOT NULL,
    contribution_points NUMERIC NOT NULL,
    status              TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS valuation_metrics (
    id                  BIGSERIAL PRIMARY KEY,
    run_id              TEXT NOT NULL,
    ticker              TEXT NOT NULL,
    as_of_date          DATE NOT NULL,
    metric_name         TEXT NOT NULL,
    value               NUMERIC,
    status              TEXT NOT NULL,
    score               NUMERIC,
    reference_value     NUMERIC,
    source              TEXT,
    calculation_method  TEXT NOT NULL,
    raw_inputs          JSONB NOT NULL
);

CREATE TABLE IF NOT EXISTS score_history (
    id                      BIGSERIAL PRIMARY KEY,
    run_id                  TEXT NOT NULL,
    score_date              DATE NOT NULL,
    ticker                  TEXT NOT NULL,
    price                   NUMERIC,
    quality_score           NUMERIC NOT NULL,
    quality_change_since_baseline NUMERIC NOT NULL,
    quality_change_recent   NUMERIC,
    valuation_score         NUMERIC,
    valuation_label         TEXT,
    data_confidence         NUMERIC NOT NULL,
    warnings                JSONB NOT NULL,
    thesis_status           TEXT NOT NULL,
    decision_state          TEXT NOT NULL,
    decision_reasons        JSONB NOT NULL,
    portfolio_weight        NUMERIC NOT NULL,
    base_target_weight      NUMERIC NOT NULL,
    sector_weight           NUMERIC NOT NULL,
    portfolio_impact_pp     NUMERIC NOT NULL,
    last_fundamental_update DATE,
    last_valuation_update   DATE,
    explanation             JSONB NOT NULL,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_sh_ticker_date ON score_history (ticker, score_date);

CREATE TABLE IF NOT EXISTS signal_log (
    id                          BIGSERIAL PRIMARY KEY,
    run_id                      TEXT NOT NULL,
    sim_date                    DATE NOT NULL,
    ticker                      TEXT NOT NULL,
    decision_state              TEXT NOT NULL,
    price_at_signal             NUMERIC,
    current_weight              NUMERIC NOT NULL,
    base_target_weight          NUMERIC NOT NULL,
    suggested_review_direction  TEXT NOT NULL,
    difference                  NUMERIC NOT NULL,
    portfolio_impact_now_pp     NUMERIC NOT NULL,
    portfolio_impact_at_target_pp NUMERIC NOT NULL,
    sector_weight_now           NUMERIC NOT NULL,
    sector_weight_after         NUMERIC NOT NULL,
    cash_impact                 NUMERIC NOT NULL,
    dry_run                     BOOLEAN NOT NULL CHECK (dry_run = TRUE)
);

-- Immutability / append-only
CREATE OR REPLACE FUNCTION cockpit_forbid_mutation() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION '% is append-only/immutable', TG_TABLE_NAME;
END;
$$ LANGUAGE plpgsql;

DO $$
DECLARE t TEXT;
BEGIN
    FOREACH t IN ARRAY ARRAY['baseline_snapshot','datapoints','quality_observations',
                             'valuation_metrics','score_history','signal_log'] LOOP
        EXECUTE format('DROP TRIGGER IF EXISTS %I_immutable ON %I', t, t);
        EXECUTE format('CREATE TRIGGER %I_immutable BEFORE UPDATE OR DELETE ON %I
                        FOR EACH ROW EXECUTE FUNCTION cockpit_forbid_mutation()', t, t);
    END LOOP;
END $$;

COMMIT;
