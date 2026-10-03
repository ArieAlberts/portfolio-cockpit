from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
from urllib.request import Request, urlopen

from .reliability import RetryPolicy, request_with_retry
from .source_monitor import SourceObservation, observe_source


SEC_CIK_RE = re.compile(r"/Archives/edgar/data/(\d+)/", re.IGNORECASE)
SUFFIX_RE = re.compile(r"\.(L|TO|SW|HE|BR|PA|DE)$", re.IGNORECASE)


@dataclass(frozen=True)
class PeerSourceSpec:
    peer_ticker: str
    mode: str
    url: str
    source_quality: str
    dependent_targets: tuple[str, ...]


def normalize_sec_lookup_ticker(ticker: str) -> str:
    return SUFFIX_RE.sub("", ticker).upper()


def cik_from_sec_archive_url(url: str) -> str | None:
    match = SEC_CIK_RE.search(url)
    if not match:
        return None
    return str(int(match.group(1))).zfill(10)


def _sec_ticker_get(url: str, *, user_agent: str, timeout: int):
    request = Request(
        url,
        headers={
            "User-Agent": user_agent,
            "Accept": "application/json",
            "Accept-Encoding": "identity",
        },
    )
    with urlopen(request, timeout=timeout) as response:
        return response.read(5_000_000), {k.lower(): v for k, v in response.headers.items()}


def fetch_sec_ticker_map(
    *,
    user_agent: str,
    timeout: int = 20,
    retry_attempts: int = 3,
    retry_base_seconds: float = 1.0,
    getter: Callable[..., tuple[bytes, dict[str, str]]] = _sec_ticker_get,
) -> dict[str, str]:
    body, _ = request_with_retry(
        getter,
        "https://www.sec.gov/files/company_tickers.json",
        user_agent=user_agent,
        timeout=timeout,
        policy=RetryPolicy(
            attempts=retry_attempts,
            base_delay_seconds=retry_base_seconds,
        ),
    )
    data = json.loads(body.decode("utf-8"))
    result: dict[str, str] = {}
    for row in data.values():
        ticker = str(row.get("ticker", "")).upper()
        cik = row.get("cik_str")
        if ticker and cik is not None:
            result[ticker] = str(int(cik)).zfill(10)
    return result


def _fallback_source(company: dict[str, Any]) -> tuple[str, str, str] | None:
    source = company.get("source") or {}
    url = source.get("url")
    if not url:
        return None

    cik = cik_from_sec_archive_url(url)
    if cik:
        return (
            "SEC_SUBMISSIONS_JSON",
            f"https://data.sec.gov/submissions/CIK{cik}.json",
            "HIGH",
        )

    return ("HTML_PAGE", str(url), "FALLBACK_STATIC_OR_IR_PAGE")


def build_peer_source_specs(
    *,
    root: Path,
    peer_index: dict[str, Any],
    sec_ticker_map: dict[str, str] | None = None,
    discovery_overrides: dict[str, dict[str, str]] | None = None,
) -> list[PeerSourceSpec]:
    sec_ticker_map = sec_ticker_map or {}
    overrides = discovery_overrides or {}

    peer_sources: dict[str, dict[str, Any]] = {}
    dependencies: dict[str, set[str]] = {}

    for target, relative_path in peer_index["datasets"].items():
        dataset = json.loads((root / relative_path).read_text(encoding="utf-8"))
        for peer, company in dataset.get("companies", {}).items():
            if peer == dataset.get("target_ticker"):
                continue
            if company.get("role") in {"GATE", "CONTEXT_ONLY"}:
                continue
            if not company.get("source"):
                continue
            dependencies.setdefault(peer, set()).add(target)
            peer_sources.setdefault(peer, company)

    specs: list[PeerSourceSpec] = []
    for peer in sorted(peer_sources):
        company = peer_sources[peer]

        if peer in overrides:
            override = overrides[peer]
            specs.append(
                PeerSourceSpec(
                    peer_ticker=peer,
                    mode=override["mode"],
                    url=override["url"],
                    source_quality=override.get("source_quality", "HIGH"),
                    dependent_targets=tuple(sorted(dependencies[peer])),
                )
            )
            continue

        lookup = normalize_sec_lookup_ticker(peer)
        cik = sec_ticker_map.get(lookup)
        if cik:
            specs.append(
                PeerSourceSpec(
                    peer_ticker=peer,
                    mode="SEC_SUBMISSIONS_JSON",
                    url=f"https://data.sec.gov/submissions/CIK{cik}.json",
                    source_quality="HIGH",
                    dependent_targets=tuple(sorted(dependencies[peer])),
                )
            )
            continue

        fallback = _fallback_source(company)
        if fallback is None:
            continue
        mode, url, quality = fallback
        specs.append(
            PeerSourceSpec(
                peer_ticker=peer,
                mode=mode,
                url=url,
                source_quality=quality,
                dependent_targets=tuple(sorted(dependencies[peer])),
            )
        )

    return specs


def observe_peer_source(
    spec: PeerSourceSpec,
    *,
    user_agent: str,
    timeout: int,
    retry_attempts: int,
    retry_base_seconds: float,
    html_fingerprint_mode: str = "RELEVANT_LINKS",
    html_link_patterns: list[str] | None = None,
) -> SourceObservation:
    entry = {"mode": spec.mode, "url": spec.url}
    if spec.mode == "HTML_PAGE":
        entry["fingerprint_mode"] = html_fingerprint_mode
        entry["link_patterns"] = html_link_patterns
    return observe_source(
        entry,
        user_agent=user_agent,
        timeout=timeout,
        retry_attempts=retry_attempts,
        retry_base_seconds=retry_base_seconds,
    )
