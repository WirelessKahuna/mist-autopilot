"""
Diagnostic endpoints — remove before final submission.
These endpoints expose internal data for development verification only.
They are NOT secured beyond the existing API token on the backend.
"""

import asyncio
from fastapi import APIRouter
from config import get_settings
from mist_client import mist, MistAPIError

router = APIRouter(prefix="/api/debug", tags=["debug"])
settings = get_settings()


@router.get("/wlan-audit")
async def wlan_audit():
    """
    Returns every SSID across the org with PSKs anonymized to PWD-A, PWD-B etc.
    Used to visually verify PSK reuse detection logic.
    """
    org_id = settings.mist_org_id

    # Fetch org-level WLANs and site list
    try:
        org_wlans, sites = await asyncio.gather(
            mist.get_org_wlans(org_id),
            mist.get_sites(org_id),
        )
    except MistAPIError as e:
        return {"error": str(e)}

    # Fetch all site-level WLANs in parallel
    site_wlan_results = await asyncio.gather(
        *[mist.get_site_wlans(site["id"]) for site in sites],
        return_exceptions=True,
    )

    site_map = {s["id"]: s.get("name", s["id"]) for s in sites}

    # Build master PSK → token map (PWD-A, PWD-B, ...)
    psk_token: dict[str, str] = {}
    counter = 0

    def get_token(psk: str) -> str:
        nonlocal counter
        if psk not in psk_token:
            label = ""
            n = counter
            while True:
                label = chr(65 + (n % 26)) + label
                n = n // 26 - 1
                if n < 0:
                    break
            psk_token[psk] = f"PWD-{label}"
            counter += 1
        return psk_token[psk]

    rows = []

    # Org-level WLANs
    for w in org_wlans:
        auth     = w.get("auth", {})
        auth_type = auth.get("type", "open")
        psk      = auth.get("psk")
        token    = get_token(psk) if psk else None
        rows.append({
            "scope":      "org",
            "site":       "— org level —",
            "ssid":       w.get("ssid", "?"),
            "auth_type":  auth_type,
            "psk_token":  token,
            "vlan":       w.get("vlan_id") if w.get("vlan_enabled") else None,
            "portal":     w.get("portal", {}).get("enabled", False),
        })

    # Site-level WLANs
    for site, wlan_list in zip(sites, site_wlan_results):
        if isinstance(wlan_list, Exception):
            continue
        site_name = site_map[site["id"]]
        for w in wlan_list:
            auth      = w.get("auth", {})
            auth_type = auth.get("type", "open")
            psk       = auth.get("psk")
            token     = get_token(psk) if psk else None
            rows.append({
                "scope":     "site",
                "site":      site_name,
                "ssid":      w.get("ssid", "?"),
                "auth_type": auth_type,
                "psk_token": token,
                "vlan":      w.get("vlan_id") if w.get("vlan_enabled") else None,
                "portal":    w.get("portal", {}).get("enabled", False),
            })

    # Build PSK reuse summary — which tokens appear on multiple SSID names
    from collections import defaultdict
    token_to_ssids: dict[str, set] = defaultdict(set)
    for row in rows:
        if row["psk_token"]:
            token_to_ssids[row["psk_token"]].add(row["ssid"])

    reuse_warnings = {
        token: list(ssids)
        for token, ssids in token_to_ssids.items()
        if len(ssids) > 1
    }

    return {
        "note": "PSKs are anonymized. Same token = same passphrase. Different token = different passphrase.",
        "psk_reuse_warnings": reuse_warnings if reuse_warnings else "None detected",
        "wlans": rows,
    }
