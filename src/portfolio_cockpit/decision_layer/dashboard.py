"""Static HTML dashboard: one self-contained file, no scripts, no external hosts.

Quality Drift, Fundamental Quality (peer) and Valuation are separate,
visually distinct blocks:
  Quality Drift  -> "62 (+12 since baseline)"   own development vs baseline 50
  Fundamental Q. -> score only when DISPLAY_READY, otherwise "n.v.t. (DATA_CHECK)"
  Valuation      -> "43 / Expensive"            versus own history + peers
Scores are never called a percentile. Drill-down uses <details> elements.
"""
from __future__ import annotations

import html
import json
import re
from pathlib import Path
from typing import Any

from portfolio_cockpit.config import load_config

from .config import load_decision_config, missing_owner_inputs
from .decision import _fq_for, _fundamental_quality
from .drift import build_drift_snapshot
from .io import read_current
from .risk import impact_pp
from .valuation import build_valuation_snapshot
from .warnings import contract_warnings, load_target_confidence


REVISION_RE = re.compile(r"^(?P<prefix>[a-z_]+)_(?P<date>\d{4}-\d{2}-\d{2})(?:_r(?P<rev>\d+))?\.json$")


def _esc(value: Any) -> str:
    return html.escape("" if value is None else str(value))


def _fmt(value: Any, digits: int = 1, suffix: str = "") -> str:
    if value is None:
        return "—"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return f"{value:.{digits}f}{suffix}"
    return str(value)


def _signed(value: float | None, digits: int = 1) -> str:
    return "—" if value is None else f"{value:+.{digits}f}"


def _history(root: Path, rel_dir: str, prefix: str, extract) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    directory = root / rel_dir
    if not directory.is_dir():
        return out
    files = []
    for path in directory.glob(f"{prefix}_*.json"):
        match = REVISION_RE.match(path.name)
        if match and match["prefix"] == prefix:
            files.append((match["date"], int(match["rev"] or 1), path))
    for day, rev, path in sorted(files):
        payload = json.loads(path.read_text(encoding="utf-8"))
        for ticker, result in payload.get("results", {}).items():
            out.setdefault(ticker, []).append(
                {"as_of": day, "revision": rev, "file": path.relative_to(root).as_posix(), **extract(result)}
            )
    return out


def collect(root: Path, as_of: str | None = None) -> dict[str, Any]:
    """Gather everything the dashboard shows; computes drift/valuation in memory if not written."""
    repo_cfg = load_config(root)
    cfg = load_decision_config(root)

    found = read_current(root, root / "data/drift", "current_quality_drift")
    drift = found[1] if found else build_drift_snapshot(root=root, as_of=as_of)
    drift_written = found is not None
    found = read_current(root, root / "data/valuation", "current_valuation")
    valuation = found[1] if found else build_valuation_snapshot(root=root, as_of=as_of)
    valuation_written = found is not None
    found = read_current(root, root / "data/decisions", "current_decisions")
    decisions = found[1] if found else None
    _, fq_snapshot = _fundamental_quality(root)
    _, confidence = load_target_confidence(root)

    owner_missing = missing_owner_inputs(cfg)
    positions = cfg["positions"]["positions"]
    thesis = cfg["thesis_status"]["positions"]
    shock = float(cfg["risk_scenarios"]["standard_shock"])

    history = {
        "drift": _history(root, "data/drift", "quality_drift",
                          lambda r: {"score": r.get("drift_score"), "status": r.get("status")}),
        "valuation": _history(root, "data/valuation", "valuation",
                              lambda r: {"score": r.get("valuation_score"), "status": r.get("status")}),
        "decisions": _history(root, "data/decisions", "decisions",
                              lambda r: {"score": None, "status": r.get("decision_state")}),
    }

    rows = []
    for ticker, position in repo_cfg["portfolio"]["positions"].items():
        d = drift["results"].get(ticker, {})
        v = valuation["results"].get(ticker, {})
        c = confidence.get(ticker, {})
        decision = (decisions or {}).get("results", {}).get(ticker)
        weight = positions[ticker].get("weight_pct")
        warnings = (
            contract_warnings("drift", d.get("warnings", []))
            + contract_warnings("valuation", v.get("warnings", []))
            + contract_warnings("confidence", c.get("raw_warnings", []))
        )
        rows.append(
            {
                "ticker": ticker,
                "company": position.get("company"),
                "company_type": position["company_type"],
                "portfolio_weight_pct": weight,
                "base_target_weight_pct": position["weight_pct"],
                "portfolio_impact_pp": impact_pp(float(weight), shock) if weight is not None else None,
                "drift": d,
                "valuation": v,
                "fundamental_quality": _fq_for(fq_snapshot, ticker),
                "confidence": c,
                "thesis": thesis[ticker],
                "decision": decision,
                "warnings": warnings,
                "history": {k: h.get(ticker, []) for k, h in history.items()},
            }
        )
    return {
        "as_of": drift["as_of"],
        "drift_as_of": drift["as_of"],
        "valuation_as_of": valuation["as_of"],
        "decisions_as_of": decisions["as_of"] if decisions else None,
        "drift_written": drift_written,
        "valuation_written": valuation_written,
        "owner_missing": owner_missing,
        "impact_label": cfg["risk_scenarios"]["standard_label"],
        "portfolio_risk": (decisions or {}).get("portfolio_risk"),
        "rows": rows,
    }


