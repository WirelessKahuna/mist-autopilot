import logging
from fastapi import APIRouter, HTTPException, Header

from config import get_settings
from mist_client import mist, MistAPIError, get_mist_client
from session_store import session_store
from models import ModuleOutput
from modules import ALL_MODULES

router = APIRouter(prefix="/api/modules", tags=["modules"])
logger = logging.getLogger(__name__)
settings = get_settings()

_module_map = {m.module_id: m for m in ALL_MODULES}


@router.get("/", response_model=list[dict])
async def list_modules():
    """Return module registry metadata — id, name, icon."""
    return [
        {"module_id": m.module_id, "display_name": m.display_name, "icon": m.icon}
        for m in ALL_MODULES
    ]


@router.get("/{module_id}", response_model=ModuleOutput)
async def run_module(module_id: str, x_session_token: str = Header(None)):
    """Run a single module and return its output. Used for tile-level refresh.
    Requires an active session (X-Session-Token header); no env-var fallback."""
    module = _module_map.get(module_id)
    if not module:
        raise HTTPException(status_code=404, detail=f"Module '{module_id}' not found.")

    if not x_session_token:
        raise HTTPException(
            status_code=401,
            detail="No active session. Connect an org token to continue.",
        )
    creds = session_store.get(x_session_token)
    if not creds:
        raise HTTPException(
            status_code=401,
            detail="Session not found or expired. Reconnect your org token.",
        )

    client = get_mist_client(creds.api_token, api_base=creds.api_base)
    org_id = creds.org_id
    selected_site_ids = creds.selected_site_ids

    try:
        all_sites = await client.get_sites(org_id)
    except MistAPIError as e:
        raise HTTPException(status_code=e.status_code or 502, detail=e.message)

    # Honor site selection if one exists for this session
    if selected_site_ids:
        sites = [s for s in all_sites if s["id"] in selected_site_ids]
    else:
        sites = all_sites

    return await module.run(org_id, sites, client)
