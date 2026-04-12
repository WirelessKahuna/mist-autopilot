"""
MarvisIQ — Marvis Actions Analyzer
=====================================
Fetches and analyzes open Marvis AI actions across the org.
Surfaces active issues by category, identifies recurrent problems,
flags self-drivable actions that haven't been enabled, and highlights
sites generating disproportionate action volume.

API endpoint:
  GET /api/v1/orgs/{org_id}/marvis/actions

Action structure:
  category     — ap | switch | gateway | wireless | wired
  symptom      — ap_disconnect | sw_offline | dns_failure | etc.
  status       — open | validated | snoozed
  severity     — numeric (60 = high)
  batch_count  — number of events in this action batch
  self_drivable — whether Marvis can auto-remediate
  site_id      — site where the action occurred
  suggestion   — Marvis recommended action string

Checks performed:
  1. Open actions by category    — per-category breakdown of open issues
  2. Recurrent issues            — batch_count > RECURRENCE_THRESHOLD → Warning
  3. Self-drivable not enabled   — self_drivable=True but status=open → Info
  4. Site concentration          — one site > SITE_CONCENTRATION_PCT of all actions → Warning
  5. No open actions             — clean org → Healthy
"""

import asyncio
import logging
import time
from collections import defaultdict
from datetime import datetime, timezone

from models import ModuleOutput, Finding, Severity, SiteResult
from mist_client import MistClient, MistAPIError
from .base import BaseModule

logger = logging.getLogger(__name__)

# Thresholds
RECURRENCE_THRESHOLD    = 50   # batch_count above this = recurrent issue
SITE_CONCENTRATION_PCT  = 60   # % of actions from one site = concentration warning

# Human-readable category and symptom labels
CATEGORY_LABELS: dict[str, str] = {
    "ap":      "Access Point",
    "switch":  "Switch",
    "gateway": "WAN Edge / Gateway",
    "wireless": "Wireless",
    "wired":   "Wired",
}

SYMPTOM_LABELS: dict[str, str] = {
    "ap_disconnect":     "AP Disconnected",
    "sw_offline":        "Switch Offline",
    "dns_failure":       "DNS Failure",
    "dhcp_failure":      "DHCP Failure",
    "bad_cable":         "Bad Cable",
    "port_flap":         "Port Flapping",
    "missing_vlan":      "Missing VLAN",
    "negotiation_mismatch": "Negotiation Mismatch",
    "arp_failure":       "ARP Failure",
    "radius_failure":    "RADIUS Failure",
}

SEVERITY_MAP: dict[int, str] = {
    60: "High",
    50: "Medium",
    40: "Low",
}


def _severity_label(sev: int) -> str:
    if sev >= 60:
        return "High"
    if sev >= 50:
        return "Medium"
    return "Low"