# ---------------------------------------------------------------- rendering


STATE_CLASS = {
    "ADD_CANDIDATE": "s-add",
    "HOLD": "s-hold",
    "NO_ADD": "s-noadd",
    "REVIEW_REDUCE": "s-reduce",
    "THESIS_REVIEW": "s-thesis",
    "DATA_CHECK": "s-check",
}


def _drift_cell(d: dict[str, Any]) -> str:
    if d.get("drift_score") is None:
        diag = d.get("diagnostic_drift_score")
        title = f' title="diagnostic {diag:.1f}"' if diag is not None else ""
        return f"<span{title}>{_esc(d.get('status', '—'))}</span>"
    return (
        f"<b>{d['drift_score']:.0f}</b> ({_signed(d.get('drift_change_since_baseline'), 0)} since baseline)"
        f"<div class=small>{_esc(d.get('status'))}</div>"
    )


def _fq_cell(fq: dict[str, Any]) -> str:
    if fq.get("status") == "DISPLAY_READY" and fq.get("score") is not None:
        return f"<b>{fq['score']:.0f}</b> <span class=small>/ peer mean 50</span>"
    band = fq.get("diagnostic_band")
    tip = ""
    if fq.get("diagnostic_score") is not None:
        tip = f"diagnostic {fq['diagnostic_score']:.1f}"
        if band and None not in band:
            tip += f" (band {band[0]:.1f}–{band[1]:.1f}, {fq.get('stability_flag')})"
    title = f' title="{_esc(tip)}"' if tip else ""
    return f"<span{title}>n.v.t. ({_esc(fq.get('status') or 'DATA_CHECK')})</span>"


def _valuation_cell(v: dict[str, Any]) -> str:
    if v.get("valuation_score") is None:
        return f"<span>{_esc(v.get('status', '—'))}</span>"
    return f"<b>{v['valuation_score']:.0f}</b> / {_esc(v.get('label'))}"


def _warning_cell(warnings: list[dict[str, str]]) -> str:
    if not warnings:
        return "—"
    counts: dict[str, int] = {}
    for w in warnings:
        counts[w["code"]] = counts.get(w["code"], 0) + 1
    title = _esc("\n".join(f"{w['axis']}: {w['detail']}" for w in warnings))
    chips = " ".join(f"<span class=warn>{_esc(code)}×{n}</span>" for code, n in sorted(counts.items()))
    return f'<span title="{title}">{chips}</span>'


def _row(r: dict[str, Any]) -> str:
    d, v, c, decision = r["drift"], r["valuation"], r["confidence"], r["decision"]
    state = decision["decision_state"] if decision else "NOT_RUN"
    price = v.get("price")
    return (
        "<tr>"
        f'<td><a href="#t-{_esc(r["ticker"])}"><b>{_esc(r["ticker"])}</b></a>'
        f'<div class=small>{_esc(r["company"])}</div></td>'
        f"<td class=num>{_fmt(r['portfolio_weight_pct'], 1, '%')}</td>"
        f"<td class=num>{_fmt(r['base_target_weight_pct'], 1, '%')}</td>"
        f"<td class=num>{_fmt(price, 2)} {_esc(v.get('currency') or '')}</td>"
        f"<td class=q>{_drift_cell(d)}</td>"
        f"<td class=f>{_fq_cell(r['fundamental_quality'])}</td>"
        f"<td class=v>{_valuation_cell(v)}</td>"
        f"<td class=num>{_fmt(c.get('data_confidence'), 1)}</td>"
        f"<td class=num>{_fmt(r['portfolio_impact_pp'], 2, ' pp')}</td>"
        f"<td>{_esc(r['thesis'].get('status') or '—')}</td>"
        f'<td><span class="state {STATE_CLASS.get(state, "s-none")}">{_esc(state)}</span></td>'
        f"<td>{_esc(d.get('last_fundamental_update') or '—')}</td>"
        f"<td>{_esc(v.get('price_as_of') or '—')}</td>"
        f"<td>{_warning_cell(r['warnings'])}</td>"
        "</tr>"
    )


