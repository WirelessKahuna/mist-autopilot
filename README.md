# Mist Autopilot
### Self-Driving Network Org Health Review

Live: (https://tools.wirelesskahuna.com)
GitHub: (https://github.com/WirelessKahuna/mist-autopilot)

Mist Autopilot reviews an entire Juniper Mist organization in a single pass, across every selected site, and returns a scored, explained health report. Each of its twelve analysis modules queries live Mist APIs, identifies problems, classifies them by severity, and recommends specific corrective actions.

It runs in any modern browser. No installation. No agent. No access to your wired or wireless infrastructure beyond a read-only API token you control.

For the hackathon customer-impact narrative, see CUSTOMER_IMPACT.md. For our honest self-assessment against the rubric, see SELF_SCORE.md.

---

## Why Mist Autopilot

Mist organizations grow. A single org can span dozens, hundreds, or thousands of sites. Each site has its own WLANs, RF template, security posture, subscription state, AP inventory, WAN configuration, and SLE history. Keeping up with all of it manually is not realistic for most network operations teams.

Mist Autopilot is a second opinion. Point it at an org, pick the sites you care about, click Scan. In under a minute it produces a cross-site audit covering roaming health, SLE anomalies, configuration drift, RF hygiene, security posture, client experience trends, AP lifecycle compliance, WAN and uplink health, subscription status, Marvis Minis readiness, Access Assurance configuration, and open Marvis actions.

Every finding is explained. Every finding includes a recommended remediation. Nothing is written back to your org.

### What makes it different

- **Any org, any size.** No hard-coded org IDs. Bring a token, pick sites, scan.
- **Any browser.** The live deployment at `tools.wirelesskahuna.com` works from anywhere you can open a web page (Chrome, Safari, Edge, Firefox, on Windows, Mac, Linux, iOS, or Android).
- **Any Mist cloud.** Autopilot auto-detects which of Mist's twelve geographic clouds (Global 01-05, EMEA 01-04, APAC 01-03) the token authenticates against and routes all API calls and deep-links accordingly. No configuration required.
- **Read-only by design.** An Observer token is all the app needs to do its job. The UI visualizes the token's access role on the org pill (mist-blue for Observer, red for Admin/Write), so operators see at a glance what the token can do.
- **Fix in Mist deep-links.** Every critical finding includes a one-click link that routes the operator directly to the exact Mist portal page that resolves it: not the org landing page, not a search, the specific Subscriptions, NAC Policies, WLAN Templates, or AP Detail view.
- **Shareable PDF report.** A client-side PDF export bundles the full run into a professional report (executive summary, module results table, finding detail, and per-site breakdown), ready to hand to a director, customer, or auditor.
- **Zero data persistence.** Tokens are held in memory for the session. No database. No disk writes. No telemetry.
- **Self-driving framing.** Every module is categorized against a three-level autonomy scale (L1 detect → L2 classify → L3 act) so operators can see exactly how much of the loop is being closed today and what's coming next.

---

## See it running

The live production deployment is at **[tools.wirelesskahuna.com](https://tools.wirelesskahuna.com)**.

To use it, you need exactly two things:

1. **A web browser.** Any modern browser on any OS.
2. **A Mist Org API Token.** Generate one at `manage.mist.com` under Organization → Settings → API Token. Observer role is sufficient.

Open the site, paste your token, pick the sites you want scanned, click Scan. **That's the entire flow.**

> **What the live site does not require.** Everything in the *Self-Hosting* section of this README (Docker, Python, Node, the HPE OneDrive project path, local environment files) is only needed if you want to build, modify, or run your own instance. None of it is required to use Mist Autopilot against your own org through the live site.

---

## The twelve modules

Every module runs against the sites you selected, in parallel, on every refresh. Each returns a score (0-100), a severity classification, a one-line summary, and a list of findings. Findings include a title, detail explanation, affected entities, and a recommended action.

Modules are grouped below by domain.

### Security & Access

**🔐 SecureScope: Wireless security audit.** Inspects every WLAN against wireless security best practices. Classifies open SSIDs by risk (no VLAN, shared VLAN with a protected SSID, click-through captive portal, authenticated captive portal). Flags PMF-disabled WPA2/WPA3 SSIDs, PSK reuse across differently-named SSIDs, 802.1X SSIDs with no RADIUS servers configured (suppressing Mist Access Assurance, RADSEC, and Passpoint variants), missing rogue AP detection, and SSIDs left in WPA3 or OWE transition mode.

**🔑 AuthGuard: Access Assurance & NAC health.** Audits Mist NAC rule configuration, SCEP/PKI status, CA certificate presence and expiry, and the set of 802.1X-backed WLANs consuming those policies. Parses each uploaded CA certificate to flag expired, expiring-in-30-days, and expiring-in-90-days conditions. Detects unresolved tag references in NAC rules, missing certificate-based authentication rules, and disabled or unnamed rules.

### Wireless Health

**📡 RoamGuard: Roaming health.** Uses SLE roaming classifiers combined with fast roam event counts to identify genuine sticky-client problems as opposed to coverage gaps masquerading as roaming issues. Flags 802.1X SSIDs without 802.11r (Fast BSS Transition) enabled and recommends High Density data rates on sites with sub-80 roaming SLE.

**📊 SLE Sentinel: Multi-domain SLE monitoring.** Monitors wireless, wired, and WAN SLE metrics across every site against both absolute thresholds and per-site 7-day baselines. Classifies each anomaly by its top contributing classifiers (the L2 failure domain) and emits a specific recommendation tied to the metric and its dominant classifier. Includes a webhook notification stub, ready to enable for L3 outbound signaling.

**📶 RF Fingerprint Analyzer: RF configuration audit.** Detects sites with no RF template assigned, band-utilization imbalance (more than 30% of clients on 2.4 GHz when 5 or 6 GHz is present), DFS instability (three or more radar events in seven days), RF templates that exclude all DFS channels, channel-width mismatches across APs on the same band at the same site, and TX power outliers (APs deviating 6 dB or more from site average).

**📈 Client Experience Trends: 30-day SLE trend analysis.** Compares each site's last-7-day SLE performance against a prior 23-day baseline across seven wireless metrics. Classifies each site as improving, stable, or degrading based on a per-metric 10% relative-change threshold. Automatically filters out weekend samples for weekday-dominant sites (less than 20% weekend user-minutes) so office sites aren't judged on idle weekends.

### Config Governance

**🔍 Config Drift Detective: SSID drift and VLAN collision audit.** Uses the `/wlans/derived` endpoint to resolve fully-scoped WLAN configuration per site, then diffs same-named SSIDs across sites. Classifies differences as critical (security-type mismatches) or warning (VLAN or rate-set mismatches) and proposes Mist WLAN Variables for fields expected to differ. Flags site-local WLANs that could be migrated into templates. Per-site VLAN collision detection identifies multiple SSIDs sharing a VLAN, with security-aware severity (open + authenticated on the same VLAN is a critical finding).

**🔄 AP Lifecycle Monitor: Firmware & fleet health.** Mirrors Mist's Version Compliance logic at per-site, per-model granularity. Detects sites with Auto Update disabled, same-model APs running mixed firmware (an interrupted upgrade signature; cross-model differences are expected and not flagged), disconnected APs, and End-of-Sale hardware. An L3 action stub is in place to enable the Marvis Self-Driving Action for non-compliant APs on a per-site basis when operators are ready to close that loop automatically.

### WAN & Gateway

**🌐 WAN & Uplink Sentinel: Gateway, tunnel, and WAN SLE monitoring.** Inspects gateway device stats, org-level WAN tunnel status, gateway device events, and WAN SLE metrics (gateway-health, wan-availability, application-health). Distinguishes between tunnel-down-with-failover-active (warning) and tunnel-down-with-no-failover-path (critical). Detects tunnel flapping, recurring failover events, and degraded WAN SLEs. Gracefully returns a clean summary on wireless-only orgs with no WAN Assurance subscription.

### Licensing & Readiness

**📋 SUBMonitor: Subscription & license audit.** Audits Mist license entitlements against deployed AP inventory. Flags expired subscriptions, subscriptions expiring within 30 days (critical) and 31-90 days (warning), SUB-MAN coverage gaps where deployed APs exceed entitlements, and APs running on eval subscriptions that cannot be renewed.

**🤖 MinisMonitor: Marvis Minis readiness.** Audits the prerequisites for Marvis Minis synthetic testing. Checks SUB-VNA entitlement (required), org-level Minis enablement, custom application probe configuration, WAN speedtest setting, per-site overrides, and AP firmware minimum version (0.14.29313). Flags sites or APs that would be excluded from Minis execution.

### AI-Driven Ops

**🔬 MarvisIQ: Marvis Actions analyzer.** Fetches active Marvis suggestions from the Mist platform's AI actions engine. Groups open actions by category (AP, switch, gateway, wireless, wired), identifies recurrent issues with elevated batch counts, detects self-drivable actions that have not been enabled for auto-remediation, and flags sites generating disproportionate action volume (over 60% concentration at a single site signals systemic infrastructure problems).

---

## Autonomy framework

Mist Autopilot uses a three-level autonomy scale to describe how much of the operations loop each module closes today:

| Level | Description | Example |
|-------|-------------|---------|
| **L1: Detect** | The module queries live Mist APIs and identifies a problem. | "Site X has 3 radar events in the last 7 days." |
| **L2: Classify** | The module reasons about the detected problem to narrow the failure domain. | "The degraded SLE is driven by the *weak-signal* classifier at 47% impact; this is an RF coverage problem, not an authentication problem." |
| **L3: Act** | The module takes or prepares action to remediate the problem. | "Enable the Marvis Self-Driving Action for non-compliant APs at this site." |

Every module in the current build operates at L1 across its entire check surface. Several modules extend to L2 by classifying failure domain, root cause, or site-level context. Two modules (SLE Sentinel and AP Lifecycle Monitor) include ready-to-activate L3 action stubs (webhook notification and Marvis auto-remediation respectively) that can be enabled when operators are prepared to close the loop automatically.

### Fix in Mist: human-in-the-loop remediation routing

Between L2 and L3 sits a practical operator need that pure detection and pure automation both miss: *I've seen the finding, now take me to the page that fixes it.* Every critical finding surfaced by any module includes a **Fix in Mist ↗** button on the drill-down card that opens the specific Mist portal page that resolves it, in the correct cloud's portal, for the correct org, scoped to the specific site where applicable. Examples: SUBMonitor critical findings open `#!subscription`; AuthGuard critical findings open `#!nacPolicy`; AP Lifecycle disconnected-AP criticals open the specific AP's detail page; RF Fingerprint DFS-instability criticals open the assigned RF template. This compresses the detect → diagnose → remediate loop from minutes of clicking into a single click, while keeping the operator in control of the change.

---

## How to use it

### Path A: In your browser (no installation)

1. Open **[tools.wirelesskahuna.com](https://tools.wirelesskahuna.com)**. First-time visitors land on the Autopilot welcome page with a single *Connect an Org* call to action, product pitch, and a screenshot of the full dashboard. The app does not auto-open into any org.
2. Click *Connect an Org*.
3. Paste a Mist Org API Token. (Generate one at `manage.mist.com → Organization → Settings → API Token`.) On submission, Autopilot probes each of Mist's twelve geographic clouds in turn until one authenticates the token, then routes all subsequent API calls and portal deep-links to the matching cloud. The detected cloud is surfaced in the connect response.
4. Optionally check *Remember this org across browser sessions* to save the token to the browser's local storage for one-click re-connect later. Saved orgs can be removed at any time via the *Forget* control.
5. Pick the sites you want scanned. The site picker lists every active site (sites with one or more assigned APs) and shows the AP count next to each. Sites with no assigned APs are rolled up into an inactive-sites summary and are not scanned. By default all active sites are selected; review the list and deselect any sites you want to exclude before clicking *Scan*.
6. The dashboard runs all twelve modules in parallel and renders results as tiles, each with a score, severity, and summary. Click any tile to drill into findings. Critical findings include a *Fix in Mist ↗* button that opens the exact Mist portal page that resolves the finding. Download a PDF report from the dashboard footer.

### Multi-org management

Field engineers and MSPs working across many customer orgs can store multiple tokens locally via the *Remember this org* option. On return visits:

- **One saved org:** Autopilot auto-connects silently on page load.
- **Multiple saved orgs:** a Welcome screen lists every saved org as a one-click connect button; the most recently used org auto-connects by default.
- **New org:** the Welcome screen includes a *Connect a new org* action that opens the credentials modal.

Saved orgs are scoped to the browser's origin and removable at any time via the *Forget* control. No org list is ever synced to the server.

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

This is also why the site picker shows AP counts per site and defaults to showing only sites with assigned APs. Before scanning a very large org, review the selected sites and deselect any you don't need. An unchecked scan across a many-hundred-site org can consume a substantial fraction of the hourly quota in a single pass.

### Path B: Self-hosting

Self-hosting is for contributors, reviewers, and operators who want to run their own instance. **It is not required to use Mist Autopilot against your own org**; `tools.wirelesskahuna.com` is the production deployment.

**Prerequisites**

- Docker Desktop (Docker Engine + Compose)
- A Mist Org API Token (pasted through the UI at runtime; Observer role is sufficient)

**Configure**

```bash
cp .env.example .env
```

Edit `.env`:

```
MIST_API_BASE_URL=https://api.mist.com  # default base for pydantic settings; sessions auto-detect their cloud
CACHE_TTL_SECONDS=300
LOG_LEVEL=INFO
```

> **Note on env vars.** Earlier versions of Autopilot supported `MIST_API_TOKEN` and `MIST_ORG_ID` as fallback credentials when no UI session was active. That fallback has been removed: the hosted deployment and self-hosted instances both require the operator to connect a token through the UI. This guarantees the app never opens into a baked-in org.

Supported Mist clouds (all auto-detected at runtime from session tokens): Global 01 (`api.mist.com`), Global 02 (`api.gc1.mist.com`), Global 03 (`api.ac2.mist.com`), Global 04 (`api.gc2.mist.com`), Global 05 (`api.gc4.mist.com`), EMEA 01 (`api.eu.mist.com`), EMEA 02 (`api.gc3.mist.com`), EMEA 03 (`api.ac6.mist.com`), EMEA 04 (`api.gc6.mist.com`), APAC 01 (`api.ac5.mist.com`), APAC 02 (`api.gc5.mist.com`), APAC 03 (`api.gc7.mist.com`).

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

Python 3.12 + FastAPI on the backend, React + Vite + Tailwind on the frontend. Single-image Docker deploy with Nginx fronting a local uvicorn process; the same container serves the built frontend and proxies `/api/*` to the backend.

```
mist-autopilot/
├── backend/                      Python 3.12 + FastAPI
│   ├── main.py                   API entrypoint + CORS + router registration
│   ├── mist_client.py            Async Mist API client (retry, cache, throttle, call counter)
│   ├── mist_clouds.py            Registry of the 12 Mist cloud API/portal endpoints + auto-detect helper
│   ├── config.py                 Pydantic settings from env vars
│   ├── session_store.py          In-memory per-session credential store (8-hour TTL, role + cloud aware)
│   ├── models/                   Pydantic response schemas (ModuleOutput, Finding, OrgSummary...)
│   ├── modules/                  Twelve analysis modules + BaseModule + _mist_urls deep-link helpers
│   └── routers/                  FastAPI routers (org, modules, credentials)
└── frontend/                     React + Vite + Tailwind
    └── src/
        ├── api/                  Axios client + session token helpers
        ├── components/           Dashboard tiles, credential modal, site picker, drill-downs, PDF report generator
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
| `GET` | `/api/org/summary` | Runs all modules in parallel and returns org score, site count, per-module output, and a `site_id → site_name` map. Requires `X-Session-Token`; returns 401 otherwise. |
| `GET` | `/api/org/sites` | Returns the raw site list for the active session. Requires `X-Session-Token`. |
| `GET` | `/api/org/stats` | Returns `{ last_refresh, hourly }` API call counters for the active org. Requires `X-Session-Token`. |

### Module operations

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/modules/` | Returns the module registry: `module_id`, `display_name`, `icon` for each. |
| `GET` | `/api/modules/{module_id}` | Runs a single module and returns its output. Used for tile-level refresh. Requires `X-Session-Token`. |

### Credentials & sessions

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/credentials/connect` | Validates a submitted Mist token, discovers the org via `/api/v1/self`, fetches sites + inventory in parallel, counts APs per site, creates a session, and returns `session_id`, org info, active sites (with AP counts), and inactive-site count. |
| `POST` | `/api/credentials/sites` | Updates the selected site IDs for the current session. Requires `X-Session-Token` header. |
| `DELETE` | `/api/credentials/session` | Clears the current session on the server. Frontend also clears browser session state, forgets the last-used-org marker, and returns to the landing page (or welcome picker if other saved orgs remain). |

### Health

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/health` | Liveness probe; returns `{ "status": "ok", "version": "1.0.0" }`. |

Session credentials are passed via the `X-Session-Token` request header when present.

---

## Security posture

**Session-only backend, no env-var fallback.** Every `/api/org/*` and `/api/modules/*` request requires a valid `X-Session-Token` header. Without one the backend returns 401. The hosted deployment has no Mist credentials in its environment at all — every scan uses a token the operator pasted at runtime.

**Token scope.** Observer role is sufficient for every current module; the app issues no writes today. Any Mist role is accepted (admin, write, helpdesk, installer, read, observer); the `/api/credentials/connect` response includes a `can_write` flag computed from the token's org role (true for `admin`/`write`, false for all other roles) and the frontend renders the org pill with a red "Admin mode" label when `can_write` is true and a mist-blue "Observer mode" label otherwise, so operators can see at a glance what the token they pasted is capable of. Write-capable actions are planned for future L3 modules and will be gated on `can_write`.

**Token storage, server side.** Session tokens live in a Python `SessionStore` dict in the FastAPI process. No disk writes, no database, no log output of token material. Sessions expire after 8 hours of inactivity. Container restarts (Railway deploys, crashes, idle cycling) wipe the entire store.

**Token storage, browser side, default.** The `session_id` (not the Mist token) is held in the browser's `sessionStorage`, cleared automatically when the tab closes.

**Token storage, browser side, opt-in.** If the user checks *Remember this org across browser sessions* on the connect dialog, the Mist token is additionally written to the browser's `localStorage` under the key `mist_saved_orgs`. This persists across browser restarts until the user clicks *Forget* on that saved org or clears browser storage. A companion `mist_last_used_org_id` key is used to auto-connect the most recently used org on page load when multiple saved orgs exist; this key is cleared on *Disconnect*, when *Forget* removes the matching org, and when the saved-orgs list drops to zero. The backend never writes the token anywhere; persistence is entirely a browser-local opt-in.

**Transport.** Every Mist API call is issued server-side from the FastAPI backend. The token never reaches third-party services. The browser only ever sees the opaque `session_id`.

**Data at rest.** None. The app holds responses in memory only. There is no database, no persistent cache, no file-based state.

**Caching.** API responses are cached in-process in an `TTLCache` with a 5-minute default TTL, keyed by URL + params. This cache is per-process and evaporates on restart.

**Rate limit awareness.** The built-in API call counter exposes both per-refresh and hourly counts. Modules use in-parallel fetch patterns with a 0.25-second inter-request throttle, honor `Retry-After` on 429 responses, and cache responses aggressively to stay well under the Mist hourly budget on typical scans.

---

## Scoring

Every module returns a 0-100 score derived from its list of findings using a square-root diminishing-returns curve:

```
score = 100 − 20·√C − 10·√W − 2·√I
```

where C, W, I are counts of critical, warning, and info findings. Clamped to [0, 100]. The curve keeps operator intuition intact (one critical hurts meaningfully more than one warning) while preventing a module with many findings of the same severity from flooring at zero and becoming indistinguishable from a less-bad case.

Score ranges map to severity: **80-100 Healthy, 60-79 Info, 40-59 Warning, 0-39 Critical**.

**Org Health** (the score at the top of the dashboard) is the unweighted arithmetic mean of every module's score, rounded to the nearest integer. Modules that error out (score = None) are excluded from the average so one broken check doesn't drag down an otherwise healthy org.

See `docs/architecture.md` for the reference table of score values at different finding counts.

---

## Project status

Hackathon deliverable: HPE / Juniper Mist Field PLM AI Ops Hackathon.
Deadline: April 20, 2026.

Team Signal & Noise:
- **Mike Wade**, Field PLM, AI-Ops Specialist, HPE. [@WirelessKahuna](https://www.linkedin.com/in/wirelesskahuna/)
  [WirelessKahuna](https://github.com/WirelessKahuna)

Live deployment: https://tools.wirelesskahuna.com (Railway-hosted, custom domain via GoDaddy CNAME). Repository: https://github.com/WirelessKahuna/mist-autopilot

---

## Document status

This README is maintained in parallel with the code. The canonical source of truth for the module list is `backend/modules/__init__.py`. The canonical source of truth for API routes is the FastAPI routers under `backend/routers/`. If this document ever disagrees with either, the code wins.

Last synced with code: April 18, 2026.
