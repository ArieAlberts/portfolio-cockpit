from pathlib import Path

from portfolio_cockpit.scoring.decision import VALID_DECISION_STATES
from portfolio_cockpit.scoring.decision_pipeline import build_decision_snapshot
from portfolio_cockpit.scoring.drift_pipeline import build_drift_snapshot


ROOT = Path(__file__).resolve().parents[1]


def test_drift_pipeline_covers_entire_portfolio_at_immutable_baseline(tmp_path: Path):
    payload = build_drift_snapshot(root=ROOT, signals_dir=tmp_path / "no-signals")
    assert payload["summary"]["portfolio_companies"] == 23
    assert payload["summary"]["baseline"] == 23
    assert payload["summary"]["updated"] == 0
    assert payload["summary"]["data_check"] == 0
    assert all(
        item["quality_drift_score"] == 50.0
        and item["execution_effect"] == "NONE"
        for item in payload["results"].values()
    )


def test_decision_pipeline_covers_entire_portfolio_without_execution_effect(
    tmp_path: Path,
):
    payload = build_decision_snapshot(
        root=ROOT,
        valuation_path=tmp_path / "no-valuation.json",
        thesis_path=tmp_path / "no-thesis.json",
        signals_dir=tmp_path / "no-signals",
    )
    assert payload["summary"]["portfolio_companies"] == 23
    assert set(payload["decisions"]) == set(
        build_drift_snapshot(root=ROOT, signals_dir=tmp_path / "no-signals")["results"]
    )
    assert all(
        item["decision_state"] in VALID_DECISION_STATES
        and item["execution_effect"] == "NONE"
        for item in payload["decisions"].values()
    )
    assert all(
        item["decision_state"] == "HOLD"
        and item["reasons"] == ["VALUATION_PENDING"]
        for item in payload["decisions"].values()
    )
