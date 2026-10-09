# M2 evidence: real LLM structured triage of a real Semgrep finding

- When: 2026-10-09 12:38 PDT (read-only: no ledger or GitHub writes)
- Provider: Gemini `gemini-2.5-flash` on Vertex AI (google-genai, ADC), `response_schema=Triage`, temperature 0
- Fingerprint is stable across commits be44ef5 → 0466b57 (`1848c95b27df0133`), as designed

```
live checkout SHA: 0466b575ca6732bde0464600ca031631bbba1132
findings: 1
finding karyashield.python.subprocess-shell-true demo/target_seed/app/ping_tool.py:8 fp=1848c95b27df0133
provider: Gemini gemini-2.5-flash on Vertex AI  ok=True  elapsed=8.9s
{
  "is_actionable": true,
  "risk_level": "high",
  "summary": "The application executes a shell command constructed with user-controlled input via `subprocess.run(shell=True)`, leading to OS command injection.",
  "why_it_matters": "Using `shell=True` with `subprocess.run` allows the shell to interpret the command string. If any part of this string, like the `host` variable, comes from untrusted external input, an attacker can inject arbitrary shell commands. This can lead to severe consequences, including data exfiltration, unauthorized system access, denial of service, or complete system compromise, depending on the privileges of the running process.",
  "recommended_fix": "Avoid using `shell=True` when executing external commands, especially when any part of the command string is derived from user input. Instead, pass the command and its arguments as a list to `subprocess.run`. This bypasses the shell and prevents command injection. For this specific case, modify the code to: `subprocess.run(['ping', '-c', '1', host], capture_output=True)`. If `shell=True` is strictly necessary, ensure all user-supplied input is properly sanitized and escaped for the shell, though this is generally more complex and error-prone than avoiding `shell=True`.",
  "confidence": 0.9
}
```
