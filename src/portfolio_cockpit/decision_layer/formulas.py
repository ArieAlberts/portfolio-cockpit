"""Whitelisted valuation formula registry. No eval: name -> function.

Each entry: (required inputs, fn(inputs) -> (numerator, denominator), method).
"""
from __future__ import annotations

from typing import Any, Callable


def _market_cap(i: dict[str, float]) -> float:
    return i["price"] * i["shares_outstanding"]


def _enterprise_value(i: dict[str, float]) -> float:
    return _market_cap(i) + i["net_debt"] + (i.get("minorities") or 0.0)


Formula = tuple[tuple[str, ...], Callable[[dict[str, Any]], tuple[float, float]], str]

FORMULAS: dict[str, Formula] = {
    "price_over_forward_eps": (
        ("price", "forward_eps"),
        lambda i: (i["price"], i["forward_eps"]),
        "price / forward EPS (consensus, next 12 months)",
    ),
    "price_over_eps": (
        ("price", "eps_ttm"),
        lambda i: (i["price"], i["eps_ttm"]),
        "price / EPS (trailing 12 months)",
    ),
    "ev_over_ebit": (
        ("price", "shares_outstanding", "net_debt", "ebit"),
        lambda i: (_enterprise_value(i), i["ebit"]),
        "(price * shares + net debt + minorities) / EBIT",
    ),
    "ev_over_ebitda": (
        ("price", "shares_outstanding", "net_debt", "ebitda"),
        lambda i: (_enterprise_value(i), i["ebitda"]),
        "(price * shares + net debt + minorities) / EBITDA",
    ),
    "ev_over_normalized_ebitda": (
        ("price", "shares_outstanding", "net_debt", "normalized_ebitda"),
        lambda i: (_enterprise_value(i), i["normalized_ebitda"]),
        "EV / mid-cycle (normalized) EBITDA",
    ),
    "fcf_over_market_cap": (
        ("price", "shares_outstanding", "fcf"),
        lambda i: (i["fcf"], _market_cap(i)),
        "free cash flow (ttm) / market cap",
    ),
    "price_over_bvps": (
        ("price", "bvps"),
        lambda i: (i["price"], i["bvps"]),
        "price / book value per share",
    ),
    "distributions_over_market_cap": (
        ("price", "shares_outstanding", "distributions_ttm"),
        lambda i: (i["distributions_ttm"], _market_cap(i)),
        "(dividends + buybacks, ttm) / market cap",
    ),
    "price_over_navps": (
        ("price", "navps"),
        lambda i: (i["price"], i["navps"]),
        "price / NAV per share",
    ),
    "market_cap_over_risked_npv": (
        ("price", "shares_outstanding", "risked_npv"),
        lambda i: (_market_cap(i), i["risked_npv"]),
        "market cap / risk-adjusted project NPV",
    ),
}

MARKET_FIELDS = (
    "price",
    "shares_outstanding",
    "net_debt",
    "minorities",
    "forward_eps",
    "eps_ttm",
    "ebit",
    "ebitda",
    "normalized_ebitda",
    "fcf",
    "bvps",
    "distributions_ttm",
    "navps",
    "risked_npv",
)
