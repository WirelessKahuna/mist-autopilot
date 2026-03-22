import asyncio
import logging
from typing import Any

import httpx
from cachetools import TTLCache

from config import get_settings

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
    def __init__(self):
        self.base_url = settings.mist_api_base_url.rstrip("/")
        self.headers = {
            "Authorization": f"Token {settings.mist_api_token}",
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


# Singleton instance — imported by all modules
mist = MistClient()
