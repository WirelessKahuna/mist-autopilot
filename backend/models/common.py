from __future__ import annotations
from enum import Enum
from typing import Any
from pydantic import BaseModel


class Severity(str, Enum):
    ok = "ok"
    info = "info"
    warning = "warning"
    critical = "critical"
    unavailable = "unavailable"
    coming_soon = "coming_soon"


class Finding(BaseModel):
    severity: Severity
    title: str
    detail: str
    site_id: str | None = None
    site_name: str | None = None
    affected: list[str] = []       # AP names, SSID names, etc.
    recommendation: str | None = None
    raw: dict[str, Any] | None = None  # original API data for drill-down
    fix_url: str | None = None     # optional deep-link into the Mist portal for manual remediation


class SiteResult(BaseModel):
    site_id: str
    site_name: str
    score: int | None = None       # 0–100, None if data unavailable
    severity: Severity = Severity.ok
    findings: list[Finding] = []


class ModuleOutput(BaseModel):
    module_id: str
    display_name: str
    icon: str                       # emoji icon for the dashboard tile
    score: int | None = None        # 0–100 org-wide aggregate, None if unavailable
    severity: Severity = Severity.ok
    summary: str = ""               # one-line human-readable summary
    findings: list[Finding] = []    # org-level findings
    sites: list[SiteResult] = []    # per-site breakdown
    status: str = "ok"              # ok | coming_soon | error
    error: str | None = None        # populated if status == error


class OrgSummary(BaseModel):
    org_id: str
    org_name: str
    site_count: int
    overall_score: int | None = None
    modules: list[ModuleOutput] = []
    site_names: dict[str, str] = {}  # {site_id: site_name} for report generation
    can_write: bool = False          # True when session token has admin or write role
    portal_base: str = "https://manage.mist.com"  # Mist portal base URL for this session's cloud
    cloud_id: str = "global"         # human-readable cloud id (global, eu, gc1, ac2, ...)
