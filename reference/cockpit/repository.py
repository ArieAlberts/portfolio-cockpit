"""Opslaglaag (SQLite-implementatie; PostgreSQL-schema in migrations/postgres).

Historische tabellen zijn append-only (DB-triggers). De baseline is immutable:
zowel de repository als de database weigeren overschrijven.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime
from pathlib import Path
from typing import Iterable

from .confidence import DataPoint

MIGRATIONS = Path(__file__).resolve().parent.parent / "migrations" / "sqlite"


class BaselineImmutableError(RuntimeError):
    pass


class Repository:
    def __init__(self, path: str = ":memory:"):
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        for f in sorted(MIGRATIONS.glob("*.sql")):
            self.conn.executescript(f.read_text(encoding="utf-8"))

    # ---- securities / posities -------------------------------------------
    def add_security(self, ticker, company_name, company_type, sector, base_target_weight,
                     beta=None, thesis_status="INTACT"):
        self.conn.execute(
            "INSERT INTO securities (ticker, company_name, company_type, sector, beta, base_target_weight, thesis_status)"
            " VALUES (?,?,?,?,?,?,?)",
            (ticker, company_name, company_type, sector, beta, base_target_weight, thesis_status))
        self.conn.commit()

    def set_thesis_status(self, ticker, status):
        self.conn.execute("UPDATE securities SET thesis_status=? WHERE ticker=?", (status, ticker))
        self.conn.commit()

    def set_position(self, ticker, weight):
        self.conn.execute(
            "INSERT INTO positions (ticker, weight) VALUES (?,?) "
            "ON CONFLICT(ticker) DO UPDATE SET weight=excluded.weight, updated_at=CURRENT_TIMESTAMP",
            (ticker, weight))
        self.conn.commit()

    def securities(self) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT s.*, COALESCE(p.weight, 0) AS weight FROM securities s "
            "LEFT JOIN positions p USING (ticker) ORDER BY s.ticker").fetchall()

    # ---- baseline ----------------------------------------------------------
    def create_baseline(self, ticker: str, baseline_date: date, metrics: Iterable[dict]):
        """metrics: dicts met metric_name, baseline_value, source, source_date."""
        sec = self.conn.execute("SELECT * FROM securities WHERE ticker=?", (ticker,)).fetchone()
        if sec is None:
            raise KeyError(ticker)
        if self.conn.execute("SELECT 1 FROM baseline_snapshot WHERE ticker=? LIMIT 1", (ticker,)).fetchone():
            raise BaselineImmutableError(f"baseline voor {ticker} bestaat al en is immutable")
        with self.conn:
            for m in metrics:
                self.conn.execute(
                    "INSERT INTO baseline_snapshot (ticker, company_name, company_type, baseline_date,"
                    " metric_name, baseline_value, source, source_date) VALUES (?,?,?,?,?,?,?,?)",
                    (ticker, sec["company_name"], sec["company_type"], str(baseline_date),
                     m["metric_name"], m["baseline_value"], m["source"], str(m["source_date"])))

    def baseline(self, ticker: str) -> dict[str, sqlite3.Row]:
        rows = self.conn.execute("SELECT * FROM baseline_snapshot WHERE ticker=?", (ticker,)).fetchall()
        return {r["metric_name"]: r for r in rows}

    # ---- datapoints --------------------------------------------------------
    def add_datapoint(self, dp: DataPoint):
        self.conn.execute(
            "INSERT INTO datapoints (ticker, metric_name, kind, raw_value, currency, period, source,"
            " source_type, filing_id, as_of_date, retrieved_at, calculation_method)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (dp.ticker, dp.metric_name, dp.kind, dp.raw_value, dp.currency, dp.period, dp.source,
             dp.source_type, dp.filing_id, str(dp.as_of_date), dp.retrieved_at.isoformat(),
             dp.calculation_method))
        self.conn.commit()

    def datapoints(self, ticker: str, as_of: date) -> list[DataPoint]:
        rows = self.conn.execute(
            "SELECT * FROM datapoints WHERE ticker=? AND as_of_date<=? ORDER BY as_of_date, id",
            (ticker, str(as_of))).fetchall()
        return [DataPoint(r["ticker"], r["metric_name"], r["raw_value"], r["source"], r["source_type"],
                          r["filing_id"], date.fromisoformat(r["as_of_date"]),
                          datetime.fromisoformat(r["retrieved_at"]), r["currency"], r["period"],
                          r["calculation_method"], r["kind"]) for r in rows]

    def add_reference(self, ticker, metric_name, ref_type, value, source, as_of_date, method=None):
        self.conn.execute(
            "INSERT INTO valuation_references (ticker, metric_name, ref_type, value, source, as_of_date, method)"
            " VALUES (?,?,?,?,?,?,?)", (ticker, metric_name, ref_type, value, source, str(as_of_date), method))
        self.conn.commit()

    def references(self, ticker: str, as_of: date) -> dict[str, dict[str, float]]:
        rows = self.conn.execute(
            "SELECT * FROM valuation_references WHERE ticker=? AND as_of_date<=? ORDER BY as_of_date, id",
            (ticker, str(as_of))).fetchall()
        out: dict[str, dict[str, float]] = {}
        for r in rows:  # laatste wint
            out.setdefault(r["metric_name"], {})[r["ref_type"]] = r["value"]
        return out

    # ---- resultaten (append-only) -----------------------------------------
    def insert_quality_observations(self, run_id, ticker, obs_date, contributions):
        with self.conn:
            for c in contributions:
                self.conn.execute(
                    "INSERT INTO quality_observations (run_id, ticker, observation_date, metric_name, raw_value,"
                    " source, source_date, confidence, delta_vs_baseline, normalized_signal, metric_weight,"
                    " contribution_points, status) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (run_id, ticker, str(obs_date), c.metric_name, c.raw_value, c.source, c.source_date,
                     None, c.delta_vs_baseline, c.normalized_signal, c.metric_weight,
                     c.contribution_points, c.status))

    def insert_valuation_metrics(self, run_id, ticker, as_of, metrics):
        with self.conn:
            for m in metrics:
                self.conn.execute(
                    "INSERT INTO valuation_metrics (run_id, ticker, as_of_date, metric_name, value, status, score,"
                    " reference_value, source, calculation_method, raw_inputs) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (run_id, ticker, str(as_of), m.metric_name, m.value, m.status, m.score, m.reference_value,
                     m.source, m.calculation_method, json.dumps(m.raw_inputs)))

    def insert_score_history(self, row: dict):
        cols = list(row)
        vals = [json.dumps(v) if isinstance(v, (list, dict)) else v for v in row.values()]
        self.conn.execute(f"INSERT INTO score_history ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})", vals)
        self.conn.commit()

    def score_history(self, ticker: str | None = None) -> list[dict]:
        q = "SELECT * FROM score_history" + (" WHERE ticker=?" if ticker else "") + " ORDER BY score_date, id"
        rows = self.conn.execute(q, (ticker,) if ticker else ()).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            for k in ("warnings", "decision_reasons", "explanation"):
                d[k] = json.loads(d[k])
            out.append(d)
        return out

    def last_score(self, ticker: str, before: date) -> dict | None:
        r = self.conn.execute(
            "SELECT quality_score FROM score_history WHERE ticker=? AND score_date<? ORDER BY score_date DESC, id DESC LIMIT 1",
            (ticker, str(before))).fetchone()
        return dict(r) if r else None

    def last_signal_by_metric(self, ticker: str, before: date) -> dict[str, float]:
        rows = self.conn.execute(
            "SELECT metric_name, normalized_signal, raw_value, observation_date FROM quality_observations"
            " WHERE ticker=? AND observation_date<? ORDER BY observation_date, id", (ticker, str(before))).fetchall()
        return {r["metric_name"]: dict(r) for r in rows}

    def insert_signal(self, run_id, sim_date, price, row):
        self.conn.execute(
            "INSERT INTO signal_log (run_id, sim_date, ticker, decision_state, price_at_signal, current_weight,"
            " base_target_weight, suggested_review_direction, difference, portfolio_impact_now_pp,"
            " portfolio_impact_at_target_pp, sector_weight_now, sector_weight_after, cash_impact, dry_run)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,1)",
            (run_id, str(sim_date), row.ticker, row.decision_state, price, row.current_weight,
             row.base_target_weight, row.suggested_review_direction, row.difference,
             row.portfolio_impact_now_pp, row.portfolio_impact_at_target_pp, row.sector_weight_now,
             row.sector_weight_after, row.cash_impact))
        self.conn.commit()

    def signal_log(self) -> list[dict]:
        return [dict(r) for r in self.conn.execute("SELECT * FROM signal_log ORDER BY id").fetchall()]