def _source_link(source: dict[str, Any] | None) -> str:
    if not source:
        return "—"
    title = _esc(source.get("title") or source.get("source_type") or "source")
    date = _esc(source.get("publication_date") or source.get("as_of_date") or "")
    url = source.get("url")
    if url and str(url).startswith(("https://", "http://")):
        return f'<a href="{_esc(url)}" rel="noopener noreferrer">{title}</a> {date}'
    return f"{title} {date}"


def _drift_detail(d: dict[str, Any]) -> str:
    metrics = d.get("metrics") or []
    if not metrics:
        return "<p class=small>No drift metrics.</p>"
    ordered = sorted(metrics, key=lambda m: -(m.get("contribution_points") or 0.0))
    rows = []
    for m in ordered:
        points = m.get("contribution_points") or 0.0
        cls = "pos" if points > 0 else "neg" if points < 0 else ""
        rows.append(
            "<tr>"
            f"<td>{_esc(m['component'])}.{_esc(m['metric'])}</td>"
            f"<td class=num>{_fmt(m.get('baseline_value'), 2)}</td>"
            f"<td class=num>{_fmt(m.get('previous_value'), 2)}</td>"
            f"<td class=num>{_fmt(m.get('raw_value'), 2)}</td>"
            f"<td class=num>{_fmt(m.get('normalized_signal'), 2)}</td>"
            f'<td class="num {cls}">{_signed(points, 2)}</td>'
            f"<td>{_esc(m.get('status'))}</td>"
            f"<td>{_source_link(m.get('source') or m.get('baseline_source'))}</td>"
            "</tr>"
        )
    return (
        "<table class=inner><tr><th>Metric</th><th>Baseline</th><th>Previous</th><th>New</th>"
        "<th>Signal</th><th>Points</th><th>Status</th><th>Source</th></tr>" + "".join(rows) + "</table>"
    )


def _valuation_detail(v: dict[str, Any]) -> str:
    metrics = v.get("metrics") or []
    if not metrics:
        return f"<p class=small>{_esc(v.get('status', 'No valuation'))}.</p>"
    rows = []
    for m in metrics:
        refs = ", ".join(
            f"{_esc(kind)} {_fmt(item.get('value'), 2)} ({_esc(item.get('method'))})"
            for kind, item in (m.get("reference") or {}).items()
        )
        rows.append(
            "<tr>"
            f"<td>{_esc(m['metric'])}</td>"
            f"<td class=num>{_fmt(m.get('value'), 2)}</td>"
            f"<td>{_esc(m.get('status'))}</td>"
            f"<td class=num>{_fmt(m.get('score'), 0)}</td>"
            f"<td class=num>{_fmt(m.get('reference_value'), 2)}</td>"
            f"<td>{refs or '—'}</td>"
            f"<td>{_esc(m.get('calculation_method'))}</td>"
            f"<td>{_esc(m.get('note'))}</td>"
            "</tr>"
        )
    return (
        "<table class=inner><tr><th>Metric</th><th>Value</th><th>Status</th><th>Score</th>"
        "<th>Reference</th><th>Reference basis</th><th>Method</th><th>Note</th></tr>"
        + "".join(rows)
        + "</table>"
    )


def _confidence_detail(c: dict[str, Any]) -> str:
    if not c:
        return "<p class=small>No target confidence.</p>"
    parts = ", ".join(f"{_esc(k)} {_fmt(v, 0)}" for k, v in (c.get("components") or {}).items())
    return f"<p>Score {_fmt(c.get('data_confidence'), 1)} ({_esc(c.get('status'))}): {parts}</p>"


