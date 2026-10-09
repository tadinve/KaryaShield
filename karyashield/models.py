"""Pydantic data contracts shared across KaryaShield modules."""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

Severity = Literal["INFO", "WARNING", "ERROR"]
SEVERITY_RANK = {"INFO": 0, "WARNING": 1, "ERROR": 2}


class Finding(BaseModel):
    rule_id: str
    path: str  # repo-relative, validated inside checkout
    start_line: int
    end_line: int
    severity: Severity
    message: str = Field(max_length=1000)
    snippet: str = Field(max_length=1500)
    commit_sha: str
    repo: str  # from validated config, never from LLM output
    fingerprint: str


class Triage(BaseModel):
    """Schema requested from the LLM. Plain types only; bounds are enforced in code."""

    is_actionable: bool
    risk_level: Literal["low", "medium", "high", "critical"]
    summary: str
    why_it_matters: str
    recommended_fix: str
    confidence: float


class TriageResult(BaseModel):
    ok: bool
    triage: Optional[Triage] = None
    error: Optional[str] = None


class Decision(BaseModel):
    allowed: bool
    reasons: list[str]  # gate failures (empty when allowed)


class FindingOutcome(BaseModel):
    fingerprint: str
    rule_id: str
    path: str
    start_line: int
    action: Literal[
        "issue_created",
        "would_create",
        "duplicate",
        "reconciled",
        "blocked",
        "vetoed",
        "triage_error",
        "write_uncertain",
        "manual_investigation",
        "error",
    ]
    detail: str = ""
    issue_url: Optional[str] = None
