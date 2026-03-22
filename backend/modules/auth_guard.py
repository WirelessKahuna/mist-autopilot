from models import ModuleOutput
from mist_client import MistClient
from .base import BaseModule


class AuthGuardModule(BaseModule):
    module_id    = "auth_guard"
    display_name = "AuthGuard"
    icon         = "🔑"

    async def analyze(self, org_id: str, sites: list[dict], client: MistClient) -> ModuleOutput:
        return self._coming_soon_output()
