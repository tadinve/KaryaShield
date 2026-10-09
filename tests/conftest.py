"""Shared fixtures. Unit tests use mocks only; no network."""
from __future__ import annotations

import copy
from pathlib import Path

import pytest

from karyashield import github_adapter as gh
from karyashield.config import Config
from karyashield.models import Finding, Triage, TriageResult
from karyashield.scanner import compute_fingerprint
from karyashield.store import Ledger
from karyashield.workflow import Deps

REPO = "tadinve/KaryaShield"
SHA = "a" * 40


def make_cfg(**kw) -> Config:
    base = dict(
        llm_provider="openai_compat", llm_model="m", llm_base_url="http://x", llm_api_key="x", gcp_project="", gcp_location="us-central1", ch_host="", ch_port=8443, ch_user="u", ch_password="", ch_database="t", ch_secure=True,
        github_repo=REPO, github_branch="main", allowlist=(REPO,), enable_writes=True,
        min_severity="WARNING", workspace_dir=Path("/tmp/ks"), scan_timeout=90,
        llm_timeout=45, watch_interval=1,
    )
    base.update(kw)
    return Config(**base)


def make_finding(**kw) -> Finding:
    rule = kw.pop("rule_id", "karyashield.python.subprocess-shell-true")
    path = kw.pop("path", "app/ping_tool.py")
    snippet = kw.pop("snippet", 'return subprocess.run(f"ping -c 1 {host}", shell=True)')
    repo = kw.pop("repo", REPO)
    base = dict(rule_id=rule, path=path, start_line=8, end_line=8, severity="ERROR",
                message="shell=True", snippet=snippet, commit_sha=SHA, repo=repo,
                fingerprint=compute_fingerprint(repo, rule, path, snippet, 0))
    base.update(kw)
    return Finding(**base)


GOOD_TRIAGE = TriageResult(ok=True, triage=Triage(
    is_actionable=True, risk_level="high", summary="Command injection", why_it_matters="RCE",
    recommended_fix="Use argument list without shell=True", confidence=0.2))


class MemoryBackend:
    """In-memory stand-in for ClickHouseBackend (latest-version-wins semantics)."""

    def __init__(self):
        self.rows: dict[str, dict] = {}
        self.events: list[tuple] = []
        self.runs: list[dict] = []
        self.writes = 0
        self.fail_on_status: str | None = None  # simulate a crash when writing this status

    def latest(self, fp):
        d = self.rows.get(fp)
        return copy.deepcopy(d) if d else None

    def put(self, doc):
        if self.fail_on_status and doc["status"] == self.fail_on_status:
            raise RuntimeError("simulated ClickHouse failure")
        cur = self.rows.get(doc["fingerprint"])
        if cur is None or doc["version"] > cur["version"]:
            self.rows[doc["fingerprint"]] = copy.deepcopy(doc)
        self.writes += 1

    def event(self, fp, kind, detail, run_id):
        self.events.append((fp, kind, detail, run_id))
        self.writes += 1

    def record_run(self, row):
        self.runs.append(row)

    def recent(self, n):
        return list(self.rows.values())[:n]


class FakeGitHub:
    def __init__(self):
        self.issues: dict[str, str] = {}  # fingerprint -> url
        self.created: list[tuple[str, str]] = []
        self.create_raises = None

    def find_issue(self, repo, fp):
        return self.issues.get(fp)

    def create_issue(self, repo, title, body):
        if self.create_raises:
            raise self.create_raises
        url = f"https://github.com/{repo}/issues/{len(self.created) + 1}"
        self.created.append((repo, url))
        fp = body.split(gh.MARKER_PREFIX)[1].split(" ")[0]
        self.issues[fp] = url
        return url


@pytest.fixture
def ledger():
    return Ledger(MemoryBackend())


@pytest.fixture
def fake_gh():
    return FakeGitHub()


def make_deps(fake_gh, findings, triage=GOOD_TRIAGE):
    co = gh.Checkout(path=Path("/tmp/ks"), sha=SHA)
    return Deps(
        fetch=lambda repo, branch, ws: co,
        scan=lambda path, repo, sha: (findings, []),
        triage=lambda f: triage,
        find_issue=fake_gh.find_issue,
        create_issue=fake_gh.create_issue,
    )
