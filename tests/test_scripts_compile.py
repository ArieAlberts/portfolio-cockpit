from pathlib import Path
import py_compile

ROOT = Path(__file__).resolve().parents[1]


def test_all_python_sources_and_scripts_compile():
    files = sorted((ROOT / "src").rglob("*.py")) + sorted((ROOT / "scripts").rglob("*.py"))
    assert files
    for path in files:
        py_compile.compile(str(path), doraise=True)
