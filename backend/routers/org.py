import asyncio
import logging
from fastapi import APIRouter, HTTPException

from config import get_settings
from mist_client import mist, MistAPIError, api_counter
from models import OrgSummary
from modules import ALL_MODULES

router = APIRouter(prefix="/api/org", tags=["org"])
logger = logging.getLogger(__name__)
settings = get_settings()


@router.get("/summary", response_model=OrgSummary)
async def get_org_summary():
    """
    Fetch org info and run all modules in parallel.
    Returns the complete OrgSummary used to render the dashboard.
    """
    org_id = settings.mist_org_id
    api_counter.reset_last_refresh()

    try:
        org_info = await mist.get_org_info(org_id)
        sites = await mist.get_sites(org_id)
    except MistAPIError as e:
        raise HTTPException(status_code=e.status_code or 502, detail=e.message)

    # Run all modules concurrently
    module_results = await asyncio.gather(
        *[module.run(org_id, sites, mist) for module in ALL_MODULES]
    )

    # Compute overall org health score (average of modules that have scores)
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
async def get_sites():
    """Return raw site list — used for the org selector."""
    org_id = settings.mist_org_id
    try:
        return await mist.get_sites(org_id)
    except MistAPIError as e:
        raise HTTPException(status_code=e.status_code or 502, detail=e.message)

@router.get("/stats")
async def get_stats():
    """Return API call counters for display in the dashboard header."""
    from mist_client import api_counter
    return api_counter.stats()
