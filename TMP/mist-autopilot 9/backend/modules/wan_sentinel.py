"""
WAN & Uplink Sentinel
=====================
Monitors WAN gateway health, tunnel status, failover events, and WAN SLEs
across all sites in the org. Gracefully handles wireless-only orgs with no
WAN Assurance subscription — returns a clean "no WAN devices found" summary.

Checks performed:
  1. Tunnel down — no failover path → Critical
                 — failover active   → Warning
  2. Tunnel flapping — 3+ tunnel up/down events in 7 days → Warning
  3. WAN SLE degraded — gateway-health, wan-availability, or
                        application-health < 80 → Warning
  4. Recurring WAN instability — 3+ failover events in 7 days → Warning

API sources:
  Org tunnel stats: GET /api/v1/orgs/{org_id}/stats/tunnels?type=wan
    Fields: tunnel_name, up (bool), peer_ip, peer_host, site_id, node, last_event
  Gateway device events: GET /api/v1/sites/{site_id}/devices/events?duration=7d
    Relevant event types:
      GW_TUNNEL_DOWN / GW_TUNNEL_UP    — for flap counting
      GW_WAN_FAILOVER                  — for failover event counting
  WAN SLE metrics (same endpoint pattern as wireless):
    GET /api/v1/sites/{site_id}/sle/site/{site_id}/metric/{metric}/summary?duration=7d
    WAN metrics: gateway-health, wan-availability, application-health
    Returns 400/404 on sites without WAN Assurance — handled gracefully.

Failover detection logic:
  A tunnel is considered "down with failover active" when:
    - The tunnel is down (up == False)
    - AND another tunnel to the same peer/site is up (secondary path carrying traffic)
  Otherwise "down with no failover" → Critical.
"""

import asyncio
import logging
import math
from collections import defaultdict

from models import ModuleOutput, Finding, Severity, SiteResult
from mist_client import MistClient, MistAPIError
from .base import BaseModule

logger = logging.getLogger(__name__)

WAN_SLE_THRESHOLD    = 80
FLAP_THRESHOLD       = 3   # tunnel up/down events in 7d → flapping
FAILOVER_THRESHOLD   = 3   # failover events in 7d → recurring instability

# WAN SLE metric keys to check — 400/404 handled gracefully per metric
WAN_SLE_METRICS = ["gateway-health", "wan-availability", "application-health"]

# Gateway event types
TUNNEL_DOWN_TYPES  = {"GW_TUNNEL_DOWN", "GW_PEER_DOWN", "GW_VPN_DOWN"}
TUNNEL_UP_TYPES    = {"GW_TUNNEL_UP", "GW_PEER_UP", "GW_VPN_UP"}
FAILOVER_TYPES     = {"GW_WAN_FAILOVER", "GW_FAILOVER", "GW_PATH_CHANGE"}


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


