"""
Client Experience Trends
========================
Measures SLE trend direction per site over 30 days, comparing the last
7 days against the prior 23-day baseline. Identifies sites that are
improving, stable, or degrading — and which specific metrics are driving
the movement.

Weekend normalization (compromise approach):
  - For each site, calculate weekend user-minutes as a % of total.
  - If weekends < 20% of traffic → "weekday site" → filter to Mon-Fri
    samples only for both windows before scoring.
  - If weekends >= 20% → all samples used (retail, hospitality, campus).

Trend classification (per metric, per site):
  - Improving:  last-7d score > baseline by ≥ 10% relative
  - Degrading:  last-7d score < baseline by ≥ 10% relative
  - Stable:     change < 10% in either direction

Site-level trend = majority vote across all metrics with data.
"""

import asyncio
import logging
import math
from collections import defaultdict
from datetime import datetime, timezone

from models import ModuleOutput, Finding, Severity, SiteResult
from mist_client import MistClient
from .base import BaseModule

logger = logging.getLogger(__name__)

# Wireless SLE metrics to trend — same keys confirmed working in SLE Sentinel
TREND_METRICS = [
    ("coverage",          "Coverage"),
    ("capacity",          "Capacity"),
    ("roaming",           "Roaming"),
    ("throughput",        "Throughput"),
    ("ap-availability",   "AP Uptime"),
    ("failed-to-connect", "Successful Connect"),
    ("time-to-connect",   "Time to Connect"),
]

# Weekend = Saturday (5) and Sunday (6) in Python's weekday() (Mon=0)
WEEKEND_DAYS = {5, 6}

# Threshold for classifying a site as "weekday-dominant"
WEEKEND_TRAFFIC_THRESHOLD = 0.20  # < 20% weekend → filter weekends out

# Minimum relative change to call a trend notable
TREND_THRESHOLD = 0.10  # 10%


def _score_from_samples(
    total_raw: list,
    degraded_raw: list,
    start_ts: int,
    interval: int,
    weekday_only: bool,
) -> float | None:
    """
    Calculate SLE success rate from a slice of hourly samples.
    Optionally filters to weekday hours only.

    Returns 0–100 float, or None if no valid data in the window.
    """
    pairs = []
    for i, (t, d) in enumerate(zip(total_raw, degraded_raw)):
        if t is None or d is None or t <= 0:
            continue
        if weekday_only:
            bucket_ts = start_ts + i * interval
            dt = datetime.fromtimestamp(bucket_ts, tz=timezone.utc)
            if dt.weekday() in WEEKEND_DAYS:
                continue
        pairs.append((float(t), float(d)))

    if not pairs:
        return None

    total_sum    = sum(t for t, _ in pairs)
    degraded_sum = sum(d for _, d in pairs)
    if total_sum <= 0:
        return None

    return float(max(0, min(100, math.ceil((1 - degraded_sum / total_sum) * 100))))


def _weekend_fraction(total_raw: list, start_ts: int, interval: int) -> float:
    """
    Calculate what fraction of user-minutes fall on weekends.
    Used to decide whether to apply weekend filtering.
    """
    weekend_total = 0.0
    all_total     = 0.0
    for i, t in enumerate(total_raw):
        if t is None or t <= 0:
            continue
        all_total += float(t)
        bucket_ts = start_ts + i * interval
        dt = datetime.fromtimestamp(bucket_ts, tz=timezone.utc)
        if dt.weekday() in WEEKEND_DAYS:
            weekend_total += float(t)
    return weekend_total / all_total if all_total > 0 else 0.0


def _relative_change(baseline: float, recent: float) -> float:
    """Relative change from baseline to recent. Positive = improvement."""
    if baseline <= 0:
        return 0.0
    return (recent - baseline) / baseline


