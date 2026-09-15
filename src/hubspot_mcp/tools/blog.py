"""MCP tools for blog posts and blog instances. Drafts only."""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from ..config import build_edit_url
from ..hubspot import blog as hub_blog
from ..models.common import blog_post_summary, wrap_untrusted
from .pages import validate_slug


def register(mcp: FastMCP, context: dict[str, Any]) -> None:
    client = context["client"]
    settings = context["settings"]
    portal = settings.hubspot_portal_id

    @mcp.tool()
    def list_blogs() -> list[dict[str, Any]]:
        """List the blog instances in the portal, e.g. a marketing blog and a tech blog.

        Use this first to get the `blog_id` that create_blog_post_draft needs.
        """
        rows = hub_blog.list_blogs(client)
        return [
            {
                "id": str(b.get("id", "")),
                "name": b.get("name") or b.get("htmlTitle"),
                "url": b.get("absoluteUrl") or b.get("rootUrl"),
                "language": b.get("language"),
            }
            for b in rows
        ]

    @mcp.tool()
    def list_blog_posts(
        name_contains: str | None = None,
        blog_id: str | None = None,
        state: str = "ANY",
        language: str | None = None,
        updated_after: str | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        """List blog posts.

        Args:
          name_contains: case-insensitive substring of the post title.
          blog_id: restrict to one blog instance — see list_blogs.
          state: ANY | DRAFT | PUBLISHED | SCHEDULED. Default ANY.
          language: ISO 639-1 code.
          updated_after: ISO 8601 timestamp.
          limit: maximum results, 1-100. Default 20.
        """
        rows, truncated = hub_blog.list_blog_posts(
            client,
            name_contains=name_contains,
            blog_id=blog_id,
            state=state,
            language=language,
            updated_after=updated_after,
            limit=limit,
        )
        out: dict[str, Any] = {
            "results": [blog_post_summary(r, portal_id=portal) for r in rows],
            "count": len(rows),
        }
        if truncated:
            out["note"] = "Search stopped early — there may be more matches."
        return out

    @mcp.tool()
    def get_blog_post(
        post_id: str, include_content: bool = False, draft: bool = True
    ) -> dict[str, Any]:
        """Fetch one blog post.

        Args:
          post_id: HubSpot blog post ID.
          include_content: set True to include the full postBody HTML.
            Post bodies are large — leave this off unless you need to edit them.
          draft: True (default) reads the draft version, False reads live.
        """
        raw = hub_blog.get_blog_post(client, post_id, draft=draft)
        if include_content:
            return wrap_untrusted(raw, kind="blog-post")
        summary = blog_post_summary(raw, portal_id=portal)
        summary["meta_description"] = raw.get("metaDescription")
        summary["version"] = "draft" if draft else "live"
        summary["note"] = "Call again with include_content=True to see the post body."
        return summary

    @mcp.tool()
    def create_blog_post_draft(
        blog_id: str,
        title: str,
        slug: str,
        content_html: str,
        meta_description: str | None = None,
        language: str = "en",
        tag_ids: list[str] | None = None,
        featured_image_url: str | None = None,
        author_id: str | None = None,
    ) -> dict[str, Any]:
        """Create a new blog post in DRAFT state.

        Args:
          blog_id: target blog instance — see list_blogs.
          title: post title.
          slug: URL slug. Lowercase, hyphens, no leading slash.
          content_html: the post body as HTML.
          meta_description: SEO meta description.
          language: ISO 639-1 code. Default 'en'.
          tag_ids: HubSpot blog tag IDs.
          featured_image_url: absolute URL of an image hosted in HubSpot.
          author_id: blog author ID — see list_blog_authors.
        """
        payload: dict[str, Any] = {
            "contentGroupId": blog_id,
            "name": title,
            "htmlTitle": title,
            "slug": validate_slug(slug),
            "postBody": content_html,
            "language": language,
        }
        if meta_description:
            payload["metaDescription"] = meta_description
        if tag_ids:
            payload["tagIds"] = tag_ids
        if featured_image_url:
            payload["featuredImage"] = featured_image_url
            payload["useFeaturedImage"] = True
        if author_id:
            payload["blogAuthorId"] = author_id

        created = hub_blog.create_blog_post(client, payload)
        return blog_post_summary(created, portal_id=portal)

    @mcp.tool()
    def update_blog_post_draft(post_id: str, fields: dict[str, Any]) -> dict[str, Any]:
        """Patch a blog post's DRAFT. The published version is never touched.

        Args:
          post_id: HubSpot blog post ID.
          fields: any of name, htmlTitle, slug, postBody, postSummary,
            metaDescription, language, tagIds, featuredImage, blogAuthorId.

        Fields that could publish or schedule the post are refused and listed
        in `rejected_fields`.
        """
        if "slug" in fields:
            fields = {**fields, "slug": validate_slug(str(fields["slug"]))}
        safe, rejected = hub_blog.sanitize_post_fields(
            fields, allow_raw_html=settings.allow_raw_html
        )
        if not safe:
            raise ValueError(
                f"No writable fields supplied. Rejected: {rejected or list(fields)}. "
                f"Allowed: {sorted(hub_blog.ALLOWED_POST_FIELDS)}"
            )
        updated = hub_blog.update_blog_post_draft(client, post_id, safe)
        out = blog_post_summary(updated, portal_id=portal)
        out["updated_fields"] = sorted(safe)
        if rejected:
            out["rejected_fields"] = rejected
        return out

    @mcp.tool()
    def reset_blog_post_draft(post_id: str) -> dict[str, Any]:
        """Discard draft changes on a blog post and restore the live version.

        DESTRUCTIVE and irreversible. Confirm with the user before calling.
        """
        hub_blog.reset_post_draft(client, post_id)
        return {
            "id": post_id,
            "reset": True,
            "edit_url": build_edit_url("blog-post", post_id, portal),
        }
