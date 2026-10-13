"""Deterministic tests for dated data and public/private publication boundary."""
from portfolio_cockpit.decision_layer.freshness import (
    age_status, assess_freshness, sessions_old, stale_inputs,
)
from portfolio_cockpit.decision_layer.dashboard import collect, render

from dl_helpers import ROOT


def test_weekends_do_not_count_as_trading_sessions():
    assert sessions_old("2026-10-09", "2026-10-10") == 0
    assert sessions_old("2026-10-09", "2026-10-12") == 1
    assert sessions_old("2026-10-09", "2026-10-13") == 2
    assert age_status("2026-10-09", "2026-10-12")["status"] == "FRESH"
    assert age_status("2026-10-09", "2026-10-13")["status"] == "STALE"


def test_missing_malformed_or_future_dates_are_not_fresh():
    assert age_status(None, "2026-10-13")["status"] == "MISSING_OR_INVALID"
    assert age_status("invalid", "2026-10-13")["status"] == "MISSING_OR_INVALID"
    assert age_status("2026-10-14", "2026-10-13")["status"] == "MISSING_OR_INVALID"


def test_repository_dates_trigger_stale_portfolio_warnings():
    result = assess_freshness(ROOT, "2026-10-13")
    assert result["account"]["as_of"] == "2026-10-04"
    assert result["positions"]["status"] == "STALE"
    assert result["market"]["status"] == "STALE"
    assert result["valuation"]["status"] == "STALE"
    assert result["decisions"]["status"] == "STALE"
    assert "positions" in stale_inputs(result)


def test_public_dashboard_hides_broker_details_and_historical_signals():
    data = collect(ROOT, "2026-10-13")
    assert data["account_snapshot"] is None
    assert data["portfolio_inputs_stale"] is True
    page = render(data)
    assert "Private account data are not published" in page
    assert "209975.48" not in page
    assert "549342.00" not in page
    assert "Historical portfolio inputs" in page
    assert "STALE_DATA" in page
    assert "— (stale price)" in page
    assert "Historical only:" in page
    assert "Unavailable: historical position weights." in page


def test_local_explicit_private_mode_does_not_change_public_default():
    public = collect(ROOT, "2026-10-13")
    private = collect(ROOT, "2026-10-13", include_private_account=True)
    assert public["account_snapshot"] is None
    assert private["account_snapshot"]["as_of"] == "2026-10-04"
