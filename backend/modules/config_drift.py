"""
Config Drift Detective
======================
Detects SSID configuration drift across sites and VLAN collisions
within sites. Classifies SSID families and recommends consolidation
using Mist WLAN Templates and Variables.

Checks performed:
  1. SSID Family Diff       — groups all WLANs by name, diffs config fields
  2. Template Compliance    — flags SSIDs not using templates when they could
  3. VLAN Collision Audit   — detects multiple SSIDs on the same VLAN per site
  4. Security Boundary Check— open + authenticated SSIDs on same VLAN
"""

import asyncio
import logging
from collections import defaultdict
from itertools import combinations
from typing import Any

from models import ModuleOutput, Finding, Severity, SiteResult
from mist_client import MistClient
from .base import BaseModule
from ._mist_urls import org_config_url, templates_url, wlan_fix_url, wlan_template_url

logger = logging.getLogger(__name__)

# ── Field classification ────────────────────────────────────────────────────

# Fields where ANY difference across sites = CRITICAL finding
CRITICAL_DIFF_FIELDS = {
    "auth":                "Security type",
    "auth_servers":        "RADIUS auth servers",
    "acct_servers":        "RADIUS accounting servers",
    "security":            "Security policy",
    "wpa_mode":            "WPA mode",
    "disable_pmf":         "PMF setting",
    "enable_local_keying": "Local keying",
}

# Fields where differences = WARNING (often intentional, but worth flagging)
WARNING_DIFF_FIELDS = {
    "vlan_id":          "VLAN ID",
    "vlan_ids":         "VLAN pool",
    "dynamic_vlan":     "Dynamic VLAN",
    "band":             "Band enablement",
    "hide_ssid":        "Hide SSID",
    "interface":        "Network interface",
    "roam_mode":        "Roam mode",
    "client_limit_up":  "Client upload limit",
    "client_limit_down":"Client download limit",
    "rateset":          "Rate set",
}

# Fields that are EXPECTED to differ — prime Mist Variable candidates
VARIABLE_CANDIDATE_FIELDS = {"vlan_id", "vlan_ids", "auth_servers", "acct_servers"}

# Auth types ranked by security level (lower = less secure)
AUTH_SECURITY_RANK = {
    "open":   0,
    "psk":    1,
    "psk2":   1,
    "wpa2":   1,
    "eap":    2,
    "eap192": 2,
    "8021x":  2,
}


def _auth_rank(auth_type: str) -> int:
    return AUTH_SECURITY_RANK.get((auth_type or "open").lower(), 0)


def _is_open(auth_type: str) -> bool:
    return (auth_type or "open").lower() == "open"


def _get_auth_type(wlan: dict) -> str:
    """Extract auth type string from wlan — handles both string and dict auth field."""
    auth = wlan.get("auth", "open")
    if isinstance(auth, dict):
        return auth.get("type", "open")
    return auth or "open"


def _get_vlan(wlan: dict) -> int | None:
    vid = wlan.get("vlan_id")
    if vid is not None:
        try:
            return int(vid)
        except (ValueError, TypeError):
            pass
    return None


def _field_val(wlan: dict, field: str) -> Any:
    val = wlan.get(field)
    if val == "" or val == []:
        return None
    return val


def _suggest_variable_name(field: str) -> str:
    mapping = {
        "vlan_id":      "vlan_id",
        "vlan_ids":     "vlan_ids",
        "auth_servers": "radius_auth_server",
        "acct_servers": "radius_acct_server",
    }
    return mapping.get(field, field)


# ── SSID Family Analysis ────────────────────────────────────────────────────

