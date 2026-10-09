"""Semgrep subprocess runner and normalizer. Semgrep output is untrusted data."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path, PurePosixPath

from .config import PINNED_RULE_IDS, RULES_FILE
from .models import Finding

MAX_SNIPPET_LINES = 20
MAX_SNIPPET_CHARS = 1500
MAX_MESSAGE_CHARS = 1000
MAX_FINDINGS = 200
# Per-file problems that do not invalidate the rest of the scan.
NONFATAL_ERROR_MARKERS = ("Syntax error", "Lexical error", "PartialParsing", "Timeout", "Other syntax error")

_SEVERITY_MAP = {
    "ERROR": "ERROR", "HIGH": "ERROR", "CRITICAL": "ERROR",
    "WARNING": "WARNING", "MEDIUM": "WARNING",
    "INFO": "INFO", "LOW": "INFO",
}
_SECRET_RE = re.compile(
    r"(?i)((?:api[_-]?key|secret|token|passw(?:or)?d|pwd)\s*[:=]\s*)(['\"]?)[^\s'\"]{4,}\2"
    r"|(sk-[A-Za-z0-9_-]{16,})|(gh[pousr]_[A-Za-z0-9]{20,})|(mongodb(?:\+srv)?://[^\s'\"]+)"
)


class ScanError(RuntimeError):
    """Scan failed. Never treat as 'clean'."""


class PathSafetyError(ValueError):
    pass


def redact(text: str) -> str:
    def _sub(m: re.Match) -> str:
        if m.group(1):
            return f"{m.group(1)}{m.group(2)}[REDACTED]{m.group(2)}"
        return "[REDACTED]"
    return _SECRET_RE.sub(_sub, text)


def safe_relative_path(checkout: Path, reported: str) -> str:
    """Return a canonical repo-relative POSIX path, or raise PathSafetyError."""
    if not reported or "\x00" in reported:
        raise PathSafetyError("empty path")
    p = PurePosixPath(reported.replace("\\", "/"))
    if p.is_absolute() or reported.startswith("/") or re.match(r"^[A-Za-z]:", reported):
        raise PathSafetyError(f"absolute path rejected: {reported!r}")
    if any(part == ".." for part in p.parts):
        raise PathSafetyError(f"traversal rejected: {reported!r}")
    parts = [x for x in p.parts if x not in (".", "")]
    if not parts or parts[0] == ".git":
        raise PathSafetyError(f"path rejected: {reported!r}")
    root = checkout.resolve()
    full = (root / Path(*parts)).resolve()  # resolves symlinks
    if not full.is_relative_to(root):
        raise PathSafetyError(f"path escapes checkout: {reported!r}")
    if not full.is_file():
        raise PathSafetyError(f"not a regular file in checkout: {reported!r}")
    return "/".join(parts)


def normalize_rule_id(check_id: str) -> str | None:
    """Semgrep prefixes rule IDs with the config path; map back to pinned IDs."""
    for rid in PINNED_RULE_IDS:
        if check_id == rid or check_id.endswith("." + rid):
            return rid
    return None


def normalize_snippet(text: str) -> str:
    return "\n".join(line.strip() for line in text.splitlines() if line.strip())


def read_snippet(checkout: Path, rel_path: str, start: int, end: int) -> str:
    end = min(end, start + MAX_SNIPPET_LINES - 1)
    with open(checkout.resolve() / rel_path, encoding="utf-8", errors="replace") as fh:
        lines = fh.read().splitlines()
    chunk = "\n".join(lines[start - 1:end])
    return redact(chunk)[:MAX_SNIPPET_CHARS]


def compute_fingerprint(repo: str, rule_id: str, path: str, norm_snippet: str, occurrence: int) -> str:
    # start_line deliberately excluded (SPEC rev 2).
    raw = f"{repo}|{rule_id}|{path}|{norm_snippet}|{occurrence}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def classify_errors(errors: list) -> tuple[list[str], list[str]]:
    """Split Semgrep errors into (fatal, warnings)."""
    fatal, warnings = [], []
    for err in errors or []:
        etype = err.get("type")
        etype_s = json.dumps(etype) if not isinstance(etype, str) else etype
        msg = f"{etype_s}: {str(err.get('message', ''))[:200]}"
        has_path = bool(err.get("path") or err.get("spans"))
        if any(m in etype_s for m in NONFATAL_ERROR_MARKERS) and has_path:
            warnings.append(msg)
        elif err.get("level") == "warn":
            warnings.append(msg)
        else:
            fatal.append(msg)
    return fatal, warnings


def parse_semgrep_json(raw: str, checkout: Path, repo: str, commit_sha: str) -> tuple[list[Finding], list[str]]:
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError) as e:
        raise ScanError(f"semgrep output is not valid JSON: {e}") from e
    if not isinstance(data, dict) or not isinstance(data.get("results"), list):
        raise ScanError("semgrep JSON missing 'results'")
    fatal, warnings = classify_errors(data.get("errors", []))
    if fatal:
        raise ScanError("semgrep fatal errors: " + "; ".join(fatal[:3]))

    staged = []
    for r in data["results"][:MAX_FINDINGS]:
        rule_id = normalize_rule_id(str(r.get("check_id", "")))
        if rule_id is None:
            warnings.append(f"ignored non-pinned rule {r.get('check_id')!r}")
            continue
        try:
            rel = safe_relative_path(checkout, str(r.get("path", "")))
            start = int(r["start"]["line"])
            end = int(r["end"]["line"])
        except (PathSafetyError, KeyError, TypeError, ValueError) as e:
            warnings.append(f"rejected result: {e}")
            continue
        if start < 1 or end < start:
            warnings.append(f"rejected result: bad line range {start}-{end}")
            continue
        extra = r.get("extra") or {}
        sev = _SEVERITY_MAP.get(str(extra.get("severity", "")).upper())
        if sev is None:
            warnings.append(f"rejected result: unknown severity {extra.get('severity')!r}")
            continue
        snippet = read_snippet(checkout, rel, start, end)
        staged.append((rule_id, rel, start, end, sev, str(extra.get("message", "")), snippet))

    staged.sort(key=lambda s: (s[1], s[2], s[0]))
    seen: dict[tuple, int] = {}
    findings = []
    for rule_id, rel, start, end, sev, message, snippet in staged:
        norm = normalize_snippet(snippet)
        key = (rule_id, rel, norm)
        occ = seen.get(key, 0)
        seen[key] = occ + 1
        findings.append(Finding(
            rule_id=rule_id, path=rel, start_line=start, end_line=end, severity=sev,
            message=redact(message)[:MAX_MESSAGE_CHARS], snippet=snippet,
            commit_sha=commit_sha, repo=repo,
            fingerprint=compute_fingerprint(repo, rule_id, rel, norm, occ),
        ))
    return findings, warnings


def semgrep_bin() -> str:
    local = Path(sys.executable).parent / "semgrep"
    return str(local) if local.exists() else (shutil.which("semgrep") or "semgrep")


def run_semgrep(checkout: Path, timeout: int) -> str:
    cmd = [
        semgrep_bin(), "scan", "--config", str(RULES_FILE), "--json",
        "--metrics=off", "--disable-version-check", "--timeout", "30",
        "--max-target-bytes", "1000000", "--exclude", ".git", "--exclude", ".venv",
        "--exclude", "node_modules", ".",
    ]
    env = {k: v for k, v in os.environ.items() if k in ("PATH", "HOME", "LANG", "LC_ALL", "TMPDIR")}
    env["SEMGREP_SEND_METRICS"] = "off"
    try:
        proc = subprocess.run(cmd, cwd=checkout, capture_output=True, text=True,
                              timeout=timeout, shell=False, env=env)
    except subprocess.TimeoutExpired as e:
        raise ScanError(f"semgrep timed out after {timeout}s") from e
    except FileNotFoundError as e:
        raise ScanError("semgrep not found on PATH") from e
    if not proc.stdout.strip():
        raise ScanError(f"semgrep produced no JSON (exit {proc.returncode}): {proc.stderr[-300:]}")
    return proc.stdout


def scan(checkout: Path, repo: str, commit_sha: str, timeout: int) -> tuple[list[Finding], list[str]]:
    return parse_semgrep_json(run_semgrep(checkout, timeout), checkout, repo, commit_sha)
