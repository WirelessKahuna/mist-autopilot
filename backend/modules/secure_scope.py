"""
SecureScope
===========
Audits every WLAN across the org against wireless security best practices.
Also checks per-site security settings for rogue AP detection.

Checks performed:
  1. Open SSID classification    — severity varies by VLAN and captive portal config
  2. PMF enforcement             — warning when disabled on WPA2/WPA3 SSIDs
  3. PSK reuse across SSID names — same passphrase on differently-named SSIDs
  4. 802.1X misconfiguration     — EAP auth with no RADIUS servers configured
  5. Rogue AP detection          — warning when not enabled at site level
  6. OWE transition mode         — info, educates on why it should be disabled
  7. WPA3 transition mode        — info, educates on why it should be disabled

Open SSID severity ladder:
  Critical: open + no VLAN assigned
  Critical: open + VLAN shared with a protected SSID at same site
  Warning:  open + captive portal with no authentication (click-through)
  Info:     open + captive portal with real authentication (password/email/SSO/etc.)
"""

import asyncio
import logging
from collections import defaultdict

from models import ModuleOutput, Finding, Severity, SiteResult
from mist_client import MistClient
from .base import BaseModule
from ._mist_urls import org_config_url

logger = logging.getLogger(__name__)

# Portal auth types that represent real authentication vs click-through only
AUTHENTICATED_PORTAL_TYPES = {
    "password", "email", "sso", "sponsor",
    "facebook", "google", "amazon", "microsoft",
    "azure", "multi", "external",
}

# Auth types that support/require PMF checks
PMF_APPLICABLE_AUTH = {"psk", "eap", "eap192"}

# Auth types considered "protected" for VLAN collision purposes
PROTECTED_AUTH_TYPES = {"psk", "psk-tkip", "eap", "eap192"}


def _get_vlan_id(wlan: dict) -> int | None:
    if not wlan.get("vlan_enabled", False):
        return None
    vid = wlan.get("vlan_id")
    try:
        return int(vid) if vid is not None else None
    except (ValueError, TypeError):
        return None


def _portal_auth_type(wlan: dict) -> str | None:
    """Return the captive portal auth type, or None if no portal."""
    portal = wlan.get("portal", {})
    if not portal or not portal.get("enabled", False):
        return None
    return portal.get("auth", "none")


def _is_wpa3(wlan: dict) -> bool:
    auth = wlan.get("auth", {})
    pairwise = auth.get("pairwise", [])
    return "wpa3" in pairwise or auth.get("type") in ("eap192",)


