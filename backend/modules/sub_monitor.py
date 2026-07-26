"""
SUBMonitor: Subscription Auditor and Renewal Analyzer
=====================================================
Audits Mist subscription entitlements against actual usage and projects
entitlement levels forward in time so renewal cliffs are visible before
they become outages.

Data source: GET /api/v1/orgs/{org_id}/licenses
(the URL path is a legacy Mist API artifact; all authored vocabulary in
this module is "subscription")

Response field semantics, verified 26-JUL-2026 against a live customer
org by cross-checking the raw payload with the Subscriptions UI:
  entitled     : sum of quantities on subscription lines active right now
  summary      : devices currently consuming each subscription type (Usage)
  fully_loaded : worst-case demand if the feature were enabled everywhere
  licenses[]   : full purchase history, one line per order line item,
                 including long-expired lines back to org creation

Checks performed (v2):
  1. Exceeded now:      usage > entitled for any SKU              -> Critical
  2. Future breach:     entitled drops below current usage,
                        within 90 days                            -> Critical
                        within 91 to 180 days                     -> Warning
  3. Renewal decision:  expiry within 180 days that does not
                        breach coverage                           -> Info
  4. Evaluations:       evals present                             -> Warning

Expired lines that were superseded by later purchases produce no
findings. They exist only as history inside the renewal data payload.
"""

import logging
from datetime import datetime, timezone

from models import ModuleOutput, Finding, Severity
from mist_client import MistClient, MistAPIError
from .base import BaseModule
from ._mist_urls import subscriptions_url

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# SKU dictionary
# Labels verified against a customer org Subscriptions UI capture, 26-JUL-2026.
# Do not edit labels without a UI screenshot or Juniper document as provenance.
# ---------------------------------------------------------------------------
SKU_LABELS: dict[str, str] = {
    "SUB-MAN":   "Wi-Fi Management and Assurance",
    "SUB-VNA":   "Marvis for Wireless",
    "SUB-ENG":   "vBLE Engagement",
    "SUB-AST":   "Asset Visibility",
    "SUB-ME":    "Mist Edge",
    "SUB-CLNT":  "Access Assurance Standard",
    "SUB-EX24":  "Wired Assurance 24",
    "SUB-EX48":  "Wired Assurance 48",
    "SUB-SVNA":  "Marvis for Wired Network",
    "SUB-WAN":   "WAN Assurance",
    "SUB-WAN1":  "WAN Assurance for Class 1",
    "SUB-WAN2":  "WAN Assurance for Class 2",
    "SUB-WAN3":  "WAN Assurance for Class 3",
    "SUB-WAN4":  "WAN Assurance for Class 4",
    "SUB-WAN5":  "WAN Assurance for Class 5",
    "SUB-WVNA":  "Marvis for WAN",
    "SUB-WVNA1": "Marvis for WAN for SRX Class 1",
    "SUB-WVNA2": "Marvis for WAN for SRX Class 2",
    "SUB-WVNA3": "Marvis for WAN for SRX Class 3",
    "SUB-WVNA4": "Marvis for WAN for SRX Class 4",
    "SUB-WVNA5": "Marvis for WAN for SRX Class 5",
}

# Paired SKU convention: these arrive as twin order lines with identical
# quantity and dates. The frontend uses this to roll pairs up for display.
PAIRED_SKUS: list[tuple[str, str]] = [
    ("SUB-MAN",  "SUB-VNA"),
    ("SUB-EX48", "SUB-SVNA"),
    ("SUB-EX24", "SUB-SVNA"),
]

BREACH_CRITICAL_DAYS = 90
BREACH_WARNING_DAYS  = 180

DAY_SECONDS = 86400


def _fmt_date(epoch: int) -> str:
    return datetime.fromtimestamp(epoch, tz=timezone.utc).strftime("%d-%b-%Y").upper()


def _join_orders(orders: list[str]) -> str:
    """Render order IDs for findings text; pseudo-orders get readable names."""
    names = {"Mist": "eval", "00000000": "Mist grant"}
    return ", ".join(names.get(o, o) for o in orders)


def classify_line(line: dict) -> str:
    """
    production   : purchased subscription line, renewable
    system_grant : Mist-issued grant (order 00000000), not renewable
    eval         : evaluation subscription (order "Mist"), not renewable
    """
    order = line.get("order_id") or ""
    sub_id = line.get("subscription_id") or ""
    if order == "Mist" or sub_id.startswith("SUB-Eval"):
        return "eval"
    if order == "00000000":
        return "system_grant"
    return "production"


def entitlement_events(lines: list[dict]) -> dict[str, list[tuple[int, int, str]]]:
    """
    Convert subscription lines into per-SKU event lists for a sweep:
    (+quantity at start_time, -quantity at end_time), sorted by time.
    """
    events: dict[str, list[tuple[int, int, str]]] = {}
    for line in lines:
        sku = line.get("type")
        qty = line.get("quantity") or 0
        start = line.get("start_time")
        end = line.get("end_time")
        order = line.get("order_id") or ""
        if not sku or qty <= 0 or start is None or end is None:
            continue
        events.setdefault(sku, [])
        events[sku].append((start, qty, order))
        events[sku].append((end, -qty, order))
    for sku in events:
        events[sku].sort(key=lambda e: e[0])
    return events


