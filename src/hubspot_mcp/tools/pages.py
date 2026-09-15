"""MCP tools for landing pages and site pages. Drafts only."""

from __future__ import annotations

import re
from typing import Any, Literal

from mcp.server.fastmcp import FastMCP

from ..config import build_edit_url
from ..hubspot import pages as hub_pages
from ..models.common import page_summary, wrap_untrusted

PageType = Literal["landing", "site"]

SLUG_PATTERN = re.compile(r"^[a-z0-9]+(?:[-_/][a-z0-9]+)*$")


def validate_slug(slug: str) -> str:
    """Normalize and validate a URL slug, or explain exactly what is wrong."""
    cleaned = slug.strip().strip("/")
    if not cleaned:
        raise ValueError("slug must not be empty.")
    if not SLUG_PATTERN.match(cleaned):
        raise ValueError(
            f"Invalid slug {slug!r}. Use lowercase letters, digits and hyphens, "
            f"with '/' only as a path separator — for example "
            f"'webcast-january-2026' or 'en/webcast-january-2026'. "
            f"No spaces, no uppercase, no leading slash."
        )
    return cleaned


def _build_page_payload(
    *,
    name: str,
    template_path: str,
    slug: str,
    html_title: str | None,
    meta_description: str | None,
    language: str,
    domain: str | None,
    featured_image_url: str | None,
    layout_sections: dict[str, Any] | None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "name": name,
        "templatePath": template_path,
        "slug": validate_slug(slug),
        "language": language,
    }
    if html_title:
        payload["htmlTitle"] = html_title
    if meta_description:
        payload["metaDescription"] = meta_description
    if domain:
        payload["domain"] = domain
    if featured_image_url:
        payload["featuredImage"] = featured_image_url
        payload["useFeaturedImage"] = True
    if layout_sections:
        payload["layoutSections"] = layout_sections
    return payload


