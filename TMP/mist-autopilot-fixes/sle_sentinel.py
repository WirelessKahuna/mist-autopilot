"""
SLE Sentinel
============
Monitors all Mist SLE metrics (Wireless, Wired, WAN) across every site
in the org. Fires anomaly findings when a metric either:
  - Drops below a fixed threshold (absolute floor), OR
  - Drops more than a configured number of points from its recent baseline

Autonomy levels implemented:
  L1 — Detects SLE anomalies org-wide
  L2 — Classifies failure domain (RF / client / switch / WAN) using
        the SLE classifier breakdown returned by the Mist API
  L3 — Webhook notification hook-in point (stubbed, ready to enable)

Adding webhook notifications:
  Set WEBHOOK_URL in your .env and uncomment the _notify() call
  at the bottom of analyze(). The payload is pre-built.
"""

import asyncio
import logging
import math
from dataclasses import dataclass

from models import ModuleOutput, Finding, Severity, SiteResult
from mist_client import MistClient
from .base import BaseModule

logger = logging.getLogger(__name__)

# ── SLE metric definitions ───────────────────────────────────────────────────

@dataclass
class SLEMetric:
    key: str            # Mist API metric key
    label: str          # Human-readable name
    scope: str          # "wireless" | "wired" | "wan"
    threshold: float    # Absolute floor — below this = anomaly
    baseline_drop: float  # Drop from baseline that triggers anomaly


METRICS: list[SLEMetric] = [
    # Wireless — confirmed working metric keys per Mist SLE API docs
    SLEMetric("coverage",          "Coverage",           "wireless", threshold=80.0, baseline_drop=10.0),
    SLEMetric("capacity",          "Capacity",           "wireless", threshold=80.0, baseline_drop=10.0),
    SLEMetric("roaming",           "Roaming",            "wireless", threshold=75.0, baseline_drop=10.0),
    SLEMetric("throughput",        "Throughput",         "wireless", threshold=80.0, baseline_drop=10.0),
    SLEMetric("ap-availability",   "AP Uptime",          "wireless", threshold=90.0, baseline_drop=5.0),
    SLEMetric("failed-to-connect", "Successful Connect", "wireless", threshold=90.0, baseline_drop=5.0),
    SLEMetric("time-to-connect",   "Time to Connect",    "wireless", threshold=80.0, baseline_drop=10.0),
    # Wired — requires Wired Assurance subscription; 404 if not licensed
    # Note: switch-health and wired-nac require Wired Assurance
    SLEMetric("wired-nac",         "Wired NAC",          "wired",    threshold=90.0, baseline_drop=5.0),
    # WAN — requires WAN Assurance subscription; 404 if not licensed
    SLEMetric("wan-availability",  "WAN Availability",   "wan",      threshold=95.0, baseline_drop=5.0),
]

METRIC_MAP = {m.key: m for m in METRICS}

# Lookup: SLE metric key → likely failure domains for L2 classification
FAILURE_DOMAIN_MAP: dict[str, list[str]] = {
    "coverage":           ["RF / Coverage", "AP placement", "TX power"],
    "capacity":           ["RF / Interference", "Channel utilization", "Client density"],
    "roaming":            ["RF / Roaming", "Band steering", "BSS transition"],
    "throughput":         ["RF / Throughput", "Client capability", "Congestion"],
    "ap-availability":    ["AP health", "PoE", "Uplink connectivity"],
    "failed-to-connect":  ["Authentication", "DHCP", "Association"],
    "time-to-connect":    ["Authentication latency", "DHCP", "RADIUS"],
    "switch-health":      ["Switch CPU/memory", "PoE budget", "Switch unreachable"],
    "wired-nac":          ["802.1X auth", "RADIUS", "Certificate"],
    "wan-availability":   ["WAN link", "Gateway", "ISP"],
    "application-health": ["WAN bandwidth", "QoS policy", "ISP throttling"],
}

