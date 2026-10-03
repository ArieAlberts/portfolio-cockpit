-- Portfolio Cockpit v2 — beslissingsondersteunend schema (SQLite, voor tests/demo).
-- Zie migrations/postgres/ voor de productievariant.

CREATE TABLE IF NOT EXISTS securities (
    ticker              TEXT PRIMARY KEY,
    company_name        TEXT NOT NULL,
    company_type        TEXT NOT NULL CHECK (company_type IN
                         ('GENERAL_OPERATING_COMPANY','INSURER','DEVELOPMENT_PRE_REVENUE','CYCLICAL_MINING')),
    sector              TEXT NOT NULL,
    beta                REAL,
    base_target_weight  REAL NOT NULL,          -- strategisch; nooit door de engine gewijzigd
    thesis_status       TEXT NOT NULL DEFAULT 'INTACT' CHECK (thesis_status IN ('INTACT','WATCH','BROKEN')),
    created_at          TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Huidige posities (muteerbare stand; historie zit in score_history)
CREATE TABLE IF NOT EXISTS positions (
    ticker      TEXT PRIMARY KEY REFERENCES securities(ticker),
    weight      REAL NOT NULL,
    updated_at  TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- 1. QUALITY: immutable baseline
CREATE TABLE IF NOT EXISTS baseline_snapshot (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker          TEXT NOT NULL REFERENCES securities(ticker),
    company_name    TEXT NOT NULL,
    company_type    TEXT NOT NULL,
    baseline_date   TEXT NOT NULL,
    metric_name     TEXT NOT NULL,
    baseline_value  REAL NOT NULL,
    source          TEXT NOT NULL,
    source_date     TEXT NOT NULL,
    created_at      TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (ticker, metric_name)
);
CREATE TRIGGER IF NOT EXISTS baseline_no_update BEFORE UPDATE ON baseline_snapshot
BEGIN SELECT RAISE(ABORT, 'baseline_snapshot is immutable'); END;
CREATE TRIGGER IF NOT EXISTS baseline_no_delete BEFORE DELETE ON baseline_snapshot
BEGIN SELECT RAISE(ABORT, 'baseline_snapshot is immutable'); END;

-- 3. DATA CONFIDENCE: ieder datapunt met provenance (append-only)
CREATE TABLE IF NOT EXISTS datapoints (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker              TEXT NOT NULL REFERENCES securities(ticker),
    metric_name         TEXT NOT NULL,
    kind                TEXT NOT NULL CHECK (kind IN ('FUNDAMENTAL','MARKET','ASSESSMENT')),
    raw_value           REAL NOT NULL,
    currency            TEXT,
    period              TEXT,
    source              TEXT NOT NULL,
    source_type         TEXT NOT NULL,
    filing_id           TEXT,
    as_of_date          TEXT NOT NULL,
    retrieved_at        TEXT NOT NULL,
    calculation_method  TEXT
);
CREATE INDEX IF NOT EXISTS ix_dp_ticker_metric ON datapoints (ticker, metric_name, as_of_date);

-- Referenties voor waardering (eigen historie, sectorgenoten) — append-only
CREATE TABLE IF NOT EXISTS valuation_references (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker      TEXT NOT NULL REFERENCES securities(ticker),
    metric_name TEXT NOT NULL,
    ref_type    TEXT NOT NULL CHECK (ref_type IN ('own_history','peers')),
    value       REAL NOT NULL,
    source      TEXT NOT NULL,
    as_of_date  TEXT NOT NULL,
    method      TEXT
);

-- 1. QUALITY: periodieke snapshots (per run, append-only)
CREATE TABLE IF NOT EXISTS quality_observations (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id              TEXT NOT NULL,
    ticker              TEXT NOT NULL,
    observation_date    TEXT NOT NULL,
    metric_name         TEXT NOT NULL,
    raw_value           REAL,
    source              TEXT,
    source_date         TEXT,
    confidence          REAL,
    delta_vs_baseline   REAL,
    normalized_signal   REAL NOT NULL CHECK (normalized_signal BETWEEN -1 AND 1),
    metric_weight       REAL NOT NULL,
    contribution_points REAL NOT NULL,
    status              TEXT NOT NULL
);

-- 2. VALUATION: per metric per run (append-only)
CREATE TABLE IF NOT EXISTS valuation_metrics (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id              TEXT NOT NULL,
    ticker              TEXT NOT NULL,
    as_of_date          TEXT NOT NULL,
    metric_name         TEXT NOT NULL,
    value               REAL,
    status              TEXT NOT NULL,
    score               REAL,
    reference_value     REAL,
    source              TEXT,
    calculation_method  TEXT NOT NULL,
    raw_inputs          TEXT NOT NULL      -- JSON
);

-- 7. HISTORY & AUDIT TRAIL (append-only)
CREATE TABLE IF NOT EXISTS score_history (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id                  TEXT NOT NULL,
    score_date              TEXT NOT NULL,
    ticker                  TEXT NOT NULL,
    price                   REAL,
    quality_score           REAL NOT NULL,
    quality_change_since_baseline REAL NOT NULL,
    quality_change_recent   REAL,
    valuation_score         REAL,
    valuation_label         TEXT,
    data_confidence         REAL NOT NULL,
    warnings                TEXT NOT NULL,   -- JSON
    thesis_status           TEXT NOT NULL,
    decision_state          TEXT NOT NULL,
    decision_reasons        TEXT NOT NULL,   -- JSON
    portfolio_weight        REAL NOT NULL,
    base_target_weight      REAL NOT NULL,
    sector_weight           REAL NOT NULL,
    portfolio_impact_pp     REAL NOT NULL,
    last_fundamental_update TEXT,
    last_valuation_update   TEXT,
    explanation             TEXT NOT NULL,   -- JSON: bijdragen per metric, bron, oud/nieuw, datum
    created_at              TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- 8. SIMULATION / SIGNAL LOG (append-only, altijd dry-run)
CREATE TABLE IF NOT EXISTS signal_log (
    id                          INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id                      TEXT NOT NULL,
    sim_date                    TEXT NOT NULL,
    ticker                      TEXT NOT NULL,
    decision_state              TEXT NOT NULL,
    price_at_signal             REAL,
    current_weight              REAL NOT NULL,
    base_target_weight          REAL NOT NULL,
    suggested_review_direction  TEXT NOT NULL,
    difference                  REAL NOT NULL,
    portfolio_impact_now_pp     REAL NOT NULL,
    portfolio_impact_at_target_pp REAL NOT NULL,
    sector_weight_now           REAL NOT NULL,
    sector_weight_after         REAL NOT NULL,
    cash_impact                 REAL NOT NULL,
    dry_run                     INTEGER NOT NULL CHECK (dry_run = 1)
);

-- Append-only bescherming voor alle historische tabellen
CREATE TRIGGER IF NOT EXISTS dp_no_update BEFORE UPDATE ON datapoints BEGIN SELECT RAISE(ABORT, 'append-only'); END;
CREATE TRIGGER IF NOT EXISTS dp_no_delete BEFORE DELETE ON datapoints BEGIN SELECT RAISE(ABORT, 'append-only'); END;
CREATE TRIGGER IF NOT EXISTS qo_no_update BEFORE UPDATE ON quality_observations BEGIN SELECT RAISE(ABORT, 'append-only'); END;
CREATE TRIGGER IF NOT EXISTS qo_no_delete BEFORE DELETE ON quality_observations BEGIN SELECT RAISE(ABORT, 'append-only'); END;
CREATE TRIGGER IF NOT EXISTS vm_no_update BEFORE UPDATE ON valuation_metrics BEGIN SELECT RAISE(ABORT, 'append-only'); END;
CREATE TRIGGER IF NOT EXISTS vm_no_delete BEFORE DELETE ON valuation_metrics BEGIN SELECT RAISE(ABORT, 'append-only'); END;
CREATE TRIGGER IF NOT EXISTS sh_no_update BEFORE UPDATE ON score_history BEGIN SELECT RAISE(ABORT, 'append-only'); END;
CREATE TRIGGER IF NOT EXISTS sh_no_delete BEFORE DELETE ON score_history BEGIN SELECT RAISE(ABORT, 'append-only'); END;
CREATE TRIGGER IF NOT EXISTS sl_no_update BEFORE UPDATE ON signal_log BEGIN SELECT RAISE(ABORT, 'append-only'); END;
CREATE TRIGGER IF NOT EXISTS sl_no_delete BEFORE DELETE ON signal_log BEGIN SELECT RAISE(ABORT, 'append-only'); END;
