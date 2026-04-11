"""
AuthGuard — Access Assurance & NAC Health
==========================================
Audits Mist Access Assurance (NAC) configuration health across the org.
Checks rule quality, PKI/SCEP status, CA certificate presence, tag
integrity, and 802.1X WLAN coverage.

Checks performed:
  1. NAC rules exist              — no rules → Critical
  2. Default-deny missing         — no catch-all deny rule → Warning
  3. Unnamed NAC rules            — rules with empty name → Info
  4. Disabled NAC rules           — enabled: false → Info
  5. SCEP/PKI status              — mist_scep_status not enabled → Warning
  6. CA certificates present      — empty cacerts → Critical
  7. Cert auth configured         — at least one cert-matching rule → Warning if missing
  8. Unresolved tag references    — rule references unknown tag UUID → Warning
  9. NAC-enabled WLANs            — count of EAP/802.1X WLANs → Info

API endpoints used:
  GET /api/v1/orgs/{org_id}/nacrules
  GET /api/v1/orgs/{org_id}/nactags
  GET /api/v1/orgs/{org_id}/setting
  GET /api/v1/sites/{site_id}/wlans  (per site, for WLAN auth type audit)
"""

import asyncio
import logging

from models import ModuleOutput, Finding, Severity
from mist_client import MistClient, MistAPIError
from .base import BaseModule

logger = logging.getLogger(__name__)