class SecureScopeModule(BaseModule):
    module_id    = "secure_scope"
    display_name = "SecureScope"
    icon         = "🔐"

    async def analyze(self, org_id: str, sites: list[dict], client: MistClient) -> ModuleOutput:

        # ── 1. Fetch all WLANs + site settings in parallel ───────────────────
        # Use /wlans/derived for fully scope-resolved WLANs per site
        results = await asyncio.gather(
            *[client.get_site_wlans_derived(site["id"]) for site in sites],
            *[client.get(f"/api/v1/sites/{site['id']}/setting", use_cache=True)
              for site in sites],
            return_exceptions=True,
        )

        n = len(sites)
        site_wlan_lists   = results[:n]
        site_setting_list = results[n:]

        # Build per-site WLAN and settings maps
        site_map      = {s["id"]: s.get("name", s["id"]) for s in sites}
        site_wlans:   dict[str, list[dict]] = {}
        site_settings: dict[str, dict]      = {}

        for site, wlan_list, setting in zip(sites, site_wlan_lists, site_setting_list):
            sid = site["id"]
            if not isinstance(wlan_list, Exception):
                for w in wlan_list:
                    w["_site_id"]   = sid
                    w["_site_name"] = site_map[sid]
                site_wlans[sid] = wlan_list
            if not isinstance(setting, Exception):
                site_settings[sid] = setting

        # ── 2. PSK reuse — build org-wide PSK → SSID name index ─────────────
        # Flag when the same passphrase appears on differently-named SSIDs
        psk_to_ssids: dict[str, set[str]] = defaultdict(set)
        psk_to_sites: dict[str, set[str]] = defaultdict(set)

        all_wlans: list[dict] = []
        for wlan_list in site_wlans.values():
            all_wlans.extend(wlan_list)

        for w in all_wlans:
            auth = w.get("auth", {})
            if auth.get("type") in ("psk", "psk-tkip") and auth.get("psk"):
                psk  = auth["psk"]
                ssid = w.get("ssid", "")
                sid  = w.get("_site_id") or "org"
                psk_to_ssids[psk].add(ssid)
                psk_to_sites[psk].add(site_map.get(sid, sid))

        # PSKs shared across different SSID names
        reused_psks = {
            psk: ssids
            for psk, ssids in psk_to_ssids.items()
            if len(ssids) > 1
        }

        # ── 3. Org-level PSK reuse findings (before site loop) ───────────────
        # All reused PSKs live in org-level WLANs in this org, so we emit
        # findings here rather than inside the per-site loop.
        all_findings: list[Finding] = []
        psk_reuse_findings: list[Finding] = []

        BAND_SUFFIXES = {"2.4", "5", "6", "2", "5ghz", "6ghz", "2.4ghz"}

        def _base(name: str) -> str:
            parts = name.rsplit(" ", 1)
            if len(parts) == 2 and parts[1].lower() in BAND_SUFFIXES:
                return parts[0].strip()
            return name.strip()

        for psk, ssid_set in reused_psks.items():
            # Group SSIDs by their base name — collapse band variants into one
            base_to_ssids: dict[str, list[str]] = defaultdict(list)
            for s in sorted(ssid_set):
                base_to_ssids[_base(s)].append(s)

            # Only count distinct base names — band variants of the same SSID
            # count as one. e.g. "Mist APoS 2.4", "Mist APoS 5", "Mist APoS 6"
            # → one base "Mist APoS", not three distinct SSIDs.
            distinct_bases = list(base_to_ssids.keys())

            if len(distinct_bases) <= 1:
                continue  # all variants of the same SSID — expected, suppress

            # Build display list: use the canonical name (first in sorted group)
            display_ssids = [members[0] if len(members) == 1
                             else f"{members[0]} (+ {len(members)-1} band variant{'s' if len(members)>2 else ''})"
                             for members in base_to_ssids.values()]

            reuse_severity = Severity.critical if len(distinct_bases) > 2 else Severity.warning
            f = Finding(
                severity=reuse_severity,
                title=f"PSK reuse — same passphrase on {len(distinct_bases)} differently-named SSIDs",
                detail=(
                    f"The following SSIDs share an identical passphrase: "
                    f"{', '.join(display_ssids)}. "
                    f"Sharing a PSK across different SSID names allows clients "
                    f"credentialed for one network to authenticate to another, "
                    f"breaking intended access boundaries."
                ),
                site_id=None,
                site_name="org-level",
                affected=display_ssids,
                recommendation=(
                    "Assign a unique passphrase to each distinct SSID. "
                    "Consider Mist Multi-PSK (MPSK) for per-user or per-role "
                    "credential management without passphrase sharing."
                ),
                fix_url=(
                    org_config_url(client.portal_base, org_id)
                    if reuse_severity == Severity.critical else None
                ),
            )
            psk_reuse_findings.append(f)
            all_findings.append(f)

        # ── 4. Analyse per site ──────────────────────────────────────────────
        site_results: list[SiteResult] = []

        for site in sites:
            sid       = site["id"]
            site_name = site_map[sid]
            wlans     = site_wlans.get(sid, [])
            setting   = site_settings.get(sid, {})
            site_findings: list[Finding] = []

            # Build VLAN map for this site: vlan_id → list of SSIDs using it
            vlan_ssid_map: dict[int, list[dict]] = defaultdict(list)
            for w in wlans:
                vid = _get_vlan_id(w)
                if vid is not None:
                    vlan_ssid_map[vid].append(w)

            protected_vlans = {
                _get_vlan_id(w)
                for w in wlans
                if w.get("auth", {}).get("type") in PROTECTED_AUTH_TYPES
                and _get_vlan_id(w) is not None
            }

            for w in wlans:
                ssid      = w.get("ssid", w.get("id", "unknown"))
                auth      = w.get("auth", {})
                auth_type = auth.get("type", "open")

                # ── Check 1: Open SSID ───────────────────────────────────────
                if auth_type == "open":
                    vlan_id     = _get_vlan_id(w)
                    portal_auth = _portal_auth_type(w)

                    if vlan_id is None:
                        site_findings.append(Finding(
                            severity=Severity.critical,
                            title=f'"{ssid}" — open SSID with no VLAN assigned',
                            detail=(
                                f'SSID "{ssid}" is open (no authentication) and has no '
                                f'VLAN assigned. Clients land on the native/untagged VLAN '
                                f'with no segmentation from the rest of the network.'
                            ),
                            site_id=sid,
                            site_name=site_name,
                            affected=[ssid],
                            recommendation=(
                                "Assign a dedicated isolated VLAN to this open SSID immediately. "
                                "Consider adding a captive portal with authentication if this "
                                "SSID is intended for guest access."
                            ),
                            fix_url=org_config_url(client.portal_base, org_id, sid),
                        ))
                    elif vlan_id in protected_vlans:
                        protected_ssids = [
                            w2.get("ssid", "?") for w2 in wlans
                            if _get_vlan_id(w2) == vlan_id
                            and w2.get("auth", {}).get("type") in PROTECTED_AUTH_TYPES
                        ]
                        site_findings.append(Finding(
                            severity=Severity.critical,
                            title=f'"{ssid}" — open SSID shares VLAN {vlan_id} with protected SSIDs',
                            detail=(
                                f'Open SSID "{ssid}" is on VLAN {vlan_id}, which is also '
                                f'used by protected SSID(s): {", ".join(protected_ssids)}. '
                                f'Open clients are Layer 2 adjacent to authenticated clients.'
                            ),
                            site_id=sid,
                            site_name=site_name,
                            affected=[ssid] + protected_ssids,
                            recommendation=(
                                f'Move "{ssid}" to a dedicated guest VLAN isolated from '
                                f'corporate resources. This finding overlaps with Config Drift '
                                f'VLAN collision detection and should be prioritized.'
                            ),
                            fix_url=org_config_url(client.portal_base, org_id, sid),
                        ))
                    elif portal_auth is None or portal_auth == "none":
                        site_findings.append(Finding(
                            severity=Severity.warning,
                            title=f'"{ssid}" — open SSID with unauthenticated captive portal',
                            detail=(
                                f'SSID "{ssid}" is open with a click-through captive portal '
                                f'(no credentials required). Anyone in range can connect '
                                f'without any identity verification.'
                            ),
                            site_id=sid,
                            site_name=site_name,
                            affected=[ssid],
                            recommendation=(
                                "Consider adding authentication to the captive portal "
                                "(email, sponsored access, or password) to provide "
                                "accountability and terms-of-use acceptance."
                            ),
                        ))
                    elif portal_auth in AUTHENTICATED_PORTAL_TYPES:
                        site_findings.append(Finding(
                            severity=Severity.info,
                            title=f'"{ssid}" — open SSID with authenticated captive portal ({portal_auth})',
                            detail=(
                                f'SSID "{ssid}" is open but uses a captive portal with '
                                f'{portal_auth} authentication. This provides identity '
                                f'accountability but no over-the-air encryption.'
                            ),
                            site_id=sid,
                            site_name=site_name,
                            affected=[ssid],
                            recommendation=(
                                "Consider migrating to OWE (Opportunistic Wireless Encryption) "
                                "to add over-the-air encryption while maintaining the open "
                                "captive portal experience for clients."
                            ),
                        ))

                # ── Check 2: PMF not enforced ────────────────────────────────
                # Collected after the loop — consolidated per site below
                pass

                # ── Check 3: 802.1X with no RADIUS servers ───────────────────
                if auth_type in ("eap", "eap192"):
                    auth_servers = w.get("auth_servers", [])
                    mist_nac     = w.get("mist_nac", {}) or {}
                    hotspot20    = w.get("hotspot20", {}) or {}

                    uses_mist_nac  = mist_nac.get("enabled", False)
                    uses_hotspot20 = hotspot20.get("enabled", False)
                    uses_radsec    = any(
                        str(s.get("secret", "")).upper() == "RADSEC"
                        for s in auth_servers
                        if isinstance(s, dict)
                    )

                    # Suppress if using Mist Access Assurance, RADSEC, or Passpoint
                    if not auth_servers and not uses_mist_nac and not uses_hotspot20:
                        site_findings.append(Finding(
                            severity=Severity.warning,
                            title=f'"{ssid}" — 802.1X SSID with no RADIUS servers configured',
                            detail=(
                                f'SSID "{ssid}" is configured for 802.1X (Enterprise) '
                                f'authentication but has no RADIUS authentication servers '
                                f'defined and is not using Mist Access Assurance. '
                                f'Clients will fail to authenticate.'
                            ),
                            site_id=sid,
                            site_name=site_name,
                            affected=[ssid],
                            recommendation=(
                                "Add RADIUS authentication servers under the SSID configuration, "
                                "enable Mist Access Assurance (mist_nac), or configure RADSEC "
                                "for Passpoint/OpenRoaming deployments."
                            ),
                        ))

            # ── Check 2: PMF disabled — consolidated per site ─────────────────
            pmf_disabled_ssids = [
                w.get("ssid", "?") for w in wlans
                if w.get("auth", {}).get("type", "open") in PMF_APPLICABLE_AUTH
                and w.get("disable_pmf", False)
            ]
            if pmf_disabled_ssids:
                site_findings.append(Finding(
                    severity=Severity.warning,
                    title=f"{site_name} — PMF disabled on {len(pmf_disabled_ssids)} SSID(s)",
                    detail=(
                        f"Protected Management Frames (802.11w) is disabled on the following "
                        f"SSID(s): {', '.join(pmf_disabled_ssids)}. "
                        f"PMF protects against deauthentication and disassociation attacks. "
                        f"It is required for WPA3 and strongly recommended for WPA2."
                    ),
                    site_id=sid,
                    site_name=site_name,
                    affected=pmf_disabled_ssids,
                    recommendation=(
                        "Enable PMF on all affected SSIDs. Set to 'Required' for WPA3 SSIDs "
                        "and 'Capable' for WPA2 SSIDs to maintain backward compatibility."
                    ),
                ))

            # ── Check 6: OWE transition mode — consolidated per site ────────────
            owe_ssids = [
                w.get("ssid", "?") for w in wlans
                if w.get("auth", {}).get("type", "open") == "open"
                and w.get("auth", {}).get("owe", "disabled") == "enabled"
            ]
            if owe_ssids:
                site_findings.append(Finding(
                    severity=Severity.info,
                    title=f"{site_name} — {len(owe_ssids)} SSID(s) in OWE transition mode",
                    detail=(
                        f"The following SSID(s) are running OWE transition mode, which "
                        f"simultaneously serves open and OWE-encrypted clients: "
                        f"{', '.join(owe_ssids)}. "
                        f"Transition mode is appropriate during migration but reduces the "
                        f"security benefit of OWE when left enabled long-term."
                    ),
                    site_id=sid,
                    site_name=site_name,
                    affected=owe_ssids,
                    recommendation=(
                        "Once your client population fully supports OWE, disable transition "
                        "mode and set OWE to 'Required'. Leaving it enabled permanently means "
                        "open clients can still connect without encryption."
                    ),
                ))

            # ── Check 7: WPA3 transition mode — consolidated per site ─────────
            wpa3_transition_ssids = [
                w.get("ssid", "?") for w in wlans
                if _is_wpa3(w)
                and w.get("auth", {}).get("type", "open") in ("psk", "eap")
                and any(p in w.get("auth", {}).get("pairwise", []) for p in ("wpa2-ccmp", "wpa2-tkip"))
            ]
            if wpa3_transition_ssids:
                site_findings.append(Finding(
                    severity=Severity.info,
                    title=f"{site_name} — {len(wpa3_transition_ssids)} SSID(s) in WPA3/WPA2 transition mode",
                    detail=(
                        f"The following SSID(s) are advertising both WPA3 and WPA2 "
                        f"(transition mode): {', '.join(wpa3_transition_ssids)}. "
                        f"This is appropriate during migration but retains WPA2 attack "
                        f"vectors including KRACK and dictionary attacks on the PSK. "
                        f"Transition mode should be a temporary bridge, not a permanent configuration."
                    ),
                    site_id=sid,
                    site_name=site_name,
                    affected=wpa3_transition_ssids,
                    recommendation=(
                        "Once all clients support WPA3, disable transition mode and set "
                        "the SSID to WPA3-only. Audit your client inventory to determine "
                        "when it is safe to make this change."
                    ),
                ))

            # ── Check 4: Rogue AP detection not enabled ──────────────────────
            rogue = setting.get("rogue", {})
            if not rogue.get("enabled", False):
                site_findings.append(Finding(
                    severity=Severity.warning,
                    title=f"{site_name} — rogue AP detection not enabled",
                    detail=(
                        f"Rogue AP detection is disabled for {site_name}. "
                        f"Without this, unauthorized APs connected to the wired "
                        f"network will go undetected. Rogue detection is disabled "
                        f"by default and must be explicitly enabled per site."
                    ),
                    site_id=sid,
                    site_name=site_name,
                    affected=[site_name],
                    recommendation=(
                        "Enable rogue AP detection under Organization > Site Configuration "
                        "> Security Configuration. Also enable Honeypot AP detection to "
                        "identify APs spoofing your SSIDs."
                    ),
                ))

            all_findings.extend(site_findings)
            # Include org-level PSK reuse findings in site drill-down view
            # and factor them into the site score so the breakdown reflects reality
            combined = psk_reuse_findings + site_findings
            site_score = self.score_from_findings(combined)
            site_results.append(SiteResult(
                site_id=sid,
                site_name=site_name,
                score=site_score,
                severity=self.severity_from_score(site_score),
                findings=combined,
            ))

        # ── 4. Score and summarise ───────────────────────────────────────────
        score    = self.score_from_findings(all_findings)
        severity = self.severity_from_score(score)

        critical_count = sum(1 for f in all_findings if f.severity == Severity.critical)
        warning_count  = sum(1 for f in all_findings if f.severity == Severity.warning)
        info_count     = sum(1 for f in all_findings if f.severity == Severity.info)

        if not all_findings:
            summary = f"No security issues detected across {len(sites)} sites."
        else:
            parts = []
            if critical_count: parts.append(f"{critical_count} critical")
            if warning_count:  parts.append(f"{warning_count} warnings")
            if info_count:     parts.append(f"{info_count} informational")
            summary = ", ".join(parts) + f" across {len(sites)} sites."

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
