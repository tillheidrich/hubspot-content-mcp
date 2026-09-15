"""Discovery tools: templates, domains, blog authors."""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from ..hubspot import discovery as hub_discovery


def register(mcp: FastMCP, context: dict[str, Any]) -> None:
    client = context["client"]

    @mcp.tool()
    def list_templates(limit: int = 100) -> list[dict[str, Any]]:
        """List CMS templates available in the portal.

        Use this to find the `template_path` that the page and email create
        tools need. If it returns an error about the Design Manager API, copy
        the path from Design Manager in the HubSpot UI instead.

        Args:
          limit: maximum results, 1-100. Default 100.
        """
        rows = hub_discovery.list_templates(client, limit=limit)
        return [
            {
                "id": str(t.get("id", "")),
                "path": t.get("path") or t.get("templatePath"),
                "label": t.get("label") or t.get("filename") or t.get("name"),
                "template_type": t.get("template_type") or t.get("templateType"),
                "is_available_for_new_content": t.get("is_available_for_new_content"),
            }
            for t in rows
        ]

    @mcp.tool()
    def list_domains(limit: int = 100) -> list[dict[str, Any]]:
        """List domains connected to the portal.

        Useful when a portal serves several domains and a page needs an
        explicit `domain` on creation.

        Args:
          limit: maximum results, 1-100. Default 100.
        """
        rows = hub_discovery.list_domains(client, limit=limit)
        return [
            {
                "id": str(d.get("id", "")),
                "domain": d.get("domain"),
                "is_primary_landing_page": bool(d.get("isPrimaryLandingPage")),
                "is_primary_site_page": bool(d.get("isPrimarySitePage")),
                "is_primary_blog_post": bool(d.get("isPrimaryBlogPost")),
                "is_resolving": bool(d.get("isResolving")),
                "is_ssl_enabled": bool(d.get("isSslEnabled")),
            }
            for d in rows
        ]

    @mcp.tool()
    def list_blog_authors(limit: int = 100) -> list[dict[str, Any]]:
        """List blog authors, for setting `author_id` on a blog post draft.

        Args:
          limit: maximum results, 1-100. Default 100.
        """
        rows = hub_discovery.list_authors(client, limit=limit)
        return [
            {
                "id": str(a.get("id", "")),
                "name": a.get("displayName") or a.get("fullName") or a.get("name"),
                "email": a.get("email"),
                "slug": a.get("slug"),
            }
            for a in rows
        ]
