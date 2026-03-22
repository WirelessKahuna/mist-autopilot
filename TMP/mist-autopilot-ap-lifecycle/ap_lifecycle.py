"""
AP Lifecycle Monitor
====================
Inventories every AP across the org and identifies infrastructure
health issues that require attention:

  1. Firmware Compliance   — APs running non-current firmware per model
  2. Mixed Firmware Sites  — Sites with multiple firmware versions (instability risk)
  3. Disconnected APs      — APs not connected to cloud
  4. EOL/EOS Awareness     — Flags models that are approaching or past support end

Autonomy levels:
  L1 — Detects firmware non-compliance, disconnected APs, mixed versions
  L2 — Identifies the majority firmware per model, per-site mixed version analysis
  L3 — Documents Marvis self-driving firmware upgrade as recommended action

Note: Marvis Actions already supports autonomous firmware upgrades (self-driving mode).
      This module surfaces the findings; enabling Marvis self-driving is the L3 action.
"""

import asyncio
import logging
from collections import defaultdict, Counter

from models import ModuleOutput, Finding, Severity, SiteResult
from mist_client import MistClient
from .base import BaseModule

logger = logging.getLogger(__name__)

# Models known to be EOL/EOS — update as Juniper publishes EOS notices
# Format: model_prefix -> notice message
EOL_MODELS: dict[str, str] = {
    "AP21":  "AP21 is End of Sale. Plan migration to AP32 or AP43.",
    "AP12":  "AP12 is End of Sale. Plan migration to current portfolio.",
    "AP32E": "AP32E is End of Sale.",
    "BT11":  "BT11 (BLE gateway) is End of Sale.",
}


def _model_prefix(model: str) -> str:
    """Extract the model family prefix for EOL matching."""
    return model.split("-")[0] if model else ""


def _firmware_sort_key(version: str) -> tuple:
    """
    Parse Mist firmware version strings for comparison.
    Handles formats like '0.14.29728', '0.12.27365', '0.14.0-27'
    Returns a tuple for reliable comparison.
    """
    try:
        parts = version.replace("-", ".").split(".")
        return tuple(int(p) for p in parts if p.isdigit())
    except Exception:
        return (0,)


