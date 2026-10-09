"""Incident ledger on ClickHouse (sponsor tool).

ClickHouse has no unique keys or compare-and-set, so the ledger is:
- `incidents`: ReplacingMergeTree(version) keyed by fingerprint; every state change inserts a
  new row with a higher version, and reads use FINAL to get the latest state.
- `incident_events`: append-only audit trail.
- `scan_runs`: one row per run, for real-time analytics.
Duplicate prevention therefore relies on three layers: (1) a single-writer lock per machine
(see cli.py), (2) the latest-state check here, and (3) the authoritative GitHub labeled-issue
marker check that precedes every issue create (workflow.py).
"""
from __future__ import annotations

import threading
import time
from datetime import datetime, timedelta, timezone

from .models import Finding, Triage

STALE_RESERVATION = timedelta(minutes=10)

INCIDENT_COLUMNS = [
    "fingerprint", "repo", "rule_id", "path", "line", "severity", "first_seen_commit",
    "last_seen_commit", "status", "reserved_by", "reserved_at", "triage_summary", "triage_risk",
    "triage_actionable", "triage_confidence", "github_issue_url", "created_at", "updated_at", "version",
]

DDL = [
    """CREATE TABLE IF NOT EXISTS {db}.incidents (
        fingerprint String, repo String, rule_id String, path String, line UInt32,
        severity LowCardinality(String), first_seen_commit String, last_seen_commit String,
        status LowCardinality(String), reserved_by String, reserved_at DateTime64(3, 'UTC'),
        triage_summary String, triage_risk LowCardinality(String), triage_actionable UInt8,
        triage_confidence Float32, github_issue_url String,
        created_at DateTime64(3, 'UTC'), updated_at DateTime64(3, 'UTC'), version UInt64
    ) ENGINE = ReplacingMergeTree(version) ORDER BY fingerprint""",
    """CREATE TABLE IF NOT EXISTS {db}.incident_events (
        fingerprint String, at DateTime64(3, 'UTC'), type LowCardinality(String),
        detail String, run_id String
    ) ENGINE = MergeTree ORDER BY (fingerprint, at)""",
    """CREATE TABLE IF NOT EXISTS {db}.scan_runs (
        run_id String, at DateTime64(3, 'UTC'), repo String, sha String, mode LowCardinality(String),
        findings UInt32, actionable UInt32, issues_created UInt32, duplicates_skipped UInt32,
        reconciled UInt32, errors UInt32, elapsed_seconds Float32, fatal String,
        host LowCardinality(String) DEFAULT 'local'
    ) ENGINE = MergeTree ORDER BY at""",
    # Migration for tables created before the host column existed.
    "ALTER TABLE {db}.scan_runs ADD COLUMN IF NOT EXISTS host LowCardinality(String) DEFAULT 'local'",
]


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


_version_lock = threading.Lock()
_last_version = 0


