# KaryaShield Status
- Updated at: 2026-10-09 11:52 PDT
- Milestone completed: M0 partial (local toolchain + code skeleton + unit tests). M0 NOT complete: Atlas, OpenAI, and the GitHub target aren't verified yet.
- Last actual command: `.venv/bin/python -m pytest -q`
- Result: PASS, 50 passed in 1.57s. Includes a real local Semgrep 1.180.0 scan of both seeded fixtures. GitHub/AkashML/ClickHouse mocked in the other tests.
- Real sponsor integrations working: Semgrep (local, real) / Akash (AkashML) NOT YET VERIFIED / ClickHouse NOT YET VERIFIED
- GitHub issue URL: NOT YET
- Remaining blocker: (1) `.env` with AKASHML_API_KEY + CLICKHOUSE_HOST/PASSWORD; (2) builder pushes KaryaShield code to tadinve/KaryaShield (now the demo target) and creates the `karyashield` label (remote writes, need builder authorization)
- Next single action: builder commits+pushes, creates label, fills `.env`; then run `doctor`
- Submission state: NOT SUBMITTED

## Log
- 11:04 venv (Python 3.12) + deps installed: semgrep 1.180.0, openai 2.14.0, pymongo 4.18.3, pydantic 2.14.0
- 11:08 Real Semgrep scan of local fixtures: 2 findings; confirmed CE returns `"requires login"` for `extra.lines` / `extra.fingerprint` → snippets read from checkout
- 11:10 pytest: 45 passed
- 11:11 Local demo target repo staged at ../karyashield-demo-target (1 commit, flaw #1). Not pushed.
- 11:15 Builder chose tadinve/KaryaShield as demo target. Removed ../karyashield-demo-target. Flaw #2 parked as demo/live_flaw2_calc.py.txt. Real full-tree Semgrep scan: exactly 1 finding (flaw #1). pytest: 45 passed.
- 11:35 Builder switched LLM to Gemini (implemented, 48 tests passed).
- 11:40 Event page checked: sponsors are ClickHouse, Pi, Akash, Guild.ai, Semgrep, Senso.ai. MongoDB/OpenAI/Gemini don't count. Builder chose Akash + ClickHouse.
- 11:50 Rewrote triage → AkashML (OpenAI-compatible, base URL verified: /v1/models returns 401 without key), ledger → ClickHouse (ReplacingMergeTree + events + scan_runs), added init-db + single-writer lock. pytest: 50 passed.
