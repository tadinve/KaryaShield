"""Typed, validated configuration from environment / .env."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RULES_FILE = PROJECT_ROOT / "rules" / "karyashield.yml"
# Pinned rule IDs. Only findings from these rules can ever produce an issue.
PINNED_RULE_IDS = (
    "karyashield.python.subprocess-shell-true",
    "karyashield.python.eval-non-literal",
)
MAX_ISSUES_PER_RUN = 3
ISSUE_LABEL = "karyashield"

_REPO_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})/[A-Za-z0-9._-]{1,100}$")
_BRANCH_RE = re.compile(r"^[A-Za-z0-9._/-]{1,100}$")


class ConfigError(ValueError):
    pass


def validate_repo(value: str) -> str:
    """Exact OWNER/REPO only: no URL, host, whitespace, traversal or metacharacters."""
    if not isinstance(value, str) or not _REPO_RE.match(value) or ".." in value:
        raise ConfigError(f"invalid repo identifier: {value!r}")
    if value.split("/")[1] in (".", ".."):
        raise ConfigError(f"invalid repo identifier: {value!r}")
    return value


@dataclass(frozen=True)
class Config:
    llm_provider: str
    llm_model: str
    llm_base_url: str
    llm_api_key: str
    gcp_project: str
    gcp_location: str
    ch_host: str
    ch_port: int
    ch_user: str
    ch_password: str
    ch_database: str
    ch_secure: bool
    github_repo: str
    github_branch: str
    allowlist: tuple[str, ...]
    enable_writes: bool
    min_severity: str
    workspace_dir: Path
    scan_timeout: int
    llm_timeout: int
    watch_interval: int

    def redacted(self) -> dict:
        return {
            "llm_provider": self.llm_provider,
            "llm_model": self.llm_model,
            "llm": (f"vertex project={self.gcp_project} location={self.gcp_location}" if self.llm_provider == "vertex"
                    else f"base_url={self.llm_base_url} api_key={'set' if self.llm_api_key else 'MISSING'}"),
            "clickhouse_host": "set" if self.ch_host else "MISSING",
            "clickhouse_password": "set" if self.ch_password else "MISSING",
            "clickhouse_database": self.ch_database,
            "github_repo": self.github_repo,
            "github_branch": self.github_branch,
            "allowlist": list(self.allowlist),
            "enable_writes": self.enable_writes,
            "min_severity": self.min_severity,
        }


def _int(name: str, default: int) -> int:
    raw = os.getenv(name, str(default))
    try:
        v = int(raw)
    except ValueError as e:
        raise ConfigError(f"{name} must be an integer") from e
    if v <= 0:
        raise ConfigError(f"{name} must be positive")
    return v


def load_config(env_file: Path | None = None) -> Config:
    load_dotenv(env_file or PROJECT_ROOT / ".env", override=False)
    repo = validate_repo(os.getenv("GITHUB_REPO", "").strip())
    allowlist = tuple(
        validate_repo(r.strip())
        for r in os.getenv("DEMO_REPO_ALLOWLIST", "").split(",")
        if r.strip()
    )
    if repo not in allowlist:
        raise ConfigError("GITHUB_REPO is not in DEMO_REPO_ALLOWLIST")
    branch = os.getenv("GITHUB_BRANCH", "main").strip()
    if not _BRANCH_RE.match(branch) or ".." in branch or branch.startswith("-"):
        raise ConfigError(f"invalid branch: {branch!r}")
    min_sev = os.getenv("KARYASHIELD_MIN_SEVERITY", "WARNING").strip().upper()
    if min_sev not in ("INFO", "WARNING", "ERROR"):
        raise ConfigError("KARYASHIELD_MIN_SEVERITY must be INFO, WARNING or ERROR")
    # Writes are enabled ONLY by the exact string "true".
    enable_writes = os.getenv("KARYASHIELD_ENABLE_WRITES", "false").strip().lower() == "true"
    llm_provider = os.getenv("LLM_PROVIDER", "vertex").strip().lower()
    if llm_provider not in ("vertex", "openai_compat"):
        raise ConfigError("LLM_PROVIDER must be 'vertex' or 'openai_compat'")
    if llm_provider == "vertex" and not os.getenv("GOOGLE_CLOUD_PROJECT", "").strip():
        raise ConfigError("GOOGLE_CLOUD_PROJECT is required for LLM_PROVIDER=vertex")
    ch_db = os.getenv("CLICKHOUSE_DATABASE", "karyashield").strip()
    if not re.match(r"^[A-Za-z_][A-Za-z0-9_]{0,62}$", ch_db):
        raise ConfigError("CLICKHOUSE_DATABASE must be a plain identifier")
    ws = Path(os.getenv("WORKSPACE_DIR", ".workspaces"))
    if not ws.is_absolute():
        ws = PROJECT_ROOT / ws
    return Config(
        llm_provider=llm_provider,
        llm_model=os.getenv("LLM_MODEL", "gemini-2.5-flash").strip(),
        llm_base_url=os.getenv("LLM_BASE_URL", "https://api.openai.com/v1").strip(),
        llm_api_key=os.getenv("LLM_API_KEY", "").strip(),
        gcp_project=os.getenv("GOOGLE_CLOUD_PROJECT", "").strip(),
        gcp_location=os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1").strip(),
        ch_host=os.getenv("CLICKHOUSE_HOST", "").strip(),
        ch_port=_int("CLICKHOUSE_PORT", 8443),
        ch_user=os.getenv("CLICKHOUSE_USER", "default").strip(),
        ch_password=os.getenv("CLICKHOUSE_PASSWORD", ""),
        ch_database=ch_db,
        ch_secure=os.getenv("CLICKHOUSE_SECURE", "true").strip().lower() == "true",
        github_repo=repo,
        github_branch=branch,
        allowlist=allowlist,
        enable_writes=enable_writes,
        min_severity=min_sev,
        workspace_dir=ws,
        scan_timeout=_int("SCAN_TIMEOUT_SECONDS", 90),
        llm_timeout=_int("LLM_TIMEOUT_SECONDS", 45),
        watch_interval=_int("WATCH_INTERVAL_SECONDS", 120),
    )
