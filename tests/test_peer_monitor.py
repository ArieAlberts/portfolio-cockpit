import json
from pathlib import Path

from portfolio_cockpit.monitoring.peer_monitor import (
    build_peer_source_specs,
    cik_from_sec_archive_url,
    normalize_sec_lookup_ticker,
)

ROOT = Path(__file__).resolve().parents[1]


def test_sec_archive_url_extracts_padded_cik():
    url="https://www.sec.gov/Archives/edgar/data/64040/abc/file.htm"
    assert cik_from_sec_archive_url(url) == "0000064040"


def test_suffix_is_removed_for_sec_lookup():
    assert normalize_sec_lookup_ticker("TRI.TO") == "TRI"
    assert normalize_sec_lookup_ticker("RELX.L") == "RELX"


def test_peer_specs_cover_dependencies_and_prefer_sec_resolution(tmp_path: Path):
    peer_file=tmp_path/"p.json"
    peer_file.write_text(json.dumps({
        "target_ticker":"TARGET",
        "companies":{
            "TARGET":{"role":"TARGET"},
            "PEER":{"role":"PEER","source":{"url":"https://ir.example.com/results"}},
        }
    }))
    idx={"datasets":{"TARGET":"p.json"}}
    specs=build_peer_source_specs(
        root=tmp_path,
        peer_index=idx,
        sec_ticker_map={"PEER":"0000123456"},
    )
    assert len(specs)==1
    assert specs[0].mode=="SEC_SUBMISSIONS_JSON"
    assert specs[0].url.endswith("CIK0000123456.json")
    assert specs[0].dependent_targets==("TARGET",)


def test_real_peer_index_produces_many_unique_sources():
    idx=json.loads((ROOT/"data/peers/index.json").read_text(encoding="utf-8"))
    specs=build_peer_source_specs(root=ROOT,peer_index=idx,sec_ticker_map={})
    assert len(specs) >= 40
    assert any("WKL" in spec.dependent_targets for spec in specs)
