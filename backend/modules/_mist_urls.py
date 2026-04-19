"""
Mist portal deep-link builders.

Every helper takes `portal_base` as the first argument so URLs are built
for the correct Mist cloud (global / EMEA / APAC). portal_base is sourced
from MistClient.portal_base, which is derived from the session's api_base
during the cloud auto-detect probe in routers/credentials.py.

URL anchor patterns verified against live Mist portal sessions on
2026-04-16. If Mist changes their SPA routing these helpers are the
single place to update.
"""


def _url(portal_base: str, anchor: str) -> str:
    return f"{portal_base}/admin/?org_id={{org_id}}#!{anchor}".replace(
        "{org_id}", ""  # placeholder removed inside formatters that accept org_id
    )


def org_config_url(portal_base: str, org_id: str, site_id: str | None = None) -> str:
    """
    Organization Configuration page. With site_id, deep-links to that
    specific site's configuration view. Without, lands on the site list.
    """
    if site_id:
        return f"{portal_base}/admin/?org_id={org_id}#!configuration/{site_id}"
    return f"{portal_base}/admin/?org_id={org_id}#!configuration"


def rf_template_url(portal_base: str, org_id: str, template_id: str) -> str:
    return f"{portal_base}/admin/?org_id={org_id}#!rftemplates/rfTemplate/{template_id}"


def marvis_actions_url(portal_base: str, org_id: str) -> str:
    return f"{portal_base}/admin/?org_id={org_id}#!virtualAssistant/action"


def ap_detail_url(portal_base: str, org_id: str, device_id: str, site_id: str) -> str:
    """
    AP detail page. Requires Mist device_id (UUID) — NOT the MAC. The
    device_id is available on each record returned by /orgs/{org_id}/inventory.
    """
    return f"{portal_base}/admin/?org_id={org_id}#!ap/detail/{device_id}/{site_id}"


def subscriptions_url(portal_base: str, org_id: str) -> str:
    return f"{portal_base}/admin/?org_id={org_id}#!subscription"


def nac_policies_url(portal_base: str, org_id: str) -> str:
    return f"{portal_base}/admin/?org_id={org_id}#!nacPolicy"


def templates_url(portal_base: str, org_id: str) -> str:
    """
    WLAN Templates landing page. Best destination for findings that relate
    to SSID/PSK configuration defined at the template level (vs per-site
    overrides), since that's where PSKs and shared SSID settings live.
    """
    return f"{portal_base}/admin/?org_id={org_id}#!templates"


def wlan_template_url(portal_base: str, org_id: str, template_id: str) -> str:
    """
    Direct link to a specific WLAN template. Use for template-pushed WLANs
    where the fix lives in the org-level template, not the site config.
    Lands on the template page where the operator selects the specific WLAN.
    """
    return f"{portal_base}/admin/?org_id={org_id}#!templates/template/{template_id}"


def wlan_url(portal_base: str, org_id: str, wlan_id: str, site_id: str) -> str:
    """
    Direct link to a site-local WLAN edit page.
    Use for WLANs configured directly at the site level (not template-pushed).
    """
    return f"{portal_base}/admin/?org_id={org_id}#!wlan/detail/{wlan_id}/{site_id}"


_NULL_SITE_ID = "00000000-0000-0000-0000-000000000000"


def wlan_fix_url(portal_base: str, org_id: str, wlan: dict) -> str | None:
    """
    Smart WLAN fix URL: routes to the right page based on whether the WLAN
    is site-local or template-pushed.

    - Site-local  (site_id != null UUID): links directly to the WLAN edit page
    - Template-pushed (site_id == null UUID): links to the specific template page
    - No template_id available: falls back to the templates list page

    Expects wlan dict to carry _site_id annotation (set by SecureScope/ConfigDrift
    when iterating derived WLANs).
    """
    wlan_site_id   = wlan.get("site_id", _NULL_SITE_ID) or _NULL_SITE_ID
    wlan_id        = wlan.get("id", "")
    template_id    = wlan.get("template_id", "")
    active_site_id = wlan.get("_site_id", "")

    if wlan_site_id != _NULL_SITE_ID and wlan_id and active_site_id:
        return wlan_url(portal_base, org_id, wlan_id, active_site_id)
    elif template_id:
        return wlan_template_url(portal_base, org_id, template_id)
    else:
        return templates_url(portal_base, org_id)
