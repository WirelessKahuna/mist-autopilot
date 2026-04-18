# Mist Autopilot
### Self-Driving Network Org Health Review

**Live:** [tools.wirelesskahuna.com](https://tools.wirelesskahuna.com)

Mist Autopilot reviews an entire Juniper Mist organization in a single pass — across every selected site — and returns a scored, explained health report. Each of its twelve analysis modules queries live Mist APIs, identifies problems, classifies them by severity, and recommends specific corrective actions.

It runs in any modern browser. No installation. No agent. No access to your wired or wireless infrastructure beyond a read-only API token you control.

**Project size:** ~6,963 lines of application code across 44 files (Python + React/JSX).

---

## Why Mist Autopilot

Mist organizations grow. A single org can span dozens, hundreds, or thousands of sites. Each site has its own WLANs, RF template, security posture, subscription state, AP inventory, WAN configuration, and SLE history. Keeping up with all of it manually is not realistic for most network operations teams.

Mist Autopilot is a second opinion. Point it at an org, pick the sites you care about, click Scan. In under a minute it produces a cross-site audit covering roaming health, SLE anomalies, configuration drift, RF hygiene, security posture, client experience trends, AP lifecycle compliance, WAN and uplink health, subscription status, Marvis Minis readiness, Access Assurance configuration, and open Marvis actions.

Every finding is explained. Every finding includes a recommended remediation. Nothing is written back to your org.

### What makes it different

- **Any org, any size.** No hard-coded org IDs. Bring a token, pick sites, scan.
- **Any browser.** The live deployment at `tools.wirelesskahuna.com` works from anywhere you can open a web page.
- **Read-only by design.** An Observer token is all the app needs to do its job. You can use a higher-privilege token if you choose — the app will not issue writes today.
- **Zero data persistence.** Tokens are held in memory for the session. No database. No disk writes. No telemetry.
- **Self-driving framing.** Every module is categorized against a three-level autonomy scale (L1 detect → L2 classify → L3 act) so operators can see exactly how much of the loop is being closed today and what's coming next.

---

## See it running

The live production deployment is at **[tools.wirelesskahuna.com](https://tools.wirelesskahuna.com)**.

To use it, you need exactly two things:

1. **A web browser.** Any modern browser on any OS.
2. **A Mist Org API Token.** Generate one at `manage.mist.com` under *Organization → Settings → API Token*. Observer role is sufficient.

Open the site, paste your token, pick the sites you want scanned, click Scan. That's the entire flow.

> **What the live site does not require.** Everything in the *Self-Hosting* section of this README — Docker, Python, Node, the HPE OneDrive project path, local environment files — is only needed if you want to build, modify, or run your own instance. None of it is required to use Mist Autopilot against your own org through the live site.

---

## The twelve modules

Every module runs against the sites you selected, in parallel, on every refresh. Each returns a score (0–100), a severity classification, a one-line summary, and a list of findings. Findings include a title, detail explanation, affected entities, and a recommended action.

Modules are grouped below by domain.

### Security & Access

**🔐 SecureScope — Wireless security audit.** Inspects every WLAN against wireless security best practices. Classifies open SSIDs by risk (no VLAN, shared VLAN with a protected SSID, click-through captive portal, authenticated captive portal). Flags PMF-disabled WPA2/WPA3 SSIDs, PSK reuse across differently-named SSIDs, 802.1X SSIDs with no RADIUS servers configured (suppressing Mist Access Assurance, RADSEC, and Passpoint variants), missing rogue AP detection, and SSIDs left in WPA3 or OWE transition mode.

**🔑 AuthGuard — Access Assurance & NAC health.** Audits Mist NAC rule configuration, SCEP/PKI status, CA certificate presence and expiry, and the set of 802.1X-backed WLANs consuming those policies. Parses each uploaded CA certificate to flag expired, expiring-in-30-days, and expiring-in-90-days conditions. Detects unresolved tag references in NAC rules, missing certificate-based authentication rules, and disabled or unnamed rules.

### Wireless Health

**📡 RoamGuard — Roaming health.** Uses SLE roaming classifiers combined with fast roam event counts to identify genuine sticky-client problems as opposed to coverage gaps masquerading as roaming issues. Flags 802.1X SSIDs without 802.11r (Fast BSS Transition) enabled and recommends High Density data rates on sites with sub-80 roaming SLE.

**📊 SLE Sentinel — Multi-domain SLE monitoring.** Monitors wireless, wired, and WAN SLE metrics across every site against both absolute thresholds and per-site 7-day baselines. Classifies each anomaly by its top contributing classifiers (the L2 failure domain) and emits a specific recommendation tied to the metric and its dominant classifier. Includes a webhook notification stub, ready to enable for L3 outbound signaling.

**📶 RF Fingerprint Analyzer — RF configuration audit.** Detects sites with no RF template assigned, band-utilization imbalance (more than 30% of clients on 2.4 GHz when 5 or 6 GHz is present), DFS instability (three or more radar events in seven days), RF templates that exclude all DFS channels, channel-width mismatches across APs on the same band at the same site, and TX power outliers (APs deviating 6 dB or more from site average).

**📈 Client Experience Trends — 30-day SLE trend analysis.** Compares each site's last-7-day SLE performance against a prior 23-day baseline across seven wireless metrics. Classifies each site as improving, stable, or degrading based on a per-metric 10% relative-change threshold. Automatically filters out weekend samples for weekday-dominant sites (less than 20% weekend user-minutes) so office sites aren't judged on idle weekends.

### Config Governance

**🔍 Config Drift Detective — SSID drift and VLAN collision audit.** Uses the `/wlans/derived` endpoint to resolve fully-scoped WLAN configuration per site, then diffs same-named SSIDs across sites. Classifies differences as critical (security-type mismatches) or warning (VLAN or rate-set mismatches) and proposes Mist WLAN Variables for fields expected to differ. Flags site-local WLANs that could be migrated into templates. Per-site VLAN collision detection identifies multiple SSIDs sharing a VLAN, with security-aware severity (open + authenticated on the same VLAN is a critical finding).

**🔄 AP Lifecycle Monitor — Firmware & fleet health.** Mirrors Mist's Version Compliance logic at per-site, per-model granularity. Detects sites with Auto Update disabled, same-model APs running mixed firmware (an interrupted upgrade signature — cross-model differences are expected and not flagged), disconnected APs, and End-of-Sale hardware. An L3 action stub is in place to enable the Marvis Self-Driving Action for non-compliant APs on a per-site basis when operators are ready to close that loop automatically.

### WAN & Gateway

**🌐 WAN & Uplink Sentinel — Gateway, tunnel, and WAN SLE monitoring.** Inspects gateway device stats, org-level WAN tunnel status, gateway device events, and WAN SLE metrics (gateway-health, wan-availability, application-health). Distinguishes between tunnel-down-with-failover-active (warning) and tunnel-down-with-no-failover-path (critical). Detects tunnel flapping, recurring failover events, and degraded WAN SLEs. Gracefully returns a clean summary on wireless-only orgs with no WAN Assurance subscription.

### Licensing & Readiness

**📋 SUBMonitor — Subscription & license audit.** Audits Mist license entitlements against deployed AP inventory. Flags expired subscriptions, subscriptions expiring within 30 days (critical) and 91–90 days (warning), SUB-MAN coverage gaps where deployed APs exceed entitlements, and APs running on eval subscriptions that cannot be renewed.

**🤖 MinisMonitor — Marvis Minis readiness.** Audits the prerequisites for Marvis Minis synthetic testing. Checks SUB-VNA entitlement (required), org-level Minis enablement, custom application probe configuration, WAN speedtest setting, per-site overrides, and AP firmware minimum version (0.14.29313). Flags sites or APs that would be excluded from Minis execution.

### AI-Driven Ops

**🔬 MarvisIQ — Marvis Actions analyzer.** Fetches active Marvis suggestions from the Mist platform's AI actions engine. Groups open actions by category (AP, switch, gateway, wireless, wired), identifies recurrent issues with elevated batch counts, detects self-drivable actions that have not been enabled for auto-remediation, and flags sites generating disproportionate action volume (over 60% concentration at a single site signals systemic infrastructure problems).

---

## Autonomy framework

Mist Autopilot uses a three-level autonomy scale to describe how much of the operations loop each module closes today:

| Level | Description | Example |
|-------|-------------|---------|
| **L1 — Detect** | The module queries live Mist APIs and identifies a problem. | "Site X has 3 radar events in the last 7 days." |
| **L2 — Classify** | The module reasons about the detected problem to narrow the failure domain. | "The degraded SLE is driven by the *weak-signal* classifier at 47% impact — this is an RF coverage problem, not an authentication problem." |
| **L3 — Act** | The module takes or prepares action to remediate the problem. | "Enable the Marvis Self-Driving Action for non-compliant APs at this site." |

Every module in the current build operates at L1 across its entire check surface. Several modules extend to L2 by classifying failure domain, root cause, or site-level context. Two modules (SLE Sentinel and AP Lifecycle Monitor) include ready-to-activate L3 action stubs — webhook notification and Marvis auto-remediation respectively — that can be enabled when operators are prepared to close the loop automatically.

---

## How to use it

### Path A — In your browser (no installation)

1. Open **[tools.wirelesskahuna.com](https://tools.wirelesskahuna.com)**.
2. Click *Connect an Org*.
3. Paste a Mist Org API Token. (Generate one at `manage.mist.com → Organization → Settings → API Token`.)
4. Optionally check *Remember this org across browser sessions* to save the token to the browser's local storage for one-click re-connect later. Saved orgs can be removed at any time via the *Forget* control.
5. Pick the sites you want scanned. The site picker lists every active site (sites with one or more assigned APs) and shows the AP count next to each. Sites with no assigned APs are rolled up into an inactive-sites summary and are not scanned. By default all active sites are selected — review the list and deselect any sites you want to exclude before clicking *Scan*.
6. The dashboard runs all twelve modules in parallel and renders results as tiles, each with a score, severity, and summary. Click any tile to drill into findings. Download a PDF report from the dashboard footer.

### Token handling

| Scenario | What happens |
|----------|--------------|
| *Remember* not checked | Token held in server memory for the duration of the session. Tab close ends the session in the browser; server session expires after 8 hours of inactivity or when the container restarts. |
| *Remember* checked | Token additionally written to the browser's `localStorage` under the key `mist_saved_orgs`, scoped to the `tools.wirelesskahuna.com` origin. Persists across browser sessions until the user explicitly removes it via *Forget*, or clears browser storage. |

The token is never written to disk on the server, never logged, and never transmitted anywhere other than `api.mist.com`.

### API call budget awareness

Mist enforces an hourly API request quota per token. Mist Autopilot shows two running counters in the UI so operators can pace their scans:

- **Current (per refresh).** API calls issued during the most recent scan. Resets at the start of every scan.
- **Hourly.** Total API calls issued against the active org within the current UTC hour. Resets automatically at the top of the hour, in line with Mist's own hourly rate-limit window.

This is also why the site picker shows AP counts per site and defaults to showing only sites with assigned APs. Before scanning a very large org, review the selected sites and deselect any you don't need — an unchecked scan across a many-hundred-site org can consume a substantial fraction of the hourly quota in a single pass.

### Path B — Self-hosting

Self-hosting is for contributors, reviewers, and operators who want to run their own instance. **It is not required to use Mist Autopilot against your own org** — `tools.wirelesskahuna.com` is the production deployment.

**Prerequisites**

- Docker Desktop (Docker Engine + Compose)
- A Mist Org API Token (for `.env`-based default credentials, optional — the UI accepts tokens at runtime)

**Configure**

```bash
cp .env.example .env
```

Edit `.env`:

```
MIST_API_TOKEN=your_token_here        # optional — used as default if UI session absent
MIST_API_BASE_URL=https://api.mist.com # https://api.eu.mist.com, https://api.gc1.mist.com for other clouds
MIST_ORG_ID=your_org_id_here          # optional — used as default if UI session absent
CACHE_TTL_SECONDS=300
LOG_LEVEL=INFO
```

**Run**

```bash
docker compose up
```

Open `http://localhost:3000`.

### Local development (without Docker)

Backend:

```bash
cd backend
pip install -r requirements.txt
cp ../.env.example ../.env   # fill in values
uvicorn main:app --reload
```

Frontend:

```bash
cd frontend
npm install
npm run dev
```

---

## Architecture

Mist Autopilot is approximately **6,963 lines of application code across 44 files** — Python 3.11 + FastAPI on the backend, React + Vite + Tailwind on the frontend.

```
mist-autopilot/
├── backend/                      Python 3.11 + FastAPI
│   ├── main.py                   API entrypoint + CORS + router registration
│   ├── mist_client.py            Async Mist API client (retry, cache, throttle, call counter)
│   ├── config.py                 Pydantic settings from env vars
│   ├── session_store.py          In-memory per-session credential store (8-hour TTL)
│   ├── models/                   Pydantic response schemas (ModuleOutput, Finding, OrgSummary...)
│   ├── modules/                  Twelve analysis modules + BaseModule
│   └── routers/                  FastAPI routers — org, modules, credentials
└── frontend/                     React + Vite + Tailwind
    └── src/
        ├── api/                  Axios client + session token helpers
        ├── components/           Dashboard tiles, credential modal, site picker, drill-downs, report
        ├── pages/                Dashboard page
        └── utils/                Saved-orgs helper, severity helper
```

### Module pattern

Every module inherits from `BaseModule` and implements one method:

```python
async def analyze(self, org_id, sites, client) -> ModuleOutput:
    ...
```

Each module fetches the Mist endpoints it needs (typically in parallel via `asyncio.gather`), analyzes the responses, builds a list of `Finding` objects, computes a score, and returns a `ModuleOutput`. On every dashboard refresh all twelve modules run concurrently.

Adding a new module is two steps:

1. Create `backend/modules/my_module.py` with a class inheriting `BaseModule`.
2. Add its import and an instance to the `ALL_MODULES` list in `backend/modules/__init__.py`.

The new module appears in the dashboard automatically.

---

## API reference

Interactive OpenAPI documentation is available at `/docs` on the running backend (e.g. `http://localhost:8000/docs` when self-hosted).

### Org operations

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/org/summary` | Runs all modules in parallel and returns org score, site count, per-module output, and a `site_id → site_name` map. Uses the session token's credentials when present; otherwise falls back to env-var defaults. |
| `GET` | `/api/org/sites` | Returns the raw site list for the active credentials. |
| `GET` | `/api/org/stats` | Returns `{ last_refresh, hourly }` API call counters for the active org. |

### Module operations

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/modules/` | Returns the module registry — `module_id`, `display_name`, `icon` for each. |
| `GET` | `/api/modules/{module_id}` | Runs a single module and returns its output. Used for tile-level refresh. |

### Credentials & sessions

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/credentials/connect` | Validates a submitted Mist token, discovers the org via `/api/v1/self`, fetches sites + inventory in parallel, counts APs per site, creates a session, and returns `session_id`, org info, active sites (with AP counts), and inactive-site count. |
| `POST` | `/api/credentials/sites` | Updates the selected site IDs for the current session. Requires `X-Session-Token` header. |
| `DELETE` | `/api/credentials/session` | Clears the current session, reverting to env-var defaults. |

### Health

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/health` | Liveness probe — returns `{ "status": "ok", "version": "1.0.0" }`. |

Session credentials are passed via the `X-Session-Token` request header when present.

---

## Security posture

**Token scope.** Observer role is sufficient for every current module — the app issues no writes today. Higher-privilege tokens (Admin, Helpdesk, etc.) are accepted. Write-capable actions are planned for future L3 modules.

**Token storage — server side.** Session tokens live in a Python `SessionStore` dict in the FastAPI process. No disk writes, no database, no log output of token material. Sessions expire after 8 hours of inactivity. Container restarts (Railway deploys, crashes, idle cycling) wipe the entire store.

**Token storage — browser side, default.** The `session_id` (not the Mist token) is held in the browser's `sessionStorage`, cleared automatically when the tab closes.

**Token storage — browser side, opt-in.** If the user checks *Remember this org across browser sessions* on the connect dialog, the Mist token is additionally written to the browser's `localStorage` under the key `mist_saved_orgs`. This persists across browser restarts until the user clicks *Forget* on that saved org or clears browser storage. The backend never writes the token anywhere — persistence is entirely a browser-local opt-in.

**Transport.** Every Mist API call is issued server-side from the FastAPI backend. The token never reaches third-party services. The browser only ever sees the opaque `session_id`.

**Data at rest.** None. The app holds responses in memory only. There is no database, no persistent cache, no file-based state.

**Caching.** API responses are cached in-process in an `TTLCache` with a 5-minute default TTL, keyed by URL + params. This cache is per-process and evaporates on restart.

**Rate limit awareness.** The built-in API call counter exposes both per-refresh and hourly counts. Modules use in-parallel fetch patterns with a 0.25-second inter-request throttle, honor `Retry-After` on 429 responses, and cache responses aggressively to stay well under the Mist hourly budget on typical scans.

---

## Project status

**Hackathon deliverable — HPE / Juniper Mist Field PLM AI Ops Hackathon.**
**Deadline:** April 20, 2026.

**Team:**
- **Mike Wade** — Field PLM, AI-Ops Specialist, HPE. CWNE #421. [@WirelessKahuna](https://twitter.com/WirelessKahuna)
- **Garth Humphrey** — [slugboy1122](https://github.com/slugboy1122)

**Live deployment:** [tools.wirelesskahuna.com](https://tools.wirelesskahuna.com) (Railway-hosted, custom domain via GoDaddy CNAME).

---

## Document status

This README is maintained in parallel with the code. The canonical source of truth for the module list is `backend/modules/__init__.py`. The canonical source of truth for API routes is the FastAPI routers under `backend/routers/`. If this document ever disagrees with either, the code wins.

**Last synced with code:** April 16, 2026.
