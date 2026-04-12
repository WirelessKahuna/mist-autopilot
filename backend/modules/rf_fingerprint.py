"""
RF Fingerprint Analyzer
=======================
Audits RF configuration and behavior across all sites and APs.

Checks performed:
  1. Band utilization imbalance  — >30% clients on 2.4 GHz when 5/6 GHz present → Warning
  2. DFS instability             — 3+ radar events at site in 7 days → Critical
  3. DFS not configured          — RF template/site config excludes all DFS channels → Warning
  4. Channel width mismatches    — APs on same band at same site using different widths → Warning
  5. TX power outliers           — AP deviates ≥6 dB from site average per band → Info

Data sources:
  AP stats:     GET /api/v1/sites/{site_id}/stats/devices?type=ap
                radio_stat.band_24 / band_5 / band_6 each contain:
                  channel, bandwidth, power, num_clients
  Device events: GET /api/v1/sites/{site_id}/devices/events?type=AP_RADAR_DETECTED&duration=7d
  RF templates:  GET /api/v1/orgs/{org_id}/rftemplates
  Site settings: GET /api/v1/sites/{site_id}/setting  (rf_template_id, band overrides)

DFS channel sets (5 GHz, US regulatory domain):
  DFS channels: 52, 56, 60, 64, 100, 104, 108, 112, 116, 120, 124, 128, 132, 136, 140, 144
  Non-DFS 5 GHz UNII-1/UNII-3: 36, 40, 44, 48, 149, 153, 157, 161, 165
"""

import asyncio
import logging
import statistics
from collections import defaultdict

from models import ModuleOutput, Finding, Severity, SiteResult
from mist_client import MistClient
from .base import BaseModule

logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────

BAND_IMBALANCE_THRESHOLD = 0.30   # >30% clients on 2.4 GHz triggers Warning
DFS_RADAR_THRESHOLD      = 3      # 3+ radar events in 7d → Critical
TX_POWER_OUTLIER_DB      = 6      # ≥6 dB deviation from site average → Info
MIN_APS_FOR_ANALYSIS     = 2      # skip checks that need multiple APs

# DFS channels — 5 GHz only (6 GHz has its own AFC regime, not DFS in same sense)
DFS_CHANNELS_5GHZ = {
    52, 56, 60, 64,                          # UNII-2A
    100, 104, 108, 112, 116, 120,            # UNII-2C
    124, 128, 132, 136, 140, 144,            # UNII-2C extended
}

NON_DFS_5GHZ = {36, 40, 44, 48, 149, 153, 157, 161, 165}

# Bands in AP radio_stat
RADIO_BANDS = ["band_24", "band_5", "band_6"]
BAND_LABELS = {"band_24": "2.4 GHz", "band_5": "5 GHz", "band_6": "6 GHz"}


def _get_radio(ap: dict, band_key: str) -> dict | None:
    return ap.get("radio_stat", {}).get(band_key) or None


def _all_radios(ap: dict) -> list[tuple[str, dict]]:
    """Return (band_key, radio_dict) for all active radios on this AP."""
    result = []
    for band_key in RADIO_BANDS:
        r = _get_radio(ap, band_key)
        if r and r.get("channel"):
            result.append((band_key, r))
    return result


def _channels_include_dfs(channels: list) -> bool:
    """Return True if the channel list includes any DFS channels."""
    return any(int(c) in DFS_CHANNELS_5GHZ for c in channels if c)


def _channels_exclude_all_dfs(channels: list) -> bool:
    """
    Return True if a non-empty channel list contains NO DFS channels.
    An empty list means 'automatic' — all channels allowed, so NOT an exclusion.
    """
    if not channels:
        return False  # empty = automatic = DFS not excluded
    ch_set = {int(c) for c in channels if c}
    return not (ch_set & DFS_CHANNELS_5GHZ)


