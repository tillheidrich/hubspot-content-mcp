"""Blog posts and blog instances.

Endpoints used:
  GET   /cms/v3/blogs/posts
  GET   /cms/v3/blogs/posts/{id}
  GET   /cms/v3/blogs/posts/{id}/draft
  POST  /cms/v3/blogs/posts
  PATCH /cms/v3/blogs/posts/{id}/draft        ← draft buffer, never live
  POST  /cms/v3/blogs/posts/{id}/draft/reset
  GET   /cms/v3/blog-settings/settings        (blog instances)
"""

from __future__ import annotations

from typing import Any

from .client import HubSpotClient, path_segment
from .pages import FORBIDDEN_FIELDS, MAX_SEARCH_PAGES, STATE_FILTERS

ALLOWED_POST_FIELDS = frozenset(
    {
        "name",
        "htmlTitle",
        "slug",
        "postBody",
        "postSummary",
        "metaDescription",
        "language",
        "tagIds",
        "featuredImage",
        "featuredImageAltText",
        "useFeaturedImage",
        "blogAuthorId",
        "contentGroupId",
    }
)

RAW_HTML_FIELDS = frozenset({"headHtml", "footerHtml"})


def sanitize_post_fields(
    fields: dict[str, Any], *, allow_raw_html: bool = False
) -> tuple[dict[str, Any], list[str]]:
    writable = ALLOWED_POST_FIELDS | (RAW_HTML_FIELDS if allow_raw_html else frozenset())
    accepted: dict[str, Any] = {}
    rejected: list[str] = []
    for key, value in fields.items():
        if key in FORBIDDEN_FIELDS or key not in writable:
            rejected.append(key)
        else:
            accepted[key] = value
    return accepted, sorted(rejected)


def _title_of(row: dict[str, Any]) -> str:
    return (row.get("name") or row.get("htmlTitle") or "").lower()


def list_blog_posts(
    client: HubSpotClient,
    *,
    name_contains: str | None = None,
    blog_id: str | None = None,
    state: str | None = None,
    language: str | None = None,
    updated_after: str | None = None,
    limit: int = 20,
    archived: bool = False,
) -> tuple[list[dict[str, Any]], bool]:
    """List blog posts. Returns (results, search_truncated)."""
    wanted = max(1, min(limit, 100))
    params: dict[str, Any] = {"limit": 100 if name_contains else wanted, "archived": archived}

    if state and state.upper() != "ANY":
        try:
            params["state__in"] = STATE_FILTERS[state.upper()]
        except KeyError:
            raise ValueError(
                f"state must be one of ANY, DRAFT, PUBLISHED, SCHEDULED — got {state!r}"
            ) from None
    if language:
        params["language__in"] = language
    if updated_after:
        params["updatedAt__gte"] = updated_after
    if blog_id:
        params["contentGroupId"] = blog_id

    if not name_contains:
        data = client.get("/cms/v3/blogs/posts", params=params)
        return (data.get("results", []) if isinstance(data, dict) else []), False

    needle = name_contains.lower()
    matches: list[dict[str, Any]] = []
    after: str | None = None

    for _ in range(MAX_SEARCH_PAGES):
        page_params = dict(params)
        if after:
            page_params["after"] = after
        data = client.get("/cms/v3/blogs/posts", params=page_params)
        if not isinstance(data, dict):
            break

        for row in data.get("results", []):
            if needle in _title_of(row):
                matches.append(row)
                if len(matches) >= wanted:
                    return matches, True

        after = (data.get("paging") or {}).get("next", {}).get("after")
        if not after:
            return matches, False

    return matches, True


def get_blog_post(client: HubSpotClient, post_id: str, *, draft: bool = False) -> dict[str, Any]:
    suffix = "/draft" if draft else ""
    pid = path_segment(post_id, field="post_id")
    return client.get(f"/cms/v3/blogs/posts/{pid}{suffix}")


def create_blog_post(client: HubSpotClient, payload: dict[str, Any]) -> dict[str, Any]:
    body = {k: v for k, v in payload.items() if k not in FORBIDDEN_FIELDS}
    body["state"] = "DRAFT"
    return client.post("/cms/v3/blogs/posts", json_body=body)


def update_blog_post_draft(
    client: HubSpotClient, post_id: str, patch: dict[str, Any]
) -> dict[str, Any]:
    """PATCH the draft buffer. The live post is untouched."""
    safe = {k: v for k, v in patch.items() if k not in FORBIDDEN_FIELDS}
    pid = path_segment(post_id, field="post_id")
    return client.patch(f"/cms/v3/blogs/posts/{pid}/draft", json_body=safe)


def reset_post_draft(client: HubSpotClient, post_id: str) -> None:
    client.post(f"/cms/v3/blogs/posts/{path_segment(post_id, field='post_id')}/draft/reset")


def list_blogs(client: HubSpotClient, *, limit: int = 50) -> list[dict[str, Any]]:
    data = client.get("/cms/v3/blog-settings/settings", params={"limit": max(1, min(limit, 100))})
    return data.get("results", []) if isinstance(data, dict) else []
