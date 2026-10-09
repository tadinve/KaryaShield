# Mender evidence: AI patch proposal + sandbox verification (read-only)

- When: 2026-10-09 14:41 PDT · `python -m karyashield.cli mend` · no repo writes, nothing executed

```
[MEND] tadinve/KaryaShield@9501f0442637: 1 finding(s); LLM=Gemini gemini-3.6-flash (Gemini API)

=== karyashield.python.subprocess-shell-true demo/target_seed/app/ping_tool.py:8 -> PATCH VERIFIED (8.8s)
  ✓ diff confined to demo/target_seed/app/ping_tool.py: 2 changed line(s)
  ✓ patched file parses (ast.parse, never executed)
  ✓ sandbox Semgrep re-scan: karyashield.python.subprocess-shell-true 1 → 0
  ✓ no new findings introduced
explanation: Replaced shell execution via string interpolation with a list of command arguments passed to subprocess.run, eliminating shell=True and preventing command injection.
--- a/demo/target_seed/app/ping_tool.py
+++ b/demo/target_seed/app/ping_tool.py
@@ -6,3 +6,3 @@
 def ping_host(host):
     # BAD: user-controlled host is interpolated into a shell command.
-    return subprocess.run(f"ping -c 1 {host}", shell=True, capture_output=True)
+    return subprocess.run(["ping", "-c", "1", host], capture_output=True)

```
