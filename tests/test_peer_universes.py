from pathlib import Path
import yaml

from portfolio_cockpit.scoring.peers import validate_peer_universe


ROOT = Path(__file__).resolve().parents[1]


def load_universes():
    data = yaml.safe_load((ROOT / "config/peer_universes.yaml").read_text(encoding="utf-8"))
    return data["universes"]


def test_every_portfolio_ticker_has_a_peer_universe_definition():
    portfolio = yaml.safe_load((ROOT / "config/portfolio.yaml").read_text(encoding="utf-8"))
    universes = load_universes()
    assert set(portfolio["positions"]) == set(universes)


def test_insufficient_peer_set_is_blocked():
    result = validate_peer_universe(load_universes()["ABX"])
    assert result.valid is False
    assert result.status == "INSUFFICIENT"


def test_wkl_peer_set_meets_minimum_count():
    result = validate_peer_universe(load_universes()["WKL"])
    assert result.valid is True
    assert result.peer_count >= result.minimum_peer_count


def test_limited_direct_peer_sets_can_define_lower_minimum():
    result = validate_peer_universe(load_universes()["IMCD"])
    assert result.valid is True
    assert result.minimum_peer_count == 3


def test_oklo_development_peer_set_is_allowed_but_limited():
    result = validate_peer_universe(load_universes()["OKLO"])
    assert result.valid is True
    assert result.confidence == "MEDIUM"
