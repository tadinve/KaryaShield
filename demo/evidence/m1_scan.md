# M1 evidence: live GitHub fetch + real Semgrep scan

- When: 2026-10-09 11:44 PDT
- Command: `fetch_checkout` + `scanner.scan` via `.venv/bin/python` (read-only; no writes)
- Live remote SHA (gh api): `be44ef5d49334fd7df6117e8aa8fbe4061dd390b`
- Checkout HEAD: same SHA (verified)
- Semgrep 1.180.0, pinned `rules/karyashield.yml`, `--metrics=off`
- Result: 1 finding, 0 warnings, 5.4s total

| Rule | Location | Severity | Fingerprint (prefix) |
|---|---|---|---|
| `karyashield.python.subprocess-shell-true` | `demo/target_seed/app/ping_tool.py:8` | ERROR | `1848c95b27df0133` |

Snippet (read from checkout; Semgrep CE returns "requires login" for `extra.lines`):
```
return subprocess.run(f"ping -c 1 {host}", shell=True, capture_output=True)
```
