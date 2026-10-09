"""CWE classification: an explicit, asserted rule → CWE mapping (never model-generated).

- Reference taxonomy: MITRE 2025 CWE Top 25 (data/cwe_top25_2025.json), classification only, not detectors.
- Each pinned Semgrep rule maps to exactly one CWE. Unknown IDs are rejected at import time.
- A mapping states which weakness CLASS the rule targets; it is not proof that an exploit works.
- CVE: KaryaShield scans first-party code. A CVE identifies a specific *published* vulnerability in a
  product; a finding in your own code has no CVE unless one is assigned, so we never attach or invent one.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

TAXONOMY_FILE = Path(__file__).resolve().parent.parent / "data" / "cwe_top25_2025.json"
TOP25_SOURCE_URL = "https://cwe.mitre.org/top25/archive/2025/2025_cwe_top25"
CVE_PROGRAM_URL = "https://www.cve.org/"
CISA_KEV_URL = "https://www.cisa.gov/known-exploited-vulnerabilities-catalog"

# CWEs used by our rules that are NOT in the Top 25, with their official MITRE names/links.
_EXTRA_KNOWN = {
    "CWE-95": {"name": "Improper Neutralization of Directives in Dynamically Evaluated Code ('Eval Injection')",
               "url": "https://cwe.mitre.org/data/definitions/95.html", "parent": "CWE-94"},
}

# Explicit rule → CWE mapping (inspected against rules/karyashield.yml metadata).
RULE_TO_CWE = {
    "karyashield.python.subprocess-shell-true": "CWE-78",  # OS command injection via shell=True
    "karyashield.python.eval-non-literal": "CWE-95",       # eval of non-literal input: specific child of CWE-94
}


@dataclass(frozen=True)
class CweInfo:
    cwe_id: str
    name: str
    source_url: str
    top25_rank: int | None
    parent_id: str | None = None
    parent_top25_rank: int | None = None


def _load_top25() -> dict[str, dict]:
    doc = json.loads(TAXONOMY_FILE.read_text())
    return {w["cwe_id"]: w for w in doc["weaknesses"]}


TOP25 = _load_top25()


def _info(cwe_id: str) -> CweInfo:
    if cwe_id in TOP25:
        w = TOP25[cwe_id]
        return CweInfo(cwe_id, w["short_name"], w["official_url"], w["rank"])
    if cwe_id in _EXTRA_KNOWN:
        e = _EXTRA_KNOWN[cwe_id]
        parent = e.get("parent")
        return CweInfo(cwe_id, e["name"], e["url"], None, parent, TOP25.get(parent, {}).get("rank"))
    raise ValueError(f"unknown CWE id {cwe_id!r}: refusing to classify (no hallucinated IDs)")


# Validate the whole mapping at import time: an unknown ID is a programming error, never silently passed.
CLASSIFICATION = {rule: _info(cwe) for rule, cwe in RULE_TO_CWE.items()}


def classify(rule_id: str) -> CweInfo | None:
    return CLASSIFICATION.get(rule_id)


def coverage() -> list[dict]:
    """Which CWEs are covered by working rules (evidence-backed), relative to the Top 25."""
    rows = []
    for rule, info in CLASSIFICATION.items():
        rows.append({"rule": rule, "cwe_id": info.cwe_id, "name": info.name,
                     "top25_rank": info.top25_rank, "parent": info.parent_id,
                     "parent_top25_rank": info.parent_top25_rank})
    return rows


def top25_label(info: CweInfo) -> str:
    if info.top25_rank:
        return f"2025 CWE Top 25 #{info.top25_rank}"
    if info.parent_id and info.parent_top25_rank:
        return f"not in the Top 25; child of {info.parent_id} (Top 25 #{info.parent_top25_rank})"
    return "not in the 2025 CWE Top 25"
