# KaryaShield Status
- Updated at: 2026-10-09 11:44 PDT
- Milestone completed: M1 PASS (live fetch + real Semgrep). M0 partial: AkashML, ClickHouse and the issue label aren't verified yet.
- Last actual command: live `fetch_checkout` + `scan` against tadinve/KaryaShield@be44ef5
- Result: PASS, 1 real finding (subprocess-shell-true, demo/target_seed/app/ping_tool.py:8), checkout SHA == live SHA. Evidence: demo/evidence/m1_scan.md
- Real sponsor integrations working: Semgrep (REAL, live repo) / Akash (AkashML) NOT YET VERIFIED / ClickHouse NOT YET VERIFIED
- GitHub issue URL: NOT YET
- Remaining blocker: (1) `.env` with AKASHML_API_KEY + CLICKHOUSE_HOST/PASSWORD; (2) `karyashield` label on tadinve/KaryaShield; (3) `init-db` for ClickHouse schema
- Next single action: builder fills `.env`, creates label, runs init-db; then run `doctor`
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
