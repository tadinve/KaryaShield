"""CWE classification: explicit mapping, unknown IDs rejected, no CVE invented."""
import re
from pathlib import Path

import pytest

from karyashield import cwe
from karyashield import github_adapter as gh
from tests.conftest import GOOD_TRIAGE, make_finding

ROOT = Path(__file__).resolve().parent.parent


def test_taxonomy_loaded_25():
    assert len(cwe.TOP25) == 25 and cwe.TOP25["CWE-78"]["rank"] == 9 and cwe.TOP25["CWE-94"]["rank"] == 10


def test_explicit_mapping():
    a = cwe.classify("karyashield.python.subprocess-shell-true")
    b = cwe.classify("karyashield.python.eval-non-literal")
    assert (a.cwe_id, a.top25_rank) == ("CWE-78", 9)
    assert (b.cwe_id, b.top25_rank, b.parent_id, b.parent_top25_rank) == ("CWE-95", None, "CWE-94", 10)
    assert cwe.classify("some.other.rule") is None


def test_unknown_cwe_rejected():
    with pytest.raises(ValueError):
        cwe._info("CWE-99999")


def test_rule_file_metadata_matches_mapping():
    text = (ROOT / "rules" / "karyashield.yml").read_text()
    for rule, cid in cwe.RULE_TO_CWE.items():
        block = text.split("id: " + rule)[1].split("- id:")[0]
        assert f'cwe: "{cid}:' in block, (rule, cid)


def test_coverage_is_only_what_rules_detect():
    assert {r["cwe_id"] for r in cwe.coverage()} == {"CWE-78", "CWE-95"}


def test_issue_body_classifies_and_never_invents_cve():
    f = make_finding(cwe_id="CWE-78", cwe_source_url="https://cwe.mitre.org/data/definitions/78.html")
    _, body = gh.build_issue(f, GOOD_TRIAGE.triage, "fake")
    assert "CWE-78" in body and "Top 25 #9" in body and "not proof of exploitability" in body
    assert not re.search(r"CVE-\d{4}-\d{4,}", body)
    assert "| VERIFIED | no |" in body and "| REMEDIATED | no |" in body
