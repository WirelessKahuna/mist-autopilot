from models import ModuleOutput
from mist_client import MistClient
from .base import BaseModule


class SLESentinelModule(BaseModule):
    module_id = "sle_sentinel"
    display_name = "SLE Sentinel"
    icon = "📊"

    async def analyze(self, org_id: str, sites: list[dict], client: MistClient) -> ModuleOutput:
        return self._coming_soon_output()
