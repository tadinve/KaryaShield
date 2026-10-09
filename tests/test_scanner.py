import json
import os
import shutil
from pathlib import Path

import pytest

from karyashield.scanner import (
    PathSafetyError, ScanError, classify_errors, parse_semgrep_json, safe_relative_path, scan,
)
from tests.conftest import REPO, SHA

ROOT = Path(__file__).resolve().parent.parent


def _result(path="app/x.py", line=2, check="rules.karyashield.python.subprocess-shell-true", sev="ERROR"):
    return {"check_id": check, "path": path, "start": {"line": line}, "end": {"line": line},
            "extra": {"severity": sev, "message": "shell=True", "lines": "requires login"}}


@pytest.fixture
def checkout(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "x.py").write_text("import subprocess\nsubprocess.run(cmd, shell=True)\n")
    return tmp_path


def test_normalization(checkout):
    raw = json.dumps({"results": [_result()], "errors": []})
    findings, warnings = parse_semgrep_json(raw, checkout, REPO, SHA)
    assert len(findings) == 1 and not warnings
    f = findings[0]
    assert f.rule_id == "karyashield.python.subprocess-shell-true"
    assert (f.path, f.start_line, f.severity, f.message) == ("app/x.py", 2, "ERROR", "shell=True")
    assert f.snippet == "subprocess.run(cmd, shell=True)"  # read from checkout, not "requires login"
    assert len(f.fingerprint) == 64


@pytest.mark.parametrize("raw", ["", "not json", "{}", json.dumps({"results": None})])
def test_malformed_json_fails(checkout, raw):
    with pytest.raises(ScanError):
        parse_semgrep_json(raw, checkout, REPO, SHA)


def test_fatal_vs_nonfatal_errors(checkout):
    nonfatal = {"type": "Syntax error", "level": "warn", "path": "app/bad.py", "message": "x"}
    findings, warnings = parse_semgrep_json(
        json.dumps({"results": [_result()], "errors": [nonfatal]}), checkout, REPO, SHA)
    assert len(findings) == 1 and warnings
    fatal = {"type": "InvalidRuleSchemaError", "level": "error", "message": "bad rule"}
    with pytest.raises(ScanError):
        parse_semgrep_json(json.dumps({"results": [], "errors": [fatal]}), checkout, REPO, SHA)
    assert classify_errors([fatal])[0]


@pytest.mark.parametrize("bad", ["../../outside.py", "/etc/passwd", "app/../../x.py", ".git/config", ""])
def test_path_safety_rejects(checkout, bad):
    with pytest.raises(PathSafetyError):
        safe_relative_path(checkout, bad)


def test_symlink_escape_rejected(checkout, tmp_path_factory):
    outside = tmp_path_factory.mktemp("outside") / "secret.py"
    outside.write_text("x = 1\n")
    os.symlink(outside, checkout / "app" / "link.py")
    with pytest.raises(PathSafetyError):
        safe_relative_path(checkout, "app/link.py")
    findings, warnings = parse_semgrep_json(
        json.dumps({"results": [_result(path="app/link.py", line=1)]}), checkout, REPO, SHA)
    assert findings == [] and warnings


def test_non_pinned_rule_ignored(checkout):
    findings, _ = parse_semgrep_json(
        json.dumps({"results": [_result(check="python.other.rule")]}), checkout, REPO, SHA)
    assert findings == []


def test_fingerprint_stable_when_lines_inserted_above(checkout):
    raw = json.dumps({"results": [_result(line=2)]})
    fp1 = parse_semgrep_json(raw, checkout, REPO, SHA)[0][0].fingerprint
    (checkout / "app" / "x.py").write_text("# new\n# lines\nimport subprocess\nsubprocess.run(cmd, shell=True)\n")
    fp2 = parse_semgrep_json(json.dumps({"results": [_result(line=4)]}), checkout, REPO, SHA)[0][0].fingerprint
    assert fp1 == fp2


def test_identical_flaws_get_distinct_fingerprints(checkout):
    (checkout / "app" / "x.py").write_text("subprocess.run(cmd, shell=True)\nsubprocess.run(cmd, shell=True)\n")
    raw = json.dumps({"results": [_result(line=1), _result(line=2)]})
    fps = {f.fingerprint for f in parse_semgrep_json(raw, checkout, REPO, SHA)[0]}
    assert len(fps) == 2


def test_snippet_secrets_redacted(checkout):
    (checkout / "app" / "x.py").write_text('subprocess.run("x", shell=True, env={"API_KEY": "sk-abcdefghijklmnopqrstuv"})\n')
    f = parse_semgrep_json(json.dumps({"results": [_result(line=1)]}), checkout, REPO, SHA)[0][0]
    assert "sk-abcdefghijklmnopqrstuv" not in f.snippet


@pytest.mark.skipif(not (shutil.which("semgrep") or (Path(os.sys.executable).parent / "semgrep").exists()),
                    reason="semgrep not installed")
def test_real_semgrep_on_seed_fixtures(tmp_path):
    """Real Semgrep run (local, no network) against the seeded demo fixtures."""
    shutil.copytree(ROOT / "demo" / "target_seed", tmp_path / "t")
    shutil.copy(ROOT / "demo" / "live_flaw2_calc.py.txt", tmp_path / "t" / "app" / "calc.py")
    findings, warnings = scan(tmp_path / "t", REPO, SHA, timeout=120)
    got = sorted((f.rule_id, f.path) for f in findings)
    assert got == [("karyashield.python.eval-non-literal", "app/calc.py"),
                   ("karyashield.python.subprocess-shell-true", "app/ping_tool.py")]
