"""GitHub access via git + gh CLI. Argument arrays only, never shell=True."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .config import ISSUE_LABEL, validate_repo
from .models import Finding, Triage

MARKER_PREFIX = "<!-- karyashield:fingerprint="
ISSUE_LIST_LIMIT = 500
_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_HASH_RE = re.compile(r"^[0-9a-f]{64}$")


class GitHubError(RuntimeError):
    pass


class WriteUncertain(GitHubError):
    """Issue create outcome unknown (timeout / unverifiable output). Never auto-retry."""


@dataclass
class Checkout:
    path: Path
    sha: str


def _run(cmd: list[str], timeout: int = 60, cwd: Path | None = None) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GH_PROMPT_DISABLED"] = "1"
    env["GH_NO_UPDATE_NOTIFIER"] = "1"
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True,
                          timeout=timeout, shell=False, env=env)


def _git(args: list[str], cwd: Path | None = None, timeout: int = 120) -> str:
    cmd = ["git", "-c", "core.hooksPath=/dev/null", "-c", "protocol.file.allow=never", *args]
    p = _run(cmd, timeout=timeout, cwd=cwd)
    if p.returncode != 0:
        raise GitHubError(f"git {args[0]} failed: {p.stderr.strip()[-300:]}")
    return p.stdout.strip()


def _repo_from_remote(url: str) -> str | None:
    m = re.match(r"^(?:https://github\.com/|git@github\.com:|ssh://git@github\.com/)([^/]+/[^/]+?)(?:\.git)?/?$", url)
    return m.group(1) if m else None


def remote_head_sha(repo: str, branch: str) -> str:
    """Live SHA of branch on GitHub (used by watch)."""
    repo = validate_repo(repo)
    p = _run(["gh", "api", f"repos/{repo}/commits/{branch}", "--jq", ".sha"], timeout=30)
    sha = p.stdout.strip()
    if p.returncode != 0 or not _SHA_RE.match(sha):
        raise GitHubError(f"cannot read live SHA for {repo}@{branch}: {p.stderr.strip()[-200:]}")
    return sha


def fetch_checkout(repo: str, branch: str, workspace: Path) -> Checkout:
    """Clone or update the allowed repo and hard-reset to the live remote branch."""
    repo = validate_repo(repo)
    workspace.mkdir(parents=True, exist_ok=True)
    dest = workspace / repo.replace("/", "__")
    if not (dest / ".git").is_dir():
        if dest.exists():
            shutil.rmtree(dest)
        p = _run(["gh", "repo", "clone", repo, str(dest), "--", "--no-checkout",
                  "-c", "core.hooksPath=/dev/null"], timeout=180)
        if p.returncode != 0:
            raise GitHubError(f"clone failed: {p.stderr.strip()[-300:]}")
    origin = _git(["remote", "get-url", "origin"], cwd=dest)
    if (_repo_from_remote(origin) or "").lower() != repo.lower():
        raise GitHubError(f"origin {origin!r} does not match allowed repo {repo}")
    _git(["fetch", "--no-tags", "--prune", "origin", f"+refs/heads/{branch}:refs/remotes/origin/{branch}"], cwd=dest)
    sha = _git(["rev-parse", f"refs/remotes/origin/{branch}"], cwd=dest)
    if not _SHA_RE.match(sha):
        raise GitHubError(f"invalid SHA {sha!r}")
    _git(["checkout", "--force", "--detach", sha], cwd=dest)
    _git(["clean", "-fdx"], cwd=dest)
    if _git(["rev-parse", "HEAD"], cwd=dest) != sha:
        raise GitHubError("checkout HEAD does not match fetched SHA")
    return Checkout(path=dest, sha=sha)


def marker(fingerprint: str) -> str:
    if not _HASH_RE.match(fingerprint):
        raise ValueError("bad fingerprint")
    return f"{MARKER_PREFIX}{fingerprint} -->"


def find_issue_by_marker(repo: str, fingerprint: str) -> str | None:
    """List ALL labeled issues (open+closed) and match the exact marker locally.
    Raises GitHubError on any failure or if the listing may be truncated (fail closed)."""
    repo = validate_repo(repo)
    p = _run(["gh", "issue", "list", "--repo", repo, "--label", ISSUE_LABEL, "--state", "all",
              "--limit", str(ISSUE_LIST_LIMIT), "--json", "number,url,body,state"], timeout=60)
    if p.returncode != 0:
        raise GitHubError(f"issue list failed: {p.stderr.strip()[-300:]}")
    try:
        issues = json.loads(p.stdout or "[]")
    except json.JSONDecodeError as e:
        raise GitHubError("issue list returned invalid JSON") from e
    if len(issues) >= ISSUE_LIST_LIMIT:
        raise GitHubError("labeled issue listing may be truncated; failing closed")
    m = marker(fingerprint)
    for issue in issues:
        if m in (issue.get("body") or ""):
            url = issue.get("url", "")
            validate_issue_url(repo, url)
            return url
    return None


def validate_issue_url(repo: str, url: str) -> str:
    pat = rf"^https://github\.com/{re.escape(repo)}/issues/\d+$"
    if not re.match(pat, url, flags=re.IGNORECASE):
        raise GitHubError(f"unexpected issue URL {url!r}")
    return url


def build_issue(f: Finding, t: Triage) -> tuple[str, str]:
    short = f.rule_id.split(".")[-1]
    title = f"[KaryaShield] {short} in {f.path}:{f.start_line}"[:200]
    blob = f"https://github.com/{f.repo}/blob/{f.commit_sha}/{f.path}#L{f.start_line}-L{f.end_line}"
    fence = "````"
    body = f"""## Static analysis finding (Semgrep)

