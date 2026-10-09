# Dry-run evidence: real end-to-end, read-only

- When: 2026-10-09 13:00 PDT
- Command: `python -m karyashield.cli run --once --dry-run` (real GitHub, Semgrep, Gemini/Vertex, ClickHouse reads)

```
[FETCH] tadinve/KaryaShield@main
[FETCH] live commit 77ade8cb754eabf887fb3f46e7a1724d9de64b03
[SCAN] semgrep (pinned rules/karyashield.yml)
[SCAN] 1 finding(s)
[TRIAGE/POLICY] karyashield.python.subprocess-shell-true demo/target_seed/app/ping_tool.py:8 fp=1848c95b27df
    -> WOULD_CREATE  all gates pass except write gate
------------------------------------------------------------
run_id=655022459e71 mode=dry-run repo=tadinve/KaryaShield sha=77ade8cb754eabf887fb3f46e7a1724d9de64b03
findings=1 actionable=1 issues_created=0 duplicates_skipped=0 reconciled=0 errors=0 elapsed=12.86s
```

ClickHouse after dry run (proves zero ledger writes):
```
ClickHouse incidents rows: 0
ClickHouse incident_events rows: 0
ClickHouse scan_runs rows: 0
```

Issue body was reviewed; fixed: truncated LLM code fence now closed before footer/marker; heading names the actual model.
