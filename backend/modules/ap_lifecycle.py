"""
AP Lifecycle Monitor
====================
Inventories every AP across the org and identifies infrastructure
health issues requiring attention. Mirrors Mist's own Version Compliance
logic — per-model, per-site firmware analysis.

Checks performed:
  1. Auto Update disabled      — primary finding, sites with no automated
                                 firmware remediation path
  2. Same-model mixing         — per-site: APs of the same model running
                                 different firmware versions (something
                                 interrupted the upgrade). Cross-model
                                 differences are expected and NOT flagged.
  3. Disconnected APs          — APs not connected to Mist cloud
  4. EOL hardware              — known End-of-Sale model families

Autonomy levels:
  L1 — Detects all four conditions above
  L2 — Per-model per-site analysis, identifies which models/versions differ
  L3 — References Marvis Self-Driving Actions as the remediation path
"""

import asyncio
import logging
from collections import defaultdict, Counter

from models import ModuleOutput, Finding, Severity, SiteResult
from mist_client import MistClient
from .base import BaseModule
from ._mist_urls import ap_detail_url, org_config_url

logger = logging.getLogger(__name__)

# Known EOL/EOS model prefixes — update as Juniper publishes notices
EOL_MODELS: dict[str, str] = {
    "AP21":  "AP21 is End of Sale. Plan migration to AP32 or AP43.",
    "AP12":  "AP12 is End of Sale. Plan migration to current portfolio.",
    "AP32E": "AP32E is End of Sale.",
    "BT11":  "BT11 (BLE gateway) is End of Sale.",
}


def _model_prefix(model: str) -> str:
    return model.split("-")[0] if model else ""


def _firmware_sort_key(version: str) -> tuple:
    """Parse Mist firmware version strings for comparison."""
    try:
        parts = version.replace("-", ".").split(".")
        return tuple(int(p) for p in parts if p.isdigit())
    except Exception:
        return (0,)


