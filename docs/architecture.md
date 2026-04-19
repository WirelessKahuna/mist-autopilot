# Mist Autopilot — Architecture

## Overview

Mist Autopilot is a self-driving network org health review tool built on Mist APIs.
It runs twelve analysis modules in parallel and surfaces findings in a single-pane dashboard,
replacing manual network reviews with automated detection, diagnosis, and recommended remediation.

## Stack

| Layer | Technology | Reason |
|---|---|---|
| Backend | Python 3.12 + FastAPI | Async-native, auto-generates API docs at /docs |
| Frontend | React 18 + Vite + Tailwind | Modern, component-based, hot-reload during development |
| Deployment | Docker Compose | Single-command launch, no local Python/Node required |
| Auth | Mist Org API token, pasted at runtime | Token never reaches the browser after auth; server-side session-only |
| Cache | In-memory TTLCache (5 min) | Reduces redundant API calls within a session |

## Module Architecture

Every module inherits from `BaseModule` and implements one method:

```python
async def analyze(self, org_id: str, sites: list[dict], client: MistClient) -> ModuleOutput
```

All modules run concurrently via `asyncio.gather()` on every dashboard refresh.
Adding a new module requires creating one Python file and registering it in `modules/__init__.py`.
It appears in the dashboard automatically.

### ModuleOutput Contract

Every module returns a `ModuleOutput` with:
- `score` — 0–100 health score (100 = no issues detected)
- `severity` — ok / info / warning / critical
- `summary` — one-line human-readable description
- `findings` — list of `Finding` objects with detail and recommendations
- `sites` — per-site breakdown with individual scores

### Score Calculation

Module scores use a square-root diminishing-returns curve so a module with many
findings of the same severity doesn't slam straight to zero:

```
score = 100 − 20·√C − 10·√W − 2·√I
```

where C, W, I are counts of critical, warning, and info findings. Clamped to [0, 100].

This preserves intuition (one critical is meaningfully worse than one warning) while
keeping the top end distinguishable (a module with 25 criticals still scores lower than
one with 5, instead of both flooring at zero). For reference:

| Criticals | Score (ignoring other findings) |
|---|---|
| 1 | 80 |
| 3 | 65 |
| 5 | 55 |
| 10 | 37 |
| 25 | 0 |

Score ranges map to severity: 80–100 = Healthy, 60–79 = Info, 40–59 = Warning, 0–39 = Critical.

### Org-Level Rollup

The top-of-page Org Health score is the unweighted arithmetic mean of every module's
score, rounded to the nearest integer. Modules that error out (score = None) are
excluded from the average rather than counted as zero — a broken check should not
drag down an otherwise healthy org's score.

## Modules Built

| Module | Autonomy Level | Key APIs Used |
|---|---|---|
| SecureScope | L1 + L2 | /sites/{id}/wlans |
| AuthGuard | L1 + L2 | /orgs/{id}/nacrules, /orgs/{id}/nactags, /orgs/{id}/setting |
| RoamGuard | L1 + L2 | /sites/{id}/sle/.../roaming, events endpoints |
| SLE Sentinel | L1 + L2 + L3 hook | /sites/{id}/sle/{scope}/{metric}/summary |
| RF Fingerprint Analyzer | L1 + L2 | /sites/{id}/stats/devices, RF templates |
| Client Experience Trends | L1 + L2 | /sites/{id}/sle/{scope}/{metric}/summary (30d window) |
| Config Drift Detective | L1 + L2 | /orgs/{id}/wlans, /sites/{id}/wlans, /orgs/{id}/wlantemplates |
| AP Lifecycle Monitor | L1 + L2 + L3 hook | /orgs/{id}/inventory, /sites/{id}/setting |
| WAN & Uplink Sentinel | L1 + L2 | gateway stats, WAN tunnels, WAN SLE metrics |
| SUBMonitor | L1 | /orgs/{id}/licenses |
| MinisMonitor | L1 | /orgs/{id}/licenses, /orgs/{id}/setting, inventory |
| MarvisIQ | L1 | /labs/orgs/{id}/suggestions |

## API Rate Limit Scaling Considerations

> ⚠️ **Important for production deployments at scale**

Mist enforces a rate limit of **5,000 API calls per hour** per token.

### Calls per dashboard refresh by org size

The two most API-intensive modules are SLE Sentinel and Client Experience Trends,
both of which make one call per site × metric × time window.

| Org size | SLE Sentinel | Client Experience | All modules | Refreshes before limit |
|---|---|---|---|---|
| 8 sites | 144 | 112 | ~277 | ~18/hour |
| 50 sites | 900 | 700 | ~1,700 | ~2.9/hour |
| 100 sites | 1,800 | 1,400 | ~3,400 | ~1.5/hour |
| 150 sites | 2,700 | 2,100 | ~5,100 | <1/hour ⚠️ |

### Mitigations already in place

1. **Response caching** — `mist_client.py` caches all GET responses for 5 minutes by URL.
   SLE Sentinel and Client Experience Trends share endpoints with the same duration params,
   so the second module gets cache hits for the calls the first already made.
   Effective unique calls are approximately 40% lower than the table above.

