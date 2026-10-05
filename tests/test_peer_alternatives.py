"""Peer-alternatives signal: analysis only, thresholds from config, same FQ gates."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from dl_helpers import ROOT, datapoint, market_entry, reference, repo_copy, write_market, write_refs
from portfolio_cockpit.config import load_config
from portfolio_cockpit.decision_layer import peer_alternatives as pa
from portfolio_cockpit.decision_layer.decision import FORBIDDEN_OUTPUT_KEYS
from portfolio_cockpit.decision_layer.peer_quality import (
    QualityResult,
    candidate_peers,
    score_peer,
    score_target,
    swap_target,
)
from portfolio_cockpit.decision_layer.valuation import MarketDataError
from portfolio_cockpit.scoring.pipeline import build_score_snapshot

AS_OF = "2026-10-05"  # ISO week 41
NEXT_WEEK = "2026-10-12"
POSITION = "ASR"
PEER = "NN.AS"


# ------------------------------------------------------------------ fixtures


def _multiple(value: float, as_of: str = AS_OF) -> dict:
    return {**datapoint(value, as_of), "method": "test multiple"}


def _write_market_peers(root: Path, entries: dict, as_of: str = AS_OF) -> Path:
    path = root / "data/market_peers" / f"{as_of}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"schema_version": 1, "as_of": as_of, "tickers": entries}), encoding="utf-8")
    return path


def _peer_entry(pb: float, pe: float, sy: float, as_of: str = AS_OF) -> dict:
    return {"multiples": {"price_to_book": _multiple(pb, as_of), "pe": _multiple(pe, as_of),
                          "shareholder_yield": _multiple(sy, as_of)}}


def _setup(tmp_path: Path, *, peer_entry: dict, as_of: str = AS_OF) -> Path:
    """ASR scores exactly 50 against a peer median of P/B 1.0, P/E 10, yield 8%."""
    root = repo_copy(tmp_path)
    write_market(root, {POSITION: market_entry(price_date=as_of, price=50.0, bvps=50.0, eps_ttm=5.0,
                                               shares_outstanding=100.0, distributions_ttm=400.0)}, as_of)
    write_refs(root, POSITION, {"price_to_book": reference(None, 1.0), "pe": reference(None, 10.0),
                                "shareholder_yield": reference(None, 0.08)})
    _write_market_peers(root, {PEER: peer_entry}, as_of)
    return root


@pytest.fixture
def peer_fq(monkeypatch):
    """Give NN.AS a DISPLAY_READY Fundamental Quality; every other peer is scored for real."""
    state = {"score": 80.0}

    def fake(*, dataset, peer, company_type, repo_config):
        if peer != PEER:
            return score_peer(dataset=dataset, peer=peer, company_type=company_type, repo_config=repo_config)
        return QualityResult(ticker=peer, status="DISPLAY_READY", score=state["score"], diagnostic_score=state["score"],
                             stability_flag="STABLE", data_confidence=100.0, warnings=(),
                             metrics={"solvency_ratio_pct": {"value": 200.0, "clipped_z_score": 1.0}})

    monkeypatch.setattr(pa, "score_peer", fake)
    return state


def _alert(payload: dict) -> dict | None:
    found = [a for a in payload["alerts"] if a["position"] == POSITION and a["peer"] == PEER]
    return found[0] if found else None


def _cfg(root: Path) -> dict:
    return yaml.safe_load((root / pa.CONFIG_PATH).read_text(encoding="utf-8"))


def _write_cfg(root: Path, cfg: dict) -> None:
    (root / pa.CONFIG_PATH).write_text(yaml.safe_dump(cfg), encoding="utf-8")


# -------------------------------------------------------------------- config


def test_real_repo_config_loads():
    cfg = pa.load_peer_alternatives_config(ROOT)
    assert cfg["minimum_data_confidence"] == 80
    assert cfg["persistence"]["required_consecutive_runs"] == 2


@pytest.mark.parametrize(
    "mutate",
    [
        lambda c: c["rules"].pop("CHEAPER_PEER"),
        lambda c: c["rules"]["STRONGER_PEER"].update(min_fq_advantage=-1),
        lambda c: c.update(minimum_data_confidence=101),
        lambda c: c["persistence"].update(required_consecutive_runs=0),
        lambda c: c["persistence"].update(run_period="daily"),
        lambda c: c["valuation_only"].update(enabled="yes"),
    ],
)
def test_invalid_config_fails_fast(tmp_path, mutate):
    root = repo_copy(tmp_path)
    cfg = _cfg(root)
    mutate(cfg)
    _write_cfg(root, cfg)
    with pytest.raises(pa.PeerAlternativesConfigError):
        pa.load_peer_alternatives_config(root)


# ------------------------------------------------------------ classification


def test_thresholds_come_from_config():
    cfg = pa.load_peer_alternatives_config(ROOT)
    s, c = cfg["rules"]["STRONGER_PEER"], cfg["rules"]["CHEAPER_PEER"]

    def kind(pos_fq, peer_fq, pos_val, peer_val, config=cfg):
        return pa.classify(position_fq=pos_fq, peer_fq=peer_fq, position_valuation=pos_val,
                           peer_valuation=peer_val, cfg=config)[0]

    edge_fq = 60 + s["min_fq_advantage"]
    assert kind(60, edge_fq, 50, 50 - s["max_valuation_disadvantage"]) == pa.STRONGER
    assert kind(60, edge_fq - 0.01, 50, 50) is None
    assert kind(60, edge_fq, 50, 50 - s["max_valuation_disadvantage"] - 0.01) is None
    assert kind(60, 60 - c["max_fq_disadvantage"], 50, 50 + c["min_valuation_advantage"]) == pa.CHEAPER
    assert kind(60, 60 - c["max_fq_disadvantage"] - 0.01, 50, 80) is None
    assert kind(60, 60, 50, 50 + c["min_valuation_advantage"] - 0.01) is None
    assert kind(60, edge_fq, 50, 50 + c["min_valuation_advantage"]) == pa.BETTER
    # Change the config, and the same inputs classify differently.
    stricter = json.loads(json.dumps(cfg))
    stricter["rules"]["STRONGER_PEER"]["min_fq_advantage"] = s["min_fq_advantage"] + 5
    assert kind(60, edge_fq, 50, 50, stricter) is None


def test_valuation_only_when_position_has_no_fundamental_quality():
    cfg = pa.load_peer_alternatives_config(ROOT)
    advantage = cfg["rules"]["CHEAPER_PEER"]["min_valuation_advantage"]
    kwargs = dict(position_fq=None, position_valuation=50)
    assert pa.classify(peer_fq=None, peer_valuation=50 + advantage, cfg=cfg, **kwargs) == (
        pa.CHEAPER, pa.BASIS_VALUATION_ONLY)
    # Never STRONGER/BETTER without a position FQ, even for a high-quality peer.
    assert pa.classify(peer_fq=99, peer_valuation=50, cfg=cfg, **kwargs) == (None, pa.BASIS_VALUATION_ONLY)
    off = json.loads(json.dumps(cfg))
    off["valuation_only"]["enabled"] = False
    assert pa.classify(peer_fq=None, peer_valuation=90, cfg=off, **kwargs)[0] is None


# ---------------------------------------------------------------- peer FQ


def test_scorer_reproduces_the_pipeline_for_every_position():
    """Same selection, normalization and gates as scoring/pipeline.py."""
    repo_cfg = load_config(ROOT)
    snapshot = build_score_snapshot(root=ROOT)
    index = json.loads((ROOT / "data/peers/index.json").read_text(encoding="utf-8"))["datasets"]
    confidence = json.loads(Path(ROOT / snapshot["provenance"]["target_confidence"]["path"]).read_text())["results"]
    for ticker, position in repo_cfg["portfolio"]["positions"].items():
        dataset = json.loads((ROOT / index[ticker]).read_text(encoding="utf-8"))
        result = score_target(dataset=dataset, company_type=position["company_type"], repo_config=repo_cfg,
                              target_data_confidence=confidence.get(ticker, {}).get("data_confidence_score"))
        published = snapshot["scores"].get(ticker)
        reference_item = published or snapshot["blocked"][ticker]
        assert (result.status == "DISPLAY_READY") == (published is not None), ticker
        assert result.score == (published or {}).get("fundamental_quality_score"), ticker
        assert result.diagnostic_score == (reference_item.get("diagnostic_candidate") or {}).get("score"), ticker


def test_peer_fq_uses_the_minimum_reference_count():
    repo_cfg = load_config(ROOT)
    minimum = repo_cfg["scoring"]["fundamental_quality"]["minimum_peer_values_per_metric"]
    dataset = json.loads((ROOT / "data/peers/ASR/2026-10-03.json").read_text(encoding="utf-8"))
    result = score_peer(dataset=dataset, peer=PEER, company_type="INSURER", repo_config=repo_cfg)
    assert result.metrics
    assert all(len(m["reference_tickers"]) >= minimum for m in result.metrics.values())
    assert POSITION in {t for m in result.metrics.values() for t in m["reference_tickers"]}
    assert PEER not in {t for m in result.metrics.values() for t in m["reference_tickers"]}
    # Too few companies left: the peer cannot be scored, so it is INSUFFICIENT.
    small = json.loads(json.dumps(dataset))
    keep = {POSITION, PEER, "AGS.BR"}
    small["companies"] = {t: c for t, c in small["companies"].items() if t in keep}
    thin = score_peer(dataset=small, peer=PEER, company_type="INSURER", repo_config=repo_cfg)
    assert thin.status == "INSUFFICIENT" and thin.score is None


def test_swap_gives_the_position_the_peer_role_and_leaves_input_untouched():
    dataset = json.loads((ROOT / "data/peers/IMCD/2026-10-03.json").read_text(encoding="utf-8"))
    before = json.dumps(dataset, sort_keys=True)
    swapped = swap_target(dataset, "DKSH.SW")
    assert swapped["target_ticker"] == "DKSH.SW"
    assert swapped["companies"]["IMCD"]["role"] == "BROAD_PEER"
    assert json.dumps(dataset, sort_keys=True) == before
    assert "SAGA.L" not in candidate_peers(
        json.loads((ROOT / "data/peers/ADM.L/2026-10-03.json").read_text()), ["SBRE.L", "AV.L", "SAGA.L"])


# ----------------------------------------------------------------- alerts


def test_better_peer_alert_with_scores_differences_and_sources(tmp_path, peer_fq):
    root = _setup(tmp_path, peer_entry=_peer_entry(0.8, 8.0, 0.096))
    payload = pa.build_peer_alternatives_snapshot(root=root, as_of=AS_OF)
    alert = _alert(payload)
    assert alert is not None
    assert alert["type"] == pa.BETTER and alert["basis"] == pa.BASIS_FULL
    assert alert["position_comparison_valuation"] == pytest.approx(50.0)
    assert alert["peer_comparison_valuation"] == pytest.approx(75.0)
    assert alert["peer_fundamental_quality"] == 80.0
    assert len(alert["top_metric_differences"]) == 3
    assert alert["sources"]["peer_market"] == f"data/market_peers/{AS_OF}.json"
    assert alert["sources"]["peer_median_reference"] == "data/valuation_refs/ASR.json"
    assert alert["first_seen"] == AS_OF and alert["status"] == pa.CANDIDATE
    assert payload["execution_effect"] == "NONE" and alert["execution_effect"] == "NONE"


@pytest.mark.parametrize("fq, multiples, expected", [
    (80.0, (1.0, 10.0, 0.08), pa.STRONGER),
    (66.0, (0.8, 8.0, 0.096), pa.CHEAPER),
    (55.0, (0.8, 8.0, 0.096), None),
])
def test_alert_types(tmp_path, peer_fq, fq, multiples, expected):
    peer_fq["score"] = fq
    root = _setup(tmp_path, peer_entry=_peer_entry(*multiples))
    alert = _alert(pa.build_peer_alternatives_snapshot(root=root, as_of=AS_OF))
    assert (alert["type"] if alert else None) == expected


def test_no_alert_below_minimum_data_confidence(tmp_path, peer_fq):
    root = _setup(tmp_path, peer_entry=_peer_entry(0.8, 8.0, 0.096))
    path = sorted((root / "data/confidence").glob("????-??-??.json"))[-1]
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["results"][POSITION]["data_confidence_score"] = 79.9
    path.write_text(json.dumps(payload), encoding="utf-8")
    result = pa.build_peer_alternatives_snapshot(root=root, as_of=AS_OF)
    assert _alert(result) is None
    assert "POSITION_DATA_CONFIDENCE_BELOW_MINIMUM" in result["evaluations"][POSITION]["peers"][PEER]["reasons"]


def test_no_alert_when_peer_market_data_is_stale(tmp_path, peer_fq):
    stale = "2026-09-20"
    root = _setup(tmp_path, peer_entry=_peer_entry(0.8, 8.0, 0.096, as_of=stale))
    result = pa.build_peer_alternatives_snapshot(root=root, as_of=AS_OF)
    assert _alert(result) is None
    reasons = result["evaluations"][POSITION]["peers"][PEER]["reasons"]
    assert any(r.startswith("STALE_DATA:peer_market") for r in reasons)


def test_no_alert_when_peer_fundamentals_are_stale(tmp_path, peer_fq):
    root = _setup(tmp_path, peer_entry=_peer_entry(0.8, 8.0, 0.096, as_of="2027-02-01"), as_of="2027-02-01")
    result = pa.build_peer_alternatives_snapshot(root=root, as_of="2027-02-01")
    assert _alert(result) is None
    assert any(r.startswith("STALE_DATA:peer_fundamentals")
               for r in result["evaluations"][POSITION]["peers"][PEER]["reasons"])


def test_no_quality_alert_when_peer_fq_is_insufficient(tmp_path):
    root = _setup(tmp_path, peer_entry=_peer_entry(0.5, 5.0, 0.2))
    result = pa.build_peer_alternatives_snapshot(root=root, as_of=AS_OF)
    assert _alert(result) is None
    assert "PEER_FUNDAMENTAL_QUALITY_INSUFFICIENT" in result["evaluations"][POSITION]["peers"][PEER]["reasons"]


def test_valuation_only_alert_for_position_without_fq(tmp_path, monkeypatch):
    root = _setup(tmp_path, peer_entry=_peer_entry(0.8, 8.0, 0.096))
    original = pa._fundamental_quality

    def without_scores(r):
        path, snapshot = original(r)
        return path, {**snapshot, "scores": {}}

    monkeypatch.setattr(pa, "_fundamental_quality", without_scores)
    alert = _alert(pa.build_peer_alternatives_snapshot(root=root, as_of=AS_OF))
    assert alert["type"] == pa.CHEAPER and alert["basis"] == pa.BASIS_VALUATION_ONLY
    assert all(d["axis"] == "valuation" for d in alert["top_metric_differences"])


def test_persistence_one_run_candidate_two_runs_active(tmp_path, peer_fq):
    root = _setup(tmp_path, peer_entry=_peer_entry(0.8, 8.0, 0.096))
    first = pa.build_peer_alternatives_snapshot(root=root, as_of=AS_OF)
    assert _alert(first)["status"] == pa.CANDIDATE
    pa.write_peer_alternatives_snapshot(root, first)

    # A re-run in the same ISO week never advances the alert.
    same_week = pa.build_peer_alternatives_snapshot(root=root, as_of="2026-10-09")
    assert _alert(same_week)["status"] == pa.CANDIDATE

    write_market(root, {POSITION: market_entry(price_date=NEXT_WEEK, price=50.0, bvps=50.0, eps_ttm=5.0,
                                               shares_outstanding=100.0, distributions_ttm=400.0)}, NEXT_WEEK)
    _write_market_peers(root, {PEER: _peer_entry(0.8, 8.0, 0.096, as_of=NEXT_WEEK)}, NEXT_WEEK)
    second = pa.build_peer_alternatives_snapshot(root=root, as_of=NEXT_WEEK)
    alert = _alert(second)
    assert alert["status"] == pa.ACTIVE and alert["consecutive_runs"] == 2 and alert["first_seen"] == AS_OF
    assert second["provenance"]["files"]["previous_run"]["path"].startswith("data/alerts/peer_alternatives_")


def test_write_is_immutable_and_byte_stable(tmp_path, peer_fq):
    root = _setup(tmp_path, peer_entry=_peer_entry(0.8, 8.0, 0.096))
    payload = pa.build_peer_alternatives_snapshot(root=root, as_of=AS_OF, code_version="test")
    path = pa.write_peer_alternatives_snapshot(root, payload)
    pointer = (root / "data/alerts/current.json").read_bytes()
    again = pa.write_peer_alternatives_snapshot(
        root, pa.build_peer_alternatives_snapshot(root=root, as_of=AS_OF, code_version="test"))
    assert again == path and (root / "data/alerts/current.json").read_bytes() == pointer
    assert path.name == f"peer_alternatives_{AS_OF}.json"


def _keys(value):
    if isinstance(value, dict):
        for key, item in value.items():
            yield key
            yield from _keys(item)
    elif isinstance(value, list):
        for item in value:
            yield from _keys(item)


def test_no_order_fields_and_owner_files_and_fq_untouched(tmp_path, peer_fq):
    root = _setup(tmp_path, peer_entry=_peer_entry(0.8, 8.0, 0.096))
    portfolio = (root / "config/portfolio.yaml").read_bytes()
    positions = (root / "config/positions.yaml").read_bytes()
    scoring_files = {p: p.read_bytes() for p in (root / "data/scoring").iterdir()}
    fq_before = build_score_snapshot(root=root, code_version="x")

    assert pa.main(["--root", str(root), "--as-of", AS_OF, "--write"]) == 0

    payload = json.loads(next((root / "data/alerts").glob("peer_alternatives_*.json")).read_text())
    assert payload["alerts"], "fixture should produce an alert"
    assert not FORBIDDEN_OUTPUT_KEYS & set(_keys(payload))
    assert (root / "config/portfolio.yaml").read_bytes() == portfolio
    assert (root / "config/positions.yaml").read_bytes() == positions
    assert {p: p.read_bytes() for p in (root / "data/scoring").iterdir()} == scoring_files
    fq_after = build_score_snapshot(root=root, code_version="x")
    assert fq_after["reproducibility_hash"] == fq_before["reproducibility_hash"]
    assert fq_after["scores"] == fq_before["scores"]


# ------------------------------------------------------------- market peers


def test_market_peers_validation(tmp_path):
    known, metrics = {PEER}, {"pe", "price_to_book"}
    good = {"schema_version": 1, "as_of": AS_OF, "tickers": {PEER: {"multiples": {"pe": _multiple(8.0)}}}}
    pa.validate_market_peers_file(good, known, metrics, "x")
    for bad in (
        {**good, "tickers": {"ASR": {}}},
        {**good, "tickers": {PEER: {"multiples": {"pe": datapoint(8.0)}}}},
        {**good, "tickers": {PEER: {"multiples": {"ev_sales": _multiple(2.0)}}}},
        {**good, "tickers": {PEER: {"price": datapoint(10.0)}}},
    ):
        with pytest.raises(MarketDataError):
            pa.validate_market_peers_file(bad, known, metrics, "x")


def test_direct_multiple_scores_like_computed_inputs():
    cfg = pa.load_decision_config(ROOT)["valuation"]
    refs = {"pe": reference(None, 10.0)["peers"]}
    computed = pa.company_valuation_metrics(
        entry=market_entry(price=40.0, eps_ttm=5.0), company_type="INSURER", peer_refs=refs, cfg=cfg)["pe"]
    direct = pa.company_valuation_metrics(
        entry={"multiples": {"pe": _multiple(8.0)}}, company_type="INSURER", peer_refs=refs, cfg=cfg)["pe"]
    assert computed["value"] == direct["value"] == 8.0
    assert computed["score"] == direct["score"]
    negative = pa.company_valuation_metrics(
        entry={"multiples": {"pe": _multiple(-8.0)}}, company_type="INSURER", peer_refs=refs, cfg=cfg)["pe"]
    assert negative["status"] == "NOT_APPLICABLE" and negative["score"] is None


def test_repo_run_is_analysis_only():
    payload = pa.build_peer_alternatives_snapshot(root=ROOT, as_of="2026-10-05")
    assert payload["execution_effect"] == "NONE"
    assert payload["summary"]["peers_evaluated"] > 0


# ---------------------------------------------------------------- dashboard


def test_dashboard_section_and_badges():
    from portfolio_cockpit.decision_layer import dashboard

    data = dashboard.collect(ROOT)
    base = {"top_metric_differences": [{"axis": "valuation", "metric": "pe", "difference_points": 25.0}],
            "position_fundamental_quality": 66.1, "peer_fundamental_quality": 80.0,
            "position_comparison_valuation": 50.0, "peer_comparison_valuation": 75.0,
            "basis": pa.BASIS_FULL, "first_seen": AS_OF, "execution_effect": "NONE"}
    alerts = [{**base, "position": "ASR", "peer": "NN.AS", "type": pa.BETTER, "status": pa.ACTIVE},
              {**base, "position": "EMN", "peer": "CE", "type": pa.CHEAPER, "status": pa.CANDIDATE}]
    data["peer_alternatives"] = {**data["peer_alternatives"], "alerts": alerts}
    for row in data["rows"]:
        row["peer_alerts"] = [a for a in alerts if a["position"] == row["ticker"]]
    html = dashboard.render(data)
    assert html.index("Peer-alternatieven") < html.index("Drill-down per ticker")
    assert '<tr class=pa-active><td>ACTIVE</td>' in html
    assert '<tr class=pa-cand><td>CANDIDATE</td>' in html
    assert 'class="badge pa-active"' in html and 'class="badge pa-cand"' in html


def test_dashboard_without_alerts_says_so():
    from portfolio_cockpit.decision_layer import dashboard

    html = dashboard.render(dashboard.collect(ROOT))
    assert "Peer-alternatieven" in html and "No peer alternatives flagged." in html
