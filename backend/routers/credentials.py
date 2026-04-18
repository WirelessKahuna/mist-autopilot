"""
Credentials Router
==================
Handles org credential management for multi-org support.

Endpoints:
  POST   /api/credentials/connect   — validate token, auto-detect cloud, fetch org info + sites, create session
  POST   /api/credentials/sites     — update selected sites for active session
  DELETE /api/credentials/session   — clear session (switch back to env defaults)

Cloud auto-detection:
  Mist operates multiple geographic clouds (global, EU, GC1-4, AC2). A token
  is valid on exactly one of them. On /connect we try /api/v1/self against
  each cloud's API base in turn until one returns 200 — that's the cloud
  the token belongs to. The matching portal base is stored on the session
  so deep-link builders can construct URLs for the correct Mist portal.
"""

import asyncio
import logging
import httpx

from fastapi import APIRouter, HTTPException, Header
from pydantic import BaseModel

from session_store import session_store
from config import get_settings
from mist_clouds import MIST_CLOUDS, portal_base_for_api

router = APIRouter(prefix="/api/credentials", tags=["credentials"])
logger = logging.getLogger(__name__)
settings = get_settings()


class ConnectRequest(BaseModel):
    api_token: str


class SiteSelectionRequest(BaseModel):
    site_ids: list


async def _fetch_json(url: str, token: str, timeout: float = 15.0) -> dict:
    """Simple async GET with token auth. Raises HTTPException on non-2xx."""
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.get(
            url,
            headers={"Authorization": f"Token {token}"},
        )
        if resp.status_code == 401:
            raise HTTPException(status_code=401, detail="Invalid API token — check your Org Token and try again.")
        if resp.status_code == 403:
            raise HTTPException(status_code=403, detail="Token has insufficient permissions.")
        if resp.status_code >= 400:
            raise HTTPException(status_code=400, detail=f"Mist API error {resp.status_code}")
        return resp.json()


async def _probe_cloud(token: str) -> tuple[dict, dict]:
    """
    Try /api/v1/self against each Mist cloud in MIST_CLOUDS order.
    Returns (cloud_dict, self_response_json) for the first cloud that
    authenticates the token. Raises HTTPException if no cloud accepts it.

    Probing is fast: each attempt has a short timeout, and the common case
    (global cloud) is tried first. Non-global tokens add at most ~2 seconds
    to connect in exchange for cloud-agnostic operation.
    """
    last_error = None
    for cloud in MIST_CLOUDS:
        url = f"{cloud['api']}/api/v1/self"
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(
                    url,
                    headers={"Authorization": f"Token {token}"},
                )
            if resp.status_code == 200:
                logger.info(f"Cloud detected: {cloud['id']} ({cloud['api']})")
                return cloud, resp.json()
            # 401/403 on this cloud means token isn't valid here — try next cloud.
            # Other status codes still move on but get logged for debugging.
            if resp.status_code not in (401, 403):
                logger.debug(f"Cloud probe {cloud['id']}: status {resp.status_code}")
                last_error = f"{cloud['id']} returned {resp.status_code}"
        except httpx.TimeoutException:
            logger.debug(f"Cloud probe {cloud['id']}: timeout")
            last_error = f"{cloud['id']} timed out"
        except Exception as e:
            logger.debug(f"Cloud probe {cloud['id']}: {e}")
            last_error = f"{cloud['id']}: {e}"

    raise HTTPException(
        status_code=401,
        detail=(
            "Token was rejected by every Mist cloud we tried "
            "(global, EU, GC1-4, AC2). Verify the token is a valid Org Token "
            "that has not been revoked."
        ),
    )


@router.post("/connect")
async def connect(request: ConnectRequest):
    """
    Validate an API token, auto-detect the Mist cloud it belongs to,
    discover the org, fetch sites with AP counts.
    Returns session_id + org info + site list + capability flags.
    """
    token = request.api_token.strip()
    if not token:
        raise HTTPException(status_code=400, detail="API token is required.")

    # Step 1 — Probe Mist clouds to find which one the token authenticates against
    try:
        cloud, self_data = await _probe_cloud(token)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Could not reach any Mist cloud: {str(e)}")

    api_base    = cloud["api"]
    portal_base = cloud["portal"]

    # Step 2 — Extract org_id + role from privileges
    privileges = self_data.get("privileges", [])
    org_privs = [p for p in privileges if p.get("scope") == "org"]
    if not org_privs:
        raise HTTPException(
            status_code=403,
            detail="No org-level access found. Ensure this is an Org Token with at least Observer role."
        )

    # Use first org (tokens are typically scoped to one org)
    org_id   = org_privs[0].get("org_id")
    org_role = org_privs[0].get("role", "unknown")
    org_name = org_privs[0].get("name", "")

    if not org_id:
        raise HTTPException(status_code=502, detail="Could not determine org ID from token.")

    # Step 3 — Fetch sites + inventory in parallel (on the detected cloud)
    try:
        sites_data, inventory_data = await asyncio.gather(
            _fetch_json(f"{api_base}/api/v1/orgs/{org_id}/sites", token),
            _fetch_json(f"{api_base}/api/v1/orgs/{org_id}/inventory", token),
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to fetch org data: {str(e)}")

    # Step 4 — Count APs per site
    ap_count_by_site: dict = {}
    for device in inventory_data:
        if isinstance(device, dict) and device.get("type") == "ap":
            sid = device.get("site_id")
            if sid:
                ap_count_by_site[sid] = ap_count_by_site.get(sid, 0) + 1

    # Step 5 — Build site list: active (AP count > 0) and inactive
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

    # Step 6 — Create session with cloud + role persisted
    session_id = session_store.create(
        org_id=org_id,
        api_token=token,
        org_name=org_name,
        org_role=org_role,
        api_base=api_base,
        portal_base=portal_base,
    )

    # Compute can_write using same rule as SessionCredentials.can_write
    can_write = org_role.lower() in ("admin", "write")

    logger.info(
        f"Connected: org={org_name} ({org_id[:8]}...), "
        f"cloud={cloud['id']}, role={org_role}, can_write={can_write}, "
        f"sites={len(sites_data)}, active={len(active_sites)}, inactive={len(inactive_sites)}"
    )

    return {
        "session_id":      session_id,
        "org_id":          org_id,
        "org_name":        org_name,
        "org_role":        org_role,
        "can_write":       can_write,
        "cloud_id":        cloud["id"],
        "portal_base":     portal_base,
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
