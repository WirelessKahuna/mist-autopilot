"""
SUBMonitor — Subscription & License Auditor
============================================
Audits Mist subscription entitlements against deployed AP inventory.
Uses GET /api/v1/orgs/{org_id}/licenses for all license data.

Checks performed (AP-focused, v1):
  1. Expired subscriptions         — end_time in the past → Critical
  2. Expiring within 30 days       — end_time ≤ 30d from now → Critical
  3. Expiring within 31–90 days    — end_time ≤ 90d from now → Warning
  4. Coverage gap                  — fully_loaded > entitled for SUB-MAN → Critical
  5. Eval APs                      — evals.ap > 0 → Warning (not production subscribed)

SKU reference (AP-relevant):
  SUB-MAN  — Mist AI (base AP management, required for all APs)
  SUB-ENG  — Wired Assurance (switch)
  SUB-AST  — Asset Tracking
  SUB-VNA  — Virtual Network Assistant (Marvis)
  SUB-ME   — Mist Edge
"""

import logging
from datetime import datetime, timezone, timedelta

from models import ModuleOutput, Finding, Severity, SiteResult
from mist_client import MistClient, MistAPIError
from .base import BaseModule

logger = logging.getLogger(__name__)

# Subscription types relevant to AP management
AP_SKU = "SUB-MAN"

# Human-readable SKU descriptions
SKU_LABELS: dict[str, str] = {
    "SUB-MAN":   "Mist AI (AP Management)",
    "SUB-ENG":   "Wired Assurance",
    "SUB-AST":   "Asset Tracking",
    "SUB-VNA":   "Virtual Network Assistant (Marvis)",
    "SUB-ME":    "Mist Edge",
    "SUB-EX12":  "EX12xx Switch",
    "SUB-EX24":  "EX24xx Switch",
    "SUB-SVNA":  "Wired VNA",
    "SUB-WAN":   "WAN Assurance",
    "SUB-WAN1":  "WAN Assurance (1-year)",
    "SUB-WVNA1": "WAN VNA",
}

EXPIRY_CRITICAL_DAYS = 30
EXPIRY_WARNING_DAYS  = 90


def _epoch_to_dt(epoch: int | None) -> datetime | None:
    if epoch is None:
        return None
    return datetime.fromtimestamp(epoch, tz=timezone.utc)


def _days_until(dt: datetime) -> int:
    delta = dt - datetime.now(timezone.utc)
    return delta.days