class APLifecycleModule(BaseModule):
    module_id    = "ap_lifecycle"
    display_name = "AP Lifecycle Monitor"
    icon         = "🔄"

    async def analyze(self, org_id: str, sites: list[dict], client: MistClient) -> ModuleOutput:

        # ── 1. Fetch full org AP inventory ───────────────────────────────────
        try:
            inventory = await client.get_org_inventory(org_id, device_type="ap")
        except Exception as e:
            logger.error(f"AP Lifecycle: inventory fetch failed: {e}")
            return self._error_output(f"Could not fetch AP inventory: {e}")

        if not inventory:
            return ModuleOutput(
                module_id=self.module_id,
                display_name=self.display_name,
                icon=self.icon,
                score=100,
                severity=Severity.ok,
                summary="No APs found in inventory.",
                status="ok",
            )

        # Build site lookup
        site_map = {s["id"]: s.get("name", s["id"]) for s in sites}

        # ── 2. Determine majority (current) firmware per model ───────────────
        # Group APs by model, find the most common firmware version per model.
        # That becomes the "current" baseline — non-compliant APs are flagged.
        model_firmware: dict[str, list[str]] = defaultdict(list)
        for ap in inventory:
            model = ap.get("model", "unknown")
            fw    = ap.get("firmware", ap.get("version", ""))
            if fw:
                model_firmware[model].append(fw)

        # Majority firmware per model
        current_firmware: dict[str, str] = {}
        for model, versions in model_firmware.items():
            if versions:
                counter = Counter(versions)
                majority = counter.most_common(1)[0][0]
                current_firmware[model] = majority

        # ── 3. Analyse every AP ──────────────────────────────────────────────
        all_findings: list[Finding] = []

        # Per-site tracking
        site_ap_counts:       dict[str, int]       = defaultdict(int)
        site_fw_versions:     dict[str, set]        = defaultdict(set)
        site_non_compliant:   dict[str, list[str]]  = defaultdict(list)
        site_disconnected:    dict[str, list[str]]  = defaultdict(list)
        site_eol:             dict[str, list[str]]  = defaultdict(list)

        for ap in inventory:
            ap_name   = ap.get("name") or ap.get("hostname") or ap.get("mac", "unknown")
            model     = ap.get("model", "unknown")
            firmware  = ap.get("firmware", ap.get("version", ""))
            connected = ap.get("connected", False)
            site_id   = ap.get("site_id")
            site_name = site_map.get(site_id, "Unassigned") if site_id else "Unassigned"

            if site_id:
                site_ap_counts[site_id] += 1
                if firmware:
                    site_fw_versions[site_id].add(firmware)

            # Check disconnected
            if not connected:
                if site_id:
                    site_disconnected[site_id].append(ap_name)

            # Check firmware compliance
            if firmware and model in current_firmware:
                majority_fw = current_firmware[model]
                if firmware != majority_fw:
                    ap_key = _firmware_sort_key(firmware)
                    maj_key = _firmware_sort_key(majority_fw)
                    if ap_key < maj_key:
                        if site_id:
                            site_non_compliant[site_id].append(
                                f"{ap_name} ({firmware} vs {majority_fw})"
                            )

            # Check EOL
            prefix = _model_prefix(model)
            if prefix in EOL_MODELS and site_id:
                site_eol[site_id].append(f"{ap_name} ({model})")

        # ── 4. Build per-site findings ───────────────────────────────────────
        site_results: list[SiteResult] = []

        for site in sites:
            site_id   = site["id"]
            site_name = site.get("name", site_id)
            ap_count  = site_ap_counts.get(site_id, 0)

            if ap_count == 0:
                continue

            site_findings: list[Finding] = []
            fw_versions = site_fw_versions.get(site_id, set())
            non_compliant = site_non_compliant.get(site_id, [])
            disconnected  = site_disconnected.get(site_id, [])
            eol_aps       = site_eol.get(site_id, [])

            # Mixed firmware versions at this site
            if len(fw_versions) > 1:
                sorted_versions = sorted(fw_versions, key=_firmware_sort_key, reverse=True)
                site_findings.append(Finding(
                    severity=Severity.warning,
                    title=f"{site_name} — mixed firmware versions ({len(fw_versions)} versions)",
                    detail=(
                        f"{ap_count} APs at this site are running {len(fw_versions)} different "
                        f"firmware versions: {', '.join(sorted_versions)}. "
                        f"Mixed firmware is a common cause of intermittent connectivity issues "
                        f"and inconsistent feature behavior."
                    ),
                    site_id=site_id,
                    site_name=site_name,
                    affected=list(fw_versions),
                    recommendation=(
                        "Enable Marvis Self-Driving firmware upgrade (Organization > Site Configuration) "
                        "to automatically standardize firmware during low-usage windows. "
                        "Or manually upgrade non-current APs via Organization > Access Points."
                    ),
                ))

            # Non-compliant firmware (older than site majority)
            if non_compliant:
                site_findings.append(Finding(
                    severity=Severity.warning,
                    title=f"{site_name} — {len(non_compliant)} AP(s) on non-current firmware",
                    detail=(
                        f"{len(non_compliant)} AP(s) are running firmware older than the "
                        f"majority version at their site. This creates inconsistencies and "
                        f"may prevent access to current feature capabilities."
                    ),
                    site_id=site_id,
                    site_name=site_name,
                    affected=non_compliant[:10],  # cap list length
                    recommendation=(
                        "Upgrade affected APs to match the site majority firmware. "
                        "Enable Marvis Self-Driving Actions for automated non-compliant "
                        "firmware remediation during off-hours."
                    ),
                ))

            # Disconnected APs
            if disconnected:
                severity = (
                    Severity.critical if len(disconnected) > ap_count * 0.25
                    else Severity.warning
                )
                site_findings.append(Finding(
                    severity=severity,
                    title=f"{site_name} — {len(disconnected)} AP(s) disconnected",
                    detail=(
                        f"{len(disconnected)} of {ap_count} APs at this site are not "
                        f"connected to the Mist cloud. Disconnected APs cannot be managed, "
                        f"monitored, or receive configuration updates."
                    ),
                    site_id=site_id,
                    site_name=site_name,
                    affected=disconnected[:10],
                    recommendation=(
                        "Check AP uplink connectivity and PoE status. "
                        "Review AP events in Mist for disconnect reason. "
                        "Verify LLDP/CDP on connected switch ports."
                    ),
                ))

            # EOL hardware
            if eol_aps:
                site_findings.append(Finding(
                    severity=Severity.info,
                    title=f"{site_name} — {len(eol_aps)} EOL AP model(s) detected",
                    detail=(
                        f"{len(eol_aps)} AP(s) at this site are running End-of-Sale "
                        f"hardware models. While these may still function, they will not "
                        f"receive future feature updates and have no replacement path."
                    ),
                    site_id=site_id,
                    site_name=site_name,
                    affected=eol_aps[:10],
                    recommendation=(
                        "Plan hardware refresh for EOL models. "
                        "Review Juniper's product lifecycle page for EOS timelines."
                    ),
                ))

            all_findings.extend(site_findings)
            site_score = self.score_from_findings(site_findings)
            site_results.append(SiteResult(
                site_id=site_id,
                site_name=site_name,
                score=site_score,
                severity=self.severity_from_score(site_score),
                findings=site_findings,
            ))

        # ── 5. Org-level disconnected AP summary ─────────────────────────────
        total_aps         = len(inventory)
        total_disconnected = sum(len(v) for v in site_disconnected.values())
        total_non_compliant = sum(len(v) for v in site_non_compliant.values())
        total_mixed_sites = sum(
            1 for sid in site_fw_versions if len(site_fw_versions[sid]) > 1
        )

        # ── 6. Score and summarise ───────────────────────────────────────────
        score    = self.score_from_findings(all_findings)
        severity = self.severity_from_score(score)

        if not all_findings:
            summary = (
                f"{total_aps} APs inventoried across {len(site_ap_counts)} sites — "
                f"firmware consistent, all connected."
            )
        else:
            parts = []
            if total_disconnected:
                parts.append(f"{total_disconnected} disconnected")
            if total_non_compliant:
                parts.append(f"{total_non_compliant} non-compliant firmware")
            if total_mixed_sites:
                parts.append(f"{total_mixed_sites} sites with mixed versions")
            summary = (
                f"{total_aps} APs across {len(site_ap_counts)} sites — "
                + ", ".join(parts) + "."
            )

        return ModuleOutput(
            module_id=self.module_id,
            display_name=self.display_name,
            icon=self.icon,
            score=score,
            severity=severity,
            summary=summary,
            findings=all_findings,
            sites=site_results,
            status="ok",
        )
