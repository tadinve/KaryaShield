"""KaryaShield CLI: doctor, run, watch, status."""
from __future__ import annotations

import argparse
import fcntl
import json
import os
from datetime import datetime, timezone
import shutil
import subprocess
import sys
import time

from . import github_adapter as gh
from . import health
from .config import PROJECT_ROOT, RULES_FILE, ConfigError, load_config
from .scanner import scan, semgrep_bin
from .store import ClickHouseBackend, Ledger
from .mender import propose_and_verify
from .pr import open_review_pr
from .triage import make_client, triage_finding
from .workflow import Deps, RunReport, run_once

EVIDENCE = PROJECT_ROOT / "demo" / "evidence" / "last_run.json"
# Where this process runs ("local" or "akash"); recorded in ClickHouse scan_runs.
RUN_HOST = os.getenv("KARYASHIELD_HOST", "local").strip()[:32] or "local"


def _ok(name: str, ok: bool, detail: str = "") -> bool:
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}{' — ' + detail if detail else ''}")
    return ok


def cmd_doctor(_args) -> int:
    print("KaryaShield doctor")
    good = True
    for tool, cmd in (("git", ["git", "--version"]), ("gh", ["gh", "--version"]),
                      ("semgrep", [semgrep_bin(), "--version"])):
        try:
            p = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            good &= _ok(tool, p.returncode == 0, p.stdout.strip().splitlines()[0] if p.stdout else p.stderr[-120:])
        except (FileNotFoundError, subprocess.TimeoutExpired) as e:
            good &= _ok(tool, False, str(e))
    p = subprocess.run(["gh", "auth", "status"], capture_output=True, text=True)
    good &= _ok("gh auth", p.returncode == 0)
    good &= _ok("pinned rules file", RULES_FILE.is_file(), str(RULES_FILE.relative_to(PROJECT_ROOT)))
    try:
        cfg = load_config()
    except ConfigError as e:
        _ok("config", False, str(e))
        return 1
    _ok("config", True, json.dumps(cfg.redacted()))
    for name, ok, detail in gh.doctor_repo(cfg.github_repo):
        good &= _ok(name, ok, detail)
    try:
        be = _backend(cfg)
        good &= _ok("ClickHouse ping", True, f"db={cfg.ch_database}")
        good &= _ok("ClickHouse schema", be.schema_ready(), "" if be.schema_ready() else "run: python -m karyashield.cli init-db")
    except Exception as e:
        good &= _ok("ClickHouse ping", False, _scrub(cfg, f"{type(e).__name__}: {str(e)[:150]}"))
    try:
        llm = make_client(cfg)
        if llm.provider in ("vertex", "gemini_api"):
            text = llm.client.models.generate_content(model=cfg.llm_model, contents="Reply with the single word OK.").text
        else:
            if not cfg.llm_api_key:
                raise ValueError("LLM_API_KEY not set")
            text = llm.client.chat.completions.create(model=cfg.llm_model, max_completion_tokens=16, messages=[
                {"role": "user", "content": "Reply with the single word OK."}]).choices[0].message.content
        good &= _ok("LLM model access", bool(text), llm.label)
    except Exception as e:
        good &= _ok("LLM model access", False, f"{type(e).__name__}: {str(e)[:200]}")
    print("doctor:", "ALL PASS" if good else "FAILURES PRESENT")
    return 0 if good else 1


def _scrub(cfg, text: str) -> str:
    return text.replace(cfg.ch_password, "<redacted>") if cfg.ch_password else text


def _backend(cfg) -> ClickHouseBackend:
    if not cfg.ch_host:
        raise ValueError("CLICKHOUSE_HOST not set")
    return ClickHouseBackend.connect(cfg.ch_host, cfg.ch_port, cfg.ch_user, cfg.ch_password,
                                     cfg.ch_database, cfg.ch_secure)


def _deps(cfg) -> Deps:
    llm = make_client(cfg)
    return Deps(
        scan=lambda path, repo, sha: scan(path, repo, sha, cfg.scan_timeout),
        triage=lambda f: triage_finding(llm, cfg.llm_model, f),
        llm_label=llm.label,
        mend=(lambda f, path: propose_and_verify(llm, cfg.llm_model, path, f, _sandbox_scan_fn(cfg, f)))
        if cfg.propose_patch else None,
        open_pr=open_review_pr if (cfg.open_pr and cfg.propose_patch) else None,
    )


def _sandbox_scan_fn(cfg, f):
    return lambda sb: scan(sb, f.repo, f.commit_sha, cfg.scan_timeout)[0]