def next_version() -> int:
    global _last_version
    with _version_lock:
        _last_version = max(time.time_ns() // 1000, _last_version + 1)
        return _last_version


class ClickHouseBackend:
    def __init__(self, client, database: str):
        self.c = client
        self.db = database

    @classmethod
    def connect(cls, host: str, port: int, user: str, password: str, database: str, secure: bool) -> "ClickHouseBackend":
        import certifi
        import clickhouse_connect

        client = clickhouse_connect.get_client(
            host=host, port=port, username=user, password=password, secure=secure,
            ca_cert=certifi.where() if secure else None,  # python.org macOS builds ship no root CAs
            connect_timeout=8, send_receive_timeout=30,
            # Read-your-writes across ClickHouse Cloud replicas.
            settings={"select_sequential_consistency": 1},
        )
        if not client.ping():
            raise ConnectionError("ClickHouse ping failed")
        return cls(client, database)

    def init_schema(self) -> None:
        self.c.command(f"CREATE DATABASE IF NOT EXISTS {self.db}")
        for stmt in DDL:
            self.c.command(stmt.format(db=self.db))

    def schema_ready(self) -> bool:
        r = self.c.query("SELECT count() FROM system.tables WHERE database = {db:String} "
                         "AND name IN ('incidents','incident_events','scan_runs')", parameters={"db": self.db})
        return r.result_rows[0][0] == 3

    def latest(self, fp: str) -> dict | None:
        r = self.c.query(f"SELECT {', '.join(INCIDENT_COLUMNS)} FROM {self.db}.incidents FINAL "
                         "WHERE fingerprint = {fp:String} LIMIT 1", parameters={"fp": fp})
        return dict(zip(INCIDENT_COLUMNS, r.result_rows[0])) if r.result_rows else None

    def put(self, doc: dict) -> None:
        self.c.insert(f"{self.db}.incidents", [[doc[k] for k in INCIDENT_COLUMNS]], column_names=INCIDENT_COLUMNS)

    def event(self, fp: str, kind: str, detail: str, run_id: str) -> None:
        self.c.insert(f"{self.db}.incident_events", [[fp, utcnow(), kind, detail[:300], run_id]],
                      column_names=["fingerprint", "at", "type", "detail", "run_id"])

    def record_run(self, row: dict) -> None:
        cols = list(row)
        self.c.insert(f"{self.db}.scan_runs", [[row[k] for k in cols]], column_names=cols)

    def recent(self, n: int) -> list[dict]:
        r = self.c.query(f"SELECT {', '.join(INCIDENT_COLUMNS)} FROM {self.db}.incidents FINAL "
                         "ORDER BY updated_at DESC LIMIT {n:UInt32}", parameters={"n": n})
        return [dict(zip(INCIDENT_COLUMNS, row)) for row in r.result_rows]


class Ledger:
    """State machine over an append/replace backend. All state logic is here (backend-agnostic)."""

    def __init__(self, backend):
        self.b = backend

    def get(self, fp: str) -> dict | None:
        d = self.b.latest(fp)
        if d is not None and not d.get("github_issue_url"):
            d["github_issue_url"] = None
        return d

    def _write(self, doc: dict, kind: str, detail: str, run_id: str) -> None:
        doc = dict(doc)
        doc["github_issue_url"] = doc.get("github_issue_url") or ""
        doc["updated_at"] = utcnow()
        doc["version"] = next_version()
        self.b.put(doc)
        self.b.event(doc["fingerprint"], kind, detail, run_id)

    def try_reserve(self, f: Finding, triage: Triage | None, run_id: str) -> bool:
        if self.get(f.fingerprint) is not None:
            return False
        now = utcnow()
        doc = {
            "fingerprint": f.fingerprint, "repo": f.repo, "rule_id": f.rule_id, "path": f.path,
            "line": f.start_line, "severity": f.severity, "first_seen_commit": f.commit_sha,
            "last_seen_commit": f.commit_sha, "status": "reserved", "reserved_by": run_id,
            "reserved_at": now, "triage_summary": triage.summary if triage else "",
            "triage_risk": triage.risk_level if triage else "", "triage_actionable": int(bool(triage and triage.is_actionable)),
            "triage_confidence": float(triage.confidence) if triage else 0.0,
            "github_issue_url": "", "created_at": now,
        }
        self._write(doc, "detected", f"run {run_id} reserved at {f.commit_sha[:12]}", run_id)
        # Verify we hold the reservation (guards against a concurrent writer).
        cur = self.get(f.fingerprint)
        return bool(cur and cur["reserved_by"] == run_id and cur["status"] == "reserved")

    def claim(self, fp: str, from_status: str, run_id: str, *, stale_only: bool = False) -> bool:
        d = self.get(fp)
        if d is None or d["status"] != from_status:
            return False
        if stale_only and d["reserved_at"] > utcnow() - STALE_RESERVATION:
            return False
        d.update(status="reserved", reserved_by=run_id, reserved_at=utcnow())
        self._write(d, "reclaimed", f"run {run_id} from {from_status}", run_id)
        cur = self.get(fp)
        return bool(cur and cur["reserved_by"] == run_id)

    def set_status(self, fp: str, status: str, kind: str, detail: str, *, url: str | None = None,
                   expect_run: str | None = None) -> bool:
        d = self.get(fp)
        if d is None or (expect_run and d["reserved_by"] != expect_run):
            return False
        d["status"] = status
        if url:
            d["github_issue_url"] = url
        self._write(d, kind, detail, expect_run or d["reserved_by"])
        return True

    def record_skip(self, f: Finding, triage: Triage | None, run_id: str, reason: str) -> None:
        """Record a model veto as re-claimable 'skipped' (never poisons the key)."""
        d = self.get(f.fingerprint)
        if d is None:
            if self.try_reserve(f, triage, run_id):
                self.set_status(f.fingerprint, "skipped", "skipped", reason, expect_run=run_id)
        elif d["status"] in ("skipped", "error"):
            self.set_status(f.fingerprint, "skipped", "skipped", reason)

    def touch_seen(self, fp: str, sha: str, run_id: str) -> None:
        d = self.get(fp)
        if d is not None:
            d["last_seen_commit"] = sha
            self._write(d, "already_seen", f"run {run_id} at {sha[:12]}", run_id)

    def record_run(self, rep_json: dict) -> None:
        self.b.record_run({
            "run_id": rep_json["run_id"], "at": utcnow(), "repo": rep_json["repo"], "sha": rep_json["sha"],
            "mode": rep_json["mode"], **{k: int(rep_json[k]) for k in (
                "findings", "actionable", "issues_created", "duplicates_skipped", "reconciled", "errors")},
            "elapsed_seconds": float(rep_json["elapsed_seconds"]), "fatal": rep_json["fatal"] or "",
            "host": str(rep_json.get("host", "local")),
        })

    def recent(self, n: int = 10) -> list[dict]:
        return self.b.recent(n)
