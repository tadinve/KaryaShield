# KaryaShield — Autonomous GitHub Security Defender

> **Semgrep detects. ClickHouse remembers. Akash runs the defender.**
> The AI proposes; deterministic policy disposes.

Built solo on 2026-10-09 for the [Cyberdefense Hackathon](https://tokensand.com/cyberhack) (San Francisco).

## The problem

Security teams can't review every commit, and AI agents that "fix security" tend to hallucinate findings or take actions nobody authorized. We wanted an agent that watches a live repo around the clock and takes a real action on the web, but only on **verifiable evidence**, **never twice for the same flaw**, and **never on the model's say-so**.

## What it does (30 seconds)

A KaryaShield worker runs on **Akash Network** and watches a GitHub repo. On every new commit it:

1. fetches the exact commit (verified SHA, git hooks disabled, repo code never executed)
2. scans it with **Semgrep** using a pinned ruleset (command injection and `eval` injection)
3. asks an LLM to explain the finding and suggest a fix (advisory only)
4. runs a **deterministic policy gate**: write switch, repo allowlist, SHA match, pinned rule, severity, valid triage, per-run cap
5. checks **ClickHouse** and GitHub, so the same flaw is never filed twice
6. **proposes a fix and verifies it in a sandbox** (CodeMender-style): the patched file must parse, a Semgrep re-scan must show the finding gone, no new findings may appear, and nothing is ever executed
7. files a **real GitHub issue** with evidence, a permalink, the AI assessment, the verified patch (suggested, never applied) and a hidden fingerprint marker
8. records the incident, an audit event and run analytics in **ClickHouse**

Live proof:
- Issue filed autonomously: **[tadinve/KaryaShield#1](https://github.com/tadinve/KaryaShield/issues/1)**
- The worker runs on Akash (deployment `dseq 1791582426373`), with a live status page at [http://jp4ikhmqk9alt94bi0g5c68d80.ingress.h6i-dedicated.eu-se-1.digitalfrontier.so/status](http://jp4ikhmqk9alt94bi0g5c68d80.ingress.h6i-dedicated.eu-se-1.digitalfrontier.so/status). It scanned a new commit about 25 seconds after the push ([evidence](demo/evidence/m7_akash.md)).
- The patch is proposed by the model and verified statically in a sandbox ([evidence](demo/evidence/mender.md)): flaw #1 `shell=True` → argument list, flaw #2 `eval` → `ast.literal_eval`.

## Sponsor tools

| Sponsor | What it does in KaryaShield | Proof |
|---|---|---|
| **Semgrep** | Deterministic detection: pinned local rules in [`rules/karyashield.yml`](rules/karyashield.yml), JSON output, `--metrics=off` | [M1](demo/evidence/m1_scan.md) |
| **Akash Network** | Hosts the always-on worker: a Docker image deployed from an SDL through the Akash Console API, 1 CPU replica | [M7](demo/evidence/m7_akash.md) |
| **ClickHouse** | Incident ledger (`ReplacingMergeTree`), audit trail, and `scan_runs` analytics including *where* each run executed (`local` vs `akash`) | [M4/M5](demo/evidence/m4_m5_issue_and_dedup.md) |

Not counted as sponsor tools: **Gemini** (`gemini-3.6-flash`, the triage LLM, swappable through `LLM_PROVIDER`) and **GitHub** (the data source and action surface).

## Architecture

```
                      Akash Network (decentralized compute)
 ┌─────────────────────────────────────────────────────────────────────┐
 │ karyashield worker (1 replica, CPU)  ghcr.io/tadinve/karyashield    │
 │  poll live SHA every 20s → on new commit:                           │
 │   FETCH → SCAN (Semgrep) → NORMALIZE → TRIAGE (LLM) → POLICY GATE    │
 │   → RESERVE/RECONCILE → CREATE ISSUE → RECORD → REPORT              │
 └──────┬─────────────────────────┬──────────────────────┬────────────┘
        v                         v                      v
  GitHub repo + issues      Gemini (advisory)      ClickHouse Cloud
  (labeled, marker)         JSON schema triage     incidents · events · scan_runs
```

**Trust boundaries:**
- Repository contents and Semgrep output are untrusted data, never instructions.
- The model can explain a finding or veto it. It cannot choose the repo, call tools or authorize a write.
- Model confidence never gates anything; a pinned-rule match and severity do.

**Duplicate prevention** (ClickHouse has no unique keys, so it's layered):
1. A single worker replica.
2. A reserve-then-verify step in the ledger.
3. The authoritative check: list every GitHub issue labeled `karyashield` and match the hidden `<!-- karyashield:fingerprint=… -->` marker before any create.

**Crash safety:**
- A crash between creating the issue and updating the ledger is reconciled from that marker on the next cycle.
- A create that times out is marked `write_uncertain` and never retried blindly.

**Fingerprint** = `sha256(repo | rule | path | normalized snippet | occurrence)`. It deliberately excludes the line number, so unrelated edits don't create duplicates.

## Judging criteria

| Criterion | How KaryaShield addresses it |
|---|---|
| Autonomy | An unattended worker on Akash reacts to pushes with no human in the loop |
| Idea | Evidence-grounded security triage that ends in a real, tracked issue |
| Technical implementation | Typed contracts, deterministic gate, idempotent state machine, crash reconciliation, sandbox-verified patches, 58 tests |
| Tool use | Semgrep, Akash and ClickHouse each do real work, with evidence for each |
| Presentation | A live push of a new flaw → the Akash worker files a new issue → ClickHouse records it → the next cycle creates no duplicate |

## Run it

```bash
python3.12 -m venv .venv && .venv/bin/python -m pip install -r requirements.txt
cp .env.example .env            # fill keys locally; never commit .env
gh label create karyashield --repo OWNER/REPO
.venv/bin/python -m karyashield.cli init-db     # ClickHouse tables
.venv/bin/python -m karyashield.cli doctor      # all checks must PASS
.venv/bin/python -m karyashield.cli run --once --dry-run   # read-only everywhere
.venv/bin/python -m karyashield.cli run --once             # writes only if KARYASHIELD_ENABLE_WRITES=true
.venv/bin/python -m karyashield.cli watch --max-cycles 3   # bounded local monitoring
.venv/bin/python -m karyashield.cli worker                 # unbounded loop + status server (container)
.venv/bin/python -m karyashield.cli mend                   # read-only: propose + sandbox-verify patches
.venv/bin/python -m karyashield.cli status                 # latest incidents
```

Deploy to Akash: build with `docker buildx build --platform linux/amd64 …`, push to a public registry, fill a **local, gitignored** copy of [`deploy/akash.sdl.yaml`](deploy/akash.sdl.yaml), then run `python deploy/akash_deploy.py deploy deploy/akash.sdl.local.yaml`.

Akash deployment env vars are visible to the provider, so the worker gets narrowly scoped credentials:
- a fine-grained GitHub token for this one repo, with issues write and a 1-day expiry
- a dedicated API key for the model

## Evidence (real services, not mocks)

| Milestone | Evidence |
|---|---|
| M1 live Semgrep scan | [m1_scan.md](demo/evidence/m1_scan.md) |
| M2 real LLM structured triage | [m2_triage.md](demo/evidence/m2_triage.md) |
| End-to-end dry run (zero writes) | [m3_dryrun.md](demo/evidence/m3_dryrun.md) |
| M4/M5 real issue + no duplicate | [m4_m5_issue_and_dedup.md](demo/evidence/m4_m5_issue_and_dedup.md) |
| M6 container | [m6_container.md](demo/evidence/m6_container.md) |
| M7 worker on Akash | [m7_akash.md](demo/evidence/m7_akash.md) |
| Sandbox-verified patch | [mender.md](demo/evidence/mender.md) |

Tests: `.venv/bin/python -m pytest -q` → **58 passed**. They cover path traversal and symlink escapes, the allowlist, the write gate, dry runs that write nothing, idempotency, crash reconciliation, `write_uncertain`, the per-run cap, fingerprint stability, model failure modes, and patch verification (good patch verified; cosmetic, syntax-error, new-vulnerability and oversized patches rejected; repo untouched). Unit tests use fakes; live integrations are proven only by the evidence files above.

## Limitations (honest)

- **Coverage:** exactly two pinned Semgrep rules (CWE-78 `subprocess(..., shell=True)` and CWE-95 `eval` on non-literals). This is not a general scanner.
- **Single writer:** duplicate prevention assumes one worker replica, because ClickHouse has no compare-and-set. The GitHub marker check is the backstop.
- **Fingerprints:** renaming a file or editing the flagged line produces a new fingerprint.
- **Patch verification is static:** the patched file must parse and Semgrep must stop reporting the finding. The repo's tests are not run, because KaryaShield never executes repo code. A verified patch is a suggestion for human review, never applied automatically.
- **Demo target:** the target repo is this repo, and its seeded flaws (`demo/target_seed/`) are intentionally vulnerable fixtures that are never executed.
- Not production-ready: no autonomous patching, no PRs, no multi-tenant support.

## Future work

- Ground the triage in verified remediation guidance (Senso.ai), with citations in the issue.
- Serve the LLM on an Akash GPU lease, so Akash covers inference as well as hosting.
- Open draft PRs from verified patches, with human approval only.
- More rules, and more repos per worker.

## Built during the hackathon

All code, rules, tests, the Dockerfile, the SDL and the deploy script were written on 2026-10-09. External services used as-is: GitHub, Semgrep CE, ClickHouse Cloud, Akash Console, and the Gemini API. The design log is in [SPEC.md](SPEC.md), and the timestamped progress log is in [STATUS.md](STATUS.md).