def _history_detail(history: dict[str, list[dict[str, Any]]]) -> str:
    rows = []
    for axis, items in history.items():
        for item in items:
            rows.append(
                f"<tr><td>{_esc(axis)}</td><td>{_esc(item['as_of'])}</td><td>r{item['revision']}</td>"
                f"<td class=num>{_fmt(item.get('score'), 1)}</td><td>{_esc(item.get('status'))}</td>"
                f"<td class=small>{_esc(item['file'])}</td></tr>"
            )
    if not rows:
        return "<p class=small>No written revisions yet.</p>"
    return (
        "<table class=inner><tr><th>Axis</th><th>As of</th><th>Rev</th><th>Score</th><th>Status</th>"
        "<th>File</th></tr>" + "".join(rows) + "</table>"
    )


def _detail(r: dict[str, Any]) -> str:
    decision = r["decision"] or {}
    reasons = ", ".join(_esc(x) for x in decision.get("reasons", [])) or "—"
    flags = ", ".join(_esc(x) for x in decision.get("limit_flags", [])) or "—"
    note = _esc(r["thesis"].get("note") or "")
    return (
        f'<details id="t-{_esc(r["ticker"])}"><summary><b>{_esc(r["ticker"])}</b> — '
        f'{_esc(r["company"])} <span class=small>({_esc(r["company_type"])})</span></summary>'
        f"<p><b>Decision:</b> {_esc(decision.get('decision_state', 'NOT_RUN'))}. Reasons: {reasons}. "
        f"Limit flags: {flags}. Thesis: {_esc(r['thesis'].get('status') or '—')} {note}</p>"
        f"<h3 class=hq>Quality Drift</h3>{_drift_detail(r['drift'])}"
        f"<h3 class=hv>Valuation</h3>{_valuation_detail(r['valuation'])}"
        f"<h3>Data confidence</h3>{_confidence_detail(r['confidence'])}"
        f"<h3>Revision history</h3>{_history_detail(r['history'])}"
        "</details>"
    )


def _banner(data: dict[str, Any]) -> str:
    notes = []
    missing = data["owner_missing"]
    if missing["positions"] or missing["thesis_status"]:
        notes.append(
            f"Owner inputs incomplete: {len(missing['positions'])} field(s) in config/positions.yaml, "
            f"{len(missing['thesis_status'])} in config/thesis_status.yaml. "
            "Decisions are not run; see <code>cockpit-check-inputs</code>."
        )
    if not data["drift_written"]:
        notes.append("Quality Drift computed in memory (no written revision yet).")
    if not data["valuation_written"]:
        notes.append("Valuation computed in memory (no written revision yet).")
    if not notes:
        return ""
    return "<div class=banner>" + "<br>".join(notes) + "</div>"


def _scenarios(data: dict[str, Any]) -> str:
    risk = data.get("portfolio_risk")
    if not risk:
        return ""
    rows = "".join(
        f"<tr><td>{_esc(name)}</td><td>{_esc(s['description'])}</td><td class=num>{_fmt(s['total_pp'], 2, ' pp')}</td></tr>"
        for name, s in risk["scenarios"].items()
    )
    sectors = ", ".join(f"{_esc(k)} {_fmt(v, 1, '%')}" for k, v in risk["sector_weights_pct"].items())
    return (
        f"<h2>Portfolio risk scenarios</h2><p class=small>Sector weights: {sectors}</p>"
        "<div class=wrap><table class=inner><tr><th>Scenario</th><th>Description</th><th>Portfolio impact</th></tr>"
        f"{rows}</table></div>"
    )