class ClientExperienceModule(BaseModule):
    module_id    = "client_experience"
    display_name = "Client Experience Trends"
    icon         = "📈"

    async def analyze(self, org_id: str, sites: list[dict], client: MistClient) -> ModuleOutput:

        # ── 1. Fetch 30-day SLE data for all sites × all metrics ─────────────
        # One call per site × metric for the full 30-day window.
        # We derive both the recent (last 7d) and baseline (days 8-30) windows
        # from the same response by splitting the hourly samples array.

        async def fetch_metric(site_id: str, metric_key: str) -> tuple:
            try:
                data = await client.get_site_sle_metric(
                    site_id, "wireless", metric_key, duration="30d"
                )
                return (site_id, metric_key, data)
            except Exception as e:
                logger.debug(f"Trend fetch failed site={site_id} metric={metric_key}: {e}")
                return (site_id, metric_key, None)

        tasks = [
            fetch_metric(site["id"], metric_key)
            for site in sites
            for metric_key, _ in TREND_METRICS
        ]
        fetch_results = await asyncio.gather(*tasks)

        # Organise: site_data[site_id][metric_key] = raw_response
        site_data: dict[str, dict[str, dict]] = defaultdict(dict)
        for site_id, metric_key, data in fetch_results:
            if data:
                site_data[site_id][metric_key] = data

        # ── 2. Analyse trends per site ───────────────────────────────────────
        all_findings: list[Finding] = []
        site_results: list[SiteResult] = []

        # Org-level counters for summary
        improving_sites  = 0
        degrading_sites  = 0
        stable_sites     = 0

        for site in sites:
            site_id   = site["id"]
            site_name = site.get("name", site_id)
            metrics   = site_data.get(site_id, {})

            if not metrics:
                continue

            # ── Determine weekend filtering for this site ────────────────────
            # Use the coverage metric (most likely to have data) to sample
            # weekend traffic fraction across the full 30-day window.
            weekday_only = False
            sample_data  = next(iter(metrics.values()), {})
            sle_block    = sample_data.get("sle", {}) if sample_data else {}
            samples      = sle_block.get("samples", {}) if sle_block else {}
            start_ts     = sample_data.get("start", 0) if sample_data else 0
            interval     = sle_block.get("interval", 3600) if sle_block else 3600

            if start_ts and isinstance(samples.get("total"), list):
                wf = _weekend_fraction(samples["total"], start_ts, interval)
                weekday_only = wf < WEEKEND_TRAFFIC_THRESHOLD
                logger.debug(
                    f"Site {site_name}: weekend fraction={wf:.1%} "
                    f"→ weekday_only={weekday_only}"
                )

            # ── Score each metric across two windows ─────────────────────────
            metric_trends: list[tuple[str, str, float, float, float]] = []
            # (metric_key, label, baseline_score, recent_score, rel_change)

            for metric_key, metric_label in TREND_METRICS:
                raw = metrics.get(metric_key)
                if not raw:
                    continue

                sle_b   = raw.get("sle", {})
                samps   = sle_b.get("samples", {}) if sle_b else {}
                s_start = raw.get("start", 0)
                s_ivl   = sle_b.get("interval", 3600) if sle_b else 3600
                total_r = samps.get("total",    []) if samps else []
                degr_r  = samps.get("degraded", []) if samps else []

                if not total_r or len(total_r) < 2:
                    continue

                n = len(total_r)
                # Last 7 days = roughly last 168 hourly buckets (7 × 24)
                # Baseline = everything before that
                recent_n  = min(168, n)
                split     = n - recent_n

                baseline_score = _score_from_samples(
                    total_r[:split], degr_r[:split],
                    s_start, s_ivl, weekday_only
                )
                recent_score = _score_from_samples(
                    total_r[split:], degr_r[split:],
                    s_start + split * s_ivl, s_ivl, weekday_only
                )

                if baseline_score is None or recent_score is None:
                    continue

                rel_change = _relative_change(baseline_score, recent_score)
                metric_trends.append(
                    (metric_key, metric_label, baseline_score, recent_score, rel_change)
                )

            if not metric_trends:
                continue

            # ── Classify site-level trend ────────────────────────────────────
            improving_metrics  = [m for m in metric_trends if m[4] >= TREND_THRESHOLD]
            degrading_metrics  = [m for m in metric_trends if m[4] <= -TREND_THRESHOLD]
            stable_metrics     = [m for m in metric_trends if abs(m[4]) < TREND_THRESHOLD]

            n_improving = len(improving_metrics)
            n_degrading = len(degrading_metrics)
            n_total     = len(metric_trends)

            if n_degrading > n_improving and n_degrading > n_total * 0.3:
                site_trend   = "degrading"
                site_severity = Severity.warning
                degrading_sites += 1
            elif n_improving > n_degrading and n_improving > n_total * 0.3:
                site_trend   = "improving"
                site_severity = Severity.ok
                improving_sites += 1
            else:
                site_trend   = "stable"
                site_severity = Severity.ok
                stable_sites += 1

            site_findings: list[Finding] = []

            # Only generate findings for degrading or notably improving sites
            if site_trend == "degrading":
                worst = sorted(degrading_metrics, key=lambda x: x[4])
                metric_lines = [
                    f"{label}: {baseline:.0f}% → {recent:.0f}% "
                    f"({rel*100:+.1f}%)"
                    for _, label, baseline, recent, rel in worst
                ]
                site_findings.append(Finding(
                    severity=Severity.warning,
                    title=f"{site_name} — client experience degrading",
                    detail=(
                        f"{n_degrading} of {n_total} SLE metrics declined "
                        f"≥10% over the past 7 days compared to the prior "
                        f"23-day baseline"
                        f"{' (weekday traffic only)' if weekday_only else ''}:\n"
                        + "\n".join(f"  • {l}" for l in metric_lines)
                    ),
                    site_id=site_id,
                    site_name=site_name,
                    affected=[label for _, label, _, _, _ in worst],
                    recommendation=(
                        "Review the degrading SLE metrics in the Mist dashboard "
                        "for root cause. Check for recent configuration changes, "
                        "new interference sources, or infrastructure issues at this site."
                    ),
                    raw={
                        "trend":       site_trend,
                        "weekday_only": weekday_only,
                        "metrics":     [
                            {
                                "key":      k,
                                "label":    l,
                                "baseline": b,
                                "recent":   r,
                                "change":   round(ch * 100, 1),
                            }
                            for k, l, b, r, ch in metric_trends
                        ],
                    },
                ))

            elif site_trend == "improving":
                best = sorted(improving_metrics, key=lambda x: x[4], reverse=True)
                metric_lines = [
                    f"{label}: {baseline:.0f}% → {recent:.0f}% "
                    f"({rel*100:+.1f}%)"
                    for _, label, baseline, recent, rel in best
                ]
                site_findings.append(Finding(
                    severity=Severity.info,
                    title=f"{site_name} — client experience improving",
                    detail=(
                        f"{n_improving} of {n_total} SLE metrics improved "
                        f"≥10% over the past 7 days"
                        f"{' (weekday traffic only)' if weekday_only else ''}:\n"
                        + "\n".join(f"  • {l}" for l in metric_lines)
                    ),
                    site_id=site_id,
                    site_name=site_name,
                    affected=[label for _, label, _, _, _ in best],
                    recommendation=(
                        "Positive trend — note any recent changes that may have "
                        "contributed so they can be replicated at other sites."
                    ),
                    raw={
                        "trend":       site_trend,
                        "weekday_only": weekday_only,
                        "metrics":     [
                            {
                                "key":      k,
                                "label":    l,
                                "baseline": b,
                                "recent":   r,
                                "change":   round(ch * 100, 1),
                            }
                            for k, l, b, r, ch in metric_trends
                        ],
                    },
                ))

            all_findings.extend(site_findings)

            site_score = self.score_from_findings(site_findings)
            # Stable and improving sites score 100 (no penalty findings)
            site_results.append(SiteResult(
                site_id=site_id,
                site_name=site_name,
                score=site_score,
                severity=site_severity,
                findings=site_findings,
            ))

        # ── 3. Score and summarise ───────────────────────────────────────────
        score    = self.score_from_findings(all_findings)
        severity = self.severity_from_score(score)

        active_sites = improving_sites + degrading_sites + stable_sites

        if active_sites == 0:
            summary = "No SLE trend data available — sites may have insufficient traffic."
        else:
            parts = []
            if degrading_sites:
                parts.append(f"{degrading_sites} degrading")
            if improving_sites:
                parts.append(f"{improving_sites} improving")
            if stable_sites:
                parts.append(f"{stable_sites} stable")
            summary = f"{active_sites} sites analysed — " + ", ".join(parts) + "."

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
