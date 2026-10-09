# KaryaShield Status
- Updated at: 2026-10-09 13:02 PDT
- Milestone completed: M1 PASS (11:44), M2 PASS (12:38, Gemini on Vertex AI). M0 partial: ClickHouse service + label pending.
- Last actual command: live fetch + Semgrep + `triage_finding` (Vertex Gemini) on tadinve/KaryaShield@0466b57
- Result: PASS. Schema-valid triage (risk=high, actionable, confidence 0.9) in 8.9s. Evidence: demo/evidence/m2_triage.md
- Real integrations verified live: Semgrep ✅ · LLM (Gemini/Vertex, non-sponsor) ✅ · ClickHouse ❌ (have Postgres host, need ClickHouse service) · Akash Network ❌ (not deployed)
- GitHub issue URL: NOT YET
- Remaining blocker: (1) real ClickHouse service host/password in .env; (2) `karyashield` label; (3) Akash credits. Risk: GCP project is a Qwiklabs lab (may expire; service-account keys for the container may be blocked)
- Next single action: builder creates a ClickHouse (not Postgres) service and updates .env; then init-db
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
- 13:01 Real ClickHouse service (GCP us-central1) reachable; fixed TLS CERTIFICATE_VERIFY_FAILED (python.org macOS build lacks root CAs) by passing certifi CA bundle. doctor: ClickHouse ping PASS, LLM PASS; schema + label pending builder authorization.