def _build_ssid_family(name: str, instances: list[dict],
                       portal_base: str = "", org_id: str = "") -> list[Finding]:
    findings = []
    if len(instances) < 2:
        return findings

    for field, label in CRITICAL_DIFF_FIELDS.items():
        values = {str(_field_val(w, field)) for w in instances}
        values.discard("None")
        if len(values) > 1:
            site_names = [w.get("_site_name", "org-level") for w in instances]
            raw_vals = {w.get("_site_name", "org"): _field_val(w, field) for w in instances}
            findings.append(Finding(
                severity=Severity.critical,
                title=f'"{name}" — {label} inconsistency',
                detail=(
                    f'SSID "{name}" has different {label} settings across '
                    f'{len(instances)} locations. This is likely unintentional '
                    f'and may create security inconsistencies.'
                ),
                affected=site_names,
                recommendation=(
                    f'Consolidate "{name}" into a single WLAN Template. '
                    f'If {label} must differ by site, consider whether these '
                    f'should be separate SSIDs with distinct names.'
                ),
                raw={"field": field, "values": raw_vals},
                fix_url=(
                    templates_url(portal_base, org_id)
                    if portal_base and org_id else None
                ),
            ))

    for field, label in WARNING_DIFF_FIELDS.items():
        values = {str(_field_val(w, field)) for w in instances}
        values.discard("None")
        if len(values) > 1:
            is_variable_candidate = field in VARIABLE_CANDIDATE_FIELDS
            site_vals = {w.get("_site_name", "org"): _field_val(w, field) for w in instances}
            findings.append(Finding(
                severity=Severity.warning,
                title=f'"{name}" — {label} differs across sites',
                detail=(
                    f'SSID "{name}" has {len(values)} different {label} values '
                    f'across {len(instances)} sites.'
                ),
                affected=list(site_vals.keys()),
                recommendation=(
                    f'Use Mist Variable {{{{ {_suggest_variable_name(field)} }}}} '
                    f'in the WLAN Template to handle per-site {label} differences.'
                ) if is_variable_candidate else (
                    f'Review whether {label} differences are intentional. '
                    f'If not, standardise via WLAN Template.'
                ),
                raw={"field": field, "values": site_vals},
            ))

    # All fields identical — template-ready opportunity
    if not findings:
        site_names = [w.get("_site_name", "org-level") for w in instances]
        findings.append(Finding(
            severity=Severity.info,
            title=f'"{name}" — identical across sites, not using a template',
            detail=(
                f'SSID "{name}" has identical configuration across '
                f'{len(instances)} sites but is defined separately at each site. '
                f'This creates unnecessary configuration debt.'
            ),
            affected=site_names,
            recommendation=(
                f'Consolidate "{name}" into a single WLAN Template. '
                f'No variables needed — all settings are identical.'
            ),
        ))

    return findings


# ── VLAN Collision Analysis ─────────────────────────────────────────────────

