# Why Customers Would Deploy Mist Autopilot Immediately

Mist Autopilot is a curated, opinionated lens on an org's existing Mist data. Every data point it surfaces already lives in Mist — in SLE dashboards, the inventory view, subscription pages, Marvis Actions, RF templates, WLAN templates, NAC policies, site settings. The value isn't new data. The value is selecting the ~60 things that actually matter for an operational health review, composing them into a single scored rollup, and routing the operator directly to the Mist page that resolves each critical finding.

It takes the quarterly network review that doesn't happen — because nobody has two free hours to click through thirty dashboard pages per site — and makes it a one-minute scan.

---

### Deploy in sixty seconds

Go to **tools.wirelesskahuna.com** in any modern browser. Paste a Mist Org API Token. Pick the sites to scan. Click Scan. That is the entire deployment.

No install. No agent. No CLI. No Python, no Node, no Docker. No download. No VPN, no firewall change, no approval chain. Any modern browser on any operating system — Chrome, Safari, Edge, Firefox, on Windows, Mac, Linux, iOS, Android — is the only client the operator needs. A field engineer running a pre-sales health check, a customer NetOps lead running a quarterly audit, and an MSP running a client review all look identical from Autopilot's perspective: paste a token, get a report. Observer role is sufficient for every module — Autopilot issues no writes. Download a professional PDF from the dashboard footer and hand it to a director before the next meeting.

### Curation, not replacement

Autopilot does not compete with Marvis, Minis, or the SLE dashboards. It reads them. Where Mist gives the operator everything, Autopilot gives the operator an opinion: *these twelve signals are what you should look at this quarter, in priority order, with specific remediations attached.* Every critical finding includes a "Fix in Mist" deep-link that routes straight to the exact portal page that resolves it — not the org landing page, not a search, the specific Subscriptions, NAC Policies, WLAN Templates, or AP Detail view that closes the loop.

### Automates the audit, not the change

Marvis automates the fix. Autopilot automates the audit. The operator keeps full control over remediation; Autopilot eliminates the manual click-through that would otherwise be required to know what to remediate. Two modules (SLE Sentinel and AP Lifecycle Monitor) ship with ready-to-enable Level 3 action hooks — webhook notification and Marvis Self-Driving non-compliant-AP activation — so operators ready to close the loop can do so on their own terms.

### Respects Mist's rate limits by design

Every token has a 5,000-call-per-hour budget. Autopilot exposes two live counters in the UI — per-refresh and per-hour — so operators pace their scans. The site picker defaults to active sites only (those with assigned APs) and displays AP counts so operators scope scans sensibly before running them. A 5-minute response cache shares data across modules — the second module that needs a site's SLE gets a cache hit on the first module's call. Requests have a 250ms inter-call throttle, honor `Retry-After` on 429 responses, and retry 5xx errors with exponential backoff.

### Works at any scale, in any cloud, with any role

Autopilot auto-detects the Mist cloud the token belongs to — all twelve, across Global, EMEA, and APAC regions — with no manual configuration. It handles wireless-only orgs cleanly (WAN Sentinel returns "no WAN devices found" rather than erroring). It handles orgs without SUB-VNA (MinisMonitor flags the gap and skips dependent checks). It handles orgs with thousands of APs via paginated inventory fetches. The same 12-module sweep runs against a 3-site lab and a 500-site retailer; each only surfaces findings that actually apply. The architecture documentation includes a roadmapped adaptive API-budget governor for operators running against very large orgs where a full sweep would otherwise approach the hourly limit.

### Handles the unhappy paths operators actually hit

Module errors are isolated — one broken check never takes the dashboard down, it returns a visible error tile while the other eleven render normally. Subscriptions that are expired, in eval status, or below coverage are distinguished. 802.11r warnings only fire on 802.1X SSIDs where the RADIUS round-trip cost is real. Sticky-client findings require both an SLE signal and corroborating roam-event evidence. PSK-reuse findings collapse band variants of the same SSID so a "Guest 2.4" / "Guest 5" / "Guest 6" family doesn't false-positive as three distinct SSIDs sharing a key. Client Experience Trends filters weekends out for weekday-dominant sites so an office network isn't graded on Saturday idle time.

### Token privacy posture fits enterprise security reviews

Tokens are never written to disk on the server, never logged, never transmitted to any service other than `api.mist.com`. By default they live in server memory for the session and in the browser's `sessionStorage` (cleared on tab close). A user can opt into persistent `localStorage` per org via an explicit *Remember this org* checkbox — revocable at any time with the *Forget* control on the connect dialog. Sessions expire after 8 hours of inactivity. No database. No telemetry. No third-party data sharing.

---

### The test

> *"This is exactly what a self-driving network review should do — it tells me what matters, right now, in a form I can hand to my director before lunch."*

That is the response Autopilot is designed to produce the first time an operator runs it against their own org.
