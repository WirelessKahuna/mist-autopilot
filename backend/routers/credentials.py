"""
Credentials Router
==================
Handles org credential management for multi-org support.

Endpoints:
  POST   /api/credentials/connect   — validate token, fetch org info + sites, create session
  POST   /api/credentials/sites     — update selected sites for active session
  DELETE /api/credentials/session   — clear session (switch back to env defaults)
  GET    /api/credentials/preview   — get site list with AP counts for site picker
"""

import asyncio
import logging
import httpx

from fastapi import APIRouter, HTTPException, Header
from pydantic import BaseModel

from session_store import session_store
from config import get_settings

router = APIRouter(prefix="/api/credentials", tags=["credentials"])
logger = logging.getLogger(__name__)
settings = get_settings()

MIST_BASE_URL = "https://api.mist.com"


class ConnectRequest(BaseModel):
    api_token: str


class SiteSelectionRequest(BaseModel):
    site_ids: list


async def _fetch_json(url: str, token: str) -> dict:
    """Simple async GET with token auth."""
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(
            url,
            headers={"Authorization": f"Token {token}"},
        )
        if resp.status_code == 401:
            raise HTTPException(status_code=401, detail="Invalid API token — check your Org Token and try again.")
        if resp.status_code == 403:
            raise HTTPException(status_code=403, detail="Token has insufficient permissions. Observer role required.")
        if resp.status_code >= 400:
            raise HTTPException(status_code=400, detail=f"Mist API error {resp.status_code}")
        return resp.json()


@router.post("/connect")
async def connect(request: ConnectRequest):
    """
    Validate an API token, discover the org, fetch sites with AP counts.
    Returns session_id + org info + site list for the site picker.
    """
    token = request.api_token.strip()
    if not token:
        raise HTTPException(status_code=400, detail="API token is required.")

    # Step 1 — Get self to find org_id
    try:
        self_data = await _fetch_json(f"{MIST_BASE_URL}/api/v1/self", token)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Could not reach Mist API: {str(e)}")

    # Extract org_id from privileges
    privileges = self_data.get("privileges", [])
    org_privs = [p for p in privileges if p.get("scope") == "org"]
    if not org_privs:
        raise HTTPException(
            status_code=403,
            detail="No org-level access found. Ensure this is an Org Token with Observer role."
        )

    # Use first org (tokens are typically scoped to one org)
    org_id   = org_privs[0].get("org_id")
    org_role = org_privs[0].get("role", "unknown")
    org_name = org_privs[0].get("name", "")

    if not org_id:
        raise HTTPException(status_code=502, detail="Could not determine org ID from token.")

    # Step 2 — Fetch sites + inventory in parallel
    try:
        sites_data, inventory_data = await asyncio.gather(
            _fetch_json(f"{MIST_BASE_URL}/api/v1/orgs/{org_id}/sites", token),
            _fetch_json(f"{MIST_BASE_URL}/api/v1/orgs/{org_id}/inventory", token),
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to fetch org data: {str(e)}")

    # Step 3 — Count APs per site
    ap_count_by_site: dict = {}
    for device in inventory_data:
        if isinstance(device, dict) and device.get("type") == "ap":
            sid = device.get("site_id")
            if sid:
                ap_count_by_site[sid] = ap_count_by_site.get(sid, 0) + 1

    # Step 4 — Build site list: active (AP count > 0) and inactive
    active_sites   = []
    inactive_sites = []

    for site in sites_data:
        sid       = site.get("id")
        ap_count  = ap_count_by_site.get(sid, 0)
        site_info = {
            "id":       sid,
            "name":     site.get("name", sid),
            "ap_count": ap_count,
            "timezone": site.get("timezone", ""),
            "country":  site.get("country_code", ""),
        }
        if ap_count > 0:
            active_sites.append(site_info)
        else:
            inactive_sites.append(site_info)

    # Sort active sites by name
    active_sites.sort(key=lambda s: s["name"].lower())
    inactive_sites.sort(key=lambda s: s["name"].lower())

    # Step 5 — Create session
    session_id = session_store.create(
        org_id=org_id,
        api_token=token,
        org_name=org_name,
    )

    logger.info(
        f"Connected: org={org_name} ({org_id[:8]}...), "
        f"role={org_role}, sites={len(sites_data)}, "
        f"active={len(active_sites)}, inactive={len(inactive_sites)}"
    )

    return {
        "session_id":      session_id,
        "org_id":          org_id,
        "org_name":        org_name,
        "org_role":        org_role,
        "total_sites":     len(sites_data),
        "active_sites":    active_sites,
        "inactive_count":  len(inactive_sites),
    }


@router.post("/sites")
async def select_sites(
    request: SiteSelectionRequest,
    x_session_token: str = Header(None),
):
    """Update selected sites for the active session."""
    if not x_session_token:
        raise HTTPException(status_code=400, detail="No session token provided.")

    creds = session_store.get(x_session_token)
    if not creds:
        raise HTTPException(status_code=401, detail="Session not found or expired.")

    session_store.update_selected_sites(x_session_token, request.site_ids)
    return {"selected": len(request.site_ids)}


@router.delete("/session")
async def clear_session(x_session_token: str = Header(None)):
    """Clear the active session, reverting to env var defaults."""
    if x_session_token:
        session_store.delete(x_session_token)
    return {"status": "cleared"}
