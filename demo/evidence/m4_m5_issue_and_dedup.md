# M4 + M5 evidence: real GitHub issue, ClickHouse ledger, no duplicate on rerun

- When: 2026-10-09 13:05 PDT. Write gate enabled by builder ("write"), then disabled again after the runs.
- Issue: https://github.com/tadinve/KaryaShield/issues/1
- Acceptance tests #9 (real issue with true rule/path/commit + marker) and #10 (ClickHouse record with real URL; rerun creates no duplicate): PASS

## run1
```
[FETCH] tadinve/KaryaShield@main
[FETCH] live commit 3eb1aa2e818559d3465c0d7490c45bd158594059
[SCAN] semgrep (pinned rules/karyashield.yml)
[SCAN] 1 finding(s)
[TRIAGE/POLICY] karyashield.python.subprocess-shell-true demo/target_seed/app/ping_tool.py:8 fp=1848c95b27df
    -> ISSUE_CREATED https://github.com/tadinve/KaryaShield/issues/1
------------------------------------------------------------
run_id=7382e12289d8 mode=write repo=tadinve/KaryaShield sha=3eb1aa2e818559d3465c0d7490c45bd158594059
findings=1 actionable=1 issues_created=1 duplicates_skipped=0 reconciled=0 errors=0 elapsed=20.81s
```

## run2
```
[FETCH] tadinve/KaryaShield@main
[FETCH] live commit 3eb1aa2e818559d3465c0d7490c45bd158594059
[SCAN] semgrep (pinned rules/karyashield.yml)
[SCAN] 1 finding(s)
[TRIAGE/POLICY] karyashield.python.subprocess-shell-true demo/target_seed/app/ping_tool.py:8 fp=1848c95b27df
    -> DUPLICATE https://github.com/tadinve/KaryaShield/issues/1 already filed (ledger)
------------------------------------------------------------
run_id=4e378257a0af mode=write repo=tadinve/KaryaShield sha=3eb1aa2e818559d3465c0d7490c45bd158594059
findings=1 actionable=0 issues_created=0 duplicates_skipped=1 reconciled=0 errors=0 elapsed=4.29s
```

## status
```
2026-10-09 20:05:59Z  issue_created   karyashield.python.subprocess-shell-true demo/target_seed/app/ping_tool.py:8  https://github.com/tadinve/KaryaShield/issues/1  fp=1848c95b27df
```

## gh
```
#1 OPEN [KaryaShield] subprocess-shell-true in demo/target_seed/app/ping_tool.py:8 https://github.com/tadinve/KaryaShield/issues/1
```

## ch
```
incidents (FINAL): [('1848c95b27df0133', 'issue_created', 'https://github.com/tadinve/KaryaShield/issues/1', 1, 'high')]
events: [('already_seen', 1), ('detected', 1), ('issue_created', 1)]
scan_runs: [('7382e12289d8', 'write', 1, 0, 0, 20.799999237060547), ('4e378257a0af', 'write', 0, 1, 0, 4.300000190734863)]
```

Marker check: `gh issue view 1 --json body | grep -c karyashield:fingerprint=1848c95b…` → 1