class RFFingerprintModule(BaseModule):
    module_id    = "rf_fingerprint"
    display_name = "RF Fingerprint Analyzer"
    icon         = "📶"

    async def analyze(self, org_id: str, sites: list[dict], client: MistClient) -> ModuleOutput:

        # ── 1. Parallel fetch ──────────────────────────────────────────────
        results = await asyncio.gather(
            client.get_org_rf_templates(org_id),
            *[client.get_site_aps(site["id"])                              for site in sites],
            *[client.get(f"/api/v1/sites/{site['id']}/setting",
                         use_cache=True)                                   for site in sites],
            *[client.get_site_device_events(
                site["id"], duration="7d",
                event_type="AP_RADAR_DETECTED")                            for site in sites],
            return_exceptions=True,
        )

        n = len(sites)
        rf_templates     = results[0] if not isinstance(results[0], Exception) else []
        site_ap_lists    = results[1      : n+1]
        site_settings    = results[n+1    : 2*n+1]
        site_radar_events= results[2*n+1  :]

        site_map = {s["id"]: s.get("name", s["id"]) for s in sites}

        # Build RF template channel map: template_id → band_5.channels list
        rf_template_map: dict[str, dict] = {
            t["id"]: t for t in rf_templates if isinstance(t, dict) and t.get("id")
        }

        # ── 2. Per-site analysis ───────────────────────────────────────────
        all_findings: list[Finding] = []
        site_results_out: list[SiteResult] = []

        for site, ap_list, setting, radar_result in zip(
            sites, site_ap_lists, site_settings, site_radar_events
        ):
            sid       = site["id"]
            site_name = site_map[sid]
            site_findings: list[Finding] = []

            aps = ap_list if not isinstance(ap_list, Exception) else []
            aps = [a for a in aps if isinstance(a, dict)]
            cfg = setting if not isinstance(setting, Exception) else {}

            # ── Check 0: No RF template assigned ──────────────────────────
            if not cfg.get("rf_template_id"):
                site_findings.append(Finding(
                    severity=Severity.warning,
                    title=f"{site_name} — no RF template assigned",
                    detail=(
                        f"{site_name} does not have an RF template assigned. "
                        f"Without an RF template, channel selection, TX power, "
                        f"band configuration, and RRM settings are managed manually "
                        f"per site with no centralized governance. This increases "
                        f"the risk of configuration drift and inconsistent RF policy "
                        f"across sites."
                    ),
                    site_id=sid,
                    site_name=site_name,
                    affected=[site_name],
                    recommendation=(
                        "Create an RF template under Organization > RF Templates and "
                        "assign it to this site. RF templates enable centralized, "
                        "consistent RRM configuration and allow global changes to "
                        "propagate to all assigned sites simultaneously."
                    ),
                ))

            # ── Check 1: Band utilization imbalance ────────────────────────
            clients_24 = 0
            clients_5  = 0
            clients_6  = 0
            has_5_or_6 = False

            for ap in aps:
                r24 = _get_radio(ap, "band_24")
                r5  = _get_radio(ap, "band_5")
                r6  = _get_radio(ap, "band_6")
                if r24:
                    clients_24 += r24.get("num_clients", 0) or 0
                if r5:
                    clients_5  += r5.get("num_clients", 0) or 0
                    has_5_or_6 = True
                if r6:
                    clients_6  += r6.get("num_clients", 0) or 0
                    has_5_or_6 = True

            total_clients = clients_24 + clients_5 + clients_6
            if has_5_or_6 and total_clients >= 10:
                ratio_24 = clients_24 / total_clients
                if ratio_24 > BAND_IMBALANCE_THRESHOLD:
                    site_findings.append(Finding(
                        severity=Severity.warning,
                        title=f"{site_name} — band utilization imbalance ({ratio_24:.0%} clients on 2.4 GHz)",
                        detail=(
                            f"{clients_24} of {total_clients} connected clients "
                            f"({ratio_24:.0%}) are on 2.4 GHz despite 5/6 GHz APs "
                            f"being present. 2.4 GHz has fewer channels, higher "
                            f"co-channel interference, and lower throughput capacity. "
                            f"This may indicate band steering is not enabled or effective."
                        ),
                        site_id=sid,
                        site_name=site_name,
                        affected=[site_name],
                        recommendation=(
                            "Enable band steering on affected SSIDs to prefer 5/6 GHz. "
                            "Check that 5 GHz coverage is adequate — clients stay on "
                            "2.4 GHz when 5 GHz signal is too weak to maintain a "
                            "reliable connection. Review AP placement and TX power."
                        ),
                    ))

            # ── Check 2: DFS instability ───────────────────────────────────
            radar_count = 0
            radar_aps: list[str] = []
            if not isinstance(radar_result, Exception):
                events = radar_result if isinstance(radar_result, list) \
                         else radar_result.get("results", [])
                for evt in events:
                    if isinstance(evt, dict):
                        radar_count += 1
                        ap_name = evt.get("ap_name") or evt.get("ap") or "unknown AP"
                        if ap_name not in radar_aps:
                            radar_aps.append(ap_name)

            if radar_count >= DFS_RADAR_THRESHOLD:
                site_findings.append(Finding(
                    severity=Severity.critical,
                    title=f"{site_name} — DFS instability ({radar_count} radar events in 7 days)",
                    detail=(
                        f"{radar_count} radar detection events occurred at {site_name} "
                        f"in the last 7 days, affecting AP(s): {', '.join(radar_aps[:5])}"
                        f"{'...' if len(radar_aps) > 5 else ''}. "
                        f"Each radar event forces an immediate channel change, "
                        f"dropping all associated clients and disrupting service."
                    ),
                    site_id=sid,
                    site_name=site_name,
                    affected=radar_aps[:10],
                    recommendation=(
                        "Identify the radar source — common causes include weather radar, "
                        "military radar, and airport surveillance systems. Consider "
                        "excluding the affected DFS channels from the allowed channel "
                        "list in the site RF template. Mist RRM learns DFS hit history "
                        "and deprioritizes affected channels automatically over time."
                    ),
                ))

            # ── Check 3: DFS channels not configured ───────────────────────
            # Determine effective 5 GHz channel list from RF template or site setting
            rf_template_id = cfg.get("rf_template_id")
            effective_channels_5: list = []
            source_label = "site settings"

            if rf_template_id and rf_template_id in rf_template_map:
                tmpl = rf_template_map[rf_template_id]
                effective_channels_5 = tmpl.get("band_5", {}).get("channels", []) or []
                source_label = f"RF template '{tmpl.get('name', rf_template_id)}'"
            else:
                # Fall back to site-level band_5 config
                site_band5 = cfg.get("band5", cfg.get("band_5", {}))
                effective_channels_5 = site_band5.get("channels", []) if site_band5 else []

            if _channels_exclude_all_dfs(effective_channels_5):
                site_findings.append(Finding(
                    severity=Severity.warning,
                    title=f"{site_name} — DFS channels excluded from {source_label}",
                    detail=(
                        f"The 5 GHz channel list in {source_label} contains only "
                        f"non-DFS channels: {sorted(effective_channels_5)}. "
                        f"DFS channels (UNII-2A/2C) provide additional spectrum — "
                        f"in environments with sufficient AP density, including DFS "
                        f"channels significantly increases channel reuse options and "
                        f"reduces co-channel interference."
                    ),
                    site_id=sid,
                    site_name=site_name,
                    affected=[site_name],
                    recommendation=(
                        "Review whether DFS channels are appropriate for this environment. "
                        "Best practice is to enable DFS when AP density is sufficient to "
                        "warrant the additional channels. If DFS was excluded due to known "
                        "radar sources nearby, this is intentional and can be acknowledged. "
                        "Otherwise, set the 5 GHz channel list to automatic to allow Mist "
                        "RRM to use DFS channels and learn radar hit patterns over time."
                    ),
                ))

            # ── Check 4: Channel width mismatches ──────────────────────────
            if len(aps) >= MIN_APS_FOR_ANALYSIS:
                for band_key in ["band_5", "band_6"]:
                    band_label = BAND_LABELS[band_key]
                    widths: dict[int, list[str]] = defaultdict(list)
                    for ap in aps:
                        r = _get_radio(ap, band_key)
                        if r and r.get("bandwidth") and r.get("channel"):
                            bw = int(r["bandwidth"])
                            ap_name = ap.get("name", ap.get("mac", "?"))
                            widths[bw].append(ap_name)

                    if len(widths) > 1:
                        # Multiple channel widths in use at same site on same band
                        summary = ", ".join(
                            f"{bw} MHz ({len(aps_list)} APs)"
                            for bw, aps_list in sorted(widths.items(), reverse=True)
                        )
                        site_findings.append(Finding(
                            severity=Severity.warning,
                            title=f"{site_name} — {band_label} channel width mismatch",
                            detail=(
                                f"APs at {site_name} are using mixed {band_label} "
                                f"channel widths: {summary}. "
                                f"Inconsistent channel widths can cause uneven coverage, "
                                f"capacity imbalances, and roaming issues between APs "
                                f"using different widths."
                            ),
                            site_id=sid,
                            site_name=site_name,
                            affected=list({a for ap_list in widths.values() for a in ap_list}),
                            recommendation=(
                                f"Standardize {band_label} channel width across all APs "
                                f"at this site via the RF template. If RRM is managing "
                                f"channel width automatically, review whether the mixed "
                                f"widths are intentional capacity adjustments or the "
                                f"result of suboptimal RRM decisions."
                            ),
                        ))

            # ── Check 5: TX power outliers ─────────────────────────────────
            if len(aps) >= MIN_APS_FOR_ANALYSIS:
                for band_key in ["band_24", "band_5", "band_6"]:
                    band_label = BAND_LABELS[band_key]
                    powers: list[tuple[str, int]] = []
                    for ap in aps:
                        r = _get_radio(ap, band_key)
                        if r and r.get("power") is not None and r.get("channel"):
                            ap_name = ap.get("name", ap.get("mac", "?"))
                            powers.append((ap_name, int(r["power"])))

                    if len(powers) < MIN_APS_FOR_ANALYSIS:
                        continue

                    power_values = [p for _, p in powers]
                    avg_power = statistics.mean(power_values)
                    outliers = [
                        (name, pwr) for name, pwr in powers
                        if abs(pwr - avg_power) >= TX_POWER_OUTLIER_DB
                    ]

                    if outliers:
                        outlier_strs = [
                            f"{name} ({pwr} dBm, {'+' if pwr > avg_power else ''}"
                            f"{pwr - avg_power:.0f} dB from avg)"
                            for name, pwr in sorted(outliers, key=lambda x: abs(x[1] - avg_power), reverse=True)
                        ]
                        site_findings.append(Finding(
                            severity=Severity.info,
                            title=f"{site_name} — {band_label} TX power outlier(s) detected",
                            detail=(
                                f"Site average {band_label} TX power is {avg_power:.0f} dBm. "
                                f"The following APs deviate by ≥{TX_POWER_OUTLIER_DB} dB: "
                                f"{'; '.join(outlier_strs[:5])}. "
                                f"TX power outliers may indicate coverage gaps, "
                                f"asymmetric RF environment, or RRM compensating for "
                                f"a failing or improperly placed neighbor AP."
                            ),
                            site_id=sid,
                            site_name=site_name,
                            affected=[name for name, _ in outliers[:10]],
                            recommendation=(
                                "Review AP placement and neighbor coverage for these APs. "
                                "High TX power outliers may be compensating for a coverage "
                                "gap or a missing/offline neighbor. Low outliers may "
                                "indicate APs in dense areas where RRM has reduced power "
                                "to limit interference — verify SLE coverage is healthy."
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

        critical_count = sum(1 for f in all_findings if f.severity == Severity.critical)
        warning_count  = sum(1 for f in all_findings if f.severity == Severity.warning)
        info_count     = sum(1 for f in all_findings if f.severity == Severity.info)

        if not all_findings:
            summary = f"No RF configuration issues detected across {len(sites)} sites."
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
            sites=site_results_out,
            status="ok",
        )
