"""Only a run on main may push to main.

A workflow that runs on feature-branch pushes and then does
``git push origin HEAD:main`` lands the whole unreviewed branch on main.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = sorted((ROOT / ".github/workflows").glob("*.yml"))
MAIN_GUARD = "github.ref == 'refs/heads/main'"


def _push_branches(workflow: dict) -> list[str] | None:
    triggers = workflow.get(True) or workflow.get("on") or {}  # PyYAML reads `on:` as True
    push = triggers.get("push") if isinstance(triggers, dict) else None
    if push is None:
        return []
    return (push or {}).get("branches")


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: p.name)
def test_steps_pushing_to_main_only_run_on_main(path):
    workflow = yaml.safe_load(path.read_text(encoding="utf-8"))
    branches = _push_branches(workflow)
    push_limited_to_main = branches == ["main"]
    for job_name, job in (workflow.get("jobs") or {}).items():
        for step in job.get("steps") or []:
            if "HEAD:main" not in str(step.get("run", "")):
                continue
            guarded = MAIN_GUARD in str(step.get("if", "")) or MAIN_GUARD in str(job.get("if", ""))
            assert guarded or push_limited_to_main, (
                f"{path.name}:{job_name}:{step.get('name')} pushes to main without `if: {MAIN_GUARD}`"
            )