class AuthGuardModule(BaseModule):
    module_id    = "auth_guard"
    display_name = "AuthGuard"
    icon         = "🔑"

    async def analyze(self, org_id: str, sites: list[dict], client: MistClient) -> ModuleOutput:

        # ── 1. Fetch all data in parallel ────────────────────────────────────
        nacrules_task   = client.get(f"/api/v1/orgs/{org_id}/nacrules", use_cache=True)
        nactags_task    = client.get(f"/api/v1/orgs/{org_id}/nactags", use_cache=True)
        orgsetting_task = client.get(f"/api/v1/orgs/{org_id}/setting", use_cache=True)
        wlan_tasks      = [
            client.get(f"/api/v1/sites/{site['id']}/wlans", use_cache=True)
            for site in sites
        ]

        results = await asyncio.gather(
            nacrules_task,
            nactags_task,
            orgsetting_task,
            *wlan_tasks,
            return_exceptions=True,
        )

        nacrules   = results[0] if not isinstance(results[0], Exception) else []
        nactags    = results[1] if not isinstance(results[1], Exception) else []
        orgsetting = results[2] if not isinstance(results[2], Exception) else {}
        site_wlans = results[3:]

        findings: list[Finding] = []

        # Build tag lookup for reference validation
        tag_ids = {t["id"] for t in nactags if isinstance(t, dict) and "id" in t}

        # ── 2. Check NAC rules exist ─────────────────────────────────────────
        if not nacrules:
            findings.append(Finding(
                severity=Severity.critical,
                title="No NAC rules configured",
                detail=(
                    "No Access Assurance NAC rules are defined for this org. "
                    "Without NAC rules, all authentication requests will be "
                    "handled by default policy, which may allow unrestricted access."
                ),
                recommendation=(
                    "Configure NAC rules under Organization > Access > Auth Policies. "
                    "At minimum, define rules for your primary auth method (cert, IDP, MPSK) "
                    "and a default-deny catch-all as the last rule."
                ),
            ))
            # No point checking further rule-based items
            score    = self.score_from_findings(findings)
            severity = self.severity_from_score(score)
            return ModuleOutput(
                module_id=self.module_id,
                display_name=self.display_name,
                icon=self.icon,
                score=score,
                severity=severity,
                summary="No NAC rules configured — Access Assurance not active.",
                findings=findings,
                sites=[],
                status="ok",
            )

        # ── 3. Check for default-deny catch-all ──────────────────────────────
        deny_rules = [r for r in nacrules if r.get("action") == "deny"]
        if not deny_rules:
            findings.append(Finding(
                severity=Severity.warning,
                title="No default-deny rule — NAC policy has no catch-all",
                detail=(
                    f"{len(nacrules)} NAC rule(s) exist but none use the 'deny' action. "
                    "Without a default-deny catch-all as the last rule, devices that "
                    "don't match any allow rule may receive unexpected access based on "
                    "the platform default behavior."
                ),
                recommendation=(
                    "Add a final NAC rule with action 'deny' and no matching conditions "
                    "to act as a catch-all. This ensures unmatched devices are explicitly "
                    "rejected rather than relying on implicit behavior."
                ),
            ))

        # ── 4. Check for unnamed rules ───────────────────────────────────────
        unnamed = [r for r in nacrules if not r.get("name", "").strip()]
        if unnamed:
            findings.append(Finding(
                severity=Severity.info,
                title=f"{len(unnamed)} NAC rule(s) have no name",
                detail=(
                    f"{len(unnamed)} of {len(nacrules)} NAC rules have empty names, "
                    "making them difficult to identify during audits or troubleshooting. "
                    "Rule IDs: " + ", ".join(r.get("id", "unknown")[:8] + "…" for r in unnamed)
                ),
                recommendation=(
                    "Name all NAC rules descriptively (e.g., 'Corp-Cert-Allow', "
                    "'Guest-IDP-Allow', 'Default-Deny') to improve auditability "
                    "and operational clarity."
                ),
            ))

        # ── 5. Check for disabled rules ──────────────────────────────────────
        disabled_rules = [r for r in nacrules if not r.get("enabled", True)]
        if disabled_rules:
            findings.append(Finding(
                severity=Severity.info,
                title=f"{len(disabled_rules)} NAC rule(s) are disabled",
                detail=(
                    f"{len(disabled_rules)} NAC rule(s) are currently disabled and "
                    "not enforced. Disabled rules may indicate incomplete configuration "
                    "or rules left over from testing."
                ),
                affected=[r.get("name") or r.get("id", "unknown")[:8] + "…" for r in disabled_rules],
                recommendation=(
                    "Review disabled rules and either enable them if needed, "
                    "or remove them if they are no longer required."
                ),
            ))

        # ── 6. Check cert auth rule exists ───────────────────────────────────
        cert_rules = [
            r for r in nacrules
            if r.get("matching", {}).get("auth_type") in ("cert", "eap-tls")
        ]
        if not cert_rules:
            findings.append(Finding(
                severity=Severity.warning,
                title="No certificate-based authentication rule configured",
                detail=(
                    "None of the NAC rules match on certificate authentication type. "
                    "Certificate-based (EAP-TLS) authentication is the most secure "
                    "method for Access Assurance and is required for zero-trust posture."
                ),
                recommendation=(
                    "Configure at least one NAC rule that matches on auth_type 'cert' "
                    "for corporate device authentication. Pair with Mist SCEP or an "
                    "external PKI for certificate issuance."
                ),
            ))

        # ── 7. Check PKI/SCEP status ─────────────────────────────────────────
        mist_nac    = orgsetting.get("mist_nac", {})
        scep_status = mist_nac.get("mist_scep_status", "disabled")
        cacerts     = mist_nac.get("cacerts", [])
        scep_certs  = mist_nac.get("scep_cacerts", [])

        if scep_status != "enabled":
            findings.append(Finding(
                severity=Severity.warning,
                title=f"Mist SCEP/PKI is {scep_status} — certificate issuance not active",
                detail=(
                    "Mist's built-in SCEP certificate authority is not enabled. "
                    "Without an active PKI, certificate-based authentication cannot "
                    "be provisioned to devices through Mist Access Assurance."
                ),
                recommendation=(
                    "Enable Mist SCEP under Organization > Access > PKI & Certificates, "
                    "or configure an external CA integration. "
                    "SCEP allows automatic certificate issuance to managed devices."
                ),
            ))

        # ── 8. Check CA certs present ────────────────────────────────────────
        if not cacerts:
            findings.append(Finding(
                severity=Severity.critical,
                title="No CA certificates configured in Mist NAC",
                detail=(
                    "No CA certificates are uploaded to Mist Access Assurance. "
                    "CA certificates are required to validate client certificates "
                    "during EAP-TLS authentication. Without them, certificate-based "
                    "auth will fail for all devices."
                ),
                recommendation=(
                    "Upload your root and intermediate CA certificates under "
                    "Organization > Access > PKI & Certificates > Trusted CAs. "
                    "If using Mist SCEP, enable it to auto-configure the CA chain."
                ),
            ))
        else:
            findings.append(Finding(
                severity=Severity.info,
                title=f"{len(cacerts)} CA certificate(s) configured",
                detail=(
                    f"{len(cacerts)} CA certificate(s) are uploaded to Mist NAC "
                    f"for client certificate validation"
                    + (f", plus {len(scep_certs)} SCEP CA cert(s)." if scep_certs else ".")
                ),
                recommendation=(
                    "Periodically review CA certificate expiry dates and renew "
                    "before expiration to prevent authentication outages."
                ),
            ))

        # ── 9. Check for unresolved tag references ───────────────────────────
        unresolved: list[str] = []
        for rule in nacrules:
            matching  = rule.get("matching", {})
            rule_tags = matching.get("nactags", []) + rule.get("apply_tags", [])
            for tag_id in rule_tags:
                if tag_id not in tag_ids:
                    rule_label = rule.get("name") or rule.get("id", "unknown")[:8] + "…"
                    unresolved.append(f"Rule '{rule_label}' → tag {tag_id[:8]}…")

        if unresolved:
            findings.append(Finding(
                severity=Severity.warning,
                title=f"{len(unresolved)} unresolved NAC tag reference(s)",
                detail=(
                    f"{len(unresolved)} NAC rule(s) reference tag IDs that no longer "
                    "exist in the org's NAC tag list. These dangling references may "
                    "cause rules to behave unexpectedly or silently fail to match."
                ),
                affected=unresolved[:10],
                recommendation=(
                    "Review NAC rules and remove or replace references to deleted tags. "
                    "Dangling tag references can cause silent policy gaps."
                ),
            ))

        # ── 10. Count NAC-enabled WLANs ──────────────────────────────────────
        eap_wlans: list[str] = []
        seen_wlan_ids: set   = set()

        for site, wlans in zip(sites, site_wlans):
            if isinstance(wlans, Exception):
                continue
            site_name = site.get("name", site["id"])
            for wlan in wlans:
                wlan_id   = wlan.get("id", "")
                auth_type = wlan.get("auth", {}).get("type", "")
                if wlan_id in seen_wlan_ids:
                    continue
                seen_wlan_ids.add(wlan_id)
                if auth_type in ("eap", "eap192"):
                    ssid = wlan.get("ssid", "unknown")
                    eap_wlans.append(f"{ssid} ({site_name})")

        if eap_wlans:
            findings.append(Finding(
                severity=Severity.info,
                title=f"{len(eap_wlans)} 802.1X WLAN(s) using NAC authentication",
                detail=(
                    f"{len(eap_wlans)} WLAN(s) are configured with EAP/802.1X "
                    "authentication, routing clients through Access Assurance NAC policies."
                ),
                affected=eap_wlans[:10],
                recommendation=(
                    "Ensure NAC rules cover all expected client types connecting "
                    "to these WLANs. Periodically test authentication flows end-to-end."
                ),
            ))

        # ── 11. Score and summarize ───────────────────────────────────────────
        score    = self.score_from_findings(findings)
        severity = self.severity_from_score(score)

        criticals = sum(1 for f in findings if f.severity == Severity.critical)
        warnings  = sum(1 for f in findings if f.severity == Severity.warning)

        if criticals == 0 and warnings == 0:
            summary = (
                f"{len(nacrules)} NAC rule(s), SCEP {scep_status}, "
                f"{len(cacerts)} CA cert(s), {len(eap_wlans)} 802.1X WLAN(s) — "
                f"Access Assurance configuration healthy."
            )
        else:
            parts = []
            if not deny_rules:
                parts.append("no default-deny rule")
            if not cert_rules:
                parts.append("no cert auth rule")
            if scep_status != "enabled":
                parts.append(f"SCEP {scep_status}")
            if not cacerts:
                parts.append("no CA certs")
            if unresolved:
                parts.append(f"{len(unresolved)} unresolved tag refs")
            summary = (
                f"{len(nacrules)} NAC rule(s) — " + ", ".join(parts) + "."
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
