#!/usr/bin/env python3
"""Build out/dashboard.html: one static file, no scripts, no external hosts."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from portfolio_cockpit.decision_layer.dashboard import build_dashboard  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path, default=Path("out/dashboard.html"))
    parser.add_argument("--as-of", help="ISO date for in-memory drift/valuation when none is written")
    args = parser.parse_args(argv)
    root = args.root.resolve()
    output = args.output if args.output.is_absolute() else root / args.output
    print(build_dashboard(root, output, args.as_of))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
