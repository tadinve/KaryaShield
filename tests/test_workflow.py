"""Workflow, idempotency and reconciliation (acceptance tests 3, 4, 7, 8, 13, 15)."""
from karyashield import github_adapter as gh
from karyashield.models import TriageResult
from karyashield.workflow import run_once
from tests.conftest import make_cfg, make_deps, make_finding


def test_write_gate_off_means_zero_writes_anywhere(ledger, fake_gh):
    rep = run_once(make_cfg(enable_writes=False), ledger, make_deps(fake_gh, [make_finding()]),
                   dry_run=False, log=lambda *_: None)
    assert fake_gh.created == [] and ledger.b.writes == 0
    assert rep.outcomes[0].action == "would_create"


def test_dry_run_writes_nothing_then_real_run_creates(ledger, fake_gh):
    f = make_finding()
    deps = make_deps(fake_gh, [f])
    run_once(make_cfg(), ledger, deps, dry_run=True, log=lambda *_: None)
    assert ledger.b.writes == 0 and fake_gh.created == []
    rep = run_once(make_cfg(), ledger, deps, dry_run=False, log=lambda *_: None)
    assert rep.issues_created == 1
    assert ledger.get(f.fingerprint)["status"] == "issue_created"


def test_idempotent_second_run(ledger, fake_gh):
    deps = make_deps(fake_gh, [make_finding()])
    r1 = run_once(make_cfg(), ledger, deps, dry_run=False, log=lambda *_: None)
    r2 = run_once(make_cfg(), ledger, deps, dry_run=False, log=lambda *_: None)
    assert (r1.issues_created, r2.issues_created, r2.duplicates_skipped) == (1, 0, 1)
    assert len(fake_gh.created) == 1


def test_crash_after_github_create_reconciles(ledger, fake_gh):
    f = make_finding()
    deps = make_deps(fake_gh, [f])
    ledger.b.fail_on_status = "issue_created"  # GitHub succeeds, ledger update fails
    r1 = run_once(make_cfg(), ledger, deps, dry_run=False, log=lambda *_: None)
    assert len(fake_gh.created) == 1 and r1.fatal
    ledger.b.fail_on_status = None
    r2 = run_once(make_cfg(), ledger, deps, dry_run=False, log=lambda *_: None)
    assert len(fake_gh.created) == 1 and r2.reconciled == 1
    assert ledger.get(f.fingerprint)["github_issue_url"] == fake_gh.created[0][1]


def test_write_uncertain_not_retried_then_reconciled(ledger, fake_gh):
    f = make_finding()
    deps = make_deps(fake_gh, [f])
    fake_gh.create_raises = gh.WriteUncertain("timeout")
    r1 = run_once(make_cfg(), ledger, deps, dry_run=False, log=lambda *_: None)
    assert r1.outcomes[0].action == "write_uncertain"
    fake_gh.create_raises = None
    r2 = run_once(make_cfg(), ledger, deps, dry_run=False, log=lambda *_: None)
    assert r2.outcomes[0].action == "manual_investigation" and fake_gh.created == []
    fake_gh.issues[f.fingerprint] = "https://github.com/x/y/issues/9"  # it actually landed
    r3 = run_once(make_cfg(), ledger, deps, dry_run=False, log=lambda *_: None)
    assert r3.outcomes[0].action == "reconciled" and fake_gh.created == []


def test_existing_marker_on_github_prevents_create_with_empty_ledger(ledger, fake_gh):
    f = make_finding()
    fake_gh.issues[f.fingerprint] = "https://github.com/x/y/issues/1"
    rep = run_once(make_cfg(), ledger, make_deps(fake_gh, [f]), dry_run=False, log=lambda *_: None)
    assert rep.reconciled == 1 and fake_gh.created == []


