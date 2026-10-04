"""VALUATION-module — volledig onafhankelijk van QUALITY.

valuation_score 0-100: 50 ≈ fair t.o.v. referentie (eigen historie + sectorgenoten),
hoger = aantrekkelijker, lager = duurder.

Regels:
* Alleen economisch betekenisvolle multiples per company_type (config).
* Niet bruikbaar => value=None, status=NOT_APPLICABLE.
* Een negatieve P/E of EV/EBITDA wordt NOOIT als goedkoop geïnterpreteerd:
  negatieve of nul-noemer => NOT_APPLICABLE.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict, field
from typing import Any, Callable, Optional

from .quality import clamp

NOT_APPLICABLE = "NOT_APPLICABLE"
MISSING_INPUT = "MISSING_INPUT"
NO_REFERENCE = "NO_REFERENCE"
OK = "OK"


def _mcap(i):  # marktkapitalisatie
    return i["price"] * i["shares_outstanding"]


def _ev(i):
    return _mcap(i) + i["net_debt"] + i.get("minorities", 0.0)


# formula -> (benodigde inputs, functie die (teller, noemer) teruggeeft, methode-omschrijving)
FORMULAS: dict[str, tuple[tuple[str, ...], Callable[[dict], tuple[float, float]], str]] = {
    "price_over_forward_eps": (("price", "forward_eps"), lambda i: (i["price"], i["forward_eps"]),
                               "price / forward EPS (konsensus, 12m)"),
    "price_over_eps": (("price", "eps_ttm"), lambda i: (i["price"], i["eps_ttm"]),
                       "price / EPS ttm"),
    "ev_over_ebit": (("price", "shares_outstanding", "net_debt", "ebit"),
                     lambda i: (_ev(i), i["ebit"]), "(price*shares + net debt + minorities) / EBIT"),
    "ev_over_ebitda": (("price", "shares_outstanding", "net_debt", "ebitda"),
                       lambda i: (_ev(i), i["ebitda"]), "EV / EBITDA"),
    "ev_over_normalized_ebitda": (("price", "shares_outstanding", "net_debt", "normalized_ebitda"),
                                  lambda i: (_ev(i), i["normalized_ebitda"]),
                                  "EV / mid-cycle (genormaliseerde) EBITDA"),
    "fcf_over_market_cap": (("price", "shares_outstanding", "fcf"),
                            lambda i: (i["fcf"], _mcap(i)), "FCF / market cap"),
    "price_over_bvps": (("price", "bvps"), lambda i: (i["price"], i["bvps"]),
                        "price / book value per share"),
    "distributions_over_market_cap": (("price", "shares_outstanding", "distributions"),
                                      lambda i: (i["distributions"], _mcap(i)),
                                      "(dividends + buybacks, 12m) / market cap"),
    "price_over_navps": (("price", "navps"), lambda i: (i["price"], i["navps"]),
                         "price / NAV per share"),
    "market_cap_over_risked_npv": (("price", "shares_outstanding", "risked_npv"),
                                   lambda i: (_mcap(i), i["risked_npv"]),
                                   "market cap / risk-adjusted project NPV"),
}


@dataclass
class ValuationMetric:
    metric_name: str
    value: Optional[float]
    status: str
    score: Optional[float]
    weight: float
    reference_value: Optional[float]
    source: Optional[str]
    as_of_date: Optional[str]
    calculation_method: str
    raw_inputs: dict[str, Any] = field(default_factory=dict)
    note: str = ""

    def to_dict(self):
        return asdict(self)


@dataclass
class ValuationResult:
    valuation_score: Optional[float]
    label: Optional[str]
    metrics: list[ValuationMetric]
    warnings: list[str]
    applicable_weight: float


def label_for(score: Optional[float], cfg: dict) -> Optional[str]:
    if score is None:
        return None
    for band in cfg["labels"]:
        if score >= band["min"]:
            return band["label"]
    return cfg["labels"][-1]["label"]


def _reference(refs: dict[str, float] | None, cfg: dict) -> Optional[float]:
    if not refs:
        return None
    weights = cfg["reference_weights"]
    num = den = 0.0
    for k, w in weights.items():
        v = refs.get(k)
        if v is not None and v > 0:
            num += w * v
            den += w
    return num / den if den else None


def compute_metric(name: str, company_type: str, inputs: dict, refs: dict | None,
                   cfg: dict, source: str | None, as_of: str | None) -> ValuationMetric:
    mcfg = cfg["metrics"][name]
    prof = cfg["profiles"][company_type]
    weight = prof["weights"].get(name, 0.0)
    needed, fn, method = FORMULAS[mcfg["formula"]]
    used = {k: inputs.get(k) for k in needed}
    if name in prof.get("not_applicable", []) or weight == 0.0:
        return ValuationMetric(name, None, NOT_APPLICABLE, None, 0.0, None, source, as_of, method, used,
                               f"niet economisch betekenisvol voor {company_type}")
    if any(v is None for v in used.values()) or ("net_debt" in needed and inputs.get("net_debt") is None):
        return ValuationMetric(name, None, MISSING_INPUT, None, weight, None, source, as_of, method, used,
                               "ontbrekende input")
    num, den = fn(inputs)
    if den == 0 or (mcfg["requires_positive_denominator"] and den < 0):
        return ValuationMetric(name, None, NOT_APPLICABLE, None, weight, None, source, as_of, method, used,
                               "negatieve/nul noemer — niet als goedkoop interpreteren")
    if mcfg["requires_positive_denominator"] and num <= 0:
        return ValuationMetric(name, None, NOT_APPLICABLE, None, weight, None, source, as_of, method, used,
                               "negatieve teller (bv. negatieve EV) — niet interpreteerbaar")
    value = num / den
    ref = _reference(refs, cfg)
    if ref is None:
        return ValuationMetric(name, round(value, 4), NO_REFERENCE, None, weight, None, source, as_of,
                               method, used, "geen eigen-historie/peer-referentie")
    rel = value / ref - 1.0
    signal = clamp(rel / mcfg["full_scale"], -1.0, 1.0)
    score = 50 - 50 * signal if mcfg["cheaper_when"] == "lower" else 50 + 50 * signal
    return ValuationMetric(name, round(value, 4), OK, round(score, 2), weight, round(ref, 4),
                           source, as_of, method, used)


def compute_valuation(company_type: str, inputs: dict, references: dict[str, dict],
                      cfg: dict, source: str | None = None, as_of: str | None = None) -> ValuationResult:
    prof = cfg["profiles"][company_type]
    names = list(prof["weights"]) + [m for m in prof.get("not_applicable", []) if m in cfg["metrics"]]
    metrics = [compute_metric(n, company_type, inputs, references.get(n), cfg, source, as_of)
               for n in names]
    warnings = []
    num = den = 0.0
    for m in metrics:
        if m.status == OK:
            num += m.weight * m.score
            den += m.weight
        elif m.status == NOT_APPLICABLE and m.weight > 0:
            warnings.append(f"UNSUITABLE_METRIC:{m.metric_name}")
        elif m.status == MISSING_INPUT:
            warnings.append(f"MISSING_DATA:valuation:{m.metric_name}")
    score = round(num / den, 2) if den else None
    return ValuationResult(score, label_for(score, cfg), metrics, warnings, round(den, 4))
