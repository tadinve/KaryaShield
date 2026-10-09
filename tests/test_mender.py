"""Sandbox patch verification (real Semgrep, fake LLM). Nothing is executed; the repo is never written."""
import json
import os
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

from karyashield.mender import propose_and_verify, verify_patch
from karyashield.scanner import scan
from karyashield.triage import LLMClient
from tests.conftest import REPO, SHA

ROOT = Path(__file__).resolve().parent.parent
pytestmark = pytest.mark.skipif(
    not (shutil.which("semgrep") or (Path(os.sys.executable).parent / "semgrep").exists()),
    reason="semgrep not installed")

ORIGINAL = (ROOT / "demo" / "target_seed" / "app" / "ping_tool.py").read_text()
GOOD = ORIGINAL.replace('subprocess.run(f"ping -c 1 {host}", shell=True, capture_output=True)',
                        'subprocess.run(["ping", "-c", "1", host], capture_output=True)')


@pytest.fixture
def checkout(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "ping_tool.py").write_text(ORIGINAL)
    return tmp_path


def scan_fn(path):
    return scan(path, REPO, SHA, 120)[0]


@pytest.fixture
def finding(checkout):
    return scan_fn(checkout)[0]


def test_good_patch_verified(finding):
    r = verify_patch(finding, ORIGINAL, GOOD, "use argv list", scan_fn)
    assert r.status == "verified", r.reason
    assert "-    return subprocess.run(f\"ping" in r.diff and "shell=True" not in GOOD


def test_cosmetic_patch_rejected(finding):
    r = verify_patch(finding, ORIGINAL, ORIGINAL.replace("# BAD:", "# NOTE:"), "", scan_fn)
    assert r.status == "rejected" and "still reports" in r.reason


def test_syntax_error_rejected(finding):
    r = verify_patch(finding, ORIGINAL, GOOD.replace("def ping_host(host):", "def ping_host(host)"), "", scan_fn)
    assert r.status == "rejected" and "does not parse" in r.reason


def test_new_vulnerability_rejected(finding):
    bad = GOOD + "\n\ndef calc(x):\n    return eval(x)\n"
    r = verify_patch(finding, ORIGINAL, bad, "", scan_fn)
    assert r.status == "rejected" and "new finding" in r.reason


def test_oversized_patch_rejected(finding):
    big = GOOD + "".join(f"\nX{i} = {i}" for i in range(60)) + "\n"
    assert verify_patch(finding, ORIGINAL, big, "", scan_fn).status == "rejected"


def _llm(content):
    def create(**kw):
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])
    return LLMClient("openai_compat", SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create))), "fake")


def test_propose_and_verify_end_to_end_with_fake_llm(checkout, finding):
    llm = _llm(json.dumps({"fixed_file": GOOD, "explanation": "argv list, no shell"}))
    r = propose_and_verify(llm, "m", checkout, finding, scan_fn)
    assert r.status == "verified"
    assert (checkout / "app" / "ping_tool.py").read_text() == ORIGINAL  # repo copy untouched


def test_garbage_proposal_is_error(checkout, finding):
    assert propose_and_verify(_llm("not json"), "m", checkout, finding, scan_fn).status == "error"


def test_sandbox_rejects_patch_that_is_still_exploitable(finding):
    # passes Semgrep (no literal shell=True) but still builds a shell string: the exploit test must catch it
    sneaky = ORIGINAL.replace('subprocess.run(f"ping -c 1 {host}", shell=True, capture_output=True)',
                              'subprocess.run(f"ping -c 1 {host}", capture_output=True, **{"shell": True})')
    r = verify_patch(finding, ORIGINAL, sneaky, "", scan_fn)
    assert r.status == "rejected" and "sandbox exploit test failed" in r.reason
