import asyncio
import logging
from fastapi import APIRouter, HTTPException, Header
from config import get_settings
from mist_client import mist, MistAPIError, api_counter, get_mist_client
from mist_clouds import MIST_CLOUDS
from session_store import session_store
from models import OrgSummary
from modules import ALL_MODULES

router = APIRouter(prefix="/api/org", tags=["org"])
logger = logging.getLogger(__name__)
settings = get_settings()


def _get_client_and_org(session_token: str | None):
    """Return (MistClient, org_id, selected_site_ids, creds) for an active session.
    Raises HTTPException 401 if no valid session is present; the env-var
    fallback has been removed so the hosted deployment never silently serves
    data from baked-in credentials."""
    if not session_token:
        raise HTTPException(
            status_code=401,
            detail="No active session. Connect an org token to continue.",
        )
    creds = session_store.get(session_token)
    if not creds:
        raise HTTPException(
            status_code=401,
            detail="Session not found or expired. Reconnect your org token.",
        )
    # Pass the session's stored api_base so the client hits the correct
    # Mist cloud (global / EU / GC1 / AC2 / etc.). portal_base is derived
    # inside MistClient from the api_base.
    client = get_mist_client(creds.api_token, api_base=creds.api_base)
    return client, creds.org_id, creds.selected_site_ids, creds


def _cloud_id_for_api_base(api_base: str) -> str:
    """Reverse-lookup the human-readable cloud id (global/eu/gc1/...) from the api_base URL."""
    api_base = api_base.rstrip("/")
    for cloud in MIST_CLOUDS:
        if cloud["api"] == api_base:
            return cloud["id"]
    return "global"


@router.get("/summary", response_model=OrgSummary)
async def get_org_summary(x_session_token: str = Header(None)):
    """
    Fetch org info and run all modules in parallel.
    Requires an active session (X-Session-Token header); no env-var fallback.
    """
    client, org_id, selected_site_ids, creds = _get_client_and_org(x_session_token)
    api_counter.reset_last_refresh(org_id)

    try:
        org_info = await client.get_org_info(org_id)
        all_sites = await client.get_sites(org_id)
    except MistAPIError as e:
        raise HTTPException(status_code=e.status_code or 502, detail=e.message)

    # Filter to selected sites if a selection was made
    if selected_site_ids:
        sites = [s for s in all_sites if s["id"] in selected_site_ids]
    else:
        sites = all_sites

    # Run all modules concurrently
    module_results = await asyncio.gather(
        *[module.run(org_id, sites, client) for module in ALL_MODULES]
    )

    scored = [m.score for m in module_results if m.score is not None]
    overall_score = round(sum(scored) / len(scored)) if scored else None

    # Capability + cloud info for the UI. creds is always present here because
    # _get_client_and_org raises 401 when it isn't.
    can_write   = creds.can_write
    portal_base = creds.portal_base
    cloud_id    = _cloud_id_for_api_base(client.base_url)

    return OrgSummary(
        org_id=org_id,
        org_name=org_info.get("name", "Unknown Org"),
        site_count=len(sites),
        overall_score=overall_score,
        modules=list(module_results),
        site_names={s["id"]: s["name"] for s in sites},
        can_write=can_write,
        portal_base=portal_base,
        cloud_id=cloud_id,
    )


@router.get("/sites")
async def get_sites(x_session_token: str = Header(None)):
    """Return raw site list."""
    client, org_id, _, _ = _get_client_and_org(x_session_token)
    try:
        return await client.get_sites(org_id)
    except MistAPIError as e:
        raise HTTPException(status_code=e.status_code or 502, detail=e.message)

@router.get("/stats")
async def get_stats(x_session_token: str = Header(None)):
    """Return API call counters for the current org."""
    _, org_id, _, _ = _get_client_and_org(x_session_token)
    return api_counter.stats(org_id)
