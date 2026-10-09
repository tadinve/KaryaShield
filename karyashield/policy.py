"""Deterministic write gate. The LLM cannot override any gate."""
from __future__ import annotations

import re

from .config import PINNED_RULE_IDS, Config
from .models import SEVERITY_RANK, Decision, Finding, TriageResult

_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


def evaluate(
    cfg: Config,
    finding: Finding,
    triage: TriageResult,
    *,
    checkout_sha: str | None,
    issues_created_this_run: int,
    max_issues: int,
) -> Decision:
    """Gates 1-6 and 8 from SPEC 6.4. Gate 7 (not already filed) is enforced by the
    ledger reservation + GitHub marker reconciliation in workflow.py."""
    reasons: list[str] = []
    if not cfg.enable_writes:
        reasons.append("write gate disabled (KARYASHIELD_ENABLE_WRITES!=true)")
    if finding.repo != cfg.github_repo or finding.repo not in cfg.allowlist:
        reasons.append(f"repo {finding.repo!r} not the allowlisted target")
    if not checkout_sha or not _SHA_RE.match(checkout_sha) or finding.commit_sha != checkout_sha:
        reasons.append("finding not tied to verified live checkout SHA")
    if finding.rule_id not in PINNED_RULE_IDS:
        reasons.append(f"rule {finding.rule_id!r} not in pinned ruleset")
    if finding.path.startswith("/") or ".." in finding.path.split("/"):
        reasons.append("unsafe path")
    if SEVERITY_RANK.get(finding.severity, -1) < SEVERITY_RANK[cfg.min_severity]:
        reasons.append(f"severity {finding.severity} below minimum {cfg.min_severity}")
    if not triage.ok or triage.triage is None:
        reasons.append(f"no valid triage ({triage.error})")
    elif not triage.triage.is_actionable:
        reasons.append("model veto: is_actionable=false")
    if issues_created_this_run >= max_issues:
        reasons.append(f"per-run cap reached ({max_issues})")
    return Decision(allowed=not reasons, reasons=reasons)