def level_at(events: list[tuple[int, int, str]], t: int) -> int:
    """Entitled quantity at time t (events at exactly t are applied)."""
    return sum(delta for ts, delta, _ in events if ts <= t)


def future_drops(events: list[tuple[int, int, str]], now: int) -> list[dict]:
    """
    All future expiry events, grouped by timestamp, with the entitled
    level after each event and the order IDs responsible.
    """
    grouped: dict[int, dict] = {}
    for ts, delta, order in events:
        if ts > now and delta < 0:
            rec = grouped.setdefault(ts, {"qty": 0, "orders": set()})
            rec["qty"] += -delta
            rec["orders"].add(order)
    drops = []
    for ts in sorted(grouped):
        drops.append({
            "t": ts,
            "date": _fmt_date(ts),
            "qty_expiring": grouped[ts]["qty"],
            "allowed_after": level_at(events, ts),
            "orders": sorted(grouped[ts]["orders"]),
        })
    return drops


def timeline_series(events: list[tuple[int, int, str]], now: int) -> list[dict]:
    """Forward step series for the chart: level now, then after each event."""
    series = [{"t": now, "allowed": level_at(events, now)}]
    for ts in sorted({ts for ts, _, _ in events if ts > now}):
        series.append({"t": ts, "allowed": level_at(events, ts)})
    return series