def register(mcp: FastMCP, context: dict[str, Any]) -> None:
    client = context["client"]
    settings = context["settings"]
    portal = settings.hubspot_portal_id

    def _listed(rows: list[dict[str, Any]], truncated: bool, kind: str) -> dict[str, Any]:
        out: dict[str, Any] = {
            "results": [page_summary(r, kind=kind, portal_id=portal) for r in rows],
            "count": len(rows),
        }
        if truncated:
            out["note"] = (
                "Search stopped early — there may be more matches. "
                "Narrow name_contains or raise limit."
            )
        return out

    @mcp.tool()
    def list_landing_pages(
        name_contains: str | None = None,
        state: str = "ANY",
        language: str | None = None,
        updated_after: str | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        """List landing pages.

        Args:
          name_contains: case-insensitive substring of the internal page name.
            Matching happens client-side across several pages of results.
          state: ANY | DRAFT | PUBLISHED | SCHEDULED. Default ANY.
          language: ISO 639-1 code, e.g. 'de', 'en'.
          updated_after: ISO 8601 timestamp, e.g. '2026-01-01T00:00:00Z'.
          limit: maximum number of results, 1-100. Default 20.

        Returns a dict with `results`, `count`, and optionally a `note` when the
        search was cut short.
        """
        rows, truncated = hub_pages.list_pages(
            client,
            "landing",
            name_contains=name_contains,
            state=state,
            language=language,
            updated_after=updated_after,
            limit=limit,
        )
        return _listed(rows, truncated, "landing-page")

    @mcp.tool()
    def list_site_pages(
        name_contains: str | None = None,
        state: str = "ANY",
        language: str | None = None,
        updated_after: str | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        """List site pages. Same filters as list_landing_pages."""
        rows, truncated = hub_pages.list_pages(
            client,
            "site",
            name_contains=name_contains,
            state=state,
            language=language,
            updated_after=updated_after,
            limit=limit,
        )
        return _listed(rows, truncated, "site-page")

    @mcp.tool()
    def get_page(
        page_id: str,
        page_type: PageType,
        include_content: bool = False,
        draft: bool = True,
    ) -> dict[str, Any]:
        """Fetch one landing or site page.

        By default this returns a compact summary. Module content
        (`layoutSections`) is often hundreds of kilobytes, so it is omitted
        unless you ask for it.

        Args:
          page_id: HubSpot page ID.
          page_type: 'landing' or 'site'.
          include_content: set True to include layoutSections and widgets.
            Only do this when you are about to edit module content.
          draft: True (default) reads the draft version, False reads live.
        """
        kind = "landing-page" if page_type == "landing" else "site-page"
        raw = hub_pages.get_page(client, page_type, page_id, draft=draft)
        if include_content:
            return wrap_untrusted(raw, kind=kind)
        summary = page_summary(raw, kind=kind, portal_id=portal)
        summary["template_path"] = raw.get("templatePath")
        summary["version"] = "draft" if draft else "live"
        summary["note"] = "Call again with include_content=True to see module content."
        return summary

    @mcp.tool()
    def create_landing_page_draft(
        name: str,
        template_path: str,
        slug: str,
        html_title: str | None = None,
        meta_description: str | None = None,
        language: str = "en",
        domain: str | None = None,
        featured_image_url: str | None = None,
        layout_sections: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create a new landing page in DRAFT state.

        Args:
          name: internal page name shown in the HubSpot listing.
          template_path: from list_templates, e.g. '@marketplace/theme/templates/page.html'.
          slug: URL slug. Lowercase, hyphens, no leading slash.
          html_title: contents of the <title> tag.
          meta_description: SEO meta description.
          language: ISO 639-1 code. Default 'en'.
          domain: only needed when the portal has several; otherwise the default is used.
          featured_image_url: absolute URL of an image already hosted in HubSpot.
          layout_sections: pre-built layoutSections payload for module content.
        """
        payload = _build_page_payload(
            name=name,
            template_path=template_path,
            slug=slug,
            html_title=html_title,
            meta_description=meta_description,
            language=language,
            domain=domain,
            featured_image_url=featured_image_url,
            layout_sections=layout_sections,
        )
        created = hub_pages.create_page(client, "landing", payload)
        return page_summary(created, kind="landing-page", portal_id=portal)

    @mcp.tool()
    def create_site_page_draft(
        name: str,
        template_path: str,
        slug: str,
        html_title: str | None = None,
        meta_description: str | None = None,
        language: str = "en",
        domain: str | None = None,
        featured_image_url: str | None = None,
        layout_sections: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create a new site page in DRAFT state. Same arguments as create_landing_page_draft."""
        payload = _build_page_payload(
            name=name,
            template_path=template_path,
            slug=slug,
            html_title=html_title,
            meta_description=meta_description,
            language=language,
            domain=domain,
            featured_image_url=featured_image_url,
            layout_sections=layout_sections,
        )
        created = hub_pages.create_page(client, "site", payload)
        return page_summary(created, kind="site-page", portal_id=portal)

    @mcp.tool()
    def update_page_draft(
        page_id: str,
        page_type: PageType,
        fields: dict[str, Any],
    ) -> dict[str, Any]:
        """Patch a page's DRAFT. The published version is never touched.

        Args:
          page_id: HubSpot page ID.
          page_type: 'landing' or 'site'.
          fields: any of name, slug, htmlTitle, metaDescription, language,
            featuredImage, useFeaturedImage, layoutSections, widgets,
            headHtml, footerHtml, domain.

        Any field that could publish or schedule the page is refused and
        reported back in `rejected_fields` rather than silently dropped.

        Writing layoutSections or widgets: fetch the page with
        include_content=True first, edit values inside the tree you got
        back, and send the whole tree. HubSpot accepts nothing smaller, and
        a tree you assembled yourself will not open in the drag-and-drop
        editor even when it renders correctly on the live site.

        Inside a rich-text module, keep to headings, paragraphs, lists,
        links and emphasis. Layout HTML — grid divs, columns, inline
        styles, custom classes — turns the module into one block a marketer
        cannot edit, drops the theme's spacing and typography, and may be
        stripped the next time someone saves in HubSpot. Layout belongs to
        modules and rows, not to markup.
        """
        if "slug" in fields:
            fields = {**fields, "slug": validate_slug(str(fields["slug"]))}
        safe, rejected = hub_pages.sanitize_page_fields(
            fields, allow_raw_html=settings.allow_raw_html
        )
        if not safe:
            raise ValueError(
                f"No writable fields supplied. Rejected: {rejected or list(fields)}. "
                f"Allowed: {sorted(hub_pages.ALLOWED_PAGE_FIELDS)}"
            )
        kind = "landing-page" if page_type == "landing" else "site-page"
        updated = hub_pages.update_page_draft(client, page_type, page_id, safe)
        out = page_summary(updated, kind=kind, portal_id=portal)
        out["updated_fields"] = sorted(safe)
        if rejected:
            out["rejected_fields"] = rejected
            out["note"] = (
                "These fields were not applied — they are either unknown or would "
                "change publication state, which this server does not allow."
            )
        return out

    @mcp.tool()
    def reset_draft(page_id: str, page_type: PageType) -> dict[str, Any]:
        """Discard draft changes and restore the draft to match the live version.

        DESTRUCTIVE and irreversible: any unpublished edits are lost. Confirm
        with the user before calling this.

        Args:
          page_id: HubSpot page ID.
          page_type: 'landing' or 'site'.
        """
        hub_pages.reset_draft(client, page_type, page_id)
        kind = "landing-page" if page_type == "landing" else "site-page"
        return {
            "id": page_id,
            "page_type": page_type,
            "reset": True,
            "edit_url": build_edit_url(kind, page_id, portal),
        }

    @mcp.tool()
    def duplicate_page(
        source_id: str,
        source_type: PageType,
        new_name: str,
        new_slug: str | None = None,
        overrides: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Duplicate an existing page as a new DRAFT, optionally applying overrides.

        The workhorse for "take last quarter's webcast page and make this
        quarter's version out of it".

        Args:
          source_id: ID of the page to copy.
          source_type: 'landing' or 'site'.
          new_name: internal name for the copy.
          new_slug: URL slug for the copy. HubSpot derives one if omitted.
          overrides: fields to change on the copy — same keys as update_page_draft,
            e.g. {"htmlTitle": "...", "metaDescription": "...", "layoutSections": {...}}.
        """
        cloned = hub_pages.clone_page(client, source_type, source_id, clone_name=new_name)
        if not isinstance(cloned, dict) or not cloned.get("id"):
            raise RuntimeError(
                f"HubSpot returned no page ID when cloning {source_id}. Response: {cloned!r}"
            )
        new_id = str(cloned["id"])

        patch: dict[str, Any] = {"name": new_name}
        if new_slug:
            patch["slug"] = validate_slug(new_slug)
        rejected: list[str] = []
        if overrides:
            extra, rejected = hub_pages.sanitize_page_fields(
                overrides, allow_raw_html=settings.allow_raw_html
            )
            patch.update(extra)

        cloned = hub_pages.update_page_draft(client, source_type, new_id, patch)

        kind = "landing-page" if source_type == "landing" else "site-page"
        out = page_summary(cloned, kind=kind, portal_id=portal)
        out["source_id"] = source_id
        if rejected:
            out["rejected_fields"] = rejected
        return out

    @mcp.tool()
    def create_language_variant(
        source_id: str,
        source_type: PageType,
        target_language: str,
        slug_override: str | None = None,
        layout_sections_override: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create a language variant of an existing page, e.g. EN from a DE page.

        The variant joins the source's multi-language group, so HubSpot's
        language switcher picks it up. Translate the copy yourself and pass it
        via layout_sections_override — this tool does not translate.

        Args:
          source_id: source page ID.
          source_type: 'landing' or 'site'.
          target_language: ISO 639-1 code, e.g. 'en'.
          slug_override: explicit slug for the variant.
          layout_sections_override: translated module content to apply.
        """
        variant = hub_pages.create_language_variation(
            client, source_type, source_id=source_id, target_language=target_language
        )
        if not isinstance(variant, dict) or not variant.get("id"):
            raise RuntimeError(
                f"HubSpot returned no page ID for the language variant. Response: {variant!r}"
            )
        variant_id = str(variant["id"])

        patch: dict[str, Any] = {}
        if slug_override:
            patch["slug"] = validate_slug(slug_override)
        if layout_sections_override:
            patch["layoutSections"] = layout_sections_override
        if patch:
            variant = hub_pages.update_page_draft(client, source_type, variant_id, patch)

        kind = "landing-page" if source_type == "landing" else "site-page"
        out = page_summary(variant, kind=kind, portal_id=portal)
        out["source_id"] = source_id
        out["target_language"] = target_language
        return out
