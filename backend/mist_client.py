import asyncio
import logging
from typing import Any

import httpx
from cachetools import TTLCache

from config import get_settings
from mist_clouds import portal_base_for_api

logger = logging.getLogger(__name__)

settings = get_settings()

# In-memory response cache — keyed by URL, expires per CACHE_TTL_SECONDS
_cache: TTLCache = TTLCache(maxsize=256, ttl=settings.cache_ttl_seconds)
_cache_lock = asyncio.Lock()

# Retry configuration
MAX_RETRIES = 3
RETRY_BACKOFF = 1.5  # seconds, doubles each attempt
RATE_LIMIT_DELAY = 0.25  # seconds between requests to avoid 429s


class MistAPIError(Exception):
    def __init__(self, status_code: int, message: str, url: str = ""):
        self.status_code = status_code
        self.message = message
        self.url = url
        super().__init__(f"Mist API error {status_code} on {url}: {message}")


class MistClient:
    def __init__(self, api_token: str | None = None, base_url: str | None = None):
        """
        If api_token is provided, use it (session credential).
        Otherwise fall back to env var defaults.

        portal_base is derived from base_url so modules can build deep-links
        into the correct Mist portal for the cloud this session belongs to.
        """
        self.base_url = (base_url or settings.mist_api_base_url).rstrip("/")
        self.portal_base = portal_base_for_api(self.base_url)
        token = api_token or settings.mist_api_token
        self.headers = {
            "Authorization": f"Token {token}",
            "Content-Type": "application/json",
        }
        self._last_request_time = 0.0

    async def _throttle(self):
        """Enforce minimum delay between requests."""
        now = asyncio.get_event_loop().time()
        elapsed = now - self._last_request_time
        if elapsed < RATE_LIMIT_DELAY:
            await asyncio.sleep(RATE_LIMIT_DELAY - elapsed)
        self._last_request_time = asyncio.get_event_loop().time()

    async def get(self, path: str, params: dict | None = None, use_cache: bool = True) -> Any:
        url = f"{self.base_url}{path}"
        cache_key = f"{url}?{params}"

        if use_cache:
            async with _cache_lock:
                if cache_key in _cache:
                    logger.debug(f"Cache hit: {url}")
                    return _cache[cache_key]

        await self._throttle()
        api_counter.increment()

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                async with httpx.AsyncClient(timeout=30.0) as client:
                    logger.debug(f"GET {url} (attempt {attempt})")
                    response = await client.get(url, headers=self.headers, params=params)

                if response.status_code == 429:
                    retry_after = int(response.headers.get("Retry-After", 5))
                    logger.warning(f"Rate limited on {url}, waiting {retry_after}s")
                    await asyncio.sleep(retry_after)
                    continue

                if response.status_code == 401:
                    raise MistAPIError(401, "Invalid or expired API token. Check your MIST_API_TOKEN.", url)

                if response.status_code == 403:
                    raise MistAPIError(403, "Insufficient permissions for this org.", url)

                if response.status_code == 404:
                    raise MistAPIError(404, f"Resource not found: {path}", url)

                if response.status_code >= 500:
                    if attempt < MAX_RETRIES:
                        wait = RETRY_BACKOFF * attempt
                        logger.warning(f"Server error {response.status_code} on {url}, retry in {wait}s")
                        await asyncio.sleep(wait)
                        continue
                    raise MistAPIError(response.status_code, "Mist API server error", url)

                response.raise_for_status()
                data = response.json()

                if use_cache:
                    async with _cache_lock:
                        _cache[cache_key] = data

                return data

            except httpx.TimeoutException:
                if attempt < MAX_RETRIES:
                    wait = RETRY_BACKOFF * attempt
                    logger.warning(f"Timeout on {url}, retry in {wait}s")
                    await asyncio.sleep(wait)
                    continue
                raise MistAPIError(504, "Request timed out after retries", url)

            except MistAPIError:
                raise

            except Exception as e:
                raise MistAPIError(0, str(e), url)

        raise MistAPIError(429, "Max retries exceeded", url)

    async def put(self, path: str, body: dict) -> Any:
        url = f"{self.base_url}{path}"
        await self._throttle()
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.put(url, headers=self.headers, json=body)
            response.raise_for_status()
            return response.json()

    # ------------------------------------------------------------------
    # Convenience helpers for common Mist endpoints
    # ------------------------------------------------------------------

    async def get_org_info(self, org_id: str) -> dict:
        return await self.get(f"/api/v1/orgs/{org_id}")

    async def get_sites(self, org_id: str) -> list:
        return await self.get(f"/api/v1/orgs/{org_id}/sites")

    async def get_org_wlans(self, org_id: str) -> list:
        return await self.get(f"/api/v1/orgs/{org_id}/wlans")

    async def get_site_wlans(self, site_id: str) -> list:
        return await self.get(f"/api/v1/sites/{site_id}/wlans")

    async def get_site_wlans_derived(self, site_id: str) -> list:
        """
        Fetch fully scope-resolved WLANs for a site.
        GET /api/v1/sites/{site_id}/wlans/derived
        Returns WLANs actually active at the site with template/exclusion logic
        already evaluated by Mist backend.
        Distinguishing template vs site-local:
          site_id == '00000000-0000-0000-0000-000000000000' -> template-pushed
          site_id == actual site UUID                       -> site-local config
        """
        return await self.get(f"/api/v1/sites/{site_id}/wlans/derived", use_cache=True)

    async def get_wlan_templates(self, org_id: str) -> list:
        return await self.get(f"/api/v1/orgs/{org_id}/wlantemplates")

    async def get_site_stats(self, site_id: str) -> dict:
        return await self.get(f"/api/v1/sites/{site_id}/stats")

    async def get_site_sle_metric(
        self,
        site_id: str,
        scope: str,
        metric: str,
        duration: str = "1d",
    ) -> dict:
        """
        Fetch SLE summary for a specific metric at a site.
        Correct Mist endpoint pattern:
          GET /api/v1/sites/{site_id}/sle/site/{site_id}/metric/{metric}/summary
        The scope segment is always the literal string "site" followed by site_id.
        duration: "1d" | "7d" | "30d"
        """
        return await self.get(
            f"/api/v1/sites/{site_id}/sle/site/{site_id}/metric/{metric}/summary",
            params={"duration": duration},
        )

    async def get_site_aps(self, site_id: str) -> list:
        return await self.get(f"/api/v1/sites/{site_id}/stats/devices", params={"type": "ap"})

    async def get_org_devices(self, org_id: str) -> list:
        return await self.get(f"/api/v1/orgs/{org_id}/devices/search", params={"type": "ap"})

    async def get_org_wan_tunnels(self, org_id: str) -> list:
        """
        Fetch all WAN tunnel stats for the org.
        GET /api/v1/orgs/{org_id}/stats/tunnels?type=wan
        Returns tunnel objects with: tunnel_name, up, peer_ip, peer_host,
        site_id, node, protocol, last_event fields.
        """
        try:
            result = await self.get(
                f"/api/v1/orgs/{org_id}/stats/tunnels",
                params={"type": "wan"},
                use_cache=True,
            )
            return result if isinstance(result, list) else result.get("results", [])
        except MistAPIError as e:
            if e.status_code in (400, 404):
                return []
            raise

    async def get_site_gateway_events(self, site_id: str, duration: str = "7d") -> list:
        """
        Fetch gateway-related device events for a site.
        GET /api/v1/sites/{site_id}/devices/events
        Fetches all events and filters for WAN/tunnel/failover types client-side.
        """
        try:
            result = await self.get(
                f"/api/v1/sites/{site_id}/devices/events",
                params={"duration": duration},
                use_cache=True,
            )
            events = result if isinstance(result, list) else result.get("results", [])
            return events
        except MistAPIError as e:
            if e.status_code in (400, 404):
                return []
            raise

    async def get_site_device_events(self, site_id: str, duration: str = "7d",
                                      event_type: str | None = None) -> dict:
        """
        Fetch device events for a site.
        GET /api/v1/sites/{site_id}/devices/events
        Optional event_type filter (e.g. "AP_RADAR_DETECTED").
        """
        params: dict = {"duration": duration}
        if event_type:
            params["type"] = event_type
        return await self.get(
            f"/api/v1/sites/{site_id}/devices/events",
            params=params,
            use_cache=True,
        )

    async def get_org_rf_templates(self, org_id: str) -> list:
        """Fetch all RF templates for the org."""
        return await self.get(f"/api/v1/orgs/{org_id}/rftemplates", use_cache=True)

    async def get_site_roam_events(self, site_id: str, duration: str = "7d") -> dict:
        """
        Fetch fast roam events for a site.
        GET /api/v1/sites/{site_id}/events/fast_roam
        Returns event counts by type including sticky client events.
        """
        return await self.get(
            f"/api/v1/sites/{site_id}/events/fast_roam",
            params={"duration": duration},
            use_cache=True,
        )

    async def get_org_inventory(self, org_id: str, device_type: str = "ap") -> list:
        """
        Fetch full org device inventory with pagination.
        Endpoint: GET /api/v1/orgs/{org_id}/inventory
        Handles X-Page-Total pagination — fetches all pages up to 1000 per page.
        device_type: "ap" | "switch" | "gateway" | "" (all)
        """
        all_devices: list = []
        page = 1
        limit = 1000

        while True:
            params: dict = {"limit": limit, "page": page}
            if device_type:
                params["type"] = device_type

            # Use raw httpx to access response headers for X-Page-Total
            url = f"{self.base_url}/api/v1/orgs/{org_id}/inventory"
            await self._throttle()
            async with __import__("httpx").AsyncClient(timeout=30.0) as http:
                response = await http.get(url, headers=self.headers, params=params)
                response.raise_for_status()
                page_data = response.json()
                total = int(response.headers.get("X-Page-Total", len(page_data)))

            if isinstance(page_data, list):
                all_devices.extend(page_data)
            else:
                break

            if len(all_devices) >= total:
                break
            page += 1

        return all_devices


