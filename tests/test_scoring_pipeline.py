import json
from pathlib import Path

import yaml

from portfolio_cockpit.scoring.pipeline import (
    CODE_FILES,
    CONFIG_FILES,
    build_score_snapshot,
    update_current_pointer,
    write_immutable_snapshot,
)

ROOT=Path(__file__).resolve().parents[1]


def test_pipeline_is_deterministic_for_same_inputs():
    a=build_score_snapshot(root=ROOT,code_version="TEST-COMMIT")
    b=build_score_snapshot(root=ROOT,code_version="TEST-COMMIT")
    assert json.dumps(a,sort_keys=True)==json.dumps(b,sort_keys=True)


def test_pipeline_records_provenance_and_used_peer_tickers():
    payload=build_score_snapshot(root=ROOT,code_version="TEST-COMMIT")
    assert payload["provenance"]["run_git_commit"]=="TEST-COMMIT"
    assert len(payload["provenance"]["pipeline_code_hash"])==64
    assert len(payload["provenance"]["config_hash"])==64
    assert len(payload["reproducibility_hash"])==64
    assert set(payload["provenance"]["config_files"])==set(CONFIG_FILES)
    assert set(payload["provenance"]["code_files"])==set(CODE_FILES)

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


def test_semantically_identical_snapshot_reuses_existing_file(tmp_path: Path):
    first={
        "as_of":"2026-10-03",
        "reproducibility_hash":"a"*64,
        "provenance":{"run_git_commit":"FIRST"},
    }
    second={
        "as_of":"2026-10-03",
        "reproducibility_hash":"a"*64,
        "provenance":{"run_git_commit":"SECOND"},
    }
    p1=write_immutable_snapshot(root=ROOT,payload=first,output_dir=tmp_path)
    p2=write_immutable_snapshot(root=ROOT,payload=second,output_dir=tmp_path)
    assert p1==p2
    assert "FIRST" in p1.read_text()
    assert "SECOND" not in p1.read_text()


def test_dataset_peer_minimum_mismatch_is_visible_and_blocks_publication():
    payload=build_score_snapshot(root=ROOT,code_version="TEST-COMMIT")
    ero=payload["blocked"]["ERO"]
    assert ero["dataset_rule_consistent"] is False
    assert any(w.startswith("DATASET_MIN_PEERS_MISMATCH:3!=4") for w in ero["warnings"])


def test_noop_rebuild_keeps_current_pointer_byte_stable(tmp_path: Path):
    scoring_dir=tmp_path/"data/scoring"
    first={
        "as_of":"2026-10-03",
        "pipeline_version":2,
        "reproducibility_hash":"b"*64,
        "provenance":{
            "run_git_commit":"FIRST",
            "pipeline_code_hash":"c"*64,
            "config_hash":"d"*64,
        },
    }
    second={
        **first,
        "provenance":{
            **first["provenance"],
            "run_git_commit":"SECOND",
        },
    }
    p1=write_immutable_snapshot(root=tmp_path,payload=first,output_dir=scoring_dir)
    update_current_pointer(root=tmp_path,snapshot_path=p1,payload=first)
    current_path=scoring_dir/"current.json"
    before=current_path.read_text()

    p2=write_immutable_snapshot(root=tmp_path,payload=second,output_dir=scoring_dir)
    update_current_pointer(root=tmp_path,snapshot_path=p2,payload=second)
    after=current_path.read_text()

    assert p1==p2
    assert before==after
    assert '"run_git_commit": "FIRST"' in after
