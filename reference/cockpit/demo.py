"""Fictieve voorbeelddata (source_type SAMPLE) om het systeem end-to-end te tonen.

Let op: dit zijn verzonnen ondernemingen en cijfers — geen echte posities of koersen.
"""
from __future__ import annotations

from datetime import date, datetime

from .confidence import DataPoint
from .repository import Repository

D0 = date(2026, 4, 1)    # baseline / opname
D1 = date(2026, 10, 1)   # latere observatie

SECURITIES = [
    # ticker, naam, type, sector, base_target, huidige weight, beta
    ("DEMO-OPCO", "Voorbeeld Industrie NV", "GENERAL_OPERATING_COMPANY", "Industrials", 0.08, 0.07, 1.0),
    ("DEMO-INS", "Voorbeeld Verzekeringen NV", "INSURER", "Financials", 0.08, 0.09, 0.9),
    ("DEMO-DEV", "Voorbeeld Development Corp", "DEVELOPMENT_PRE_REVENUE", "Energy", 0.03, 0.02, 1.6),
    ("DEMO-MIN", "Voorbeeld Mining plc", "CYCLICAL_MINING", "Materials", 0.05, 0.05, 1.3),
]

BASELINE = {
    "DEMO-OPCO": dict(roic=18, operating_margin=22, revenue_growth_3y=6, fcf_per_share_growth_3y=8,
                      fcf_to_net_income=1.0, net_debt_to_ebitda=1.8, interest_coverage=12,
                      share_count_change_pct=-1.0, roic_minus_wacc=9, thesis_execution_assessment=0),
    "DEMO-INS": dict(roe=14, combined_ratio=94, solvency_ratio=190, premium_growth=4,
                     operating_profit_growth=6, book_value_per_share=30,
                     capital_distribution_per_share=2.5, thesis_execution_assessment=0),
    "DEMO-DEV": dict(cash_runway_months=18, financing_requirement_musd=400, share_count_change_pct=10,
                     licensing_milestone_assessment=0, project_milestone_assessment=0,
                     contracted_backlog_musd=50, schedule_slippage_months=0),
    "DEMO-MIN": dict(normalized_fcf_per_share=3.0, net_debt_to_normalized_ebitda=1.0,
                     aisc_cost_curve_position=40, production_vs_guidance_pct=0,
                     project_milestone_assessment=0, reserve_life_years=15,
                     share_count_change_pct=0.5, thesis_execution_assessment=0),
}

LATER = {
    "DEMO-OPCO": dict(roic=20.5, operating_margin=24, revenue_growth_3y=7, fcf_per_share_growth_3y=11,
                      fcf_to_net_income=1.05, net_debt_to_ebitda=1.5, interest_coverage=14,
                      share_count_change_pct=-1.5, roic_minus_wacc=11, thesis_execution_assessment=0.5),
    "DEMO-INS": dict(roe=12, combined_ratio=99, solvency_ratio=170, premium_growth=3,
                     operating_profit_growth=-2, book_value_per_share=29,
                     capital_distribution_per_share=2.4, thesis_execution_assessment=-0.5),
    "DEMO-DEV": dict(cash_runway_months=24, financing_requirement_musd=380, share_count_change_pct=14,
                     licensing_milestone_assessment=0.8, project_milestone_assessment=0.3,
                     contracted_backlog_musd=90, schedule_slippage_months=2),
    "DEMO-MIN": None,  # geen nieuwe fundamentele data => veroudering
}