def cmd_mend(_args) -> int:
    """Read-only: propose + sandbox-verify a patch for each current finding and print it. No writes anywhere."""
    cfg = load_config()
    co = gh.fetch_checkout(cfg.github_repo, cfg.github_branch, cfg.workspace_dir)
    findings, _ = scan(co.path, cfg.github_repo, co.sha, cfg.scan_timeout)
    print(f"[MEND] {cfg.github_repo}@{co.sha[:12]}: {len(findings)} finding(s); LLM={make_client(cfg).label}")
    llm = make_client(cfg)
    rc = 0
    for f in findings:
        t0 = time.monotonic()
        p = propose_and_verify(llm, cfg.llm_model, co.path, f, _sandbox_scan_fn(cfg, f))
        print(f"\n=== {f.rule_id} {f.path}:{f.start_line} -> PATCH {p.status.upper()} ({time.monotonic()-t0:.1f}s)")
        if p.reason:
            print(f"reason: {p.reason}")
        for c in p.checks:
            print(f"  ✓ {c}")
        if p.explanation:
            print(f"explanation: {p.explanation}")
        if p.diff:
            print(p.diff)
        rc |= 0 if p.status == "verified" else 1
    return rc


def _print_summary(rep: RunReport) -> None:
    print("-" * 60)
    print(f"run_id={rep.run_id} mode={rep.mode} host={RUN_HOST} repo={rep.repo} sha={rep.sha}")
    print(f"findings={rep.findings} actionable={rep.actionable} issues_created={rep.issues_created} "
          f"duplicates_skipped={rep.duplicates_skipped} reconciled={rep.reconciled} errors={rep.errors} "
          f"elapsed={rep.elapsed_seconds}s")
    if rep.fatal:
        print(f"FATAL: {rep.fatal}")
    if RUN_HOST != "local":
        return  # containers: evidence lives in logs, /status and ClickHouse
    try:
        EVIDENCE.parent.mkdir(parents=True, exist_ok=True)
        EVIDENCE.write_text(json.dumps(rep.to_json(), indent=2))  # no snippets, no secrets
    except OSError as e:
        print(f"(could not write evidence: {e})")


