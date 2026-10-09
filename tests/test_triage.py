"""Model reliability (acceptance test 3): bad model output becomes a logged non-action."""
from types import SimpleNamespace

from karyashield.triage import triage_finding
from tests.conftest import make_finding


def client(content=None, exc=None):
    def create(**kw):
        if exc:
            raise exc
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])
    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))


GOOD_JSON = ('{"is_actionable": true, "risk_level": "high", "summary": "' + "s" * 500 +
             '", "why_it_matters": "w", "recommended_fix": "f", "confidence": 7}')


def test_valid_json_parsed_and_bounded():
    r = triage_finding(client(GOOD_JSON), "m", make_finding())
    assert r.ok and len(r.triage.summary) == 240 and r.triage.confidence == 1.0


def test_fenced_json_accepted():
    assert triage_finding(client("```json\n" + GOOD_JSON + "\n```"), "m", make_finding()).ok


def test_timeout_is_non_action():
    r = triage_finding(client(exc=TimeoutError("t")), "m", make_finding())
    assert not r.ok and "TimeoutError" in r.error


def test_refusal_or_garbage_is_non_action():
    for text in [None, "", "I can't help with that", '{"is_actionable": true}']:
        assert not triage_finding(client(text), "m", make_finding()).ok
