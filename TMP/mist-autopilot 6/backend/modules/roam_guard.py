"""
RoamGuard — Roaming Health
==========================
Analyzes roaming health per site using SLE data and fast roam events.

Checks performed:
  1. Sticky clients    — SLE roaming signal-quality/sticky-client classifier
                         corroborated by fast roam event counts
  2. 802.11r missing   — Warning only on 802.1X SSIDs (eap, eap192)
  3. High Density Data Rates not set — Info, only when site roaming SLE < 80

SLE roaming score calculation (consistent with SLE Sentinel):
  score = ceil((1 - sum(degraded) / sum(total)) * 100)

Sticky client detection (both signals required):
  SLE signal-quality/sticky-client degraded >= threshold
  AND fast roam events sticky count >= threshold

High Density Data Rates:
  WLAN rateset.template == "high-density" → High Density enabled
  Absent rateset or template == "compatible" → default (flag when roaming poor)
"""

import asyncio
import logging
import math

from models import ModuleOutput, Finding, Severity, SiteResult
from mist_client import MistClient
from .base import BaseModule

logger = logging.getLogger(__name__)

ROAMING_SLE_THRESHOLD        = 80
STICKY_EVENT_THRESHOLD       = 5
STICKY_SLE_DEGRADED_THRESHOLD = 5.0
EAP_AUTH_TYPES               = {"eap", "eap192"}
HIGH_DENSITY_TEMPLATES       = {"high-density", "high_density"}


def _calc_sle_score(sle_data: dict) -> int | None:
    try:
        samples      = sle_data.get("sle", {}).get("samples", {})
        total_arr    = [v for v in samples.get("total",    []) if v is not None]
        degraded_arr = [v for v in samples.get("degraded", []) if v is not None]
        total_sum    = sum(total_arr)
        if total_sum == 0:
            return None
        return math.ceil((1 - sum(degraded_arr) / total_sum) * 100)
    except Exception:
        return None


def _get_classifier_degraded(sle_data: dict, classifier_name: str,
                              subclassifier_name: str | None = None) -> float:
    for clf in sle_data.get("classifiers", []):
        if clf.get("name") != classifier_name:
            continue
        if subclassifier_name is None:
            return sum(v for v in clf.get("samples", {}).get("degraded", []) if v is not None)
        for sub in clf.get("classifiers", []):
            if sub.get("name") == subclassifier_name:
                return sum(v for v in sub.get("samples", {}).get("degraded", []) if v is not None)
    return 0.0


def _is_high_density(wlan: dict) -> bool:
    rateset = wlan.get("rateset", {})
    if not rateset:
        return False
    # Per-band structure: {"5": {"template": "high-density"}, ...}
    for band_cfg in rateset.values():
        if isinstance(band_cfg, dict):
            if band_cfg.get("template", "") in HIGH_DENSITY_TEMPLATES:
                return True
    # Flat structure fallback
    return rateset.get("template", "") in HIGH_DENSITY_TEMPLATES


def _has_11r(wlan: dict) -> bool:
    return wlan.get("roam_mode", "") == "11r"


def _count_sticky_events(roam_events) -> int:
    STICKY_TYPES = {"sticky", "client_sticky", "suboptimal", "signal_quality"}
    results = roam_events if isinstance(roam_events, list) else roam_events.get("results", [])
    return sum(
        1 for e in results
        if any(s in str(e.get("type", "")).lower().replace("-", "_") for s in STICKY_TYPES)
    )