def _check_vlan_collisions(site_name: str, site_id: str, wlans: list[dict],
                           portal_base: str = "", org_id: str = "") -> list[Finding]:
    findings = []

    vlan_groups: dict[int, list[dict]] = defaultdict(list)
    for w in wlans:
        vid = _get_vlan(w)
        if vid is not None:
            vlan_groups[vid].append(w)

    for vlan_id, group in vlan_groups.items():
        if len(group) < 2:
            continue

        for w1, w2 in combinations(group, 2):
            auth1 = _get_auth_type(w1)
            auth2 = _get_auth_type(w2)
            ssid1 = w1.get("ssid", w1.get("id", "unknown"))
            ssid2 = w2.get("ssid", w2.get("id", "unknown"))
            iso1  = w1.get("client_isolation", False)
            iso2  = w2.get("client_isolation", False)
            both_isolated = iso1 and iso2
            rank1 = _auth_rank(auth1)
            rank2 = _auth_rank(auth2)

            if _is_open(auth1) or _is_open(auth2):
                severity = Severity.warning if both_isolated else Severity.critical
                issue = "open authentication SSID shares a VLAN"
                risk = (
                    f'"{ssid1}" ({auth1}) and "{ssid2}" ({auth2}) are both on '
                    f'VLAN {vlan_id}. Open-auth clients are Layer 2 adjacent to '
                    f'authenticated clients. '
                    f'{"Client isolation is enabled on both SSIDs, reducing but not eliminating risk." if both_isolated else "Client isolation is NOT enabled — direct client-to-client traffic is possible."}'
                )
                rec = (
                    f'Move "{ssid2 if _is_open(auth1) else ssid1}" to a dedicated VLAN. '
                    f'{"Enable client isolation on both SSIDs as interim mitigation." if not both_isolated else "Consider dedicated VLANs regardless — client isolation does not prevent all attack vectors."}'
                )

            elif abs(rank1 - rank2) >= 1:
                severity = Severity.warning if not both_isolated else Severity.info
                issue = "mixed authentication strength on same VLAN"
                risk = (
                    f'"{ssid1}" ({auth1}) and "{ssid2}" ({auth2}) share VLAN {vlan_id}. '
                    f'PSK clients are Layer 2 adjacent to 802.1X-authenticated clients, '
                    f'undermining the stronger authentication boundary. '
                    f'{"Client isolation active on both." if both_isolated else "Client isolation is NOT enabled."}'
                )
                rec = (
                    f'Move the PSK SSID "{ssid1 if rank1 < rank2 else ssid2}" to its own VLAN '
                    f'to enforce a proper security boundary between PSK and 802.1X clients.'
                )

            else:
                severity = Severity.info
                issue = "multiple SSIDs on the same VLAN"
                risk = (
                    f'"{ssid1}" and "{ssid2}" both use VLAN {vlan_id} with similar '
                    f'auth ({auth1}). Clients from both SSIDs share the same broadcast '
                    f'domain. Different PSK passphrases do NOT provide network segmentation.'
                )
                rec = (
                    f'If these SSIDs serve different user populations, assign them '
                    f'separate VLANs. Different PSK values do not create a security boundary.'
                )

            findings.append(Finding(
                severity=severity,
                title=f'VLAN {vlan_id} collision — {issue}',
                detail=risk,
                site_id=site_id,
                site_name=site_name,
                affected=[ssid1, ssid2, f"VLAN {vlan_id}"],
                recommendation=rec,
                raw={
                    "vlan_id": vlan_id,
                    "ssid1": ssid1, "auth1": auth1, "isolated1": iso1,
                    "ssid2": ssid2, "auth2": auth2, "isolated2": iso2,
                },
                fix_url=(
                    wlan_fix_url(portal_base, org_id, w1 if _is_open(auth1) else w2)
                    if severity == Severity.critical and portal_base and org_id else None
                ),
            ))

    return findings


# ── Module ──────────────────────────────────────────────────────────────────

