# KaryaShield Status
- Updated at: 2026-10-09 13:01 PDT
- Milestone completed: M0 PASS (doctor ALL PASS), M1 PASS, M2 PASS, real e2e dry run PASS (13:00). M3 partial: ClickHouse reads verified, inserts pending first write run.
- Last actual command: `python -m karyashield.cli run --once --dry-run`
- Result: PASS. 1 finding → WOULD_CREATE, 0 errors, 12.9s; ClickHouse incidents/events/scan_runs = 0 rows (no writes). Evidence: demo/evidence/m3_dryrun.md
- Real integrations verified live: Semgrep ✅ · LLM (Gemini/Vertex, non-sponsor) ✅ · ClickHouse ✅ connect+schema+reads (inserts pending) · Akash Network ❌ (not deployed)
- GitHub issue URL: NOT YET
- Remaining blocker: builder OK to set KARYASHIELD_ENABLE_WRITES=true for the first real issue (M4). Then Akash credits for M7. Risk: Qwiklabs GCP project may expire.
- Next single action: builder approves write run → `run --once` (issue #1), then rerun for duplicate proof (M5)
- Submission state: NOT SUBMITTED

## Log
- 11:04 venv (Python 3.12) + deps installed: semgrep 1.180.0, openai 2.14.0, pymongo 4.18.3, pydantic 2.14.0
- 11:08 Real Semgrep scan of local fixtures: 2 findings; confirmed CE returns `"requires login"` for `extra.lines` / `extra.fingerprint` → snippets read from checkout
- 11:10 pytest: 45 passed
- 11:11 Local demo target repo staged at ../karyashield-demo-target (1 commit, flaw #1). Not pushed.
- 11:15 Builder chose tadinve/KaryaShield as demo target. Removed ../karyashield-demo-target. Flaw #2 parked as demo/live_flaw2_calc.py.txt. Real full-tree Semgrep scan: exactly 1 finding (flaw #1). pytest: 45 passed.
- ~11:25 Builder switched LLM to Gemini (implemented, 48 tests passed).
- ~11:28 Event page checked: sponsors are ClickHouse, Pi, Akash, Guild.ai, Semgrep, Senso.ai. MongoDB/OpenAI/Gemini don't count. Builder chose Akash + ClickHouse.
- ~11:35 Rewrote triage → AkashML (OpenAI-compatible, base URL verified: /v1/models returns 401 without key), ledger → ClickHouse (ReplacingMergeTree + events + scan_runs), added init-db + single-writer lock. pytest: 50 passed.
- ~11:38 Commits 35df93e (spec) + a452729 (M0 skeleton) pushed to origin/main.
- 11:44 M1 PASS: live GitHub fetch (SHA verified) + real Semgrep scan → 1 finding. Evidence demo/evidence/m1_scan.md. Still blocked on .env keys (all 3 empty at 11:43).
- 12:20 ClickHouse creds received but host is *.pg.clickhouse.cloud (managed Postgres; only :5432 open, :8443/:9440 closed). ClickHouse NOT verified.
- 12:35 Spec rev 5: Akash Network hosts the worker (Docker + SDL); triage via configurable OpenAI-compatible LLM (non-sponsor); milestones M6 container, M7 Akash.
- 12:38 M2 PASS: real Gemini 2.5 Flash (Vertex AI, project qwiklabs-gcp-02-…) triage of the real finding; evidence demo/evidence/m2_triage.md. LLM_PROVIDER=vertex|openai_compat added.
- ~13:00 Real ClickHouse service (GCP us-central1) reachable; fixed TLS CERTIFICATE_VERIFY_FAILED (python.org macOS build lacks root CAs) by passing certifi CA bundle. doctor: ClickHouse ping PASS, LLM PASS; schema + label pending builder authorization.
- ~13:00 Label `karyashield` created + init-db (builder OK). doctor: ALL PASS. Real e2e dry run: WOULD_CREATE, ClickHouse 0 rows. Fixed truncated code fence in issue body; issue heading names the model.