class RoamGuardModule(BaseModule):
    module_id    = "roam_guard"
    display_name = "RoamGuard"
    icon         = "📡"

    async def analyze(self, org_id: str, sites: list[dict], client: MistClient) -> ModuleOutput:

        # ── 1. Parallel fetch ──────────────────────────────────────────────
        results = await asyncio.gather(
            client.get_org_wlans(org_id),
            *[client.get_site_wlans(site["id"])                                    for site in sites],
            *[client.get_site_sle_metric(site["id"], "site", "roaming", "7d")     for site in sites],
            *[client.get_site_roam_events(site["id"], "7d")                        for site in sites],
            return_exceptions=True,
        )

        n = len(sites)
        org_wlans          = results[0] if not isinstance(results[0], Exception) else []
        site_wlan_lists    = results[1      : n+1]
        site_sle_results   = results[n+1    : 2*n+1]
        site_event_results = results[2*n+1  :]

        site_map = {s["id"]: s.get("name", s["id"]) for s in sites}
        for w in org_wlans:
            w["_site_id"] = None

        # ── 2. Per-site analysis ───────────────────────────────────────────
        all_findings: list[Finding] = []
        site_results_out: list[SiteResult] = []

        for site, wlan_list, sle_data, roam_events in zip(
            sites, site_wlan_lists, site_sle_results, site_event_results
        ):
            sid       = site["id"]
            site_name = site_map[sid]
            site_findings: list[Finding] = []

            wlans = (wlan_list if not isinstance(wlan_list, Exception) else []) + org_wlans

            # SLE roaming score
            roaming_score: int | None = None
            if not isinstance(sle_data, Exception):
                roaming_score = _calc_sle_score(sle_data)
            roaming_poor = roaming_score is not None and roaming_score < ROAMING_SLE_THRESHOLD

            # ── Check 1: Sticky clients ────────────────────────────────────
            sticky_degraded = 0.0
            if not isinstance(sle_data, Exception):
                sticky_degraded = _get_classifier_degraded(
                    sle_data, "signal-quality", "sticky-client"
                )
                if sticky_degraded == 0.0:
                    sticky_degraded = _get_classifier_degraded(sle_data, "signal-quality")

            sticky_events = 0
            if not isinstance(roam_events, Exception):
                sticky_events = _count_sticky_events(roam_events)

            if sticky_degraded >= STICKY_SLE_DEGRADED_THRESHOLD and sticky_events >= STICKY_EVENT_THRESHOLD:
                site_findings.append(Finding(
                    severity=Severity.warning,
                    title=f"{site_name} — sticky clients detected",
                    detail=(
                        f"Roaming SLE signal-quality classifier shows {sticky_degraded:.0f} "
                        f"degraded user-minutes attributed to sticky behavior over 7 days, "
                        f"corroborated by {sticky_events} sticky/suboptimal roam events. "
                        f"Sticky clients remain connected to distant APs despite better "
                        f"options available within 6+ dBm RSSI improvement range."
                    ),
                    site_id=sid,
                    site_name=site_name,
                    affected=[site_name],
                    recommendation=(
                        "Review AP TX power to ensure coverage cells don't extend beyond "
                        "design intent. Enable High Density data rates (24 Mbps MBR) to "
                        "force clients to roam when RSSI drops. Check Marvis Self-Driving "
                        "Actions > Wireless for specific client/AP recommendations."
                    ),
                ))
            elif sticky_degraded >= STICKY_SLE_DEGRADED_THRESHOLD:
                site_findings.append(Finding(
                    severity=Severity.info,
                    title=f"{site_name} — signal quality degradation during roaming",
                    detail=(
                        f"Roaming SLE signal-quality shows {sticky_degraded:.0f} degraded "
                        f"user-minutes over 7 days with no corroborating sticky client events. "
                        f"This may indicate coverage gaps rather than sticky client behavior."
                    ),
                    site_id=sid,
                    site_name=site_name,
                    affected=[site_name],
                    recommendation=(
                        "Review coverage SLE alongside roaming SLE. If coverage is also "
                        "degraded, consider RF design adjustments. If coverage is healthy, "
                        "monitor for sticky client patterns over time."
                    ),
                ))

            # ── Check 2: 802.11r missing on 802.1X SSIDs ──────────────────
            eap_without_11r = [
                w.get("ssid", "?") for w in wlans
                if w.get("auth", {}).get("type") in EAP_AUTH_TYPES and not _has_11r(w)
            ]
            if eap_without_11r:
                site_findings.append(Finding(
                    severity=Severity.warning,
                    title=f"{site_name} — 802.11r not enabled on 802.1X SSID(s)",
                    detail=(
                        f"The following 802.1X SSIDs do not have 802.11r (Fast BSS "
                        f"Transition) enabled: {', '.join(eap_without_11r)}. "
                        f"Without 802.11r, clients must complete a full RADIUS "
                        f"re-authentication on every AP transition, adding 200–2000ms "
                        f"of roaming latency — impactful for voice and real-time apps."
                    ),
                    site_id=sid,
                    site_name=site_name,
                    affected=eap_without_11r,
                    recommendation=(
                        "Enable 802.11r on all 802.1X SSIDs in Mist WLAN configuration "
                        "(roam_mode = '11r'). OKC is a fallback for clients that don't "
                        "support 802.11r, but 802.11r is the preferred standards-based option."
                    ),
                ))

            # ── Check 3: High Density data rates (conditional on poor SLE) ─
            if roaming_poor:
                wlans_without_hd = [
                    w.get("ssid", "?") for w in wlans if not _is_high_density(w)
                ]
                if wlans_without_hd:
                    score_str = str(roaming_score) if roaming_score is not None else "N/A"
                    site_findings.append(Finding(
                        severity=Severity.info,
                        title=f"{site_name} — High Density data rates not set (roaming SLE: {score_str})",
                        detail=(
                            f"Roaming SLE is {score_str} (below {ROAMING_SLE_THRESHOLD}). "
                            f"The following SSIDs are not using High Density data rates: "
                            f"{', '.join(wlans_without_hd)}. "
                            f"High Density sets a 24 Mbps minimum basic rate, which forces "
                            f"clients to roam away from APs they can only sustain at lower "
                            f"data rates — a key mitigation for sticky client behavior."
                        ),
                        site_id=sid,
                        site_name=site_name,
                        affected=wlans_without_hd,
                        recommendation=(
                            "Enable High Density data rates on affected SSIDs. "
                            "Caution: older scanners, POS terminals, and IoT devices may "
                            "not support 24 Mbps — consider enabling on 5/6 GHz bands only "
                            "if 2.4 GHz legacy devices are present."
                        ),
                    ))

            all_findings.extend(site_findings)
            site_score = self.score_from_findings(site_findings)
            site_results_out.append(SiteResult(
                site_id=sid,
                site_name=site_name,
                score=site_score,
                severity=self.severity_from_score(site_score),
                findings=site_findings,
            ))

        # ── 3. Org score and summary ───────────────────────────────────────
        score    = self.score_from_findings(all_findings)
        severity = self.severity_from_score(score)

        warning_count = sum(1 for f in all_findings if f.severity == Severity.warning)
        info_count    = sum(1 for f in all_findings if f.severity == Severity.info)

        if not all_findings:
            summary = f"No roaming issues detected across {len(sites)} sites."
        else:
            parts = []
            if warning_count: parts.append(f"{warning_count} warnings")
            if info_count:    parts.append(f"{info_count} informational")
            summary = ", ".join(parts) + f" across {len(sites)} sites."

        return ModuleOutput(
            module_id=self.module_id,
            display_name=self.display_name,
            icon=self.icon,
            score=score,
            severity=severity,
            summary=summary,
            findings=all_findings,
            sites=site_results_out,
            status="ok",
        )
