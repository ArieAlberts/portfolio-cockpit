from copy import deepcopy
from pathlib import Path

import pytest

from portfolio_cockpit.config import ConfigValidationError, load_config, validate_config


ROOT = Path(__file__).resolve().parents[1]


def test_repository_config_validates():
    config = load_config(ROOT)
    assert config["score_metrics"]["schema_version"] == 2


def test_metric_registry_is_centralized():
    config = load_config(ROOT)
    assert "component_metric_aliases" not in config["readiness"]
    metric_cfg = config["score_metrics"]
    assert metric_cfg["component_metric_aliases"]
    assert metric_cfg["metric_directions"]
    assert metric_cfg["metric_kinds"]


def test_validator_rejects_peer_minimum_drift():
    config = load_config(ROOT)
    broken = deepcopy(config)
    broken["readiness"]["minimum_peer_values_per_metric"] = (
        broken["scoring"]["fundamental_quality"]["minimum_peer_values_per_metric"] - 1
    )
    with pytest.raises(ConfigValidationError, match="minimum_peer_values_per_metric differs"):
        validate_config(broken)


def test_validator_rejects_bad_component_weight_sum():
    config = load_config(ROOT)
    broken = deepcopy(config)
    broken["company_types"]["GENERAL_OPERATING_COMPANY"]["quality_components"]["balance_sheet"] = 0.20
    with pytest.raises(ConfigValidationError, match="component weights sum"):
        validate_config(broken)


def test_validator_rejects_missing_metric_kind():
    config = load_config(ROOT)
    broken = deepcopy(config)
    broken["score_metrics"]["metric_kinds"].pop("net_debt_to_ebitda")
    with pytest.raises(ConfigValidationError, match="invalid or missing kind"):
        validate_config(broken)


def test_validator_requires_unstable_threshold_above_stable():
    config = load_config(ROOT)
    broken = deepcopy(config)
    sensitivity = broken["scoring"]["fundamental_quality"]["sensitivity"]
    sensitivity["unstable_band_width_points"] = sensitivity["stable_band_width_points"]
    with pytest.raises(ConfigValidationError, match="sensitivity thresholds"):
        validate_config(broken)


def test_validator_rejects_peer_method_drift():
    config = load_config(ROOT)
    broken = deepcopy(config)
    broken["peer_universes"]["defaults"]["method"] = "other_method"
    with pytest.raises(ConfigValidationError, match="peer_universes.defaults.method differs"):
        validate_config(broken)


def test_validator_rejects_validate_universe_below_production_minimum():
    config = load_config(ROOT)
    broken = deepcopy(config)
    broken["peer_universes"]["universes"]["WKL"]["peers"] = ["A", "B", "C"]
    with pytest.raises(ConfigValidationError, match="VALIDATE universe has only 3 peers"):
        validate_config(broken)


def test_limited_universe_may_document_fewer_than_four_peers():
    config = load_config(ROOT)
    assert config["peer_universes"]["universes"]["DKS"]["status"] == "LIMITED"
    assert config["peer_universes"]["universes"]["DKS"]["minimum_peer_count"] == 3
