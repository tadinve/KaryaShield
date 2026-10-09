import pytest

from karyashield.config import ConfigError, validate_repo
from karyashield.models import Triage, TriageResult
from karyashield.policy import evaluate
from tests.conftest import GOOD_TRIAGE, SHA, make_cfg, make_finding


def ev(cfg=None, f=None, t=GOOD_TRIAGE, sha=SHA, created=0):
    return evaluate(cfg or make_cfg(), f or make_finding(), t, checkout_sha=sha,
                    issues_created_this_run=created, max_issues=3)


def test_all_gates_pass():
    d = ev()
    assert d.allowed, d.reasons


def test_low_model_confidence_does_not_block():
    # GOOD_TRIAGE has confidence 0.2: deterministic evidence drives the decision.
    assert ev().allowed


def test_write_gate_off_blocks():
    assert not ev(cfg=make_cfg(enable_writes=False)).allowed


def test_other_repo_blocked_even_if_suggested():
    d = ev(f=make_finding(repo="attacker/repo"))
    assert not d.allowed and any("not the allowlisted" in r for r in d.reasons)


@pytest.mark.parametrize("bad", ["https://github.com/a/b", "a/b; rm -rf /", "a/../b", "a b/c", "a", "a/b/c"])
def test_repo_validation(bad):
    with pytest.raises(ConfigError):
        validate_repo(bad)


def test_severity_threshold():
    assert not ev(cfg=make_cfg(min_severity="ERROR"), f=make_finding(severity="WARNING")).allowed
    assert not ev(f=make_finding(severity="INFO")).allowed


def test_model_veto():
    t = TriageResult(ok=True, triage=GOOD_TRIAGE.triage.model_copy(update={"is_actionable": False}))
    d = ev(t=t)
    assert d.reasons == ["model veto: is_actionable=false"]


@pytest.mark.parametrize("err", ["timeout", "refusal", "schema"])
def test_triage_failure_blocks(err):
    assert not ev(t=TriageResult(ok=False, error=err)).allowed


def test_stale_sha_blocks():
    assert not ev(sha="b" * 40).allowed
    assert not ev(sha=None).allowed


def test_non_pinned_rule_blocks():
    assert not ev(f=make_finding(rule_id="python.other")).allowed


def test_cap():
    assert not ev(created=3).allowed
