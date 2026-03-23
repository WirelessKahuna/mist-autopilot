from models import ModuleOutput
from mist_client import MistClient
from .base import BaseModule

class MarvisIQModule(BaseModule):
    module_id    = "marvis_iq"
    display_name = "MarvisIQ"
    icon         = "🔬"

    async def analyze(self, org_id: str, sites: list[dict], client: MistClient) -> ModuleOutput:
        return self._coming_soon_output()