def test_model_failure_zero_writes(ledger, fake_gh):
    deps = make_deps(fake_gh, [make_finding()], triage=TriageResult(ok=False, error="timeout"))
    rep = run_once(make_cfg(), ledger, deps, dry_run=False, log=lambda *_: None)
    assert fake_gh.created == [] and rep.outcomes[0].action == "triage_error"


def test_github_failure_marks_error_then_retry_allowed(ledger, fake_gh):
    f = make_finding()
    deps = make_deps(fake_gh, [f])
    fake_gh.create_raises = gh.GitHubError("422")
    run_once(make_cfg(), ledger, deps, dry_run=False, log=lambda *_: None)
    assert ledger.get(f.fingerprint)["status"] == "error"
    fake_gh.create_raises = None
    rep = run_once(make_cfg(), ledger, deps, dry_run=False, log=lambda *_: None)
    assert rep.issues_created == 1


def test_per_run_cap(ledger, fake_gh):
    fs = [make_finding(path=f"app/f{i}.py") for i in range(5)]
    rep = run_once(make_cfg(), ledger, make_deps(fake_gh, fs), dry_run=False, log=lambda *_: None)
    assert rep.issues_created == 3


def test_issue_body_has_evidence_and_marker():
    from tests.conftest import GOOD_TRIAGE
    f = make_finding()
    title, body = gh.build_issue(f, GOOD_TRIAGE.triage)
    assert f.rule_id in body and f.path in body and f.commit_sha in body
    assert gh.marker(f.fingerprint) in body and "AI assessment" in body


def test_store_records_run_analytics(ledger, fake_gh):
    rep = run_once(make_cfg(), ledger, make_deps(fake_gh, [make_finding()]), dry_run=False, log=lambda *_: None)
    ledger.record_run(rep.to_json())
    assert ledger.b.runs[0]["issues_created"] == 1 and ledger.b.runs[0]["mode"] == "write"


def test_truncated_code_fence_is_closed_before_marker():
    from tests.conftest import GOOD_TRIAGE
    t = GOOD_TRIAGE.triage.model_copy(update={"recommended_fix": "Do this:\n```python\nsubprocess.run([...]"})
    f = make_finding()
    _, body = gh.build_issue(f, t, "Gemini x on Vertex AI")
    before_marker = body.split(gh.marker(f.fingerprint))[0]
    assert before_marker.count("```") % 2 == 0 and "Gemini x on Vertex AI" in body


def test_verified_patch_opens_draft_pr_after_issue_and_pr_failure_keeps_issue(ledger, fake_gh):
    from karyashield.mender import PatchResult
    f = make_finding()
    deps = make_deps(fake_gh, [f])
    opened = []
    deps.mend = lambda finding, path: PatchResult(status="verified", checks=["ok"], diff="d", fixed="x\n")
    deps.open_pr = lambda finding, patch, issue_url: opened.append(issue_url) or "https://github.com/o/r/pull/7"
    rep = run_once(make_cfg(), ledger, deps, dry_run=False, log=lambda *_: None)
    assert rep.issues_created == 1 and opened == [fake_gh.created[0][1]] and "pull/7" in rep.outcomes[0].detail
    f2 = make_finding(path="app/other.py")
    deps2 = make_deps(fake_gh, [f2])
    deps2.mend = deps.mend
    def boom(*a):
        raise RuntimeError("no permission")
    deps2.open_pr = boom
    rep2 = run_once(make_cfg(), ledger, deps2, dry_run=False, log=lambda *_: None)
    assert rep2.issues_created == 1 and "PR not opened" in rep2.outcomes[0].detail


def test_unverified_patch_never_opens_pr(ledger, fake_gh):
    from karyashield.mender import PatchResult
    deps = make_deps(fake_gh, [make_finding()])
    deps.mend = lambda finding, path: PatchResult(status="rejected", reason="still vulnerable")
    called = []
    deps.open_pr = lambda *a: called.append(1) or "x"
    run_once(make_cfg(), ledger, deps, dry_run=False, log=lambda *_: None)
    assert called == []