MARKET = {  # (D0, D1) koers + valuation-inputs
    "DEMO-OPCO": ({"price": 100, "shares_outstanding": 100, "net_debt": 2000, "forward_eps": 4.5, "ebit": 900, "fcf": 400},
                  {"price": 118, "shares_outstanding": 99, "net_debt": 1800, "forward_eps": 4.9, "ebit": 980, "fcf": 450}),
    "DEMO-INS": ({"price": 40, "shares_outstanding": 200, "bvps": 30, "eps_ttm": 4.4, "distributions": 700, "ebitda": 1500},
                 {"price": 33, "shares_outstanding": 200, "bvps": 29, "eps_ttm": 3.6, "distributions": 680, "ebitda": 1400}),
    "DEMO-DEV": ({"price": 5, "shares_outstanding": 100, "navps": 10, "risked_npv": 800, "eps_ttm": -0.3, "net_debt": -50},
                 {"price": 4.2, "shares_outstanding": 114, "navps": 10.5, "risked_npv": 950, "eps_ttm": -0.35, "net_debt": -80}),
    "DEMO-MIN": ({"price": 30, "shares_outstanding": 300, "net_debt": 1500, "navps": 32, "normalized_ebitda": 2000, "fcf": 700},
                 {"price": 34, "shares_outstanding": 300, "net_debt": 1500, "navps": 32, "normalized_ebitda": 2000, "fcf": 700}),
}

REFERENCES = {
    "DEMO-OPCO": {"forward_pe": (25, 23), "ev_ebit": (18, 17), "fcf_yield": (0.035, 0.04)},
    "DEMO-INS": {"price_to_book": (1.2, 1.3), "pe": (9.5, 10), "shareholder_yield": (0.07, 0.065)},
    "DEMO-DEV": {"price_to_nav": (0.5, 0.55), "market_cap_to_funded_npv": (0.6, 0.6)},
    "DEMO-MIN": {"price_to_nav": (0.9, 1.0), "ev_normalized_ebitda": (5.5, 6.0), "fcf_yield": (0.07, 0.07)},
}

MIN_FUNDAMENTAL_DATE = date(2026, 1, 15)  # oud jaarverslag => STALE_DATA op D1
PRICE_ONLY = {"price", "shares_outstanding"}


def _dp(t, m, v, d, kind, stype="SAMPLE", src="Voorbeelddata"):
    return DataPoint(t, m, float(v), src, stype, f"DEMO-{t}-{d}", d, datetime(d.year, d.month, d.day, 18),
                     "EUR", f"{d.year}H{1 if d.month <= 6 else 2}", "voorbeeld", kind)


def _kind(m):
    if m.endswith("_assessment"):
        return "ASSESSMENT"
    return "MARKET" if m in PRICE_ONLY else "FUNDAMENTAL"


def seed_baseline(repo: Repository):
    for t, name, ctype, sector, target, weight, beta in SECURITIES:
        repo.add_security(t, name, ctype, sector, target, beta=beta)
        repo.set_position(t, weight)
        fdate = MIN_FUNDAMENTAL_DATE if t == "DEMO-MIN" else D0
        for m, v in BASELINE[t].items():
            repo.add_datapoint(_dp(t, m, v, fdate, _kind(m)))
        repo.create_baseline(t, D0, [{"metric_name": m, "baseline_value": v, "source": "Voorbeelddata",
                                      "source_date": fdate} for m, v in BASELINE[t].items()])
        for m, v in MARKET[t][0].items():
            repo.add_datapoint(_dp(t, m, v, D0 if m in PRICE_ONLY else fdate, _kind(m)))
        for m, (own, peers) in REFERENCES[t].items():
            repo.add_reference(t, m, "own_history", own, "Voorbeelddata", D0, "5j mediaan")
            repo.add_reference(t, m, "peers", peers, "Voorbeelddata", D0, "peer-mediaan")


def seed_later(repo: Repository):
    for t, *_ in SECURITIES:
        later = LATER[t]
        if later:
            for m, v in later.items():
                repo.add_datapoint(_dp(t, m, v, D1, _kind(m)))
        for m, v in MARKET[t][1].items():
            if later or m in PRICE_ONLY:
                repo.add_datapoint(_dp(t, m, v, D1 if (later or m in PRICE_ONLY) else MIN_FUNDAMENTAL_DATE, _kind(m)))