# Default singleton instance — uses env var credentials
# Modules import this for standard operation
mist = MistClient()


def get_mist_client(api_token: str | None = None, api_base: str | None = None) -> "MistClient":
    """
    Factory — returns a session-scoped client if api_token provided,
    otherwise returns the default env-var singleton.

    api_base lets the caller override the cloud for this client instance —
    required for multi-cloud support, since sessions can belong to any of
    Mist's geographic clouds (EU, GC1, AC2, etc.) regardless of the env default.
    """
    if api_token:
        return MistClient(api_token=api_token, base_url=api_base)
    return mist


# ---------------------------------------------------------------------------
# API Call Counter
# ---------------------------------------------------------------------------
from datetime import datetime, timezone

class _APICounter:
    def __init__(self):
        self.last_refresh: int = 0
        self._current_hour: int = datetime.now(timezone.utc).hour
        self._hourly_by_org: dict = {}   # org_id -> hourly count
        self._active_org: str = "default"

    def _check_hour_reset(self):
        now_hour = datetime.now(timezone.utc).hour
        if now_hour != self._current_hour:
            self._hourly_by_org = {}     # reset all orgs at top of hour
            self._current_hour = now_hour

    def set_active_org(self, org_id: str):
        """Call at the start of each scan to track which org is being counted."""
        self._active_org = org_id or "default"

    def increment(self):
        self._check_hour_reset()
        self.last_refresh += 1
        org = self._active_org
        self._hourly_by_org[org] = self._hourly_by_org.get(org, 0) + 1

    def reset_last_refresh(self, org_id: str | None = None):
        self.last_refresh = 0
        if org_id:
            self.set_active_org(org_id)

    def reset_all(self):
        self.last_refresh = 0
        self._hourly_by_org = {}

    def stats(self, org_id: str | None = None) -> dict:
        self._check_hour_reset()
        org = org_id or self._active_org
        return {
            "last_refresh": self.last_refresh,
            "hourly": self._hourly_by_org.get(org, 0),
        }


api_counter = _APICounter()
