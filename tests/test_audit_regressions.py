import json
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_skyward_h1_combined_ratio_uses_h1_not_q2_headline():
    data = json.loads((ROOT / "data/peers/PLMR/2026-10-03.json").read_text(encoding="utf-8"))
    metric = data["companies"]["SKWD"]["metrics"]["combined_ratio_pct"]
    assert metric["value"] == pytest.approx(90.0)
    assert "H1" in metric["source_definition"]


def test_huntsman_q2_revenue_growth_uses_exact_prior_year_revenue():
    data = json.loads((ROOT / "data/peers/EMN/2026-10-03.json").read_text(encoding="utf-8"))
    metric = data["companies"]["HUN"]["metrics"]["reported_revenue_growth_pct"]
    expected = (1663 / 1458 - 1) * 100
    assert metric["value"] == pytest.approx(expected, rel=1e-6)