class WANSentinelModule(BaseModule):
    module_id    = "wan_sentinel"
    display_name = "WAN & Uplink Sentinel"
    icon         = "🌐"

    async def analyze(self, org_id: str, sites: list[dict], client: MistClient) -> ModuleOutput:

        site_map = {s["id"]: s.get("name", s["id"]) for s in sites}

        # ── 1. Fetch org-wide tunnel stats + per-site events + WAN SLEs ───
        results = await asyncio.gather(
            client.get_org_wan_tunnels(org_id),
            *[client.get_site_gateway_events(site["id"], "7d") for site in sites],
            *[client.get_site_sle_metric(site["id"], "site", metric, "7d")
              for site in sites
              for metric in WAN_SLE_METRICS],
            return_exceptions=True,
        )

        n = len(sites)
        m = len(WAN_SLE_METRICS)

        tunnel_stats   = results[0] if not isinstance(results[0], Exception) else []
        event_results  = results[1      : n+1]
        sle_results    = results[n+1    :]   # n*m results, ordered site0/metric0, site0/metric1...

        # ── 2. Check if any WAN devices exist in this org ─────────────────
        if not tunnel_stats:
            return ModuleOutput(
                module_id=self.module_id,
                display_name=self.display_name,
                icon=self.icon,
                score=100,
                severity=Severity.ok,
                summary="No WAN gateway devices found in this org.",
                findings=[],
                sites=[],
                status="ok",
            )

        # ── 3. Build tunnel map per site ──────────────────────────────────
        # tunnels_by_site: site_id → list of tunnel dicts
        tunnels_by_site: dict[str, list[dict]] = defaultdict(list)
        for t in tunnel_stats:
            if isinstance(t, dict):
                sid = t.get("site_id")
                if sid:
                    tunnels_by_site[sid].append(t)

        # ── 4. Per-site analysis ───────────────────────────────────────────
        all_findings: list[Finding] = []
        site_results_out: list[SiteResult] = []
        wan_sites_seen = set()

        for i, site in enumerate(sites):
            sid       = site["id"]
            site_name = site_map[sid]
            tunnels   = tunnels_by_site.get(sid, [])
            events    = event_results[i] if not isinstance(event_results[i], Exception) else []
            site_findings: list[Finding] = []

            if not tunnels:
                continue  # no WAN devices at this site — skip silently

            wan_sites_seen.add(sid)

            # ── Check 1: Tunnel down ───────────────────────────────────────
            down_tunnels = [t for t in tunnels if not t.get("up", True)]
            up_tunnels   = [t for t in tunnels if t.get("up", True)]
            up_peers     = {t.get("peer_ip") or t.get("peer_host") for t in up_tunnels}

            for t in down_tunnels:
                tunnel_name = t.get("tunnel_name") or t.get("node") or "unknown tunnel"
                peer        = t.get("peer_host") or t.get("peer_ip") or "unknown peer"
                # Failover active if another tunnel to same peer is up
                failover_active = (t.get("peer_ip") in up_peers or
                                   t.get("peer_host") in up_peers)

                if failover_active:
                    site_findings.append(Finding(
                        severity=Severity.warning,
                        title=f"{site_name} — tunnel down, failover active ({tunnel_name})",
                        detail=(
                            f"Tunnel '{tunnel_name}' to {peer} is currently down. "
                            f"A secondary path to the same peer is active and carrying "
                            f"traffic. Service continuity is maintained but the primary "
                            f"path is unavailable."
                        ),
                        site_id=sid,
                        site_name=site_name,
                        affected=[tunnel_name],
                        recommendation=(
                            "Investigate why the primary tunnel is down. Check gateway "
                            "device logs and peer connectivity. Restore the primary path "
                            "to avoid single-path dependency."
                        ),
                    ))
                else:
                    site_findings.append(Finding(
                        severity=Severity.critical,
                        title=f"{site_name} — tunnel down, no failover path ({tunnel_name})",
                        detail=(
                            f"Tunnel '{tunnel_name}' to {peer} is currently down with "
                            f"no active secondary path detected. WAN connectivity for "
                            f"this site may be fully or partially disrupted."
                        ),
                        site_id=sid,
                        site_name=site_name,
                        affected=[tunnel_name],
                        recommendation=(
                            "Investigate immediately. Check gateway device connectivity, "
                            "peer reachability, and upstream ISP status. Consider "
                            "configuring a secondary WAN path for resilience."
                        ),
                    ))

            # ── Check 2: Tunnel flapping ───────────────────────────────────
            # Count tunnel up/down pairs per tunnel name
            tunnel_event_counts: dict[str, int] = defaultdict(int)
            failover_count = 0

            for evt in events:
                if not isinstance(evt, dict):
                    continue
                etype = str(evt.get("type", "")).upper()
                if etype in TUNNEL_DOWN_TYPES or etype in TUNNEL_UP_TYPES:
                    tname = evt.get("tunnel_name") or evt.get("node") or "unknown"
                    tunnel_event_counts[tname] += 1
                if etype in FAILOVER_TYPES:
                    failover_count += 1

            for tname, count in tunnel_event_counts.items():
                if count >= FLAP_THRESHOLD * 2:  # up+down pairs, so 2 events per flap
                    site_findings.append(Finding(
                        severity=Severity.warning,
                        title=f"{site_name} — tunnel flapping ({tname}, {count // 2}+ flaps in 7 days)",
                        detail=(
                            f"Tunnel '{tname}' has experienced {count} up/down state "
                            f"changes in the last 7 days (~{count // 2} flaps). "
                            f"Flapping tunnels disrupt active sessions and indicate "
                            f"an unstable WAN path or peer connectivity issue."
                        ),
                        site_id=sid,
                        site_name=site_name,
                        affected=[tname],
                        recommendation=(
                            "Investigate the underlying WAN path for packet loss, "
                            "latency spikes, or ISP instability. Check BFD/keepalive "
                            "timer settings — overly aggressive timers can cause "
                            "flapping on marginal links."
                        ),
                    ))

            # ── Check 4: Recurring failover events ─────────────────────────
            if failover_count >= FAILOVER_THRESHOLD:
                site_findings.append(Finding(
                    severity=Severity.warning,
                    title=f"{site_name} — recurring WAN failover ({failover_count} events in 7 days)",
                    detail=(
                        f"{failover_count} WAN failover events occurred at {site_name} "
                        f"in the last 7 days. Recurring failovers indicate chronic "
                        f"primary link instability even if the link is currently up."
                    ),
                    site_id=sid,
                    site_name=site_name,
                    affected=[site_name],
                    recommendation=(
                        "Review primary WAN link quality over time — check with the ISP "
                        "for link errors, CRC counts, or known instability. Consider "
                        "adjusting failover thresholds if failovers are triggered too "
                        "aggressively on a marginal but functional link."
                    ),
                ))

            # ── Check 3: WAN SLE degraded ──────────────────────────────────
            for j, metric in enumerate(WAN_SLE_METRICS):
                sle_idx  = i * m + j
                sle_data = sle_results[sle_idx] if sle_idx < len(sle_results) else None
                if isinstance(sle_data, Exception) or sle_data is None:
                    continue
                score = _calc_sle_score(sle_data)
                if score is None:
                    continue
                if score < WAN_SLE_THRESHOLD:
                    metric_label = metric.replace("-", " ").title()
                    site_findings.append(Finding(
                        severity=Severity.warning,
                        title=f"{site_name} — {metric_label} SLE degraded ({score}%)",
                        detail=(
                            f"The {metric_label} SLE for {site_name} is {score}% "
                            f"over the last 7 days (threshold: {WAN_SLE_THRESHOLD}%). "
                            f"This indicates WAN users at this site are experiencing "
                            f"degraded service on this metric."
                        ),
                        site_id=sid,
                        site_name=site_name,
                        affected=[site_name],
                        recommendation=(
                            f"Review the {metric_label} SLE classifiers in the Mist "
                            f"portal for root cause detail. Common causes include WAN "
                            f"link quality issues, gateway resource exhaustion (CPU/memory), "
                            f"or upstream application server problems."
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

        # ── 5. Org score and summary ───────────────────────────────────────
        if not wan_sites_seen:
            return ModuleOutput(
                module_id=self.module_id,
                display_name=self.display_name,
                icon=self.icon,
                score=100,
                severity=Severity.ok,
                summary="No WAN gateway devices found across all sites.",
                findings=[],
                sites=[],
                status="ok",
            )

        score    = self.score_from_findings(all_findings)
        severity = self.severity_from_score(score)

        critical_count = sum(1 for f in all_findings if f.severity == Severity.critical)
        warning_count  = sum(1 for f in all_findings if f.severity == Severity.warning)

        if not all_findings:
            summary = f"No WAN issues detected across {len(wan_sites_seen)} WAN site(s)."
        else:
            parts = []
            if critical_count: parts.append(f"{critical_count} critical")
            if warning_count:  parts.append(f"{warning_count} warnings")
            summary = ", ".join(parts) + f" across {len(wan_sites_seen)} WAN site(s)."

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