# SLE scope strings the Mist API accepts
SCOPE_LABELS = {
    "wireless": "Wireless",
    "wired":    "Wired",
    "wan":      "WAN",
}


# ── Helpers ──────────────────────────────────────────────────────────────────

def _extract_score(sle_data: dict | None, metric_key: str) -> float | None:
    """
    Calculate SLE success rate (0-100) from Mist API per-metric summary response.

    Per Mist API docs, the response shape is:
    {
      "sle": {
        "samples": {
          "total":    [1204.1, 1243.9, ...],   # user-minutes per hour
          "degraded": [228.7,  301.4,  ...],   # degraded user-minutes per hour
          "value":    [0.581,  0.580,  ...]    # per-hour fraction (not the summary %)
        }
      },
      "classifiers": [...]
    }

    Success rate = ceil(1 - sum(degraded) / sum(total)) * 100
    Null samples (no data) are filtered out before summing.
    """
    if not sle_data or not isinstance(sle_data, dict):
        return None

    # Primary: compute from sle.samples arrays
    sle_block = sle_data.get("sle", {})
    if isinstance(sle_block, dict):
        samples = sle_block.get("samples", {})
        if isinstance(samples, dict):
            total_raw    = samples.get("total", [])
            degraded_raw = samples.get("degraded", [])
            # Filter out nulls and pair the two arrays
            pairs = [
                (t, d) for t, d in zip(total_raw, degraded_raw)
                if t is not None and d is not None and t > 0
            ]
            if pairs:
                total_sum    = sum(t for t, _ in pairs)
                degraded_sum = sum(d for _, d in pairs)
                if total_sum > 0:
                    score = math.ceil((1 - degraded_sum / total_sum) * 100)
                    return float(max(0, min(100, score)))

    # Fallback: pre-computed top-level value (some endpoint variants)
    if "value" in sle_data:
        try:
            val = float(sle_data["value"])
            # If it looks like a fraction (0-1), convert to percentage
            return round(val * 100, 1) if val <= 1.0 else round(val, 1)
        except (TypeError, ValueError):
            pass

    return None


def _extract_classifiers(sle_data: dict | None, metric_key: str) -> list[dict]:
    """
    Extract classifier impact breakdown for L2 failure domain classification.

    Mist API response shape:
    {
      "sle": { "samples": {...} },
      "classifiers": [
        {
          "name": "weak-signal",
          "samples": {
            "total":    [...],
            "degraded": [...],
            "value":    [...]
          }
        }
      ]
    }

    Classifier impact = sum(degraded) / sum(all classifiers degraded) * 100
    """
    if not sle_data or not isinstance(sle_data, dict):
        return []

    raw_classifiers = sle_data.get("classifiers", [])
    if not isinstance(raw_classifiers, list) or not raw_classifiers:
        return []

    results = []
    for clf in raw_classifiers:
        if not isinstance(clf, dict):
            continue
        name = clf.get("name") or clf.get("classifier", "unknown")
        # Calculate degraded sum from samples if available
        samples  = clf.get("samples", {})
        degraded = samples.get("degraded", []) if isinstance(samples, dict) else []
        degraded_sum = sum(d for d in degraded if d is not None)
        results.append({"name": str(name), "_degraded": degraded_sum})

    # Convert to impact percentages
    total_degraded = sum(r["_degraded"] for r in results)
    classifiers = []
    for r in results:
        impact = (r["_degraded"] / total_degraded * 100) if total_degraded > 0 else 0
        classifiers.append({"name": r["name"], "impact": round(impact, 1)})

    return sorted(classifiers, key=lambda x: x["impact"], reverse=True)


def _classify_failure_domain(metric_key: str, classifiers: list[dict]) -> str:
    """
    Build an L2 failure domain string from classifier data.
    Falls back to the static domain map if no classifiers are available.
    """
    if classifiers:
        top = classifiers[:3]
        parts = [f'{c["name"]} ({c["impact"]:.0f}%)' for c in top]
        return "Top classifiers: " + ", ".join(parts)
    domains = FAILURE_DOMAIN_MAP.get(metric_key, ["Unknown"])
    return "Likely domains: " + ", ".join(domains)


