"""
wlan_utils.py — Shared WLAN scope resolution helpers
=====================================================
The Mist API endpoint GET /api/v1/sites/{site_id}/wlans returns the fully
resolved set of WLANs for a site — including WLANs inherited from org-level
WLAN Templates, with applies_to scope and exclusions already evaluated by the
Mist backend. Device profile scoping is also reflected.

This means we should NEVER fetch org-level WLANs separately and include them
at every site. Instead, we rely solely on per-site WLAN lists for all
per-site analysis, and deduplicate by WLAN ID for cross-site analysis.

Key functions:
  build_site_wlan_map   — annotate site WLAN lists and return per-site dict
  build_cross_site_index — deduplicate WLANs by ID for cross-site analysis,
                           tracking which sites each unique WLAN appears at
"""

from __future__ import annotations
from collections import defaultdict


def build_site_wlan_map(
    sites: list[dict],
    site_wlan_lists: list,   # parallel to sites, may contain Exceptions
) -> dict[str, list[dict]]:
    """
    Annotate each WLAN with _site_id and _site_name, return per-site dict.
    Sites whose WLAN fetch failed are silently skipped.
    """
    result: dict[str, list[dict]] = {}
    for site, wlan_list in zip(sites, site_wlan_lists):
        if isinstance(wlan_list, Exception):
            continue
        sid       = site["id"]
        site_name = site.get("name", sid)
        for w in wlan_list:
            w["_site_id"]   = sid
            w["_site_name"] = site_name
        result[sid] = wlan_list
    return result


def build_cross_site_index(
    site_wlan_map: dict[str, list[dict]],
) -> dict[str, dict]:
    """
    Build a cross-site WLAN index keyed by WLAN ID.

    Template WLANs appear in every applicable site's list with the same ID.
    This deduplicates them so cross-site analysis (PSK reuse, SSID drift) sees
    each unique WLAN once, annotated with all the sites it appears at.

    Returns:
        {
          wlan_id: {
            "wlan": <wlan dict>,          # one canonical copy
            "site_ids": [sid, ...],       # all sites this WLAN appears at
            "site_names": [name, ...],
          }
        }
    """
    index: dict[str, dict] = {}
    for sid, wlan_list in site_wlan_map.items():
        for w in wlan_list:
            wlan_id = w.get("id")
            if not wlan_id:
                continue
            if wlan_id not in index:
                index[wlan_id] = {
                    "wlan":       w,
                    "site_ids":   [],
                    "site_names": [],
                }
            entry = index[wlan_id]
            if sid not in entry["site_ids"]:
                entry["site_ids"].append(sid)
                entry["site_names"].append(w.get("_site_name", sid))
    return index


def unique_wlans(site_wlan_map: dict[str, list[dict]]) -> list[dict]:
    """
    Return a deduplicated list of WLAN objects (one per unique WLAN ID).
    Useful when iterating all org WLANs without double-counting template WLANs.
    Each returned WLAN is annotated with _site_ids (list of sites it applies to).
    """
    seen: dict[str, dict] = {}
    for sid, wlan_list in site_wlan_map.items():
        for w in wlan_list:
            wlan_id = w.get("id")
            if not wlan_id:
                continue
            if wlan_id not in seen:
                w["_site_ids"] = []
                seen[wlan_id] = w
            site_ids = seen[wlan_id].setdefault("_site_ids", [])
            if sid not in site_ids:
                site_ids.append(sid)
    return list(seen.values())
