from pathlib import Path


ROOT=Path(__file__).resolve().parents[1]


def test_peer_monitor_has_no_order_methods():
    text=(ROOT/"scripts/monitor_peer_sources.py").read_text(encoding="utf-8").lower()
    forbidden=("place_order","submit_order","cancel_order","modify_order")
    assert all(token not in text for token in forbidden)


def test_peer_events_are_non_executable_by_design():
    text=(ROOT/"scripts/monitor_peer_sources.py").read_text(encoding="utf-8")
    assert '"score_update_allowed": False' in text
    assert '"execution_effect": "NONE"' in text
