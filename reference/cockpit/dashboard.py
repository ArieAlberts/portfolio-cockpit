"""Statisch HTML-dashboard (zelfstandig bestand) uit score_history.

Quality en Valuation zijn visueel twee verschillende zaken:
  Quality   → "62 (+12 since baseline)"   — fundamentele ontwikkeling t.o.v. baseline 50
  Valuation → "43 / Expensive"            — waardering t.o.v. eigen historie + peers
De Quality Score wordt nergens "percentiel" genoemd.
Klik op een rij voor de onderbouwing: metrics omhoog/omlaag, bron, oud vs nieuw, datum.
"""
from __future__ import annotations

import html
import json

from .repository import Repository
from .risk import PORTFOLIO_IMPACT_LABEL


def _latest_per_ticker(history: list[dict]) -> list[dict]:
    latest: dict[str, dict] = {}
    for h in history:
        latest[h["ticker"]] = h  # history is gesorteerd op datum, id
    return [latest[k] for k in sorted(latest)]


def render(repo: Repository, scenarios: dict | None = None, title: str = "Portfolio Cockpit") -> str:
    history = repo.score_history()
    latest = _latest_per_ticker(history)
    by_ticker: dict[str, list[dict]] = {}
    for h in history:
        by_ticker.setdefault(h["ticker"], []).append(
            {k: h[k] for k in ("score_date", "quality_score", "valuation_score", "valuation_label",
                               "data_confidence", "decision_state", "price")})
    payload = {"latest": latest, "history": by_ticker, "scenarios": scenarios or {},
               "impact_label": PORTFOLIO_IMPACT_LABEL}
    data = json.dumps(payload, default=str).replace("</", "<\\/")
    return _TEMPLATE.replace("__TITLE__", html.escape(title)).replace("__DATA__", data)


