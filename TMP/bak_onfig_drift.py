from models import ModuleOutput
from mist_client import MistClient
from .base import BaseModule


class ConfigDriftModule(BaseModule):
    module_id = "config_drift"
    display_name = "Config Drift Detective"
    icon = "🔍"

    async def analyze(self, org_id: str, sites: list[dict], client: MistClient) -> ModuleOutput:
        return self._coming_soon_output()