class ConfigDriftModule(BaseModule):
    module_id    = "config_drift"
    display_name = "Config Drift Detective"
    icon         = "🔍"

    async def analyze(self, org_id: str, sites: list[dict], client: MistClient) -> ModuleOutput:

        NULL_SITE_ID = "00000000-0000-0000-0000-000000000000"

        # 1. Fetch derived WLANs per site + wlan templates in parallel
        # /wlans/derived returns fully scope-resolved WLANs including template-pushed ones
        results = await asyncio.gather(
            client.get_wlan_templates(org_id),
            *[client.get_site_wlans_derived(site["id"]) for site in sites],
            return_exceptions=True,
        )

        wlan_templates  = results[0] if not isinstance(results[0], Exception) else []
        site_wlan_lists = results[1:]

        templated_ssid_names = {
            wlan.get("ssid")
            for tmpl in wlan_templates
            for wlan in tmpl.get("wlans", [])
        }

        annotated_site_wlans: dict[str, list[dict]] = {}
        all_findings: list[Finding] = []

        for site, wlan_list in zip(sites, site_wlan_lists):
            if isinstance(wlan_list, Exception):
                logger.warning(f"Could not fetch WLANs for site {site['id']}: {wlan_list}")
                continue

            site_id   = site["id"]
            site_name = site.get("name", site_id)

            for wlan in wlan_list:
                wlan_site_id = wlan.get("site_id", NULL_SITE_ID)
                is_local     = wlan_site_id not in (NULL_SITE_ID, None, "")
                wlan["_site_name"] = site_name
                wlan["_site_id"]   = site_id
                wlan["_source"]    = "site-local" if is_local else "template"
                wlan["_is_local"]  = is_local

            annotated_site_wlans[site_id] = wlan_list

            # ── Check: site-local WLANs (not template-pushed) ────────────────
            local_wlans = [w for w in wlan_list if w.get("_is_local")]
            if local_wlans:
                local_ssids = [w.get("ssid", w.get("id", "unknown")) for w in local_wlans]
                all_findings.append(Finding(
                    severity=Severity.warning,
                    title=f"{site_name} — {len(local_wlans)} site-local WLAN(s) not using templates",
                    detail=(
                        f"{len(local_wlans)} WLAN(s) at {site_name} are configured directly "
                        f"at the site level rather than being pushed from a WLAN template: "
                        f"{', '.join(local_ssids)}. "
                        f"Site-local WLANs create configuration drift risk — changes must "
                        f"be made individually per site rather than centrally."
                    ),
                    site_id=site_id,
                    site_name=site_name,
                    affected=local_ssids,
                    recommendation=(
                        "Migrate site-local WLANs into a WLAN Template and push to sites. "
                        "Use Mist Variables (e.g. {{vlan_id}}) for any per-site differences. "
                        "This enables consistent config governance and reduces operational overhead."
                    ),
                    fix_url=wlan_fix_url(client.portal_base, org_id, local_wlans[0]),
                ))

        # 2. SSID Family Analysis — using derived WLANs per site
        family_map: dict[str, list[dict]] = defaultdict(list)
        for wlan_list in annotated_site_wlans.values():
            for wlan in wlan_list:
                if wlan.get("ssid"):
                    family_map[wlan["ssid"]].append(wlan)

        for ssid_name, instances in family_map.items():
            if ssid_name in templated_ssid_names:
                continue
            if len(instances) > 1:
                all_findings.extend(_build_ssid_family(
                    ssid_name, instances,
                    portal_base=client.portal_base, org_id=org_id,
                ))

        # 3. VLAN Collision Analysis (per site)
        site_results: list[SiteResult] = []
        for site in sites:
            site_id   = site["id"]
            site_name = site.get("name", site_id)
            wlans     = annotated_site_wlans.get(site_id, [])
            if not wlans:
                continue
            collision_findings = _check_vlan_collisions(
                site_name, site_id, wlans,
                portal_base=client.portal_base, org_id=org_id,
            )
            all_findings.extend(collision_findings)
            site_score = self.score_from_findings(collision_findings)
            site_results.append(SiteResult(
                site_id=site_id,
                site_name=site_name,
                score=site_score,
                severity=self.severity_from_score(site_score),
                findings=collision_findings,
            ))

        # 4. Score and summarise
        score    = self.score_from_findings(all_findings)
        severity = self.severity_from_score(score)

        critical_count = sum(1 for f in all_findings if f.severity == Severity.critical)
        warning_count  = sum(1 for f in all_findings if f.severity == Severity.warning)
        info_count     = sum(1 for f in all_findings if f.severity == Severity.info)
        family_count   = sum(
            1 for n, i in family_map.items()
            if len(i) > 1 and n not in templated_ssid_names
        )

        if not all_findings:
            summary = f"No drift or VLAN collisions detected across {len(sites)} sites."
        else:
            parts = []
            if critical_count: parts.append(f"{critical_count} critical")
            if warning_count:  parts.append(f"{warning_count} warnings")
            if info_count:     parts.append(f"{info_count} info")
            summary = (
                f"{family_count} SSID families analyzed — "
                + ", ".join(parts)
                + f" across {len(sites)} sites."
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
