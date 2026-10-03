from pathlib import Path
import yaml

ROOT=Path(__file__).resolve().parents[1]


def test_target_monitor_reliability_defaults_are_configured():
    cfg=yaml.safe_load((ROOT/"config/source_registry.yaml").read_text(encoding="utf-8"))
    defaults=cfg["defaults"]
    assert defaults["retry_attempts"]>=3
    assert defaults["retry_base_seconds"]>0
    assert defaults["circuit_breaker_failure_threshold"]>=2
    assert defaults["html_fingerprint_mode"]=="RELEVANT_LINKS"


def test_peer_monitor_reliability_defaults_are_configured():
    cfg=yaml.safe_load((ROOT/"config/peer_monitoring.yaml").read_text(encoding="utf-8"))
    defaults=cfg["defaults"]
    assert defaults["retry_attempts"]>=3
    assert defaults["circuit_breaker_failure_threshold"]>=2
    assert defaults["live_execution_allowed"] is False
