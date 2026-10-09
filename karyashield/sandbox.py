"""Sandboxed differential exploit test for a proposed patch.

The only place KaryaShield executes code. Defense in depth, not a VM:
- separate `python -I` process, cwd = a fresh temp dir holding ONLY the target module + harness
- empty environment (no tokens, keys or passwords), HOME = the temp dir
- rlimits: CPU seconds, file size, address space (where supported); hard wall-clock timeout
- a PEP 578 audit hook installed before the module is imported that BLOCKS network sockets,
  process spawning (subprocess, os.system/exec/spawn/fork), ctypes, and writes outside the sandbox
- rule-specific harness: dangerous sinks are replaced with recorders, so the exploit is observed,
  never carried out

A test PASSES only if the ORIGINAL code exhibits the vulnerability (the exploit is reproduced)
AND the PATCHED code does not, while still exercising the function.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

from pydantic import BaseModel

TIMEOUT_S = 15

PAYLOADS = {
    "karyashield.python.subprocess-shell-true": "127.0.0.1; echo KARYASHIELD_PWNED",
    "karyashield.python.eval-non-literal": "__import__('os').system('echo KARYASHIELD_PWNED')",
}

HARNESS = r'''
import builtins, importlib.util, json, os, sys
SANDBOX = os.path.realpath(os.getcwd())
RULE, MODULE, PAYLOAD = sys.argv[1], sys.argv[2], sys.argv[3]
events, calls = [], []

BLOCK_PREFIX = ("socket.", "subprocess.", "os.system", "os.exec", "os.posix_spawn", "os.spawn",
                "os.fork", "os.kill", "ctypes.", "pty.", "shutil.rmtree", "os.remove", "os.unlink")
def hook(event, args):
    if event.startswith(BLOCK_PREFIX):
        events.append(event)
        raise PermissionError("sandbox blocked " + event)
    if event == "exec" and IN_CALL[0]:
        events.append("exec(dynamic code)")
        raise PermissionError("sandbox blocked dynamic code execution")
    if event == "open" and args and isinstance(args[0], str) and len(args) > 1 and args[1] and any(c in str(args[1]) for c in "wax+"):
        if not os.path.realpath(args[0]).startswith(SANDBOX):
            events.append("open-write-outside")
            raise PermissionError("sandbox blocked write outside sandbox")
IN_CALL = [False]

import subprocess
class _Done:
    returncode = 0; stdout = b""; stderr = b""
def _recorder(name):
    def rec(*a, **kw):
        cmd = a[0] if a else kw.get("args")
        calls.append({"fn": name, "shell": bool(kw.get("shell", False)), "argv_is_list": isinstance(cmd, (list, tuple)),
                      "payload_intact": PAYLOAD in (cmd if isinstance(cmd, str) else list(map(str, cmd or [])))})
        return _Done()
    return rec
for n in ("run", "call", "check_call", "check_output", "Popen"):
    setattr(subprocess, n, _recorder(n))

sys.addaudithook(hook)
spec = importlib.util.spec_from_file_location("target", MODULE)
mod = importlib.util.module_from_spec(spec)
result = {"import_error": None, "called": [], "errors": []}
try:
    spec.loader.exec_module(mod)
except Exception as e:
    result["import_error"] = f"{type(e).__name__}: {e}"
import inspect
for name, fn in sorted(vars(mod).items()):
    if inspect.isfunction(fn) and fn.__module__ == "target":
        params = [p for p in inspect.signature(fn).parameters.values() if p.default is p.empty]
        if len(params) != 1:
            continue
        IN_CALL[0] = True
        try:
            fn(PAYLOAD)
        except Exception as e:
            result["errors"].append(f"{name}: {type(e).__name__}")
        finally:
            IN_CALL[0] = False
        result["called"].append(name)
if RULE.endswith("subprocess-shell-true"):
    vuln = any(c["shell"] or not c["argv_is_list"] for c in calls) or bool(events)
    exercised = bool(calls)
else:
    vuln = bool(events)
    exercised = bool(result["called"])
result.update(vulnerable=vuln, exercised=exercised, blocked_events=events, sink_calls=calls)
print("KARYASHIELD_RESULT " + json.dumps(result))
'''


class SandboxRun(BaseModel):
    vulnerable: bool | None = None
    exercised: bool = False
    detail: str = ""


class SandboxTest(BaseModel):
    passed: bool
    summary: str
    original: SandboxRun
    patched: SandboxRun


def _limits():  # runs in the child before exec
    import resource
    for res, val in ((resource.RLIMIT_CPU, 5), (resource.RLIMIT_FSIZE, 1 << 20)):
        try:
            resource.setrlimit(res, (val, val))
        except (ValueError, OSError):
            pass
    try:
        resource.setrlimit(resource.RLIMIT_AS, (1 << 30, 1 << 30))
    except (ValueError, OSError):
        pass  # not enforceable on macOS; fine on Linux (Akash)


def _run(rule_id: str, rel_path: str, content: str) -> SandboxRun:
    with tempfile.TemporaryDirectory(prefix="karyashield-sandbox-") as sb:
        mod = Path(sb) / Path(rel_path).name
        mod.write_text(content, encoding="utf-8")
        (Path(sb) / "harness.py").write_text(HARNESS, encoding="utf-8")
        try:
            p = subprocess.run([sys.executable, "-I", "harness.py", rule_id, str(mod), PAYLOADS[rule_id]],
                               cwd=sb, env={"PATH": "/usr/bin:/bin", "HOME": sb, "LANG": "C.UTF-8"},
                               capture_output=True, text=True, timeout=TIMEOUT_S, preexec_fn=_limits)
        except subprocess.TimeoutExpired:
            return SandboxRun(detail="timeout")
        line = next((ln for ln in p.stdout.splitlines() if ln.startswith("KARYASHIELD_RESULT ")), None)
        if line is None:
            return SandboxRun(detail=f"no result (exit {p.returncode}): {p.stderr[-200:]}")
        r = json.loads(line.split(" ", 1)[1])
        detail = ", ".join(filter(None, [
            f"blocked: {sorted(set(r['blocked_events']))}" if r["blocked_events"] else "",
            f"sink calls: {[(c['fn'], 'shell=True' if c['shell'] else 'argv list' if c['argv_is_list'] else 'string') for c in r['sink_calls']]}"
            if r["sink_calls"] else "",
            f"import error: {r['import_error']}" if r["import_error"] else ""]))
        return SandboxRun(vulnerable=r["vulnerable"], exercised=r["exercised"], detail=detail or "no sink reached")


def differential_test(rule_id: str, rel_path: str, original: str, patched: str) -> SandboxTest:
    if rule_id not in PAYLOADS:
        return SandboxTest(passed=False, summary="no sandbox test for this rule",
                           original=SandboxRun(), patched=SandboxRun())
    o, p = _run(rule_id, rel_path, original), _run(rule_id, rel_path, patched)
    passed = o.vulnerable is True and p.vulnerable is False and p.exercised
    if passed:
        summary = "exploit reproduced on original, blocked on patched"
    elif o.vulnerable is not True:
        summary = "could not reproduce the vulnerability on the original"
    elif p.vulnerable is not False:
        summary = "patched code is still exploitable"
    else:
        summary = "patched code was not exercised"
    return SandboxTest(passed=passed, summary=summary, original=o, patched=p)
