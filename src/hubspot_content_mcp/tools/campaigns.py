"""Campaign tools — planning, not publishing.

A campaign groups assets under a name, a date range and a goal. Creating one
puts nothing in front of the public and touches no personal data, so these
tools are always registered. Taking the assets live is the publishing
module's job, and that has its own switch.
"""

from __future__ import annotations

from typing import Any

import structlog
from mcp.server.fastmcp import FastMCP

from ..config import build_edit_url
from ..hubspot import campaigns as hub_campaigns

log = structlog.get_logger("hubspot_content_mcp.campaigns")


def _summary(campaign: dict[str, Any], portal: str) -> dict[str, Any]:
    props = campaign.get("properties", {}) or {}
    cid = str(campaign.get("id", ""))
    return {
        "id": cid,
        "name": props.get("hs_name"),
        "start_date": props.get("hs_start_date"),
        "end_date": props.get("hs_end_date"),
        "goal": props.get("hs_goal"),
        "budget": props.get("hs_budget_items_sum_amount"),
        "edit_url": build_edit_url("campaign", cid, portal),
    }


def register(mcp: FastMCP, context: dict[str, Any]) -> None:
    client = context["client"]
    settings = context["settings"]
    portal = settings.hubspot_portal_id

    @mcp.tool()
    def list_campaigns(
        limit: int = 20, after: str | None = None, sort: str | None = None
    ) -> dict[str, Any]:
        """List marketing campaigns with their dates and goals.

        This is the closest thing HubSpot has to an editorial calendar that an
        API can read: campaigns carry the start and end dates, and the assets
        hang off them.

        Args:
          limit: 1-100.
          after: paging cursor from a previous call.
          sort: a property name, prefix with '-' to reverse.
        """
        data = hub_campaigns.list_campaigns(client, limit=limit, after=after, sort=sort)
        results = [_summary(c, portal) for c in data.get("results", [])]
        return {
            "count": len(results),
            "campaigns": results,
            "next_cursor": (data.get("paging") or {}).get("next", {}).get("after"),
        }

    @mcp.tool()
    def get_campaign(campaign_id: str, properties: list[str] | None = None) -> dict[str, Any]:
        """Read one campaign. Pass `properties` for metrics beyond the basics."""
        data = hub_campaigns.get_campaign(client, campaign_id, properties=properties)
        out = _summary(data, portal)
        if properties:
            out["properties"] = data.get("properties", {})
        return out

    @mcp.tool()
    def list_campaign_assets(campaign_id: str, asset_type: str) -> dict[str, Any]:
        """List the assets attached to a campaign.

        Args:
          campaign_id: the campaign.
          asset_type: one of BLOG_POST, EMAIL, FORM, LANDING_PAGE, SITE_PAGE,
            SOCIAL_BROADCAST, AD_CAMPAIGN, CTA, OBJECT_LIST, WORKFLOW,
            EXTERNAL_WEB_URL.
        """
        data = hub_campaigns.list_campaign_assets(client, campaign_id, asset_type)
        return {
            "campaign_id": campaign_id,
            "asset_type": asset_type,
            "assets": data.get("results", []),
        }

    @mcp.tool()
    def create_campaign(
        name: str,
        start_date: str | None = None,
        end_date: str | None = None,
        goal: str | None = None,
        properties: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create a campaign.

        Args:
          name: the campaign name. The only thing HubSpot requires.
          start_date: YYYY-MM-DD.
          end_date: YYYY-MM-DD.
          goal: free text.
          properties: any further hs_* properties.

        A campaign is a planning container. Nothing here goes live, and
        nothing here is visible to the public.
        """
        props: dict[str, Any] = {"hs_name": name}
        if start_date:
            props["hs_start_date"] = start_date
        if end_date:
            props["hs_end_date"] = end_date
        if goal:
            props["hs_goal"] = goal
        if properties:
            props.update(properties)
        data = hub_campaigns.create_campaign(client, props)
        log.info("campaign.created", id=data.get("id"), name=name)
        return _summary(data, portal)

    @mcp.tool()
    def update_campaign(campaign_id: str, properties: dict[str, Any]) -> dict[str, Any]:
        """Update campaign properties. Only the keys you pass change."""
        data = hub_campaigns.update_campaign(client, campaign_id, properties)
        return _summary(data, portal)

    @mcp.tool()
    def attach_asset_to_campaign(
        campaign_id: str, asset_type: str, asset_id: str
    ) -> dict[str, Any]:
        """Attach a page, post, email or form to a campaign.

        Attribution reporting keys off this, so it is worth doing at the point
        the draft is created rather than later.
        """
        hub_campaigns.attach_asset(client, campaign_id, asset_type, asset_id)
        return {
            "campaign_id": campaign_id,
            "asset_type": asset_type,
            "asset_id": asset_id,
            "attached": True,
        }

    @mcp.tool()
    def detach_asset_from_campaign(
        campaign_id: str, asset_type: str, asset_id: str
    ) -> dict[str, Any]:
        """Remove an asset from a campaign. The asset itself is untouched."""
        hub_campaigns.detach_asset(client, campaign_id, asset_type, asset_id)
        return {
            "campaign_id": campaign_id,
            "asset_type": asset_type,
            "asset_id": asset_id,
            "attached": False,
        }
