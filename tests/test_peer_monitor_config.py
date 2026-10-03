from pathlib import Path
import yaml

ROOT=Path(__file__).resolve().parents[1]


def test_peer_universe_method_matches_scoring_method():
    universes=yaml.safe_load((ROOT/"config/peer_universes.yaml").read_text(encoding="utf-8"))
    scoring=yaml.safe_load((ROOT/"config/scoring.yaml").read_text(encoding="utf-8"))
    assert universes["defaults"]["method"] == scoring["fundamental_quality"]["peer_method"]
    assert universes["defaults"]["clip_z"] == scoring["fundamental_quality"]["clip_z_score"]


def test_verified_non_us_discovery_overrides_exist():
    cfg=yaml.safe_load((ROOT/"config/peer_monitoring.yaml").read_text(encoding="utf-8"))
    required={"AGS.BR","ARK.PA","AZE.BR","BNR.DE","CS.TO","GIB.A.TO","HEN3.DE","IMI.L","IVN.TO","JD.L","KAP.L","LUN.TO","METSO.HE","SBRE.L","SIKA.SW","SOP.PA"}
    assert required <= set(cfg["discovery_overrides"])
    assert all(cfg["discovery_overrides"][ticker]["source_quality"]=="HIGH" for ticker in required)