class SUBMonitorModule(BaseModule):
    module_id    = "sub_monitor"
    display_name = "SUBMonitor"
    icon         = "📋"

    async def analyze(self, org_id: str, sites: list[dict], client: MistClient) -> ModuleOutput:

        # 1. Fetch subscription data (one org-scoped call)
        try:
            data = await client.get(f"/api/v1/orgs/{org_id}/licenses", use_cache=False)
        except MistAPIError as e:
            return self._error_output(f"Failed to fetch subscription data: {e.message}")

        # "licenses" is the legacy Mist API response key. Normalized to
        # subscription vocabulary here and never referenced again.
        sub_lines    = data.get("licenses", []) or []
        entitled     = data.get("entitled", {}) or {}
        usage        = data.get("summary", {}) or {}
        fully_loaded = data.get("fully_loaded", {}) or {}
        evals        = data.get("evals", {}) or {}

        now = int(datetime.now(timezone.utc).timestamp())

        # 2. Classify lines once; classes tag timeline events and the order
        # table. The timeline sweeps ALL lines (production, grants, evals) so
        # levels match the Mist dashboard to the unit; grant and eval
        # expiries appear as their own timeline events.
        for line in sub_lines:
            line["_class"] = classify_line(line)
            rq = line.get("remaining_quantity")
            if rq is not None and rq != (line.get("quantity") or 0):
                logger.warning(
                    f"remaining_quantity {rq} != quantity for "
                    f"{line.get('subscription_id')}; semantics unverified, "
                    f"using quantity"
                )
        all_events = entitlement_events(sub_lines)

        findings: list[Finding] = []
        sku_payload: dict[str, dict] = {}

        skus = sorted(set(all_events) | set(entitled) | set(usage))

        for sku in skus:
            label   = SKU_LABELS.get(sku, sku)
            api_ent = entitled.get(sku, 0)
            used    = usage.get(sku, 0)
            events  = all_events.get(sku, [])
            drops   = future_drops(events, now)

            # Cross-check our sweep against the API rollup (all line classes).
            swept = level_at(all_events.get(sku, []), now)
            if swept != api_ent:
                logger.warning(
                    f"{sku}: swept entitlement {swept} != API entitled {api_ent}; "
                    f"possible amendment or unmodeled line, using API value"
                )

            status = "inactive"
            if used > api_ent:
                status = "exceeded"
            elif api_ent > 0:
                status = "active"

            sku_payload[sku] = {
                "label": label,
                "entitled": api_ent,
                "usage": used,
                "fully_loaded": fully_loaded.get(sku, 0),
                "status": status,
                "timeline": timeline_series(events, now),
                "drops": [
                    {**d, "shortfall": max(0, used - d["allowed_after"])}
                    for d in drops
                ],
            }

            # 3. Exceeded now: usage beyond current entitlement.
            if used > api_ent:
                gap = used - api_ent
                findings.append(Finding(
                    severity=Severity.critical,
                    title=f"Exceeded: {label} ({sku}), usage {used} of {api_ent} entitled",
                    detail=(
                        f"{used} devices are consuming {label} but only {api_ent} "
                        f"subscriptions are entitled. {gap} devices are operating "
                        f"beyond entitlement."
                    ),
                    affected=[f"{gap} devices over entitlement"],
                    recommendation=(
                        f"Purchase {gap} additional {sku} subscriptions, or reduce "
                        f"usage by disabling the feature at selected sites."
                    ),
                    fix_url=subscriptions_url(client.portal_base, org_id),
                ))

            # 4. Future coverage breaches and renewal decision points.
            if used > 0:
                breach_reported = False
                for d in drops:
                    days = (d["t"] - now) // DAY_SECONDS
                    if days > BREACH_WARNING_DAYS:
                        break
                    shortfall = used - d["allowed_after"]
                    if shortfall > 0 and not breach_reported:
                        breach_reported = True
                        sev = (
                            Severity.critical
                            if days <= BREACH_CRITICAL_DAYS
                            else Severity.warning
                        )
                        findings.append(Finding(
                            severity=sev,
                            title=(
                                f"Coverage breach {d['date']}: {label} ({sku}), "
                                f"shortfall {shortfall}"
                            ),
                            detail=(
                                f"{d['qty_expiring']} {sku} subscriptions expire on "
                                f"{d['date']} (order {_join_orders(d['orders'])}). "
                                f"Entitlement drops to {d['allowed_after']} against "
                                f"current usage of {used}: a shortfall of {shortfall}. "
                                f"Accounting view: renew {d['qty_expiring']} units. "
                                f"Operations view: {shortfall} devices lose coverage."
                            ),
                            affected=[f"{d['qty_expiring']} units expiring {d['date']}"],
                            recommendation=(
                                f"Initiate renewal for order(s) "
                                f"{_join_orders(d['orders'])} before {d['date']}. "
                                f"Allow 5 to 10 business days for order processing."
                            ),
                            fix_url=subscriptions_url(client.portal_base, org_id),
                        ))
                    elif shortfall <= 0:
                        findings.append(Finding(
                            severity=Severity.info,
                            title=(
                                f"Renewal decision {d['date']}: {label} ({sku}), "
                                f"{d['qty_expiring']} units"
                            ),
                            detail=(
                                f"{d['qty_expiring']} {sku} subscriptions expire on "
                                f"{d['date']} (order {_join_orders(d['orders'])}). "
                                f"Remaining entitlement {d['allowed_after']} still "
                                f"covers current usage of {used}, so this is a "
                                f"renewal decision, not an outage risk."
                            ),
                        ))

        # 5. Evaluation subscriptions (counted once, from the evals object).
        if evals:
            eval_lines = [l for l in sub_lines if l["_class"] == "eval"]
            eval_end = min(
                (l.get("end_time") for l in eval_lines if l.get("end_time")),
                default=None,
            )
            desc = ", ".join(f"{count} {kind}(s)" for kind, count in evals.items())
            end_txt = f" Evaluation period ends {_fmt_date(eval_end)}." if eval_end else ""
            findings.append(Finding(
                severity=Severity.warning,
                title=f"Evaluation subscriptions in use: {desc}",
                detail=(
                    f"{desc} operating under evaluation subscriptions rather than "
                    f"production entitlements. Evaluations have fixed end dates "
                    f"and are not renewable; they must be replaced with production "
                    f"subscriptions.{end_txt}"
                ),
                recommendation=(
                    "Convert evaluation devices to production subscriptions "
                    "before the evaluation period ends."
                ),
            ))

        # 6. Order table for the renewal report, sorted by earliest end date.
        orders: dict[str, dict] = {}
        for line in sub_lines:
            sku = line.get("type")
            if not sku:
                continue
            oid = line.get("order_id") or "unknown"
            rec = orders.setdefault(oid, {
                "order_id": oid,
                "class": line["_class"],
                "lines": [],
            })
            rec["lines"].append({
                "subscription_id": line.get("subscription_id"),
                "sku": sku,
                "label": SKU_LABELS.get(sku, sku),
                "qty": line.get("quantity") or 0,
                "start": line.get("start_time"),
                "end": line.get("end_time"),
            })
        order_table = sorted(
            orders.values(),
            key=lambda o: min((l["end"] or 0) for l in o["lines"]),
        )

        # 7. Score and summarize.
        score    = self.score_from_findings(findings)
        severity = self.severity_from_score(score)

        exceeded = [s for s, p in sku_payload.items() if p["status"] == "exceeded"]
        breaches = [f for f in findings if f.title.startswith("Coverage breach")]

        parts = []
        if exceeded:
            parts.append(f"{len(exceeded)} type(s) exceeded ({', '.join(exceeded)})")
        if breaches:
            parts.append(breaches[0].title)
        if evals:
            parts.append(f"{sum(evals.values())} eval device(s)")
        if not parts:
            active = [s for s, p in sku_payload.items() if p["status"] == "active"]
            parts.append(
                f"{len(active)} subscription type(s) active, coverage holds "
                f"for {BREACH_WARNING_DAYS} days"
            )
        summary = "; ".join(parts) + "."

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
            data={
                "as_of": now,
                "skus": sku_payload,
                "orders": order_table,
                "paired_skus": PAIRED_SKUS,
                "evals": evals,
            },
        )