class APLifecycleModule(BaseModule):
    module_id    = "ap_lifecycle"
    display_name = "AP Lifecycle Monitor"
    icon         = "🔄"

    # ── L3 Marvis automation stub ────────────────────────────────────────────
    # When ready to enable autonomous remediation:
    #   1. Uncomment the call to _enable_marvis_non_compliant() in analyze()
    #   2. The Mist API will enable the Marvis Self-Driving Action for that site
    #      which automatically upgrades non-compliant APs during the maintenance window
    #
    # async def _enable_marvis_non_compliant(self, site_id: str, client: MistClient) -> None:
    #     """Enable Marvis Self-Driving Action: Wireless > Non-Compliant for a site."""
    #     await client.put(
    #         f"/api/v1/sites/{site_id}/setting",
    #         body={"marvis": {"auto_operations": {"ap_non_compliant": True}}}
    #     )

    async def analyze(self, org_id: str, sites: list[dict], client: MistClient) -> ModuleOutput:

        # ── 1. Fetch inventory + site settings in parallel ───────────────────
        inventory_task = client.get_org_inventory(org_id, device_type="ap")
        settings_tasks = [
            client.get(f"/api/v1/sites/{site['id']}/setting", use_cache=True)
            for site in sites
        ]

        results = await asyncio.gather(
            inventory_task, *settings_tasks, return_exceptions=True
        )

        inventory     = results[0] if not isinstance(results[0], Exception) else []
        site_settings_list = results[1:]

        # Build site maps
        site_map      = {s["id"]: s.get("name", s["id"]) for s in sites}
        site_settings: dict[str, dict] = {}
        for site, setting in zip(sites, site_settings_list):
            if not isinstance(setting, Exception):
                site_settings[site["id"]] = setting

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

        # ── 2. Build per-site, per-model firmware map ────────────────────────
        # site_model_firmware[site_id][model] = [fw_version, ...]
        site_model_firmware: dict[str, dict[str, list[str]]] = defaultdict(
            lambda: defaultdict(list)
        )
        site_disconnected: dict[str, list[str]]  = defaultdict(list)
        # Keep (name, device_id) pairs for disconnected APs so we can deep-link
        # to the AP detail page in Mist. device_id comes from inventory 'id'.
        site_disconnected_meta: dict[str, list[tuple[str, str]]] = defaultdict(list)
        site_eol:          dict[str, list[str]]  = defaultdict(list)
        site_ap_counts:    dict[str, int]        = defaultdict(int)

        for ap in inventory:
            site_id   = ap.get("site_id")
            if not site_id:
                continue

            ap_name   = ap.get("name") or ap.get("hostname") or ap.get("mac", "unknown")
            device_id = ap.get("id", "")
            model     = ap.get("model", "unknown")
            firmware  = ap.get("firmware", ap.get("version", ""))
            connected = ap.get("connected", False)

            site_ap_counts[site_id] += 1

            if not connected:
                site_disconnected[site_id].append(ap_name)
                site_disconnected_meta[site_id].append((ap_name, device_id))

            if firmware and model:
                site_model_firmware[site_id][model].append(firmware)

            prefix = _model_prefix(model)
            if prefix in EOL_MODELS:
                site_eol[site_id].append(f"{ap_name} ({model})")

        # ── 3. Build per-site findings ───────────────────────────────────────
        all_findings: list[Finding] = []
        site_results: list[SiteResult] = []

        for site in sites:
            site_id   = site["id"]
            site_name = site.get("name", site_id)
            ap_count  = site_ap_counts.get(site_id, 0)

            if ap_count == 0:
                continue

            site_findings: list[Finding] = []
            setting       = site_settings.get(site_id, {})
            auto_upgrade  = setting.get("auto_upgrade", {})
            upgrade_enabled = auto_upgrade.get("enabled", False)

            # ── Check 1: Auto Update disabled ────────────────────────────────
            if not upgrade_enabled:
                site_findings.append(Finding(
                    severity=Severity.warning,
                    title=f"{site_name} — AP Auto Update is disabled",
                    detail=(
                        f"Firmware Auto Update is not enabled for this site. "
                        f"{ap_count} APs will not receive firmware updates automatically. "
                        f"Without auto-update, APs fall behind over time with no "
                        f"remediation path until manually addressed."
                    ),
                    site_id=site_id,
                    site_name=site_name,
                    affected=[f"{ap_count} APs"],
                    recommendation=(
                        "Enable Auto Update under Organization > Site Configuration > "
                        "AP Firmware Upgrade. Choose 'Auto upgrade to production firmware' "
                        "and set an upgrade window during off-hours (e.g. Sunday 2:00 AM)."
                    ),
                ))

            # ── Check 2: Same-model firmware mixing ──────────────────────────
            # Only flag when APs of the SAME model run different versions at
            # the same site. Cross-model version differences are expected.
            model_firmware = site_model_firmware.get(site_id, {})
            for model, versions in model_firmware.items():
                unique_versions = set(versions)
                if len(unique_versions) <= 1:
                    continue  # All APs of this model are on the same version

                counter      = Counter(versions)
                majority_fw  = counter.most_common(1)[0][0]
                outliers     = [
                    f"{ap.get('name') or ap.get('mac', 'unknown')} ({ap.get('firmware', ap.get('version', ''))})"
                    for ap in inventory
                    if ap.get("site_id") == site_id
                    and ap.get("model") == model
                    and ap.get("firmware", ap.get("version", "")) != majority_fw
                    and ap.get("firmware", ap.get("version", ""))
                ]
                sorted_versions = sorted(unique_versions, key=_firmware_sort_key, reverse=True)

                site_findings.append(Finding(
                    severity=Severity.warning,
                    title=f"{site_name} — {model}: {len(unique_versions)} firmware versions",
                    detail=(
                        f"{len(versions)} {model} APs at this site are running "
                        f"{len(unique_versions)} different firmware versions: "
                        f"{', '.join(sorted_versions)}. "
                        f"Majority version is {majority_fw}. "
                        f"{len(outliers)} AP(s) are on non-majority versions. "
                        f"Mixed same-model firmware is often caused by APs being "
                        f"offline during a scheduled upgrade window."
                    ),
                    site_id=site_id,
                    site_name=site_name,
                    affected=outliers[:10],
                    recommendation=(
                        f"Verify the {len(outliers)} outlier AP(s) are connected and "
                        f"will be included in the next upgrade window. "
                        f"Marvis Self-Driving Action: Wireless > Non-Compliant can "
                        f"automatically remediate this during the site maintenance window."
                    ),
                    raw={
                        "site_id":      site_id,
                        "model":        model,
                        "majority_fw":  majority_fw,
                        "outlier_count": len(outliers),
                        # L3 stub — Marvis auto_operations payload ready to fire
                        # To enable: PUT /api/v1/sites/{site_id}/setting
                        # with body: {"marvis": {"auto_operations": {"ap_non_compliant": true}}}
                        # Uncomment _enable_marvis_non_compliant() call below when ready
                        "_l3_action": "marvis_ap_non_compliant",
                        "_l3_ready":  True,
                    },
                ))

            # ── Check 3: Disconnected APs ────────────────────────────────────
            disconnected = site_disconnected.get(site_id, [])
            if disconnected:
                severity = (
                    Severity.critical if len(disconnected) > ap_count * 0.25
                    else Severity.warning
                )
                # On critical findings, deep-link to the first disconnected AP's
                # detail page so operators can see its event log directly.
                fix_url = None
                if severity == Severity.critical:
                    meta = site_disconnected_meta.get(site_id, [])
                    if meta and meta[0][1]:
                        first_device_id = meta[0][1]
                        fix_url = ap_detail_url(client.portal_base, org_id, first_device_id, site_id)

                site_findings.append(Finding(
                    severity=severity,
                    title=f"{site_name} — {len(disconnected)} AP(s) disconnected",
                    detail=(
                        f"{len(disconnected)} of {ap_count} APs at this site are not "
                        f"connected to the Mist cloud. Disconnected APs cannot be "
                        f"managed, monitored, or receive firmware updates."
                    ),
                    site_id=site_id,
                    site_name=site_name,
                    affected=disconnected[:10],
                    recommendation=(
                        "Check AP uplink connectivity and PoE status. "
                        "Review AP events in Mist for disconnect reason. "
                        "Verify LLDP/CDP on connected switch ports."
                    ),
                    fix_url=fix_url,
                ))

            # ── Check 4: EOL hardware ────────────────────────────────────────
            eol_aps = site_eol.get(site_id, [])
            if eol_aps:
                site_findings.append(Finding(
                    severity=Severity.info,
                    title=f"{site_name} — {len(eol_aps)} EOL AP model(s)",
                    detail=(
                        f"{len(eol_aps)} AP(s) at this site are End-of-Sale hardware. "
                        f"These models will not receive future feature updates."
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

        # ── 4. Score and summarise ───────────────────────────────────────────
        total_aps          = len(inventory)
        sites_no_autoupdate = sum(
            1 for sid in site_ap_counts
            if not site_settings.get(sid, {}).get("auto_upgrade", {}).get("enabled", False)
        )
        total_disconnected  = sum(len(v) for v in site_disconnected.values())
        total_mixed_models  = sum(
            1 for sid in site_model_firmware
            for versions in site_model_firmware[sid].values()
            if len(set(versions)) > 1
        )

        score    = self.score_from_findings(all_findings)
        severity = self.severity_from_score(score)

        if not all_findings:
            summary = (
                f"{total_aps} APs across {len(site_ap_counts)} sites — "
                f"auto-update enabled, firmware consistent, all connected."
            )
        else:
            parts = []
            if sites_no_autoupdate:
                parts.append(f"{sites_no_autoupdate} sites with auto-update off")
            if total_disconnected:
                parts.append(f"{total_disconnected} disconnected APs")
            if total_mixed_models:
                parts.append(f"{total_mixed_models} same-model firmware conflicts")
            summary = f"{total_aps} APs — " + ", ".join(parts) + "."

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
