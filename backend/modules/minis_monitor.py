"""
MinisMonitor — Marvis Minis Health & Readiness
===============================================
Audits Marvis Minis configuration, subscription readiness, and AP firmware
compatibility across the org. Surfaces configuration gaps and readiness
issues that would prevent Minis from running effectively.

⚠️  TEST REMINDER: Minis test result data (pass/fail per test run) requires
    a production org with an active SUB-VNA (Marvis for Wireless) subscription
    and APs running firmware ≥ 0.14.29313. Validate this module against a
    production org before marking complete.

Checks performed:
  1. SUB-VNA entitlement         — Marvis subscription required for Minis
  2. Minis enabled at org level  — synthetic_test.disabled flag
  3. Custom probes configured    — at least one application probe defined
  4. WAN speedtest enabled       — wan_speedtest.enabled flag
  5. AP firmware gate            — APs running firmware ≥ 0.14.29313
  6. Per-site Minis disabled     — sites with explicit synthetic_test.disabled

API endpoints used:
  GET /api/v1/orgs/{org_id}/licenses
  GET /api/v1/orgs/{org_id}/setting
  GET /api/v1/sites/{site_id}/setting
  GET /api/v1/orgs/{org_id}/inventory (AP firmware via existing helper)
"""

import asyncio
import logging

from models import ModuleOutput, Finding, Severity
from mist_client import MistClient, MistAPIError
from .base import BaseModule
from ._mist_urls import subscriptions_url, org_config_url

logger = logging.getLogger(__name__)

# Minimum AP firmware version for Minis support
MINIS_MIN_FIRMWARE = "0.14.29313"

# VNA subscription SKU required for Minis
VNA_SKU = "SUB-VNA"


def _firmware_meets_minimum(firmware: str, minimum: str) -> bool:
    """Compare Mist firmware version strings."""
    try:
        # Mist firmware: 0.14.29313 or 0.14.29313-1 style
        fw_clean  = firmware.split("-")[0]
        min_clean = minimum.split("-")[0]
        fw_parts  = tuple(int(x) for x in fw_clean.split("."))
        min_parts = tuple(int(x) for x in min_clean.split("."))
        return fw_parts >= min_parts
    except Exception:
        return False  # Unknown format — treat as non-compliant


