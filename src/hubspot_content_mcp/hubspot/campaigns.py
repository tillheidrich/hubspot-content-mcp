"""Marketing campaigns — the layer that turns loose assets into a plan.

Endpoints used:
  GET    /marketing/v3/campaigns
  GET    /marketing/v3/campaigns/{id}
  POST   /marketing/v3/campaigns
  PATCH  /marketing/v3/campaigns/{id}
  GET    /marketing/v3/campaigns/{id}/assets/{assetType}
  PUT    /marketing/v3/campaigns/{id}/assets/{assetType}/{assetId}
  DELETE /marketing/v3/campaigns/{id}/assets/{assetType}/{assetId}

A campaign carries no personal data of its own: it is a name, a budget, a
date range and a set of asset IDs. It sits on the content side of the
boundary for that reason, and needs no ALLOW_CRM.
"""

from __future__ import annotations

from typing import Any

from .client import HubSpotClient, path_segment

BASE = "/marketing/v3/campaigns"

# Asset types HubSpot lets you attach. The names are HubSpot's own.
ASSET_TYPES = (
    "BLOG_POST",
    "EMAIL",
    "FORM",
    "LANDING_PAGE",
    "SITE_PAGE",
    "SOCIAL_BROADCAST",
    "AD_CAMPAIGN",
    "CTA",
    "OBJECT_LIST",
    "WORKFLOW",
    "EXTERNAL_WEB_URL",
)

# Properties worth returning by default. Campaigns carry a long tail of
# computed metrics; asking for everything makes the response unreadable.
DEFAULT_PROPERTIES = (
    "hs_name",
    "hs_start_date",
    "hs_end_date",
    "hs_goal",
    "hs_budget_items_sum_amount",
    "hs_owner",
)


def list_campaigns(
    client: HubSpotClient,
    *,
    limit: int = 20,
    after: str | None = None,
    properties: list[str] | None = None,
    sort: str | None = None,
) -> dict[str, Any]:
    params: dict[str, Any] = {
        "limit": min(max(int(limit), 1), 100),
        "properties": ",".join(properties or DEFAULT_PROPERTIES),
    }
    if after:
        params["after"] = after
    if sort:
        params["sort"] = sort
    return client.get(BASE, params=params)


def get_campaign(
    client: HubSpotClient, campaign_id: str, *, properties: list[str] | None = None
) -> dict[str, Any]:
    cid = path_segment(campaign_id, field="campaign_id")
    return client.get(
        f"{BASE}/{cid}",
        params={"properties": ",".join(properties or DEFAULT_PROPERTIES)},
    )


def create_campaign(client: HubSpotClient, properties: dict[str, Any]) -> dict[str, Any]:
    """`hs_name` is the only required property."""
    return client.post(BASE, json_body={"properties": properties})


def update_campaign(
    client: HubSpotClient, campaign_id: str, properties: dict[str, Any]
) -> dict[str, Any]:
    cid = path_segment(campaign_id, field="campaign_id")
    return client.patch(f"{BASE}/{cid}", json_body={"properties": properties})


def list_campaign_assets(
    client: HubSpotClient, campaign_id: str, asset_type: str, *, limit: int = 100
) -> dict[str, Any]:
    cid = path_segment(campaign_id, field="campaign_id")
    at = path_segment(asset_type, field="asset_type")
    return client.get(f"{BASE}/{cid}/assets/{at}", params={"limit": min(max(int(limit), 1), 100)})


def attach_asset(client: HubSpotClient, campaign_id: str, asset_type: str, asset_id: str) -> Any:
    cid = path_segment(campaign_id, field="campaign_id")
    at = path_segment(asset_type, field="asset_type")
    aid = path_segment(asset_id, field="asset_id")
    return client.put(f"{BASE}/{cid}/assets/{at}/{aid}")


def detach_asset(client: HubSpotClient, campaign_id: str, asset_type: str, asset_id: str) -> Any:
    cid = path_segment(campaign_id, field="campaign_id")
    at = path_segment(asset_type, field="asset_type")
    aid = path_segment(asset_id, field="asset_id")
    return client.delete(f"{BASE}/{cid}/assets/{at}/{aid}")
