"""
Mist cloud instance definitions.

Mist operates multiple geographic cloud instances across three regions
(Global, EMEA, APAC). Each has paired API and portal hostnames. When a
user authenticates, we try /api/v1/self against each cloud's API base
until one succeeds — that determines the cloud the token belongs to,
and the matching portal base is stored for deep-link generation.

Cloud list sourced from Mist documentation (verified April 2026).
If Mist adds a new cloud, append to MIST_CLOUDS and the auto-detection
logic in credentials.py will pick it up automatically.
"""


# Ordered: Global region first (statistically most common for demos and
# North American customers), then EMEA, then APAC. Order affects probe
# speed for non-global orgs but does not affect correctness — every cloud
# is tried until one authenticates the token.
MIST_CLOUDS: list[dict] = [
    # ── Global ──────────────────────────────────────────────────────────
    {"id": "global01", "region": "Global", "api": "https://api.mist.com",     "portal": "https://manage.mist.com"},
    {"id": "global02", "region": "Global", "api": "https://api.gc1.mist.com", "portal": "https://manage.gc1.mist.com"},
    {"id": "global03", "region": "Global", "api": "https://api.ac2.mist.com", "portal": "https://manage.ac2.mist.com"},
    {"id": "global04", "region": "Global", "api": "https://api.gc2.mist.com", "portal": "https://manage.gc2.mist.com"},
    {"id": "global05", "region": "Global", "api": "https://api.gc4.mist.com", "portal": "https://manage.gc4.mist.com"},

    # ── EMEA ────────────────────────────────────────────────────────────
    {"id": "emea01",   "region": "EMEA",   "api": "https://api.eu.mist.com",  "portal": "https://manage.eu.mist.com"},
    {"id": "emea02",   "region": "EMEA",   "api": "https://api.gc3.mist.com", "portal": "https://manage.gc3.mist.com"},
    {"id": "emea03",   "region": "EMEA",   "api": "https://api.ac6.mist.com", "portal": "https://manage.ac6.mist.com"},
    {"id": "emea04",   "region": "EMEA",   "api": "https://api.gc6.mist.com", "portal": "https://manage.gc6.mist.com"},

    # ── APAC ────────────────────────────────────────────────────────────
    {"id": "apac01",   "region": "APAC",   "api": "https://api.ac5.mist.com", "portal": "https://manage.ac5.mist.com"},
    {"id": "apac02",   "region": "APAC",   "api": "https://api.gc5.mist.com", "portal": "https://manage.gc5.mist.com"},
    {"id": "apac03",   "region": "APAC",   "api": "https://api.gc7.mist.com", "portal": "https://manage.gc7.mist.com"},
]


def portal_base_for_api(api_base: str) -> str:
    """
    Derive the portal base URL from an API base URL.
    Falls back to global portal if api_base doesn't match a known cloud.
    """
    api_base = api_base.rstrip("/")
    for cloud in MIST_CLOUDS:
        if cloud["api"] == api_base:
            return cloud["portal"]
    return MIST_CLOUDS[0]["portal"]  # default: Global 01
