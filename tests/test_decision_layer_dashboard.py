import json
import re

from portfolio_cockpit.config import load_config
from portfolio_cockpit.decision_layer.config import load_decision_config
from portfolio_cockpit.decision_layer.dashboard import build_dashboard, collect, render
from portfolio_cockpit.decision_layer.decision import build_decision_snapshot, write_decision_snapshot
from portfolio_cockpit.decision_layer.drift import build_drift_snapshot, write_drift_snapshot
from portfolio_cockpit.decision_layer.valuation import build_valuation_snapshot, write_valuation_snapshot

from dl_helpers import (
    AS_OF, ROOT, blank_owner_config, filled_owner_config, market_entry, observation_from_baseline, reference, repo_copy,
    write_market, write_observation, write_owner_config, write_refs,
)

REPO_CFG = load_config(ROOT)
CFG = load_decision_config(ROOT)


def _full_root(tmp_path):
    root = repo_copy(tmp_path)
    write_owner_config(root, filled_owner_config(CFG, REPO_CFG))
    write_observation(root, observation_from_baseline(
        "ASR", CFG["quality_drift"], overrides={"solvency_ii_ratio_pct": 260, "operating_roe_pct": 14.0}))
    write_refs(root, "ASR", {"pe": reference(10.0, 11.0), "price_to_book": reference(1.4, 1.6),
                             "shareholder_yield": reference(0.08, 0.07)})
    write_market(root, {"ASR": market_entry(price=45.0, shares_outstanding=210.0, eps_ttm=6.0, bvps=40.0,
                                            distributions_ttm=1100.0)})
    write_drift_snapshot(root, build_drift_snapshot(root=root, as_of=AS_OF, code_version="t"))
    write_valuation_snapshot(root, build_valuation_snapshot(root=root, as_of=AS_OF, code_version="t"))
    write_decision_snapshot(root, build_decision_snapshot(root=root, as_of=AS_OF, code_version="t"))
    return root


def _check_static_html(text):
    assert "percentiel" not in text.lower()
    assert "percentile" not in text.lower()
    assert "PORTFOLIO IMPACT -30%" in text
    assert not re.search(r"<script[^>]*src\s*=\s*[\"']?https?:", text, re.I)
    assert "<script" not in text.lower()
    assert not re.search(r"<(link|img|iframe)[^>]*(href|src)\s*=\s*[\"']?https?:", text, re.I)


def test_dashboard_with_blank_owner_templates(tmp_path):
    root = repo_copy(tmp_path)
    write_owner_config(root, blank_owner_config(CFG))
    out = build_dashboard(root, tmp_path / "dashboard.html", AS_OF)
    text = out.read_text()
    _check_static_html(text)
    current = json.loads((ROOT / "data/scoring/current.json").read_text())
    fq = json.loads((ROOT / current["current_fundamental_quality"]).read_text())
    assert text.count("n.v.t. (DATA_CHECK)") == len(fq["blocked"])
    assert text.count("/ peer mean 50") == len(fq["scores"])
    assert "Owner inputs incomplete" in text
    assert "50</b> (+0 since baseline)" in text


def test_dashboard_with_full_inputs(tmp_path):
    root = _full_root(tmp_path)
    data = collect(root, AS_OF)
    text = render(data)
    _check_static_html(text)
    assert "Owner inputs incomplete" not in text
    for column in ("Quality Drift", "Fundamental Quality (peer)", "Valuation", "Data confidence",
                   "Thesis status", "Decision state", "Last fundamental update", "Last valuation update",
                   "Warnings", "Base target", "Adjusted target", "Current", "Gap", "Price"):
        assert column in text
    assert re.search(r"<b>\d+</b> / (Attractive|Fair|Expensive)", text)
    assert "7.00%</span>" in text  # ASR adjusted target, with multiplier tooltip
    assert "binding: AWAITING_CONFIRMATION" in text
    assert "since baseline" in text
    # Drill-down: drift metrics old vs new, valuation metric status, history.
    assert 'id="t-ASR"' in text
    assert "solvency_ii_ratio_pct" in text
    assert "price_to_book" in text
    assert "quality_drift_2026-10-03.json" in text
    asr = next(r for r in data["rows"] if r["ticker"] == "ASR")
    assert asr["portfolio_impact_pp"] == -2.1
    assert asr["decision"]["decision_state"] in {"ADD_CANDIDATE", "HOLD", "NO_ADD", "REVIEW_REDUCE",
                                                  "THESIS_REVIEW", "DATA_CHECK"}


def test_dashboard_escapes_owner_text(tmp_path):
    root = repo_copy(tmp_path)
    filled = filled_owner_config(CFG, REPO_CFG)
    filled["thesis_status"]["positions"]["ASR"]["note"] = "<script>alert(1)</script>"
    write_owner_config(root, filled)
    text = build_dashboard(root, tmp_path / "d.html", AS_OF).read_text()
    assert "<script>" not in text
    assert "&lt;script&gt;" in text
