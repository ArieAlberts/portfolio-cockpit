import json
from pathlib import Path

import yaml

from portfolio_cockpit.scoring.pipeline import (
    CONFIG_FILES,
    build_score_snapshot,
    write_immutable_snapshot,
)

ROOT=Path(__file__).resolve().parents[1]


def test_pipeline_is_deterministic_for_same_inputs():
    a=build_score_snapshot(root=ROOT,code_version="TEST-COMMIT")
    b=build_score_snapshot(root=ROOT,code_version="TEST-COMMIT")
    assert json.dumps(a,sort_keys=True)==json.dumps(b,sort_keys=True)


def test_pipeline_records_provenance_and_used_peer_tickers():
    payload=build_score_snapshot(root=ROOT,code_version="TEST-COMMIT")
    assert payload["provenance"]["code_version"]=="TEST-COMMIT"
    assert len(payload["provenance"]["config_hash"])==64
    assert set(payload["provenance"]["config_files"])==set(CONFIG_FILES)

    plmr=payload["blocked"]["PLMR"]
    assert plmr["provenance"]["peer_dataset"]["path"].endswith("PLMR/2026-10-03.json")
    assert len(plmr["provenance"]["peer_dataset"]["sha256"])==64
    assert plmr["selected_metrics"]["underwriting_quality"]["peer_tickers"]


def test_audited_insurers_remain_blocked_by_current_files():
    payload=build_score_snapshot(root=ROOT,code_version="TEST-COMMIT")
    assert "ASR" in payload["blocked"]
    assert "PLMR" in payload["blocked"]
    assert "capital_strength" in payload["blocked"]["ASR"]["missing_required_components"]
    assert "capital_strength" in payload["blocked"]["PLMR"]["missing_required_components"]


def test_plmr_peer_set_variation_is_visible():
    payload=build_score_snapshot(root=ROOT,code_version="TEST-COMMIT")
    plmr=payload["blocked"]["PLMR"]
    assert plmr["peer_set_overlap"]["code"]=="PEER_SET_VARIES_BY_METRIC"
    for component,item in plmr["selected_metrics"].items():
        assert "peer_tickers" in item
        assert "peer_values" in item


def test_snapshot_writer_never_overwrites_different_content(tmp_path: Path):
    first={"as_of":"2026-10-03","x":1}
    second={"as_of":"2026-10-03","x":2}
    p1=write_immutable_snapshot(root=ROOT,payload=first,output_dir=tmp_path)
    p1_same=write_immutable_snapshot(root=ROOT,payload=first,output_dir=tmp_path)
    p2=write_immutable_snapshot(root=ROOT,payload=second,output_dir=tmp_path)
    assert p1==p1_same
    assert p2!=p1
    assert p1.read_text()!=p2.read_text()


def test_every_readiness_alias_has_an_explicit_direction():
    readiness=yaml.safe_load((ROOT/"config/readiness.yaml").read_text(encoding="utf-8"))
    directions=yaml.safe_load((ROOT/"config/score_metrics.yaml").read_text(encoding="utf-8"))["metric_directions"]
    for company_type,components in readiness["component_metric_aliases"].items():
        for aliases in components.values():
            for metric in aliases:
                assert metric in directions[company_type], f"{company_type}:{metric}"
