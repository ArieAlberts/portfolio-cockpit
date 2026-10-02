import json
from pathlib import Path
import yaml


ROOT = Path(__file__).resolve().parents[1]


def test_every_portfolio_company_has_a_baseline():
    portfolio = yaml.safe_load((ROOT / "config/portfolio.yaml").read_text(encoding="utf-8"))
    index = json.loads((ROOT / "data/baselines/index.json").read_text(encoding="utf-8"))
    assert set(portfolio["positions"]) == set(index["baselines"])

    for ticker, relative_path in index["baselines"].items():
        path = ROOT / relative_path
        assert path.exists(), f"Missing baseline for {ticker}: {relative_path}"
        baseline = json.loads(path.read_text(encoding="utf-8"))
        assert baseline["ticker"] == ticker
        assert baseline["quality_drift_score"] == 50.0
        assert baseline["fundamental_quality_score"] is None


def test_baselines_cannot_claim_live_execution():
    index = json.loads((ROOT / "data/baselines/index.json").read_text(encoding="utf-8"))
    for relative_path in index["baselines"].values():
        text = (ROOT / relative_path).read_text(encoding="utf-8").lower()
        assert "place_order" not in text
        assert "submit_order" not in text