CSS = """
:root{--bg:#f7f7f5;--panel:#fff;--ink:#1d1d1b;--muted:#6b6b66;--line:#e3e2dc;
--q:#1f6f5c;--q-bg:#e6f2ee;--f:#3f4b8c;--f-bg:#eceefa;--v:#7a4a12;--v-bg:#f6eedf;
--neg:#b3261e;--pos:#1f6f3a;--warn:#9a6700;--warn-bg:#fff4d6}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#151514;--panel:#1e1e1c;--ink:#ecebe6;
--muted:#a3a29b;--line:#34332f;--q:#7fd1b9;--q-bg:#183129;--f:#aab4f0;--f-bg:#1e2340;--v:#e9b872;--v-bg:#33270f;
--neg:#ff8a80;--pos:#8fd19e;--warn:#f2c14e;--warn-bg:#3a2f10}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);
font:14px/1.45 system-ui,-apple-system,Segoe UI,Roboto,sans-serif}
main{max-width:1400px;margin:0 auto;padding:20px 16px 48px}
h1{font-size:20px;margin:0 0 4px}h2{font-size:16px;margin:24px 0 8px}h3{font-size:13px;margin:12px 0 4px}
.sub,.small{color:var(--muted);font-size:12px}a{color:inherit}
.legend{display:flex;gap:8px;flex-wrap:wrap;margin:8px 0 12px;font-size:12px}
.chip{padding:2px 8px;border-radius:999px;font-weight:600}
.cq{background:var(--q-bg);color:var(--q)}.cf{background:var(--f-bg);color:var(--f)}.cv{background:var(--v-bg);color:var(--v)}
.banner{background:var(--warn-bg);color:var(--warn);border-radius:8px;padding:8px 12px;margin:8px 0 12px}
.wrap{overflow-x:auto;background:var(--panel);border:1px solid var(--line);border-radius:10px}
table{border-collapse:collapse;width:100%}table.main{min-width:1300px}
th,td{padding:7px 9px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top;font-variant-numeric:tabular-nums}
th{font-size:11px;text-transform:uppercase;letter-spacing:.03em;color:var(--muted);font-weight:600}
td.num{text-align:right;white-space:nowrap}td.q,td.v{white-space:nowrap}
th.q,td.q{background:var(--q-bg)}th.f,td.f{background:var(--f-bg)}th.v,td.v{background:var(--v-bg)}
td.q b{color:var(--q)}td.f b{color:var(--f)}td.v b{color:var(--v)}
h3.hq{color:var(--q)}h3.hv{color:var(--v)}
.pos{color:var(--pos)}.neg{color:var(--neg)}
.warn{display:inline-block;background:var(--warn-bg);color:var(--warn);border-radius:4px;padding:0 4px;margin:1px;font-size:11px}
.state{font-weight:700;font-size:12px;padding:2px 6px;border-radius:4px;border:1px solid var(--line)}
.s-add{color:var(--pos)}.s-reduce,.s-thesis{color:var(--neg)}.s-check{color:var(--warn)}
details{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:8px 12px;margin:6px 0}
summary{cursor:pointer}table.inner td,table.inner th{font-size:12px}
"""


def render(data: dict[str, Any], title: str = "Portfolio Cockpit") -> str:
    head = (
        "<tr><th>Ticker</th><th>Portfolio weight</th><th>Base target weight</th><th>Price</th>"
        "<th class=q>Quality Drift</th><th class=f>Fundamental Quality (peer)</th><th class=v>Valuation</th>"
        f"<th>Data confidence</th><th>{_esc(data['impact_label'])}</th><th>Thesis status</th>"
        "<th>Decision state</th><th>Last fundamental update</th><th>Last valuation update</th><th>Warnings</th></tr>"
    )
    body = "".join(_row(r) for r in data["rows"])
    details = "".join(_detail(r) for r in data["rows"])
    return (
        "<!doctype html><html lang=en><head><meta charset=utf-8>"
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>{_esc(title)}</title><style>{CSS}</style></head><body><main>"
        f"<h1>{_esc(title)}</h1>"
        f"<p class=sub>Drift as of {_esc(data['drift_as_of'])} · Valuation as of {_esc(data['valuation_as_of'])}"
        f" · Decisions as of {_esc(data['decisions_as_of'] or 'not run')} · analytical only, execution effect NONE</p>"
        "<div class=legend><span class='chip cq'>Quality Drift: change vs own baseline (50 = baseline)</span>"
        "<span class='chip cf'>Fundamental Quality: peer-relative, 50 = peer mean</span>"
        "<span class='chip cv'>Valuation: vs own history + peers (50 ≈ fair)</span></div>"
        f"{_banner(data)}"
        f"<div class=wrap><table class=main>{head}{body}</table></div>"
        f"{_scenarios(data)}"
        f"<h2>Drill-down per ticker</h2>{details}"
        "</main></body></html>\n"
    )


def build_dashboard(root: Path, output: Path, as_of: str | None = None) -> Path:
    html_text = render(collect(root, as_of))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(html_text, encoding="utf-8")
    return output
