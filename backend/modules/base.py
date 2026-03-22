from __future__ import annotations
import logging
from abc import ABC, abstractmethod

from mist_client import MistClient, MistAPIError
from models import ModuleOutput, Severity

logger = logging.getLogger(__name__)


class BaseModule(ABC):
    """
    Every Mist Autopilot module inherits from this class.

    Subclasses must define:
        module_id    : str — unique snake_case identifier
        display_name : str — human-readable name for the dashboard tile
        icon         : str — emoji for the tile

    Subclasses must implement:
        analyze(org_id, sites, client) -> ModuleOutput

    The scaffold calls run() which wraps analyze() with error handling
    so a broken module never crashes the dashboard.
    """

    module_id: str = ""
    display_name: str = ""
    icon: str = "🔧"

    @abstractmethod
    async def analyze(
        self,
        org_id: str,
        sites: list[dict],
        client: MistClient,
    ) -> ModuleOutput:
        """
        Core analysis logic. Receives the org_id, a list of site dicts
        (from /api/v1/orgs/{org_id}/sites), and the shared MistClient.
        Must return a fully populated ModuleOutput.
        """
        ...

    async def run(self, org_id: str, sites: list[dict], client: MistClient) -> ModuleOutput:
        """
        Safe wrapper around analyze(). Returns a well-formed error output
        instead of raising, so one bad module doesn't break the dashboard.
        """
        try:
            logger.info(f"Running module: {self.module_id}")
            result = await self.analyze(org_id, sites, client)
            logger.info(f"Module {self.module_id} complete — score: {result.score}, severity: {result.severity}")
            return result
        except MistAPIError as e:
            logger.error(f"Module {self.module_id} — Mist API error: {e}")
            return self._error_output(f"Mist API error {e.status_code}: {e.message}")
        except Exception as e:
            logger.exception(f"Module {self.module_id} — unexpected error")
            return self._error_output(str(e))

    def _error_output(self, error: str) -> ModuleOutput:
        return ModuleOutput(
            module_id=self.module_id,
            display_name=self.display_name,
            icon=self.icon,
            score=None,
            severity=Severity.unavailable,
            summary="Module encountered an error. See logs for details.",
            status="error",
            error=error,
        )

    def _coming_soon_output(self) -> ModuleOutput:
        return ModuleOutput(
            module_id=self.module_id,
            display_name=self.display_name,
            icon=self.icon,
            score=None,
            severity=Severity.coming_soon,
            summary="This module is under construction.",
            status="coming_soon",
        )

    @staticmethod
    def score_from_findings(findings) -> int:
        """
        Derive a 0–100 score from a list of Finding objects.
        Starts at 100 and deducts:  critical = 20pts, warning = 10pts, info = 2pts
        """
        score = 100
        for f in findings:
            if f.severity.value == "critical":
                score -= 20
            elif f.severity.value == "warning":
                score -= 10
            elif f.severity.value == "info":
                score -= 2
        return max(0, score)

    @staticmethod
    def severity_from_score(score: int | None) -> Severity:
        if score is None:
            return Severity.unavailable
        if score >= 80:
            return Severity.ok
        if score >= 60:
            return Severity.info
        if score >= 40:
            return Severity.warning
        return Severity.critical