_TEMPLATE = r"""<!doctype html>
<html lang="nl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<style>
:root{--bg:#f7f7f5;--panel:#fff;--ink:#1d1d1b;--muted:#6b6b66;--line:#e3e2dc;
--q:#1f6f5c;--q-bg:#e6f2ee;--v:#7a4a12;--v-bg:#f6eedf;--neg:#b3261e;--pos:#1f6f3a;--warn:#9a6700;--warn-bg:#fff4d6;}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#151514;--panel:#1e1e1c;--ink:#ecebe6;
--muted:#a3a29b;--line:#34332f;--q:#7fd1b9;--q-bg:#183129;--v:#e9b872;--v-bg:#33270f;--neg:#ff8a80;--pos:#8fd19e;--warn:#f2c14e;--warn-bg:#3a2f10;}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.45 system-ui,-apple-system,Segoe UI,Roboto,sans-serif}
main{max-width:1280px;margin:0 auto;padding:20px 16px 48px}
h1{font-size:20px;margin:0 0 4px}.sub{color:var(--muted);margin:0 0 16px}
.legend{display:flex;gap:12px;flex-wrap:wrap;margin-bottom:12px;font-size:12px}
.chip{padding:2px 8px;border-radius:999px;font-weight:600}
.cq{background:var(--q-bg);color:var(--q)}.cv{background:var(--v-bg);color:var(--v)}
.wrap{overflow-x:auto;background:var(--panel);border:1px solid var(--line);border-radius:10px}
table{border-collapse:collapse;width:100%;min-width:1100px}
th,td{padding:8px 10px;border-bottom:1px solid var(--line);text-align:left;white-space:nowrap;font-variant-numeric:tabular-nums}
th{font-size:11px;text-transform:uppercase;letter-spacing:.03em;color:var(--muted);font-weight:600}
th.q,td.q{background:var(--q-bg)}th.v,td.v{background:var(--v-bg)}
td.q b{color:var(--q)}td.v b{color:var(--v)}
tr.row{cursor:pointer}tr.row:hover td{filter:brightness(.97)}
.state{font-weight:700;font-size:12px;padding:2px 6px;border-radius:4px;border:1px solid var(--line)}
.ADD_CANDIDATE{color:var(--pos)}.REVIEW_REDUCE,.THESIS_REVIEW{color:var(--neg)}.DATA_CHECK{color:var(--warn);background:var(--warn-bg)}
.neg{color:var(--neg)}.pos{color:var(--pos)}.muted{color:var(--muted)}
.warn{display:inline-block;background:var(--warn-bg);color:var(--warn);font-size:11px;padding:1px 6px;border-radius:4px;margin:1px}
#detail{margin-top:16px;background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:16px;display:none}
#detail h2{margin:0 0 4px;font-size:17px}#detail h3{font-size:13px;margin:18px 0 6px}
#detail table{min-width:0}.cols{display:grid;grid-template-columns:1fr 1fr;gap:16px}
@media(max-width:800px){.cols{grid-template-columns:1fr}}
.scen{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:10px;margin-top:16px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:12px}
.card .big{font-size:20px;font-weight:700}
</style></head><body><main>
<h1>__TITLE__</h1>
<p class="sub">Beslissingsondersteuning — geen orders. Klik een rij voor de onderbouwing.</p>
<div class="legend"><span class="chip cq">QUALITY — fundamentele ontwikkeling t.o.v. baseline (50 = onveranderd)</span>
<span class="chip cv">VALUATION — waardering t.o.v. eigen historie + peers (50 ≈ fair)</span></div>
<div class="wrap"><table id="t"><thead><tr>
<th>Ticker</th><th>Portfolio weight</th><th>Base target</th><th>Price</th>
<th class="q">Quality score</th><th class="v">Valuation</th><th>Data confidence</th>
<th id="impact-h"></th><th>Thesis</th><th>Decision</th><th>Last fundamental update</th><th>Last valuation update</th><th>Warnings</th>
</tr></thead><tbody></tbody></table></div>
<div class="scen" id="scen"></div>
<section id="detail"></section>
</main>
<script>
const D=__DATA__;
const pct=x=>x==null?'—':(x*100).toFixed(1)+'%';
const num=(x,d=1)=>x==null?'—':Number(x).toFixed(d);
const sgn=(x,d=1)=>x==null?'—':(x>=0?'+':'')+Number(x).toFixed(d);
const esc=s=>String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
document.getElementById('impact-h').textContent=D.impact_label;
const tb=document.querySelector('#t tbody');
D.latest.forEach((r,i)=>{
  const ch=r.quality_change_since_baseline;
  const val=r.valuation_score==null?'<span class="muted">n.v.t.</span>':
    `<b>${num(r.valuation_score,0)}</b> / ${r.valuation_label?esc(r.valuation_label):'<span class="muted">geen conclusie</span>'}`;
  const warns=(r.warnings||[]).map(w=>w.split(':')[0]);
  const uniq=[...new Set(warns)].map(w=>`<span class="warn">${w}</span>`).join('');
  const tr=document.createElement('tr');tr.className='row';tr.tabIndex=0;
  tr.innerHTML=`<td><b>${esc(r.ticker)}</b></td><td>${pct(r.portfolio_weight)}</td><td>${pct(r.base_target_weight)}</td>
  <td>${num(r.price,2)}</td>
  <td class="q"><b>${num(r.quality_score,0)}</b> <span class="${ch<0?'neg':ch>0?'pos':'muted'}">(${sgn(ch,0)} since baseline)</span></td>
  <td class="v">${val}</td><td>${num(r.data_confidence,0)}</td>
  <td class="neg">${sgn(r.portfolio_impact_pp,1)} pp</td><td>${esc(r.thesis_status)}</td>
  <td><span class="state ${r.decision_state}">${r.decision_state}</span></td>
  <td>${esc(r.last_fundamental_update)}</td><td>${esc(r.last_valuation_update)}</td><td>${uniq}</td>`;
  tr.onclick=()=>show(i);tr.onkeydown=e=>{if(e.key==='Enter')show(i)};tb.appendChild(tr);
});
const sc=document.getElementById('scen');
Object.entries(D.scenarios).forEach(([k,s])=>{sc.insertAdjacentHTML('beforeend',
 `<div class="card"><div class="muted">${esc(k)}</div><div class="big neg">${sgn(s.total_pp,2)} pp</div><div class="muted">${esc(s.description)}</div></div>`)});
function qrows(list){return list.map(c=>`<tr><td>${esc(c.metric_name)}</td><td>${esc(c.category)}</td>
 <td>${num(c.baseline_value,2)}</td><td>${num(c.previous_value,2)}</td><td>${num(c.raw_value,2)}</td>
 <td class="${c.contribution_points<0?'neg':'pos'}">${sgn(c.contribution_points,2)}</td>
 <td>${esc(c.source)}</td><td>${esc(c.source_date)}</td><td>${esc(c.status)}</td></tr>`).join('')}
function show(i){
  const r=D.latest[i],e=r.explanation,q=e.quality;
  const up=q.filter(c=>c.contribution_points>0).sort((a,b)=>b.contribution_points-a.contribution_points);
  const dn=q.filter(c=>c.contribution_points<0).sort((a,b)=>a.contribution_points-b.contribution_points);
  const flat=q.filter(c=>c.contribution_points===0);
  const qh='<tr><th>Metric</th><th>Categorie</th><th>Baseline</th><th>Vorige</th><th>Nieuw</th><th>Bijdrage (pnt)</th><th>Bron</th><th>Datum</th><th>Status</th></tr>';
  const vrows=e.valuation.map(m=>`<tr><td>${esc(m.metric_name)}</td><td>${esc(m.status)}</td><td>${num(m.value,3)}</td>
   <td>${num(m.reference_value,3)}</td><td>${num(m.score,0)}</td><td>${esc(m.calculation_method)}</td><td>${esc(m.note)}</td></tr>`).join('');
  const hist=(D.history[r.ticker]||[]).map(h=>`<tr><td>${esc(h.score_date)}</td><td>${num(h.quality_score,0)}</td>
   <td>${num(h.valuation_score,0)} ${esc(h.valuation_label||'')}</td><td>${num(h.data_confidence,0)}</td><td>${esc(h.decision_state)}</td><td>${num(h.price,2)}</td></tr>`).join('');
  const det=document.getElementById('detail');det.style.display='block';
  det.innerHTML=`<h2>${esc(r.ticker)} — ${esc(r.decision_state)}</h2>
  <div class="muted">${(r.decision_reasons||[]).map(esc).join(' · ')}${e.limit_flags.length?' · '+e.limit_flags.map(esc).join(' · '):''}</div>
  <h3 style="color:var(--q)">QUALITY — omhoog</h3><div class="wrap"><table>${qh}${qrows(up)||'<tr><td colspan=9 class="muted">geen</td></tr>'}</table></div>
  <h3 style="color:var(--q)">QUALITY — omlaag</h3><div class="wrap"><table>${qh}${qrows(dn)||'<tr><td colspan=9 class="muted">geen</td></tr>'}</table></div>
  <h3 class="muted">QUALITY — onveranderd / ontbrekend</h3><div class="wrap"><table>${qh}${qrows(flat)||'<tr><td colspan=9 class="muted">geen</td></tr>'}</table></div>
  <h3 style="color:var(--v)">VALUATION</h3><div class="wrap"><table><tr><th>Metric</th><th>Status</th><th>Waarde</th><th>Referentie</th><th>Score</th><th>Methode</th><th>Opmerking</th></tr>${vrows}</table></div>
  <div class="cols"><div><h3>DATA CONFIDENCE ${num(r.data_confidence,0)}</h3>
  <div>${Object.entries(e.confidence_components).map(([k,v])=>`${esc(k)}: ${num(v*100,0)}`).join(' · ')}</div>
  <div style="margin-top:6px">${(r.warnings||[]).map(w=>`<span class="warn">${esc(w)}</span>`).join(' ')||'<span class="muted">geen warnings</span>'}</div></div>
  <div><h3>HISTORIE</h3><div class="wrap"><table><tr><th>Datum</th><th>Quality</th><th>Valuation</th><th>Confidence</th><th>Decision</th><th>Price</th></tr>${hist}</table></div></div></div>`;
  det.scrollIntoView({behavior:'smooth'});
}
</script></body></html>"""
