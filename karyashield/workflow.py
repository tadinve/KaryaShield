"""Explicit synchronous workflow:
FETCH -> SCAN -> NORMALIZE -> TRIAGE -> POLICY -> RESERVE/RECONCILE -> CREATE_ISSUE -> RECORD -> REPORT
"""
from __future__ import annotations

import dataclasses
import time
import uuid
from dataclasses import dataclass, field
from typing import Callable

from . import github_adapter as gh
from .config import MAX_ISSUES_PER_RUN, Config
from .models import Finding, FindingOutcome, TriageResult
from .policy import evaluate
from .store import Ledger

WRITE_GATE_REASON_PREFIX = "write gate disabled"


@dataclass
class Deps:
    """Injected integrations (real by default, mocked in tests)."""
    fetch: Callable = gh.fetch_checkout
    scan: Callable = None  # (checkout_path, repo, sha) -> (findings, warnings)
    triage: Callable = None  # (finding) -> TriageResult
    find_issue: Callable = gh.find_issue_by_marker
    create_issue: Callable = gh.create_issue
    build_issue: Callable = gh.build_issue
    llm_label: str = "LLM"
    mend: Callable | None = None  # (finding, checkout_path) -> PatchResult; None = disabled


@dataclass
class RunReport:
    run_id: str
    repo: str
    mode: str
    sha: str = ""
    findings: int = 0
    actionable: int = 0
    issues_created: int = 0
    duplicates_skipped: int = 0
    reconciled: int = 0
    errors: int = 0
    scan_warnings: int = 0
    elapsed_seconds: float = 0.0
    outcomes: list[FindingOutcome] = field(default_factory=list)
    fatal: str | None = None

    def to_json(self) -> dict:
        d = dataclasses.asdict(self)
        d["outcomes"] = [o.model_dump() for o in self.outcomes]
        return d


def process_finding(cfg: Config, f: Finding, ledger: Ledger, deps: Deps, run_id: str,
                    checkout_sha: str, created_so_far: int, writes: bool, checkout_path=None) -> FindingOutcome:
    base = dict(fingerprint=f.fingerprint, rule_id=f.rule_id, path=f.path, start_line=f.start_line)
    doc = ledger.get(f.fingerprint)

    if doc and doc.get("status") == "issue_created":
        if writes:
            ledger.touch_seen(f.fingerprint, f.commit_sha, run_id)
        return FindingOutcome(**base, action="duplicate", issue_url=doc.get("github_issue_url"),
                              detail="already filed (ledger)")

    tr: TriageResult = deps.triage(f)
    decision = evaluate(cfg, f, tr, checkout_sha=checkout_sha,
                        issues_created_this_run=created_so_far, max_issues=MAX_ISSUES_PER_RUN)
    triage_obj = tr.triage if tr.ok else None

    if not writes:
        # Dry run / write gate off: read-only everywhere. No ledger writes, no GitHub writes.
        other = [r for r in decision.reasons if not r.startswith(WRITE_GATE_REASON_PREFIX)]
        if not tr.ok:
            return FindingOutcome(**base, action="triage_error", detail=tr.error or "")
        if other:
            return FindingOutcome(**base, action="blocked", detail="; ".join(other))
        status = f" (ledger status: {doc['status']})" if doc else ""
        patch_note = ""
        if deps.mend:
            p = deps.mend(f, checkout_path)
            patch_note = f"; patch {p.status}" + (f" ({p.reason})" if p.reason else "")
        return FindingOutcome(**base, action="would_create", detail=f"all gates pass except write gate{status}{patch_note}")

    if not tr.ok:
        return FindingOutcome(**base, action="triage_error", detail=tr.error or "")
    if not decision.allowed:
        if decision.reasons == ["model veto: is_actionable=false"]:
            ledger.record_skip(f, triage_obj, run_id, "model veto: is_actionable=false")
            return FindingOutcome(**base, action="vetoed", detail="model judged not actionable")
        return FindingOutcome(**base, action="blocked", detail="; ".join(decision.reasons))

    # --- RESERVE / RECONCILE ---
    owned = False
    if doc is None:
        owned = ledger.try_reserve(f, triage_obj, run_id)
        if not owned:
            doc = ledger.get(f.fingerprint)  # lost a race
            if doc and doc.get("status") == "issue_created":
                return FindingOutcome(**base, action="duplicate", issue_url=doc.get("github_issue_url"))

    try:
        existing = deps.find_issue(f.repo, f.fingerprint)
    except gh.GitHubError as e:
        if owned:
            ledger.set_status(f.fingerprint, "error", "reconcile_failed", str(e), expect_run=run_id)
        return FindingOutcome(**base, action="error", detail=f"marker check failed, no write: {e}")
    if existing:
        ledger.set_status(f.fingerprint, "issue_created", "reconciled", f"found existing issue {existing}", url=existing)
        return FindingOutcome(**base, action="reconciled", issue_url=existing, detail="existing GitHub issue found by marker")

    if not owned:
        status = (doc or {}).get("status")
        if status == "write_uncertain":
            return FindingOutcome(**base, action="manual_investigation",
                                  detail="previous write uncertain and no marker found; not retrying automatically")
        if status == "reserved":
            if not ledger.claim(f.fingerprint, "reserved", run_id, stale_only=True):
                return FindingOutcome(**base, action="blocked", detail="reserved by another active run")
        elif status in ("error", "skipped"):
            if not ledger.claim(f.fingerprint, status, run_id):
                return FindingOutcome(**base, action="blocked", detail="lost claim race")
        else:
            return FindingOutcome(**base, action="blocked", detail=f"unexpected ledger status {status!r}")

    # --- CREATE_ISSUE -> RECORD ---
    patch = deps.mend(f, checkout_path) if deps.mend else None
    if patch is not None:
        ledger.event(f.fingerprint, f"patch_{patch.status}", patch.reason or "; ".join(patch.checks), run_id)
    title, body = deps.build_issue(f, tr.triage, deps.llm_label, patch)
    try:
        url = deps.create_issue(f.repo, title, body)
    except gh.WriteUncertain as e:
        ledger.set_status(f.fingerprint, "write_uncertain", "write_uncertain", str(e), expect_run=run_id)
        return FindingOutcome(**base, action="write_uncertain", detail=str(e))
    except gh.GitHubError as e:
        ledger.set_status(f.fingerprint, "error", "create_failed", str(e), expect_run=run_id)
        return FindingOutcome(**base, action="error", detail=str(e))
    ledger.set_status(f.fingerprint, "issue_created", "issue_created", url, url=url, expect_run=run_id)
    return FindingOutcome(**base, action="issue_created", issue_url=url)


