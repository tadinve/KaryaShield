"""Open a DRAFT pull request with a sandbox-verified patch, for human review.

Guarantees:
- Never touches the default branch: the fix goes to a new branch `karyashield/fix-<fp12>` created from
  the exact scanned commit, via the GitHub API (no local git push).
- Always a DRAFT PR, labeled, with a "requires human review" banner; KaryaShield never merges, never
  enables auto-merge, never approves.
- Idempotent: a hidden marker in the PR body is matched (open and closed PRs) before creating another.
"""
from __future__ import annotations

import base64
import json
import os
import re
import tempfile

from .config import ISSUE_LABEL, validate_repo
from .github_adapter import GitHubError, _run, validate_issue_url
from .mender import PatchResult
from .models import Finding

PR_MARKER_PREFIX = "<!-- karyashield:patch-fingerprint="


def pr_marker(fp: str) -> str:
    return f"{PR_MARKER_PREFIX}{fp} -->"


def _gh(args: list[str], timeout: int = 60) -> str:
    p = _run(["gh", *args], timeout=timeout)
    if p.returncode != 0:
        raise GitHubError(f"gh {args[0]} {args[1] if len(args) > 1 else ''} failed: {p.stderr.strip()[-300:]}")
    return p.stdout


def find_pr_by_marker(repo: str, fp: str) -> str | None:
    out = _gh(["pr", "list", "--repo", repo, "--label", ISSUE_LABEL, "--state", "all", "--limit", "200",
               "--json", "url,body"])
    for pr in json.loads(out or "[]"):
        if pr_marker(fp) in (pr.get("body") or ""):
            return pr["url"]
    return None


def open_review_pr(f: Finding, patch: PatchResult, issue_url: str) -> str:
    """Create branch + commit (GitHub API) + DRAFT PR. Returns the PR URL."""
    repo = validate_repo(f.repo)
    if patch.status != "verified" or not patch.fixed:
        raise GitHubError("refusing to open a PR for an unverified patch")
    existing = find_pr_by_marker(repo, f.fingerprint)
    if existing:
        return existing
    branch = f"karyashield/fix-{f.fingerprint[:12]}"
    # 1. branch from the exact scanned commit (422 = already exists from an earlier partial run: reuse)
    p = _run(["gh", "api", "-X", "POST", f"repos/{repo}/git/refs", "-f", f"ref=refs/heads/{branch}",
              "-f", f"sha={f.commit_sha}"], timeout=60)
    if p.returncode != 0 and "Reference already exists" not in (p.stdout + p.stderr):
        raise GitHubError(f"create branch failed: {p.stderr.strip()[-300:]}")
    # 2. commit the patched file onto that branch only
    blob_sha = _gh(["api", f"repos/{repo}/contents/{f.path}?ref={branch}", "--jq", ".sha"]).strip()
    content = base64.b64encode(patch.fixed.encode()).decode()
    _gh(["api", "-X", "PUT", f"repos/{repo}/contents/{f.path}",
         "-f", f"message=KaryaShield: fix {f.rule_id.split('.')[-1]} in {f.path} (sandbox-verified, needs review)",
         "-f", f"content={content}", "-f", f"sha={blob_sha}", "-f", f"branch={branch}"])
    # 3. draft PR
    issue_no = issue_url.rstrip("/").split("/")[-1]
    checks = "\n".join(f"- {c}" for c in patch.checks)
    body = f"""> [!WARNING]
> **Requires human review.** Opened autonomously by KaryaShield as a **draft**. Do not merge without reviewing the change and running your own tests. KaryaShield never merges.

Proposed fix for #{issue_no}: `{f.rule_id}` in `{f.path}` (scanned commit `{f.commit_sha}`).

**What changed:** {patch.explanation}

**Verification performed by KaryaShield:**
{checks}

The sandbox exploit test ran the original and patched code in an isolated process with no secrets, no network and no process spawning; dangerous calls were recorded instead of executed.

Closes #{issue_no} when merged by a human.
{pr_marker(f.fingerprint)}
"""
    fd, tmp = tempfile.mkstemp(prefix="karyashield-pr-", suffix=".md")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(body)
        out = _gh(["pr", "create", "--repo", repo, "--draft", "--base", "main", "--head", branch,
                   "--title", f"[KaryaShield] Fix {f.rule_id.split('.')[-1]} in {f.path} (needs human review)"[:200],
                   "--body-file", tmp, "--label", ISSUE_LABEL])
    finally:
        os.unlink(tmp)
    url = out.strip().splitlines()[-1] if out.strip() else ""
    if not re.match(rf"^https://github\.com/{re.escape(repo)}/pull/\d+$", url, flags=re.IGNORECASE):
        raise GitHubError(f"unexpected PR URL {url!r}")
    return url


__all__ = ["open_review_pr", "find_pr_by_marker", "pr_marker", "validate_issue_url"]
