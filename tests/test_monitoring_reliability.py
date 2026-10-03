from pathlib import Path
from urllib.error import URLError

from portfolio_cockpit.monitoring.reliability import (
    RetryPolicy,
    deterministic_event_path,
    request_with_retry,
    source_health_failure,
    source_health_success,
    write_event_once,
)


def test_retry_uses_exponential_backoff_then_succeeds():
    calls=[]
    sleeps=[]

    def getter(url, *, user_agent, timeout):
        calls.append(url)
        if len(calls) < 3:
            raise URLError("temporary")
        return b"ok", {}

    body,_=request_with_retry(
        getter,
        "https://example.com",
        user_agent="test",
        timeout=1,
        policy=RetryPolicy(attempts=3,base_delay_seconds=0.25,max_delay_seconds=1),
        sleeper=sleeps.append,
    )
    assert body==b"ok"
    assert len(calls)==3
    assert sleeps==[0.25,0.5]


def test_event_path_is_deterministic_and_write_is_idempotent(tmp_path: Path):
    event_id,a=deterministic_event_path(
        tmp_path,entity="WKL",source_id="official",old_fingerprint="old",new_fingerprint="new"
    )
    event_id2,b=deterministic_event_path(
        tmp_path,entity="WKL",source_id="official",old_fingerprint="old",new_fingerprint="new"
    )
    assert event_id==event_id2
    assert a==b
    assert write_event_once(a,{"event_id":event_id,"detected_at":"first"}) is True
    assert write_event_once(b,{"event_id":event_id2,"detected_at":"second"}) is False
    assert "first" in a.read_text()
    assert "second" not in a.read_text()


def test_soft_circuit_opens_after_threshold_and_resets_on_success():
    health=None
    for i in range(3):
        health=source_health_failure(
            health,observed_at=f"t{i}",error="503",failure_threshold=3
        )
    assert health["circuit_state"]=="OPEN"
    assert health["consecutive_failures"]==3

    recovered=source_health_success(health,"t4")
    assert recovered["circuit_state"]=="CLOSED"
    assert recovered["consecutive_failures"]==0
