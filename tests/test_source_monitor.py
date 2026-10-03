import json

from portfolio_cockpit.monitoring.source_monitor import (
    observe_html_page,
    observe_sec_submissions,
)


def test_html_fingerprint_ignores_script_content():
    a=b"<html><body><h1>Results</h1><script>token='A'</script><a href='/report'>Report</a></body></html>"
    b=b"<html><body><h1>Results</h1><script>token='B'</script><a href='/report'>Report</a></body></html>"
    x=observe_html_page("https://example.com/investors",body=a,headers={})
    y=observe_html_page("https://example.com/investors",body=b,headers={})
    assert x.fingerprint == y.fingerprint


def test_relevant_link_mode_ignores_cosmetic_text_changes():
    a=b"<html><body><div>Updated 3 Oct</div><a href='/results/h1.pdf'>H1</a></body></html>"
    b=b"<html><body><div>Updated 4 Oct - cookie banner changed</div><a href='/results/h1.pdf'>H1</a></body></html>"
    kwargs={"fingerprint_mode":"RELEVANT_LINKS","link_patterns":[r"result",r"\.pdf"]}
    x=observe_html_page("https://example.com/investors",body=a,headers={},**kwargs)
    y=observe_html_page("https://example.com/investors",body=b,headers={},**kwargs)
    assert x.fingerprint == y.fingerprint


def test_relevant_link_mode_detects_new_result_link():
    a=b"<html><body><a href='/results/h1.pdf'>H1</a></body></html>"
    b=b"<html><body><a href='/results/h1.pdf'>H1</a><a href='/results/q3.pdf'>Q3</a></body></html>"
    kwargs={"fingerprint_mode":"RELEVANT_LINKS","link_patterns":[r"result",r"\.pdf"]}
    x=observe_html_page("https://example.com/investors",body=a,headers={},**kwargs)
    y=observe_html_page("https://example.com/investors",body=b,headers={},**kwargs)
    assert x.fingerprint != y.fingerprint


def test_sec_fingerprint_ignores_nonfinancial_forms():
    base={"filings":{"recent":{
        "accessionNumber":["A","B"],"filingDate":["2026-10-01","2026-10-02"],
        "reportDate":["2026-09-30","2026-09-30"],"form":["10-Q","4"],
        "primaryDocument":["q.htm","ownership.htm"],
    }}}
    changed=json.loads(json.dumps(base))
    changed["filings"]["recent"]["accessionNumber"][1]="CHANGED"
    x=observe_sec_submissions(body=json.dumps(base).encode(),headers={})
    y=observe_sec_submissions(body=json.dumps(changed).encode(),headers={})
    assert x.fingerprint == y.fingerprint


def test_sec_fingerprint_changes_for_new_financial_filing():
    a={"filings":{"recent":{
        "accessionNumber":["A"],"filingDate":["2026-10-01"],"reportDate":["2026-09-30"],
        "form":["10-Q"],"primaryDocument":["q.htm"]
    }}}
    b={"filings":{"recent":{
        "accessionNumber":["NEW","A"],"filingDate":["2026-10-03","2026-10-01"],"reportDate":["2026-09-30","2026-09-30"],
        "form":["8-K","10-Q"],"primaryDocument":["8k.htm","q.htm"]
    }}}
    x=observe_sec_submissions(body=json.dumps(a).encode(),headers={})
    y=observe_sec_submissions(body=json.dumps(b).encode(),headers={})
    assert x.fingerprint != y.fingerprint
