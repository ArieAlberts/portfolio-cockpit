from pathlib import Path
import yaml

ROOT=Path(__file__).resolve().parents[1]


def test_source_registry_covers_exact_portfolio():
    registry=yaml.safe_load((ROOT/"config/source_registry.yaml").read_text(encoding="utf-8"))
    portfolio=yaml.safe_load((ROOT/"config/portfolio.yaml").read_text(encoding="utf-8"))
    assert set(registry["companies"]) == set(portfolio["positions"])
    assert len(registry["companies"]) == 23


def test_every_registered_company_has_existing_baseline_and_source():
    registry=yaml.safe_load((ROOT/"config/source_registry.yaml").read_text(encoding="utf-8"))
    for ticker, company in registry["companies"].items():
        assert (ROOT/company["baseline_path"]).exists(), ticker
        assert company["sources"], ticker
        for source in company["sources"]:
            assert source["mode"] in {"HTML_PAGE","SEC_SUBMISSIONS_JSON"}
            assert source["url"].startswith("https://")


def test_monitor_cannot_enable_live_execution():
    registry=yaml.safe_load((ROOT/"config/source_registry.yaml").read_text(encoding="utf-8"))
    assert registry["defaults"]["live_execution_allowed"] is False
    assert registry["defaults"]["source_change_changes_score"] is False