class MinisMonitorModule(BaseModule):
    module_id    = "minis_monitor"
    display_name = "MinisMonitor"
    icon         = "🤖"

    async def analyze(self, org_id: str, sites: list[dict], client: MistClient) -> ModuleOutput:

        # ── 1. Fetch data in parallel ────────────────────────────────────────
        license_task  = client.get(f"/api/v1/orgs/{org_id}/licenses", use_cache=False)
        org_setting_task = client.get(f"/api/v1/orgs/{org_id}/setting", use_cache=True)
        inventory_task = client.get_org_inventory(org_id, device_type="ap")
        site_setting_tasks = [
            client.get(f"/api/v1/sites/{site['id']}/setting", use_cache=True)
            for site in sites
        ]

        results = await asyncio.gather(
            license_task,
            org_setting_task,
            inventory_task,
            *site_setting_tasks,
            return_exceptions=True,
        )

        license_data  = results[0] if not isinstance(results[0], Exception) else {}
        org_setting   = results[1] if not isinstance(results[1], Exception) else {}
        inventory     = results[2] if not isinstance(results[2], Exception) else []
        site_settings = results[3:]

        findings: list[Finding] = []

        # ── 2. Check SUB-VNA entitlement ─────────────────────────────────────
        entitled = license_data.get("entitled", {})
        vna_entitled = entitled.get(VNA_SKU, 0)

        if vna_entitled == 0:
            findings.append(Finding(
                severity=Severity.critical,
                title="SUB-VNA not entitled — Marvis Minis requires Marvis subscription",
                detail=(
                    "No active SUB-VNA (Virtual Network Assistant / Marvis for Wireless) "
                    "entitlement found. Marvis Minis requires an active Marvis subscription "
                    "to run synthetic tests. Without this subscription, Minis will not "
                    "execute any validation tests."
                ),
                recommendation=(
                    "Purchase SUB-VNA licenses for all APs in the org. "
                    "Contact your Juniper/HPE account team to add Marvis for Wireless "
                    "to your subscription."
                ),
                fix_url=subscriptions_url(client.portal_base, org_id),
            ))

        # ── 3. Check org-level Minis enabled ────────────────────────────────
        synthetic_test = org_setting.get("synthetic_test", {})
        minis_disabled = synthetic_test.get("disabled", False)

        if minis_disabled:
            findings.append(Finding(
                severity=Severity.critical,
                title="Marvis Minis is disabled at the org level",
                detail=(
                    "The org-level setting has Marvis Minis explicitly disabled. "
                    "No synthetic tests will run across any site until this is re-enabled."
                ),
                recommendation=(
                    "Enable Marvis Minis under Organization > Settings > Marvis Minis. "
                    "Or via API: PUT /api/v1/orgs/{org_id}/setting with "
                    "{\"synthetic_test\": {\"disabled\": false}}."
                ),
                fix_url=org_config_url(client.portal_base, org_id),
            ))

        # ── 4. Check custom probes configured ────────────────────────────────
        custom_probes = synthetic_test.get("custom_probes", {})
        tests         = synthetic_test.get("tests", [])

        if not minis_disabled:
            if not custom_probes:
                findings.append(Finding(
                    severity=Severity.warning,
                    title="No custom application probes configured",
                    detail=(
                        "Marvis Minis has no custom application probes defined. "
                        "While Minis will still test basic connectivity (DHCP, DNS, ARP), "
                        "application reachability testing requires at least one custom probe "
                        "targeting a business-critical application or URL."
                    ),
                    recommendation=(
                        "Add custom probes under Organization > Settings > Marvis Minis. "
                        "Define targets for business-critical applications "
                        "(e.g., ERP, cloud services, internal portals)."
                    ),
                ))
            else:
                # Report probe summary as info
                probe_types = {}
                for name, probe in custom_probes.items():
                    ptype = probe.get("type", "unknown")
                    probe_types.setdefault(ptype, []).append(name)

                probe_summary = ", ".join(
                    f"{len(v)} {k}" for k, v in probe_types.items()
                )
                findings.append(Finding(
                    severity=Severity.info,
                    title=f"{len(custom_probes)} custom probe(s) configured: {probe_summary}",
                    detail=(
                        f"Custom probes defined: {', '.join(custom_probes.keys())}. "
                        f"These probes will be tested on configured VLANs and LAN networks."
                    ),
                    recommendation=(
                        "Periodically review probe targets to ensure they reflect "
                        "current business-critical applications."
                    ),
                ))

        # ── 5. Check WAN speedtest ────────────────────────────────────────────
        wan_speedtest = synthetic_test.get("wan_speedtest", {})
        if not minis_disabled and not wan_speedtest.get("enabled", False):
            findings.append(Finding(
                severity=Severity.info,
                title="WAN speedtest not enabled",
                detail=(
                    "Marvis Minis WAN speedtest is not enabled. "
                    "Enabling this provides baseline WAN performance metrics "
                    "and helps Marvis correlate WAN degradation with user experience issues."
                ),
                recommendation=(
                    "Enable WAN speedtest under Organization > Settings > Marvis Minis "
                    "and set a preferred time of day (e.g., off-hours)."
                ),
            ))

        # ── 6. Check AP firmware gate ─────────────────────────────────────────
        non_compliant_aps: list[str] = []
        compliant_count   = 0
        total_ap_count    = 0

        for ap in inventory:
            firmware = ap.get("firmware", ap.get("version", ""))
            ap_name  = ap.get("name") or ap.get("hostname") or ap.get("mac", "unknown")
            model    = ap.get("model", "")

            if not firmware:
                continue

            total_ap_count += 1

            if _firmware_meets_minimum(firmware, MINIS_MIN_FIRMWARE):
                compliant_count += 1
            else:
                non_compliant_aps.append(f"{ap_name} ({model}) — {firmware}")

        if non_compliant_aps:
            findings.append(Finding(
                severity=Severity.warning,
                title=f"{len(non_compliant_aps)} AP(s) below minimum Minis firmware",
                detail=(
                    f"{len(non_compliant_aps)} of {total_ap_count} APs are running firmware "
                    f"older than {MINIS_MIN_FIRMWARE}, the minimum required for Marvis Minis. "
                    f"These APs cannot participate in Minis synthetic tests until upgraded."
                ),
                affected=non_compliant_aps[:10],
                recommendation=(
                    f"Upgrade affected APs to firmware ≥ {MINIS_MIN_FIRMWARE}. "
                    f"Enable Auto Update under Site Configuration to keep APs current. "
                    f"Once all APs in a site are on qualifying firmware, Minis tests "
                    f"begin automatically within ~1 hour."
                ),
            ))

        # ── 7. Check per-site Minis disabled ─────────────────────────────────
        site_map = {s["id"]: s.get("name", s["id"]) for s in sites}
        sites_disabled: list[str] = []

        for site, setting in zip(sites, site_settings):
            if isinstance(setting, Exception):
                continue
            site_synthetic = setting.get("synthetic_test", {})
            if site_synthetic.get("disabled", False):
                sites_disabled.append(site_map.get(site["id"], site["id"]))

        if sites_disabled:
            findings.append(Finding(
                severity=Severity.warning,
                title=f"{len(sites_disabled)} site(s) have Minis explicitly disabled",
                detail=(
                    f"The following sites have Marvis Minis disabled at the site level, "
                    f"overriding the org default: {', '.join(sites_disabled)}. "
                    f"No synthetic tests will run at these sites."
                ),
                affected=sites_disabled,
                recommendation=(
                    "Review whether Minis should be re-enabled at these sites. "
                    "Site-level disable is appropriate only for sites with limited AP "
                    "resources or specific operational constraints."
                ),
            ))

        # ── 8. Score and summarize ────────────────────────────────────────────
        score    = self.score_from_findings(findings)
        severity = self.severity_from_score(score)

        # Build summary
        if vna_entitled == 0:
            summary = (
                "⚠️ No SUB-VNA entitlement — Minis requires Marvis subscription. "
                "Test results unavailable; validate against a production org with SUB-VNA."
            )
        elif minis_disabled:
            summary = "Marvis Minis is disabled at the org level — no tests running."
        elif not findings or all(f.severity == Severity.info for f in findings):
            summary = (
                f"Minis enabled — {len(custom_probes)} probe(s) configured, "
                f"{compliant_count}/{total_ap_count} APs firmware-ready. "
                f"⚠️ Validate test result data against a production org with active SUB-VNA."
            )
        else:
            parts = []
            if non_compliant_aps:
                parts.append(f"{len(non_compliant_aps)} APs below firmware gate")
            if not custom_probes:
                parts.append("no custom probes")
            if sites_disabled:
                parts.append(f"{len(sites_disabled)} sites disabled")
            summary = (
                "Minis readiness issues: " + ", ".join(parts) + ". "
                "⚠️ Validate test result data against a production org with active SUB-VNA."
            )

        return ModuleOutput(
            module_id=self.module_id,
            display_name=self.display_name,
            icon=self.icon,
            score=score,
            severity=severity,
            summary=summary,
            findings=findings,
            sites=[],
            status="ok",
        )