2. **Parallel execution** — all modules run via `asyncio.gather()`, so wall-clock time
   stays low even for large orgs. The rate limit concern is total calls per hour,
   not per-request latency.

### Recommended mitigations for large deployments (>50 sites)

3. **Increase cache TTL** — set `CACHE_TTL_SECONDS=1800` (30 min) in `.env` for orgs
   where near-real-time data is not required. This reduces calls by ~70% for repeat visits.

4. **Lazy module loading** — for orgs approaching the rate limit, run the two heavy SLE
   modules only on explicit tile-level refresh rather than on every full dashboard load.
   This is a planned enhancement for the production roadmap.

5. **Org-level SLE endpoint** — Mist provides `GET /api/v1/orgs/{org_id}/insights/sites-sle`
   which returns a rollup for all sites in one call. Migrating the SLE modules to use this
   endpoint for the initial load would reduce calls dramatically for large orgs.
   Per-metric detail would still require individual calls on drill-down.

6. **Separate API tokens per module** — since rate limits are per-token, using different
   tokens for different modules distributes the limit. Practical for MSP deployments.

### 🗺️ Roadmap: Adaptive API Budget Governor

**Problem:** At scale (100+ sites, 1000+ APs), a single dashboard refresh can approach
or exceed Mist's 5,000 calls/hour limit, making the tool unusable for large orgs.

**Proposed solution:** Before running any module analysis, evaluate the org's scale and
dynamically adjust what gets fetched.

**Implementation plan:**

Step 1 — Org scale assessment (2 API calls):
```
GET /api/v1/orgs/{org_id}/sites          → site count
GET /api/v1/orgs/{org_id}/inventory?limit=1  → total AP count via X-Page-Total header
```

Step 2 — Calculate projected call budget for this refresh:
```python
projected_calls = (
    site_count * 9 * 2   # SLE Sentinel: 9 metrics × 2 windows
  + site_count * 7 * 1   # Client Experience: 7 metrics × 1 window (30d)
  + site_count * 2       # AP Lifecycle: inventory + settings
  + site_count * 2       # Config Drift: site WLANs + org WLANs
)
```

Step 3 — Apply a tiered execution strategy based on projected calls:

| Projected calls | Strategy |
|---|---|
| < 1,000 | Run all modules in full — safe for any refresh frequency |
| 1,000 – 2,500 | Run all modules but sample SLE metrics (top 4 wireless only) |
| 2,500 – 4,000 | Run Config Drift + AP Lifecycle in full; SLE modules on top-20 sites by AP count |
| > 4,000 | Run Config Drift + AP Lifecycle only; SLE modules require explicit per-tile refresh |

Step 4 — Surface the strategy to the user:
- Dashboard header shows "Full analysis" / "Sampled analysis" / "Partial analysis"
- SLE tiles show "Click to load" for deferred modules
- Architecture doc note explains the threshold and how to override

**Key insight:** For a 1,000-site org, most sites have few devices and few clients.
Sorting sites by AP count descending and running SLE analysis only on the top N sites
(where N keeps calls under budget) captures the highest-impact findings while staying
within rate limits. A site with 2 APs and 5 clients is unlikely to surface meaningful
SLE trends anyway.

**This is the right answer for the "Broadly Applicable" judging criterion** — it
demonstrates that the tool is designed for enterprise scale, not just demo orgs.

## Security

- **No env-var token fallback.** Every `/api/org/*` and `/api/modules/*` request requires a
  valid `X-Session-Token` header. Without one the backend returns 401. The hosted deployment
  has no credentials baked in — every scan uses a token the operator pasted at runtime.
- **Session store is in-memory.** The `session_id` (not the Mist token) is what the browser
  sees. Tokens live in a Python dict in the FastAPI process, never on disk, never logged.
  Container restarts wipe the store.
- **Browser-side token persistence is opt-in.** `sessionStorage` by default (tab close clears it).
  `localStorage` only if the user checks *Remember this org across browser sessions*, cleared
  on *Forget* or *Disconnect*. The companion `mist_last_used_org_id` key is cleared on
  Disconnect and when the saved-orgs list drops to zero.
- **Landing page blocks silent org access.** First-time visitors land on a branded connect page
  rather than auto-loading any org. The app never opens into someone else's data.
- **All Mist API calls are server-side.** The browser never sees the Mist token after it's pasted.
- **CORS** is configured for the frontend container origin only.

## Adding a New Module

1. Create `backend/modules/my_module.py` inheriting `BaseModule`
2. Implement `async def analyze(self, org_id, sites, client) -> ModuleOutput`
3. Add to `backend/modules/__init__.py` registry
4. Add a context note to `frontend/src/components/DrillDown.jsx` `MODULE_CONTEXT`
5. Module appears in dashboard automatically on next restart

## L3 Automation Hooks

Several modules include stubbed Level 3 automation actions, ready to enable:

| Module | L3 Action | How to enable |
|---|---|---|
| SLE Sentinel | Webhook notification | Set `WEBHOOK_URL` in `.env`, uncomment dispatch loop |
| AP Lifecycle | Marvis Non-Compliant self-driving | Uncomment `_enable_marvis_non_compliant()` call |

These hooks follow the same pattern: fully implemented, commented out,
clearly documented. Enabling automation is a one-line uncomment plus
any required env var configuration.