def run_once(cfg: Config, ledger: Ledger, deps: Deps, *, dry_run: bool, log=print) -> RunReport:
    t0 = time.monotonic()
    writes = cfg.enable_writes and not dry_run
    if not writes:
        cfg = dataclasses.replace(cfg, enable_writes=False)
    rep = RunReport(run_id=uuid.uuid4().hex[:12], repo=cfg.github_repo, mode="write" if writes else "dry-run")
    try:
        log(f"[FETCH] {cfg.github_repo}@{cfg.github_branch}")
        co = deps.fetch(cfg.github_repo, cfg.github_branch, cfg.workspace_dir)
        rep.sha = co.sha
        log(f"[FETCH] live commit {co.sha}")
        log("[SCAN] semgrep (pinned rules/karyashield.yml)")
        findings, warnings = deps.scan(co.path, cfg.github_repo, co.sha)
        rep.findings, rep.scan_warnings = len(findings), len(warnings)
        for w in warnings[:5]:
            log(f"[SCAN] warning: {w}")
        log(f"[SCAN] {len(findings)} finding(s)")
        for f in findings:
            log(f"[TRIAGE/POLICY] {f.rule_id} {f.path}:{f.start_line} fp={f.fingerprint[:12]}")
            try:
                o = process_finding(cfg, f, ledger, deps, rep.run_id, co.sha, rep.issues_created, writes, co.path)
            except gh.GitHubError as e:
                o = FindingOutcome(fingerprint=f.fingerprint, rule_id=f.rule_id, path=f.path,
                                   start_line=f.start_line, action="error", detail=str(e))
            rep.outcomes.append(o)
            log(f"    -> {o.action.upper()} {o.issue_url or ''} {o.detail}".rstrip())
            if o.action == "issue_created":
                rep.issues_created += 1
            elif o.action == "duplicate":
                rep.duplicates_skipped += 1
            elif o.action == "reconciled":
                rep.reconciled += 1
            elif o.action in ("error", "triage_error", "write_uncertain", "manual_investigation"):
                rep.errors += 1
            if o.action in ("issue_created", "would_create", "reconciled", "write_uncertain"):
                rep.actionable += 1
    except Exception as e:  # ClickHouse outage, fetch/scan failure: fail the run closed
        rep.fatal = f"{type(e).__name__}: {str(e)[:300]}"
        log(f"[FATAL] {rep.fatal}")
    rep.elapsed_seconds = round(time.monotonic() - t0, 2)
    return rep
