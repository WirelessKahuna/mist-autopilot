from models import ModuleOutput
from mist_client import MistClient
from .base import BaseModule


class SUBMonitorModule(BaseModule):
    module_id    = "sub_monitor"
    display_name = "SUBMonitor"
    icon         = "📋"

    async def analyze(self, org_id: str, sites: list[dict], client: MistClient) -> ModuleOutput:
        return self._coming_soon_output()