def _severity_for_anomaly(score: float, threshold: float, baseline: float | None) -> Severity:
    """
    Determine finding severity based on how far the score has fallen.
    """
    gap = threshold - score  # how far below threshold
    baseline_gap = (baseline - score) if baseline is not None else 0

    if score < threshold - 20 or baseline_gap > 20:
        return Severity.critical
    if score < threshold - 10 or baseline_gap > 15:
        return Severity.warning
    return Severity.info


# ── Stub for L3 webhook (ready to enable) ───────────────────────────────────

async def _notify_webhook(payload: dict) -> None:
    """
    L3 stub — push anomaly context to a webhook endpoint.
    To enable:
      1. Set WEBHOOK_URL in your .env
      2. Uncomment the import and call below
    """
    # import httpx, os
    # url = os.getenv("WEBHOOK_URL")
    # if not url:
    #     return
    # async with httpx.AsyncClient(timeout=10) as client:
    #     await client.post(url, json=payload)
    pass


# ── Module ───────────────────────────────────────────────────────────────────

class SLESentinelModule(BaseModule):
    module_id    = "sle_sentinel"
    display_name = "SLE Sentinel"
    icon         = "📊"

    async def analyze(self, org_id: str, sites: list[dict], client: MistClient) -> ModuleOutput:

        # ── 1. Fetch SLE data — one call per site × metric × window ──────────
        # Correct Mist endpoint:
        #   GET /api/v1/sites/{site_id}/sle/{scope}/{metric}/summary?duration=Xd
        # Each metric needs its own request — there is no single rollup endpoint.
        # We fetch two windows: current (1d) and baseline (7d) for drift detection.

        async def fetch_metric(
            site_id: str, scope: str, metric_key: str, duration: str
        ) -> tuple[str, str, str, dict | None]:
            try:
                data = await client.get_site_sle_metric(site_id, scope, metric_key, duration)
                return (site_id, metric_key, duration, data)
            except Exception as e:
                # 404 = metric not enabled/licensed for this site — expected, not an error
                logger.debug(
                    f"SLE unavailable site={site_id} metric={metric_key} "
                    f"duration={duration}: {e}"
                )
                return (site_id, metric_key, duration, None)

        tasks = [
            fetch_metric(site["id"], metric.scope, metric.key, window)
            for site in sites
            for metric in METRICS
            for window in ("1d", "7d")
        ]
        fetch_results = await asyncio.gather(*tasks)

        # Organise into: site_metric_data[site_id][metric_key] = {current, baseline}
        site_metric_data: dict[str, dict[str, dict]] = {}
        for site_id, metric_key, duration, data in fetch_results:
            site_metric_data.setdefault(site_id, {}).setdefault(
                metric_key, {"current": None, "baseline": None}
            )
            window = "current" if duration == "1d" else "baseline"
            site_metric_data[site_id][metric_key][window] = data

        # ── 2. Analyse each site ─────────────────────────────────────────────
        all_findings: list[Finding] = []
        site_results: list[SiteResult] = []
        webhook_payloads: list[dict] = []

        for site in sites:
            site_id   = site["id"]
            site_name = site.get("name", site_id)
            site_findings: list[Finding] = []

            for metric in METRICS:
                metric_windows = site_metric_data.get(site_id, {}).get(metric.key, {})
                curr_sle  = metric_windows.get("current")
                base_sle  = metric_windows.get("baseline")

                current_score  = _extract_score(curr_sle,  metric.key)
                baseline_score = _extract_score(base_sle,  metric.key)

                if current_score is None:
                    # Metric not available for this site (scope not licensed/enabled)
                    continue

                # ── L1: Anomaly Detection ────────────────────────────────────
                below_threshold = current_score < metric.threshold
                below_baseline  = (
                    baseline_score is not None
                    and (baseline_score - current_score) >= metric.baseline_drop
                )

                if not (below_threshold or below_baseline):
                    continue  # No anomaly — skip

                # ── L2: Failure Domain Classification ───────────────────────
                classifiers   = _extract_classifiers(curr_sle, metric.key)
                failure_domain = _classify_failure_domain(metric.key, classifiers)
                severity      = _severity_for_anomaly(
                    current_score, metric.threshold, baseline_score
                )

                # Build trigger description
                triggers = []
                if below_threshold:
                    triggers.append(
                        f"score {current_score:.1f} is below threshold of {metric.threshold}"
                    )
                if below_baseline:
                    drop = baseline_score - current_score
                    triggers.append(
                        f"dropped {drop:.1f} pts from 7-day baseline of {baseline_score:.1f}"
                    )

                scope_label = SCOPE_LABELS.get(metric.scope, metric.scope.title())

                finding = Finding(
                    severity=severity,
                    title=f"{site_name} — {metric.label} SLE anomaly",
                    detail=(
                        f"[{scope_label}] {metric.label}: current score {current_score:.1f}. "
                        f"{' and '.join(t.capitalize() for t in triggers)}. "
                        f"{failure_domain}."
                    ),
                    site_id=site_id,
                    site_name=site_name,
                    affected=[metric.label],
                    recommendation=_build_recommendation(metric, current_score, classifiers),
                    raw={
                        "metric":         metric.key,
                        "scope":          metric.scope,
                        "current_score":  current_score,
                        "baseline_score": baseline_score,
                        "threshold":      metric.threshold,
                        "classifiers":    classifiers,
                    },
                )

                site_findings.append(finding)
                all_findings.append(finding)

                # ── L3: Build webhook payload (ready to fire) ────────────────
                webhook_payloads.append({
                    "site_id":       site_id,
                    "site_name":     site_name,
                    "metric":        metric.key,
                    "metric_label":  metric.label,
                    "scope":         metric.scope,
                    "current_score": current_score,
                    "baseline_score": baseline_score,
                    "severity":      severity.value,
                    "failure_domain": failure_domain,
                    "recommendation": finding.recommendation,
                })

            site_score = self.score_from_findings(site_findings)
            site_results.append(SiteResult(
                site_id=site_id,
                site_name=site_name,
                score=site_score,
                severity=self.severity_from_score(site_score),
                findings=site_findings,
            ))

        # ── 3. L3 webhook dispatch (stubbed — uncomment to enable) ──────────
        # for payload in webhook_payloads:
        #     await _notify_webhook(payload)

        # ── 4. Score and summarise ───────────────────────────────────────────
        # Count how many site×metric combinations had actual data
        data_points = sum(
            1 for site in sites
            for metric in METRICS
            if _extract_score(
                site_metric_data.get(site["id"], {}).get(metric.key, {}).get("current"),
                metric.key
            ) is not None
        )

        score    = self.score_from_findings(all_findings)
        severity = self.severity_from_score(score)

        critical_count = sum(1 for f in all_findings if f.severity == Severity.critical)
        warning_count  = sum(1 for f in all_findings if f.severity == Severity.warning)
        anomaly_sites  = len({f.site_id for f in all_findings if f.site_id})

        scope_counts: dict[str, int] = {}
        for f in all_findings:
            scope = f.raw.get("scope", "unknown") if f.raw else "unknown"
            scope_counts[scope] = scope_counts.get(scope, 0) + 1

        if data_points == 0:
            # No SLE data at all — new org, no clients, or very recently onboarded
            summary = f"No SLE data available across {len(sites)} sites — org may be newly onboarded or have no active clients."
            severity = Severity.info
        elif not all_findings:
            summary = f"All SLE metrics healthy across {len(sites)} sites ({data_points} data points checked)."
        else:
            parts = []
            if critical_count: parts.append(f"{critical_count} critical")
            if warning_count:  parts.append(f"{warning_count} warnings")
            scope_str = ", ".join(
                f"{SCOPE_LABELS.get(k, k)}: {v}" for k, v in scope_counts.items()
            )
            summary = (
                f"{anomaly_sites} sites with SLE anomalies — "
                + ", ".join(parts)
                + f". ({scope_str})"
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


def _build_recommendation(metric: SLEMetric, score: float, classifiers: list[dict]) -> str:
    """
    Build a specific, actionable recommendation based on the metric type
    and top classifiers returned by Mist.
    """
    top_classifier = classifiers[0]["name"].lower() if classifiers else ""

    recommendations: dict[str, str] = {
        "coverage": (
            "Check for coverage gaps using the Mist location map. "
            "Review AP TX power settings and consider additional APs in weak-signal areas. "
            "Verify RRM is enabled and performing auto-adjustments."
        ),
        "capacity": (
            "Review channel utilization per AP. Check for co-channel interference (CCI) "
            "on 2.4 GHz. Consider enabling 6 GHz if APs and clients support Wi-Fi 6E. "
            "Review band steering thresholds to push clients to less congested bands."
        ),
        "roaming": (
            "Check BSS transition (802.11v) and fast BSS transition (802.11r) settings. "
            "Review sticky client thresholds. Ensure AP TX power is not too high, "
            "which can cause clients to hold onto distant APs."
        ),
        "throughput": (
            "Review minimum data rates — disable legacy rates (1, 2, 5.5 Mbps) on 5/6 GHz. "
            "Check for RF interference sources. Verify WMM QoS is enabled."
        ),
        "ap-availability": (
            "Check AP uptime in Mist dashboard. Review PoE budget on connected switches. "
            "Inspect uplink port status. Consider enabling AP auto-upgrade "
            "to resolve firmware-related crash loops."
        ),
        "failed-to-connect": (
            "Review authentication failure events in Mist. Check RADIUS server reachability "
            "and certificate validity. Verify DHCP pool capacity and lease times. "
            "Look for association failures under the classifier breakdown."
        ),
        "time-to-connect": (
            "Review RADIUS response times — high latency causes slow associations. "
            "Check DHCP server performance and pool exhaustion. "
            "Verify DNS resolution is functioning at the site."
        ),
        "switch-health": (
            "Review PoE budget utilisation per switch. Check for overloaded PoE ports. "
            "Inspect port error counters for CRC errors and duplex mismatches. "
            "Verify PoE+ (802.3at) or PoE++ (802.3bt) is used for high-draw devices."
        ),
        "wired-nac": (
            "Review 802.1X authentication failures on wired ports. "
            "Check RADIUS server reachability from the switch. "
            "Verify client certificates are valid and not expired."
        ),
        "wan-availability": (
            "Check WAN link status and gateway health in Mist. "
            "Review SD-WAN failover policies. Verify SLA probe destinations are reachable. "
            "Contact ISP if physical link is degraded."
        ),
        "application-health": (
            "Review WAN bandwidth utilisation. Check for QoS policy misconfiguration. "
            "Verify traffic shaping policies are not throttling legitimate traffic. "
            "Consider increasing WAN capacity if sustained utilisation exceeds 80%."
        ),
    }

    base_rec = recommendations.get(
        metric.key,
        f"Review {metric.label} SLE classifiers in the Mist dashboard for root cause details."
    )

    # Append classifier-specific context if available
    if top_classifier and "interference" in top_classifier:
        base_rec += " Top classifier suggests RF interference — run a spectrum scan."
    elif top_classifier and "auth" in top_classifier:
        base_rec += " Top classifier suggests authentication failures — review RADIUS logs."
    elif top_classifier and "dhcp" in top_classifier:
        base_rec += " Top classifier suggests DHCP issues — check DHCP server capacity and lease times."
    elif top_classifier and "dns" in top_classifier:
        base_rec += " Top classifier suggests DNS resolution failures — verify DNS server reachability."

    return base_rec