class MarvisIQModule(BaseModule):
    module_id    = "marvis_iq"
    display_name = "MarvisIQ"
    icon         = "🔬"

    async def analyze(self, org_id: str, sites: list[dict], client: MistClient) -> ModuleOutput:

        # ── 1. Fetch Marvis actions ───────────────────────────────────────────
        # Endpoint: /api/v1/labs/orgs/{org_id}/marvis_actions
        # Note: this is a /labs/ endpoint, not the standard /api/v1/orgs/ path
        # Params: start/end epoch timestamps, interval=3600, query=group_by_category_symptom
        end_time   = int(time.time())
        start_time = end_time - (7 * 24 * 3600)  # 7 days

        try:
            result = await client.get(
                f"/api/v1/labs/orgs/{org_id}/marvis_actions",
                params={
                    "start":    start_time,
                    "end":      end_time,
                    "interval": 3600,
                    "query":    "group_by_category_symptom",
                    "limit":    1000,
                    "active":   "true",
                },
                use_cache=False,
            )
            # Response may be list or dict with 'data' key
            if isinstance(result, dict):
                actions = result.get("data", result.get("results", []))
            elif isinstance(result, list):
                actions = result
            else:
                actions = []
        except MistAPIError as e:
            return self._error_output(f"Failed to fetch Marvis actions: {e.message}")

        findings: list[Finding] = []

        # Build site name map
        site_map = {s["id"]: s.get("name", s["id"]) for s in sites}

        # ── 2. Filter to open actions only ───────────────────────────────────
        open_actions   = [a for a in actions if a.get("status") == "open"]
        all_statuses   = defaultdict(int)
        for a in actions:
            all_statuses[a.get("status", "unknown")] += 1

        if not actions:
            return ModuleOutput(
                module_id=self.module_id,
                display_name=self.display_name,
                icon=self.icon,
                score=100,
                severity=Severity.ok,
                summary="No Marvis actions found — org is clean.",
                findings=[],
                sites=[],
                status="ok",
            )

        # ── 3. Open actions by category ──────────────────────────────────────
        by_category: dict[str, list] = defaultdict(list)
        for a in open_actions:
            by_category[a.get("category", "unknown")].append(a)

        if open_actions:
            # Build per-category findings
            for cat, cat_actions in sorted(by_category.items(), key=lambda x: -len(x[1])):
                cat_label = CATEGORY_LABELS.get(cat, cat.title())
                symptoms  = defaultdict(int)
                for a in cat_actions:
                    sym = a.get("symptom", "unknown")
                    symptoms[SYMPTOM_LABELS.get(sym, sym.replace("_", " ").title())] += 1

                symptom_summary = ", ".join(
                    f"{count} {sym}" for sym, count in
                    sorted(symptoms.items(), key=lambda x: -x[1])
                )

                # Severity based on count
                if len(cat_actions) >= 5:
                    sev = Severity.critical
                elif len(cat_actions) >= 2:
                    sev = Severity.warning
                else:
                    sev = Severity.info

                findings.append(Finding(
                    severity=sev,
                    title=f"{len(cat_actions)} open {cat_label} action(s)",
                    detail=(
                        f"Marvis has {len(cat_actions)} open {cat_label} action(s) "
                        f"requiring attention: {symptom_summary}."
                    ),
                    affected=[
                        f"{site_map.get(a.get('site_id',''), a.get('site_id','unknown'))} — "
                        f"{SYMPTOM_LABELS.get(a.get('symptom',''), a.get('symptom',''))}"
                        for a in cat_actions[:10]
                    ],
                    recommendation=(
                        f"Review {cat_label} actions in Marvis > Actions dashboard. "
                        f"Address high-severity issues first and enable self-driving "
                        f"where available to allow Marvis to auto-remediate."
                    ),
                ))

        # ── 4. Recurrent issues ──────────────────────────────────────────────
        recurrent = [
            a for a in open_actions
            if a.get("batch_count", 0) > RECURRENCE_THRESHOLD
        ]
        if recurrent:
            recurrent_details = []
            for a in recurrent[:5]:
                site_name = site_map.get(a.get("site_id", ""), "Unknown Site")
                sym       = SYMPTOM_LABELS.get(a.get("symptom", ""), a.get("symptom", ""))
                count     = a.get("batch_count", 0)
                recurrent_details.append(f"{site_name} — {sym} ({count} events)")

            findings.append(Finding(
                severity=Severity.warning,
                title=f"{len(recurrent)} recurrent issue(s) with high event count",
                detail=(
                    f"{len(recurrent)} open Marvis action(s) have accumulated more than "
                    f"{RECURRENCE_THRESHOLD} events, indicating persistent unresolved problems "
                    f"that may be recurring or have been present for an extended period."
                ),
                affected=recurrent_details,
                recommendation=(
                    "Recurrent issues with high event counts indicate problems that "
                    "are not being resolved between occurrences. Investigate root cause "
                    "rather than just addressing symptoms. Consider enabling self-driving "
                    "Marvis Actions for eligible issue types."
                ),
            ))

        # ── 5. Self-drivable actions not enabled ─────────────────────────────
        self_drivable_open = [
            a for a in open_actions
            if a.get("self_drivable") is True
        ]
        if self_drivable_open:
            findings.append(Finding(
                severity=Severity.info,
                title=f"{len(self_drivable_open)} action(s) eligible for Marvis self-driving",
                detail=(
                    f"{len(self_drivable_open)} open action(s) are marked as self-drivable, "
                    "meaning Marvis can automatically remediate these issues without manual "
                    "intervention, but self-driving has not been enabled for these action types."
                ),
                affected=[
                    f"{SYMPTOM_LABELS.get(a.get('symptom',''), a.get('symptom',''))} — "
                    f"{site_map.get(a.get('site_id',''), 'Unknown')}"
                    for a in self_drivable_open[:5]
                ],
                recommendation=(
                    "Enable self-driving for eligible Marvis Actions under "
                    "Marvis > Actions > Self-Driving Settings. "
                    "Self-driving allows Marvis to automatically fix issues like "
                    "non-compliant firmware and stuck ports during low-usage windows."
                ),
            ))

        # ── 6. Site concentration ─────────────────────────────────────────────
        if open_actions:
            site_counts: dict[str, int] = defaultdict(int)
            for a in open_actions:
                site_id = a.get("site_id", "unknown")
                site_counts[site_id] += 1

            top_site_id    = max(site_counts, key=lambda x: site_counts[x])
            top_site_count = site_counts[top_site_id]
            top_pct        = int(top_site_count / len(open_actions) * 100)
            top_site_name  = site_map.get(top_site_id, top_site_id)

            if top_pct >= SITE_CONCENTRATION_PCT and len(site_counts) > 1:
                findings.append(Finding(
                    severity=Severity.warning,
                    title=f"{top_site_name} generating {top_pct}% of all open actions",
                    detail=(
                        f"{top_site_name} accounts for {top_site_count} of {len(open_actions)} "
                        f"open Marvis actions ({top_pct}%). High action concentration at a "
                        "single site indicates a systemic issue at that location."
                    ),
                    affected=[f"{top_site_name}: {top_site_count} actions"],
                    recommendation=(
                        f"Prioritize investigation of {top_site_name}. "
                        "High action concentration often indicates infrastructure issues "
                        "such as uplink instability, power problems, or configuration drift "
                        "affecting multiple devices at once."
                    ),
                ))

        # ── 7. Score and summarize ────────────────────────────────────────────
        score    = self.score_from_findings(findings)
        severity = self.severity_from_score(score)

        total    = len(actions)
        open_ct  = len(open_actions)
        val_ct   = all_statuses.get("validated", 0)
        snooze_ct = all_statuses.get("snoozed", 0)

        if open_ct == 0:
            summary = (
                f"{total} Marvis action(s) — all validated or resolved. Org is clean."
            )
        else:
            cat_summary = ", ".join(
                f"{len(v)} {CATEGORY_LABELS.get(k, k)}"
                for k, v in sorted(by_category.items(), key=lambda x: -len(x[1]))
            )
            summary = (
                f"{open_ct} open action(s): {cat_summary}. "
                f"{val_ct} validated, {snooze_ct} snoozed."
            )

        # Build per-site results for sites with open actions
        site_results: list[SiteResult] = []
        for site_id, count in sorted(site_counts.items() if open_actions else {}.items(),
                                     key=lambda x: -x[1]):
            site_name    = site_map.get(site_id, site_id)
            site_actions = [a for a in open_actions if a.get("site_id") == site_id]
            site_findings = [
                Finding(
                    severity=Severity.warning,
                    title=f"{SYMPTOM_LABELS.get(a.get('symptom',''), a.get('symptom',''))}",
                    detail=f"Category: {CATEGORY_LABELS.get(a.get('category',''), a.get('category',''))} | "
                           f"Severity: {_severity_label(a.get('severity', 0))} | "
                           f"Events: {a.get('batch_count', 0)}",
                    site_id=site_id,
                    site_name=site_name,
                )
                for a in site_actions[:10]
            ]
            site_score = max(0, 100 - (count * 10))
            site_results.append(SiteResult(
                site_id=site_id,
                site_name=site_name,
                score=site_score,
                severity=self.severity_from_score(site_score),
                findings=site_findings,
            ))

        return ModuleOutput(
            module_id=self.module_id,
            display_name=self.display_name,
            icon=self.icon,
            score=score,
            severity=severity,
            summary=summary,
            findings=findings,
            sites=site_results,
            status="ok",
        )
