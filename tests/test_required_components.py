from pathlib import Path
import yaml

ROOT=Path(__file__).resolve().parents[1]


def test_required_components_exist_and_are_weighted():
    types=yaml.safe_load((ROOT/"config/company_types.yaml").read_text(encoding="utf-8"))
    for name,cfg in types.items():
        components=cfg["quality_components"]
        assert abs(sum(components.values())-1.0) < 1e-9, name
        required=cfg["required_components"]
        assert required, name
        assert set(required) <= set(components), name


def test_insurer_requires_capital_and_underwriting():
    types=yaml.safe_load((ROOT/"config/company_types.yaml").read_text(encoding="utf-8"))
    assert set(types["INSURER"]["required_components"])=={"capital_strength","underwriting_quality"}
