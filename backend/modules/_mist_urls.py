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