| Field | Value |
|---|---|
| Rule | `{f.rule_id}` (pinned KaryaShield ruleset) |
| Severity | {f.severity} |
| Location | [`{f.path}` lines {f.start_line}-{f.end_line}]({blob}) |
| Commit | `{f.commit_sha}` |

**Semgrep message:** {f.message}

**Evidence excerpt:**
{fence}
{f.snippet}
{fence}

## AI assessment (LLM, advisory — not verified by a human)

- **Risk level:** {t.risk_level}
- **Summary:** {t.summary}

**Why it matters:** {t.why_it_matters}

**Suggested fix:** {t.recommended_fix}

---
_Filed autonomously by KaryaShield. Write authorized by deterministic policy (pinned rule match + severity + repo allowlist), not by the model._
{marker(f.fingerprint)}
"""
    return title, body


def create_issue(repo: str, title: str, body: str, timeout: int = 60) -> str:
    """Create the issue. Returns validated URL. Raises WriteUncertain if outcome unknown,
    GitHubError on definite failure."""
    repo = validate_repo(repo)
    fd, tmp = tempfile.mkstemp(prefix="karyashield-issue-", suffix=".md")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(body)
        try:
            p = _run(["gh", "issue", "create", "--repo", repo, "--title", title,
                      "--body-file", tmp, "--label", ISSUE_LABEL], timeout=timeout)
        except subprocess.TimeoutExpired as e:
            raise WriteUncertain("gh issue create timed out") from e
        if p.returncode != 0:
            raise GitHubError(f"gh issue create failed: {p.stderr.strip()[-300:]}")
        url = p.stdout.strip().splitlines()[-1] if p.stdout.strip() else ""
        try:
            return validate_issue_url(repo, url)
        except GitHubError as e:
            raise WriteUncertain(f"issue create output unverifiable: {url[:200]!r}") from e
    finally:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass


def doctor_repo(repo: str) -> list[tuple[str, bool, str]]:
    checks = []
    p = _run(["gh", "repo", "view", repo, "--json", "nameWithOwner,hasIssuesEnabled,viewerPermission"], timeout=30)
    if p.returncode != 0:
        return [("github repo access", False, p.stderr.strip()[-200:])]
    info = json.loads(p.stdout)
    checks.append(("github repo access", True, info.get("nameWithOwner", "")))
    checks.append(("issues enabled", bool(info.get("hasIssuesEnabled")), ""))
    perm = info.get("viewerPermission", "")
    checks.append(("write permission", perm in ("ADMIN", "MAINTAIN", "WRITE"), perm))
    p = _run(["gh", "label", "list", "--repo", repo, "--search", ISSUE_LABEL, "--json", "name"], timeout=30)
    has_label = p.returncode == 0 and any(l.get("name") == ISSUE_LABEL for l in json.loads(p.stdout or "[]"))
    checks.append((f"label '{ISSUE_LABEL}' exists", has_label,
                   "" if has_label else f"run: gh label create {ISSUE_LABEL} --repo {repo}"))
    return checks
