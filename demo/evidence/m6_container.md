# M6 evidence: worker container (linux/amd64) verified locally, dry-run

- When: 2026-10-09 13:08–13:12 PDT. Image built with `docker buildx build --platform linux/amd64` (665 MB, arch amd64).
- Run: `docker run --env-file .env -e KARYASHIELD_ENABLE_WRITES=false -e KARYASHIELD_HOST=local-docker -e GH_TOKEN=… -e GOOGLE_APPLICATION_CREDENTIALS_JSON=… karyashield:local` (worker entrypoint, non-root uid 10001)

```
2026-10-09T20:08:48Z [WORKER] start host=local-docker repo=tadinve/KaryaShield@main writes=disabled interval=20s status=:8080
2026-10-09T20:08:49Z [WORKER] cycle 1: initial a6b54b795e4ce6697ef969aec76dca4b8a9cd158 -> running
[FETCH] tadinve/KaryaShield@main
[FETCH] live commit a6b54b795e4ce6697ef969aec76dca4b8a9cd158
[SCAN] semgrep (pinned rules/karyashield.yml)
[SCAN] 1 finding(s)
[TRIAGE/POLICY] karyashield.python.subprocess-shell-true demo/target_seed/app/ping_tool.py:8 fp=1848c95b27df
    -> DUPLICATE https://github.com/tadinve/KaryaShield/issues/1 already filed (ledger)
------------------------------------------------------------
run_id=18da8f551a45 mode=dry-run host=local-docker repo=tadinve/KaryaShield sha=a6b54b795e4ce6697ef969aec76dca4b8a9cd158
findings=1 actionable=0 issues_created=0 duplicates_skipped=1 reconciled=0 errors=0 elapsed=5.77s
(could not write evidence: [Errno 13] Permission denied: '/app/demo')
2026-10-09T20:09:16Z [WORKER] cycle 2: no new commit (a6b54b795e4c)
--- /healthz:
ok
--- /status:
{
  "service": "karyashield-worker",
  "started_at": "2026-10-09T20:08:48+00:00",
  "host": "local-docker",
  "repo": "tadinve/KaryaShield",
  "cycles": 2,
  "runs": 1,
  "last_sha": "a6b54b795e4ce6697ef969aec76dca4b8a9cd158",
  "last_run": {
    "run_id": "18da8f551a45",
    "mode": "dry-run",
    "sha": "a6b54b795e4ce6697ef969aec76dca4b8a9cd158",
    "findings": 1,
    "issues_created": 0,
    "duplicates_skipped": 1,
    "reconciled": 0,
    "errors": 0,
    "elapsed_seconds": 5.77
  },
  "total_issues_created": 0,
  "last_error_type": null
}
```

- Cross-environment idempotency: the container read the same ClickHouse ledger and reported issue #1 as DUPLICATE.
- In-container Gemini triage through the real entrypoint (credentials from env JSON → 0600 temp file): `ok=True risk=high`.
- Fixed after this run: evidence file write is skipped in containers (was a harmless permission warning).
