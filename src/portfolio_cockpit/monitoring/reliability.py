from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from urllib.error import HTTPError, URLError


RETRYABLE_HTTP_STATUS = {429, 500, 502, 503, 504}


@dataclass(frozen=True)
class RetryPolicy:
    attempts: int = 3
    base_delay_seconds: float = 1.0
    max_delay_seconds: float = 8.0


def request_with_retry(
    getter: Callable[..., tuple[bytes, dict[str, str]]],
    url: str,
    *,
    user_agent: str,
    timeout: int,
    policy: RetryPolicy,
    sleeper: Callable[[float], None] = time.sleep,
) -> tuple[bytes, dict[str, str]]:
    if policy.attempts < 1:
        raise ValueError("retry attempts must be >= 1")

    last_error: BaseException | None = None
    for attempt in range(1, policy.attempts + 1):
        try:
            return getter(url, user_agent=user_agent, timeout=timeout)
        except HTTPError as exc:
            last_error = exc
            if exc.code not in RETRYABLE_HTTP_STATUS or attempt >= policy.attempts:
                raise
        except (URLError, TimeoutError, OSError) as exc:
            last_error = exc
            if attempt >= policy.attempts:
                raise

        delay = min(
            policy.base_delay_seconds * (2 ** (attempt - 1)),
            policy.max_delay_seconds,
        )
        sleeper(delay)

    assert last_error is not None
    raise last_error


def deterministic_event_id(
    *,
    entity: str,
    source_id: str,
    old_fingerprint: str | None,
    new_fingerprint: str,
) -> str:
    payload = "|".join(
        [entity, source_id, old_fingerprint or "FIRST", new_fingerprint]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:20]


def deterministic_event_path(
    root: Path,
    *,
    entity: str,
    source_id: str,
    old_fingerprint: str | None,
    new_fingerprint: str,
) -> tuple[str, Path]:
    event_id = deterministic_event_id(
        entity=entity,
        source_id=source_id,
        old_fingerprint=old_fingerprint,
        new_fingerprint=new_fingerprint,
    )
    return event_id, root / entity / source_id / f"{event_id}.json"


def write_event_once(path: Path, payload: dict) -> bool:
    """Write an immutable event once.

    A rerun that observes the same fingerprint transition resolves to the same
    path and leaves the original detection timestamp untouched.
    """
    if path.exists():
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return True


def source_health_success(previous: dict | None, observed_at: str) -> dict:
    return {
        "consecutive_failures": 0,
        "circuit_state": "CLOSED",
        "last_success_at": observed_at,
        "last_error_at": (previous or {}).get("last_error_at"),
        "last_error": None,
    }


def source_health_failure(
    previous: dict | None,
    *,
    observed_at: str,
    error: str,
    failure_threshold: int,
) -> dict:
    failures = int((previous or {}).get("consecutive_failures", 0)) + 1
    return {
        "consecutive_failures": failures,
        "circuit_state": "OPEN" if failures >= failure_threshold else "CLOSED",
        "last_success_at": (previous or {}).get("last_success_at"),
        "last_error_at": observed_at,
        "last_error": error,
    }
