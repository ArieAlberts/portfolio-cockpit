from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
from typing import Any, Callable
from urllib.parse import urljoin, urlsplit, urlunsplit
from urllib.request import Request, urlopen


FINANCIAL_FORMS = {"10-K", "10-Q", "8-K", "10-K/A", "10-Q/A", "20-F", "6-K", "40-F"}


@dataclass(frozen=True)
class SourceObservation:
    fingerprint: str
    etag: str | None
    last_modified: str | None
    summary: dict[str, Any]


class _VisiblePageParser(HTMLParser):
    def __init__(self, base_url: str) -> None:
        super().__init__()
        self.base_url = base_url
        self.skip_depth = 0
        self.text: list[str] = []
        self.links: set[str] = set()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript", "svg"}:
            self.skip_depth += 1
            return
        if tag == "a":
            href = dict(attrs).get("href")
            if href:
                self.links.add(_normalize_url(urljoin(self.base_url, href)))

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript", "svg"} and self.skip_depth:
            self.skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self.skip_depth:
            cleaned = " ".join(data.split())
            if cleaned:
                self.text.append(cleaned)


def _normalize_url(url: str) -> str:
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path.rstrip("/"), parts.query, ""))


def _hash_payload(payload: str) -> str:
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _http_get(url: str, *, user_agent: str, timeout: int) -> tuple[bytes, dict[str, str]]:
    request = Request(
        url,
        headers={
            "User-Agent": user_agent,
            "Accept": "application/json,text/html,application/xhtml+xml,*/*;q=0.8",
            "Accept-Encoding": "identity",
        },
    )
    with urlopen(request, timeout=timeout) as response:
        body = response.read(3_000_000)
        headers = {k.lower(): v for k, v in response.headers.items()}
    return body, headers


def observe_html_page(url: str, *, body: bytes, headers: dict[str, str]) -> SourceObservation:
    text = body.decode("utf-8", errors="replace")
    parser = _VisiblePageParser(url)
    parser.feed(text)
    visible = re.sub(r"\s+", " ", " ".join(parser.text)).strip()
    links = sorted(link for link in parser.links if link.startswith(("http://", "https://")))
    canonical = json.dumps({"text": visible, "links": links}, ensure_ascii=False, separators=(",", ":"))
    return SourceObservation(
        fingerprint=_hash_payload(canonical),
        etag=headers.get("etag"),
        last_modified=headers.get("last-modified"),
        summary={"visible_text_chars": len(visible), "link_count": len(links)},
    )


def observe_sec_submissions(
    *,
    body: bytes,
    headers: dict[str, str],
    financial_forms: set[str] | None = None,
) -> SourceObservation:
    data = json.loads(body.decode("utf-8"))
    forms = financial_forms or FINANCIAL_FORMS
    recent = data.get("filings", {}).get("recent", {})
    keys = ["accessionNumber", "filingDate", "reportDate", "form", "primaryDocument"]
    columns = {key: recent.get(key, []) for key in keys}
    count = max((len(values) for values in columns.values()), default=0)
    selected: list[dict[str, str | None]] = []

    for i in range(count):
        form = columns["form"][i] if i < len(columns["form"]) else None
        if form not in forms:
            continue
        row = {
            key: columns[key][i] if i < len(columns[key]) else None
            for key in keys
        }
        selected.append(row)
        if len(selected) >= 25:
            break

    canonical = json.dumps(selected, sort_keys=True, separators=(",", ":"))
    return SourceObservation(
        fingerprint=_hash_payload(canonical),
        etag=headers.get("etag"),
        last_modified=headers.get("last-modified"),
        summary={
            "financial_filing_count_fingerprinted": len(selected),
            "latest_financial_filing": selected[0] if selected else None,
        },
    )


def observe_source(
    entry: dict[str, Any],
    *,
    user_agent: str,
    timeout: int = 20,
    getter: Callable[..., tuple[bytes, dict[str, str]]] = _http_get,
) -> SourceObservation:
    body, headers = getter(entry["url"], user_agent=user_agent, timeout=timeout)
    mode = entry["mode"]
    if mode == "HTML_PAGE":
        return observe_html_page(entry["url"], body=body, headers=headers)
    if mode == "SEC_SUBMISSIONS_JSON":
        return observe_sec_submissions(body=body, headers=headers)
    raise ValueError(f"Unsupported monitor mode: {mode}")


def utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def iso_z(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
