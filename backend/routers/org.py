import asyncio
import logging
from fastapi import APIRouter, HTTPException, Header
from config import get_settings
from mist_client import mist, MistAPIError, api_counter, get_mist_client
from session_store import session_store
from models import OrgSummary
from modules import ALL_MODULES

router = APIRouter(prefix="/api/org", tags=["org"])
logger = logging.getLogger(__name__)
settings = get_settings()


def _get_client_and_org(session_token: str | None):
    """Return (MistClient, org_id) for either session or env var credentials."""
    if session_token:
        creds = session_store.get(session_token)
        if creds:
            return get_mist_client(creds.api_token), creds.org_id, creds.selected_site_ids
    return mist, settings.mist_org_id, []


@router.get("/summary", response_model=OrgSummary)
async def get_org_summary(x_session_token: str = Header(None)):
    """
    Fetch org info and run all modules in parallel.
    Uses session credentials if X-Session-Token header present,
    otherwise falls back to env var defaults.
    """
    client, org_id, selected_site_ids = _get_client_and_org(x_session_token)
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

    return OrgSummary(
        org_id=org_id,
        org_name=org_info.get("name", "Unknown Org"),
        site_count=len(sites),
        overall_score=overall_score,
        modules=list(module_results),
    )


@router.get("/sites")
async def get_sites(x_session_token: str = Header(None)):
    """Return raw site list."""
    client, org_id, _ = _get_client_and_org(x_session_token)
    try:
        return await client.get_sites(org_id)
    except MistAPIError as e:
        raise HTTPException(status_code=e.status_code or 502, detail=e.message)

@router.get("/stats")
async def get_stats(x_session_token: str = Header(None)):
    """Return API call counters for the current org."""
    _, org_id, _ = _get_client_and_org(x_session_token)
    return api_counter.stats(org_id)
