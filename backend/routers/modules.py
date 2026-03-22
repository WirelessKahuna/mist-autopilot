import logging
from fastapi import APIRouter, HTTPException

from config import get_settings
from mist_client import mist, MistAPIError
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
async def run_module(module_id: str):
    """Run a single module and return its output. Used for tile-level refresh."""
    module = _module_map.get(module_id)
    if not module:
        raise HTTPException(status_code=404, detail=f"Module '{module_id}' not found.")

    org_id = settings.mist_org_id
    try:
        sites = await mist.get_sites(org_id)
    except MistAPIError as e:
        raise HTTPException(status_code=e.status_code or 502, detail=e.message)

    return await module.run(org_id, sites, mist)