class SUBMonitorModule(BaseModule):
    module_id    = "sub_monitor"
    display_name = "SUBMonitor"
    icon         = "📋"

    async def analyze(self, org_id: str, sites: list[dict], client: MistClient) -> ModuleOutput:

        # ── 1. Fetch license data ────────────────────────────────────────────
        try:
            data = await client.get(f"/api/v1/orgs/{org_id}/licenses", use_cache=False)
        except MistAPIError as e:
            return self._error_output(f"Failed to fetch license data: {e.message}")

        licenses   = data.get("licenses", [])
        entitled   = data.get("entitled", {})
        fully_loaded = data.get("fully_loaded", {})
        evals      = data.get("evals", {})

        now = datetime.now(timezone.utc)
        findings: list[Finding] = []

        # ── 2. Check each license record for expiry ──────────────────────────
        # Group by type so we report per-SKU, not per-license-line
        expired_skus:  dict[str, list] = {}
        critical_skus: dict[str, list] = {}
        warning_skus:  dict[str, list] = {}

        for lic in licenses:
            sku      = lic.get("type", "unknown")
            qty      = lic.get("quantity", 0)
            end_time = lic.get("end_time")
            sub_id   = lic.get("subscription_id", "unknown")
            end_dt   = _epoch_to_dt(end_time)

            if end_dt is None:
                continue

            days = _days_until(end_dt)
            label = SKU_LABELS.get(sku, sku)
            entry = {
                "sku":    sku,
                "label":  label,
                "qty":    qty,
                "sub_id": sub_id,
                "end_dt": end_dt,
                "days":   days,
            }

            if days < 0:
                expired_skus.setdefault(sku, []).append(entry)
            elif days <= EXPIRY_CRITICAL_DAYS:
                critical_skus.setdefault(sku, []).append(entry)
            elif days <= EXPIRY_WARNING_DAYS:
                warning_skus.setdefault(sku, []).append(entry)

        # Emit findings for expired licenses
        for sku, entries in expired_skus.items():
            total_qty = sum(e["qty"] for e in entries)
            label = SKU_LABELS.get(sku, sku)
            findings.append(Finding(
                severity=Severity.critical,
                title=f"EXPIRED: {label} ({sku}) — {total_qty} license(s)",
                detail=(
                    f"{total_qty} {sku} license(s) have expired. "
                    f"Expired subscriptions may result in loss of features or "
                    f"management capability for affected devices."
                ),
                affected=[f"{e['qty']} × {e['sub_id']} expired {abs(e['days'])} days ago" for e in entries],
                recommendation=(
                    f"Contact your Juniper/HPE account team immediately to renew {sku} licenses. "
                    f"Expired licenses may impact device management and Marvis AI functionality."
                ),
            ))

        # Emit findings for licenses expiring within 30 days
        for sku, entries in critical_skus.items():
            total_qty = sum(e["qty"] for e in entries)
            label = SKU_LABELS.get(sku, sku)
            min_days = min(e["days"] for e in entries)
            findings.append(Finding(
                severity=Severity.critical,
                title=f"Expiring in {min_days}d: {label} ({sku}) — {total_qty} license(s)",
                detail=(
                    f"{total_qty} {sku} license(s) expire within {EXPIRY_CRITICAL_DAYS} days. "
                    f"Immediate renewal action required to avoid service disruption."
                ),
                affected=[f"{e['qty']} × {e['sub_id']} expires {e['days']}d ({e['end_dt'].strftime('%Y-%m-%d')})" for e in entries],
                recommendation=(
                    f"Contact your Juniper/HPE account team to initiate renewal for {sku}. "
                    f"Allow 5–10 business days for license processing."
                ),
            ))

        # Emit findings for licenses expiring within 31–90 days
        for sku, entries in warning_skus.items():
            total_qty = sum(e["qty"] for e in entries)
            label = SKU_LABELS.get(sku, sku)
            min_days = min(e["days"] for e in entries)
            findings.append(Finding(
                severity=Severity.warning,
                title=f"Expiring in {min_days}d: {label} ({sku}) — {total_qty} license(s)",
                detail=(
                    f"{total_qty} {sku} license(s) expire within {EXPIRY_WARNING_DAYS} days. "
                    f"Begin renewal process to avoid last-minute disruption."
                ),
                affected=[f"{e['qty']} × {e['sub_id']} expires {e['days']}d ({e['end_dt'].strftime('%Y-%m-%d')})" for e in entries],
                recommendation=(
                    f"Initiate renewal for {sku} with your account team. "
                    f"Reference subscription ID(s): {', '.join(e['sub_id'] for e in entries)}."
                ),
            ))

        # ── 3. Check AP coverage gap (SUB-MAN) ──────────────────────────────
        man_entitled    = entitled.get(AP_SKU, 0)
        man_fully_loaded = fully_loaded.get(AP_SKU, 0)

        if man_fully_loaded > man_entitled:
            gap = man_fully_loaded - man_entitled
            findings.append(Finding(
                severity=Severity.critical,
                title=f"SUB-MAN coverage gap — {gap} AP(s) unlicensed",
                detail=(
                    f"The org requires {man_fully_loaded} {AP_SKU} licenses to cover all deployed APs "
                    f"but only has {man_entitled} entitled. "
                    f"{gap} AP(s) are operating without a valid management subscription."
                ),
                affected=[f"{gap} AP(s) without SUB-MAN coverage"],
                recommendation=(
                    f"Purchase {gap} additional SUB-MAN licenses to bring the org into compliance. "
                    f"Unlicensed APs may lose management functionality."
                ),
            ))

        # ── 4. Check eval APs ───────────────────────────────────────────────
        eval_aps = evals.get("ap", 0)
        if eval_aps > 0:
            findings.append(Finding(
                severity=Severity.warning,
                title=f"{eval_aps} AP(s) running on eval subscription",
                detail=(
                    f"{eval_aps} AP(s) are operating under an evaluation subscription rather than "
                    f"a production entitlement. Eval subscriptions have a fixed end date and "
                    f"are not renewable — they must be replaced with production licenses."
                ),
                affected=[f"{eval_aps} AP(s) on eval"],
                recommendation=(
                    "Convert eval APs to production SUB-MAN licenses before the eval period ends. "
                    "Contact your Juniper/HPE account team to initiate the conversion."
                ),
            ))

        # ── 5. Score and summarize ───────────────────────────────────────────
        score    = self.score_from_findings(findings)
        severity = self.severity_from_score(score)

        total_licenses = sum(lic.get("quantity", 0) for lic in licenses)
        total_skus     = len(set(lic.get("type") for lic in licenses))

        if not findings:
            summary = (
                f"{total_licenses} licenses across {total_skus} SKU(s) — "
                f"all current, {man_entitled} SUB-MAN entitlements covering all APs."
            )
        else:
            parts = []
            if expired_skus:
                parts.append(f"{len(expired_skus)} expired SKU(s)")
            if critical_skus:
                parts.append(f"{len(critical_skus)} expiring within 30d")
            if warning_skus:
                parts.append(f"{len(warning_skus)} expiring within 90d")
            if man_fully_loaded > man_entitled:
                parts.append(f"SUB-MAN gap: {man_fully_loaded - man_entitled} unlicensed APs")
            if eval_aps:
                parts.append(f"{eval_aps} eval AP(s)")
            summary = ", ".join(parts) + "."

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