def _run(cfg, dry_run: bool) -> RunReport:
    ledger = Ledger(_backend(cfg))
    # Single-writer lock: ClickHouse has no compare-and-set, so only one run per machine at a time.
    cfg.workspace_dir.mkdir(parents=True, exist_ok=True)
    with open(cfg.workspace_dir / "karyashield.lock", "w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError("another KaryaShield run holds the lock")
        rep = run_once(cfg, ledger, _deps(cfg), dry_run=dry_run)
    _print_summary(rep)
    if rep.mode == "write":
        try:
            ledger.record_run({**rep.to_json(), "host": RUN_HOST})
        except Exception as e:
            print(f"(could not record run analytics: {type(e).__name__})")
    return rep


def cmd_run(args) -> int:
    cfg = load_config()
    if not args.dry_run and not cfg.enable_writes:
        print("NOTE: KARYASHIELD_ENABLE_WRITES is not 'true' — running read-only.")
    rep = _run(cfg, args.dry_run)
    return 1 if rep.fatal or rep.errors else 0


def cmd_watch(args) -> int:
    cfg = load_config()
    last_sha = None
    rc = 0
    for cycle in range(1, args.max_cycles + 1):
        try:
            sha = gh.remote_head_sha(cfg.github_repo, cfg.github_branch)
        except gh.GitHubError as e:
            print(f"[WATCH {cycle}/{args.max_cycles}] {e}")
            rc = 1
            sha = None
        if sha and sha != last_sha:
            print(f"[WATCH {cycle}/{args.max_cycles}] {'initial' if last_sha is None else 'NEW COMMIT'} {sha} -> running")
            rep = _run(cfg, args.dry_run)
            if rep.fatal or rep.errors:
                rc = 1
            last_sha = sha
        elif sha:
            print(f"[WATCH {cycle}/{args.max_cycles}] no new commit ({sha[:12]})")
        if cycle < args.max_cycles:
            time.sleep(cfg.watch_interval)
    return rc


def _log(msg: str) -> None:
    print(f"{datetime.now(timezone.utc):%Y-%m-%dT%H:%M:%SZ} {msg}", flush=True)


def cmd_worker(_args) -> int:
    """Unbounded watch loop + status server (container entrypoint). Never crashes on a failed cycle."""
    cfg = load_config()
    port = int(os.getenv("STATUS_PORT", "8080"))
    health.update(host=RUN_HOST, repo=cfg.github_repo)
    health.serve(port)
    _log(f"[WORKER] start host={RUN_HOST} repo={cfg.github_repo}@{cfg.github_branch} "
         f"writes={'ENABLED' if cfg.enable_writes else 'disabled'} interval={cfg.watch_interval}s status=:{port}")
    last_sha, delay, cycle = None, cfg.watch_interval, 0
    while True:
        cycle += 1
        health.update(cycles=cycle)
        try:
            sha = gh.remote_head_sha(cfg.github_repo, cfg.github_branch)
            if sha != last_sha:
                _log(f"[WORKER] cycle {cycle}: {'initial' if last_sha is None else 'NEW COMMIT'} {sha} -> running")
                rep = _run(cfg, dry_run=False)  # writes only if KARYASHIELD_ENABLE_WRITES=true
                snap = health.snapshot()
                health.update(runs=snap["runs"] + 1, last_sha=sha,
                              total_issues_created=snap["total_issues_created"] + rep.issues_created,
                              last_run={k: getattr(rep, k) for k in (
                                  "run_id", "mode", "sha", "findings", "issues_created",
                                  "duplicates_skipped", "reconciled", "errors", "elapsed_seconds")})
                if rep.fatal:
                    raise RuntimeError(rep.fatal)  # retry this SHA next cycle
                last_sha = sha
            else:
                _backend(cfg)  # keepalive ping: stops the ClickHouse service idling before the next commit
                _log(f"[WORKER] cycle {cycle}: no new commit ({sha[:12]})")
            health.update(last_error_type=None)
            delay = cfg.watch_interval
        except Exception as e:
            health.update(last_error_type=type(e).__name__)
            delay = min(max(delay * 2, cfg.watch_interval), 300)
            _log(f"[WORKER] cycle {cycle} failed: {type(e).__name__}: {_scrub(cfg, str(e)[:200])}; retry in {delay}s")
        time.sleep(delay)


def cmd_pr(_args) -> int:
    """For findings already filed as issues: mend + sandbox-test, then open a DRAFT review PR.
    Requires KARYASHIELD_ENABLE_WRITES=true and KARYASHIELD_OPEN_PR=true. Never merges."""
    cfg = load_config()
    if not (cfg.enable_writes and cfg.open_pr):
        print("refusing: set KARYASHIELD_ENABLE_WRITES=true and KARYASHIELD_OPEN_PR=true for this command")
        return 1
    ledger = Ledger(_backend(cfg))
    co = gh.fetch_checkout(cfg.github_repo, cfg.github_branch, cfg.workspace_dir)
    findings, _ = scan(co.path, cfg.github_repo, co.sha, cfg.scan_timeout)
    llm, rc = make_client(cfg), 0
    for f in findings:
        doc = ledger.get(f.fingerprint)
        if not doc or doc.get("status") != "issue_created":
            print(f"[PR] skip {f.path}:{f.start_line}: no filed issue")
            continue
        p = propose_and_verify(llm, cfg.llm_model, co.path, f, _sandbox_scan_fn(cfg, f))
        print(f"[PR] {f.rule_id} {f.path}:{f.start_line} patch {p.status.upper()} {p.reason}")
        for c in p.checks:
            print(f"  ✓ {c}")
        if p.status != "verified":
            rc = 1
            continue
        url = open_review_pr(f, p, doc["github_issue_url"])
        ledger.event(f.fingerprint, "pr_opened_draft", url, "cli-pr")
        print(f"[PR] DRAFT PR for human review: {url}")
    return rc


def cmd_status(args) -> int:
    cfg = load_config()
    ledger = Ledger(_backend(cfg))
    for d in ledger.recent(args.n):
        print(f"{d['updated_at']:%Y-%m-%d %H:%M:%SZ}  {d['status']:<15} {d['rule_id']} "
              f"{d['path']}:{d['line']}  {d.get('github_issue_url') or '-'}  fp={d['fingerprint'][:12]}")
    return 0


def cmd_init_db(_args) -> int:
    cfg = load_config()
    be = _backend(cfg)
    be.init_schema()
    print(f"ClickHouse schema ready in database {cfg.ch_database}: {be.schema_ready()}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="karyashield")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("doctor")
    r = sub.add_parser("run")
    r.add_argument("--once", action="store_true", default=True)
    r.add_argument("--dry-run", action="store_true")
    w = sub.add_parser("watch")
    w.add_argument("--max-cycles", type=int, default=2)
    w.add_argument("--dry-run", action="store_true")
    sub.add_parser("init-db")
    sub.add_parser("worker")
    sub.add_parser("mend")
    sub.add_parser("pr")
    s = sub.add_parser("status")
    s.add_argument("-n", type=int, default=10)
    args = ap.parse_args(argv)
    if shutil.which("gh") is None:
        print("gh CLI not found")
        return 1
    try:
        return {"doctor": cmd_doctor, "run": cmd_run, "watch": cmd_watch, "status": cmd_status, "init-db": cmd_init_db, "worker": cmd_worker, "mend": cmd_mend, "pr": cmd_pr}[args.cmd](args)
    except ConfigError as e:
        print(f"config error: {e}")
        return 1
    except Exception as e:  # fail closed without dumping tracebacks that could carry config
        try:
            msg = _scrub(load_config(), str(e)[:200])
        except Exception:
            msg = "(details withheld)"
        print(f"FATAL: {type(e).__name__}: {msg}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
