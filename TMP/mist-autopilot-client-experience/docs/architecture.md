# Mist Autopilot — Architecture

## Overview

Mist Autopilot is a self-driving network org health review tool built on Mist APIs.
It runs eight analysis modules in parallel and surfaces findings in a single-pane dashboard,
replacing manual network reviews with automated detection, diagnosis, and recommended remediation.

## Stack

| Layer | Technology | Reason |
|---|---|---|
| Backend | Python 3.12 + FastAPI | Async-native, auto-generates API docs at /docs |
| Frontend | React 18 + Vite + Tailwind | Modern, component-based, hot-reload during development |
| Deployment | Docker Compose | Single-command launch, no local Python/Node required |
| Auth | Mist API token (env var) | Token never reaches the browser — all calls are server-side |
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

Scores start at 100 and deduct per finding:
- Critical finding: −20 points
- Warning finding: −10 points
- Info finding: −2 points

Score ranges map to severity: 80–100 = Healthy, 60–79 = Info, 40–59 = Warning, 0–39 = Critical.

## Modules Built

| Module | Autonomy Level | Key APIs Used |
|---|---|---|
| Config Drift Detective | L1 + L2 | /orgs/{id}/wlans, /sites/{id}/wlans, /orgs/{id}/wlantemplates |
| SLE Sentinel | L1 + L2 + L3 hook | /sites/{id}/sle/site/{id}/metric/{metric}/summary |
| AP Lifecycle Monitor | L1 + L2 + L3 hook | /orgs/{id}/inventory, /sites/{id}/setting |
| Client Experience Trends | L1 + L2 | /sites/{id}/sle/site/{id}/metric/{metric}/summary |

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

## Security

- API token stored in `.env` only — never committed to Git, never sent to the browser
- All Mist API calls are server-side (FastAPI backend)
- No data persisted to disk — all results are in-memory per session
- CORS configured to allow only the frontend container origin

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
