"""CMS pages — landing pages and site pages.

Endpoints used:
  GET   /cms/v3/pages/{landing-pages,site-pages}
  GET   /cms/v3/pages/{...}/{id}
  GET   /cms/v3/pages/{...}/{id}/draft
  POST  /cms/v3/pages/{...}
  PATCH /cms/v3/pages/{...}/{id}/draft          ← draft buffer, never live
  POST  /cms/v3/pages/{...}/{id}/draft/reset
  POST  /cms/v3/pages/{...}/clone
  POST  /cms/v3/pages/{...}/multi-language/create-language-variation

Why the /draft suffix matters
-----------------------------
PATCH on the bare object edits the *live* version of a published page.
PATCH on {id}/draft edits the draft buffer only; HubSpot seeds the buffer
from the live version if none exists. Every write in this module targets
the draft.
"""

from __future__ import annotations

from typing import Any, Literal

from .client import HubSpotClient, HubSpotError, path_segment

PageType = Literal["landing", "site"]

# HubSpot has no plain PUBLISHED / SCHEDULED state. These are the real values,
# grouped into the three buckets a caller is likely to mean.
STATE_FILTERS: dict[str, str] = {
    "DRAFT": "DRAFT,DRAFT_AB,DRAFT_AB_VARIANT,LOSER_AB_VARIANT",
    "PUBLISHED": "PUBLISHED_OR_SCHEDULED,PUBLISHED_AB",
    "SCHEDULED": "PUBLISHED_OR_SCHEDULED,SCHEDULED_AB",
}

# Fields a caller may write to a page draft. Anything outside this set is
# refused, which is how the drafts-only promise survives a free-form dict.
ALLOWED_PAGE_FIELDS = frozenset(
    {
        "name",
        "slug",
        "htmlTitle",
        "metaDescription",
        "language",
        "featuredImage",
        "featuredImageAltText",
        "useFeaturedImage",
        "layoutSections",
        "widgets",
        "widgetContainers",
        "domain",
    }
)

# Raw <head>/<footer> HTML is injected verbatim into every render of the page.
# A one-line <script> there is persistent XSS on the customer's marketing
# domain, and it is exactly the kind of thing a human reviewer skims past
# while checking the copy. Off unless the operator sets ALLOW_RAW_HTML.
RAW_HTML_FIELDS = frozenset({"headHtml", "footerHtml"})

# Never accepted on any write, even if someone adds them to the allow-list.
FORBIDDEN_FIELDS = frozenset(
    {
        "state",
        "currentState",
        "publishDate",
        "publishImmediately",
        "publishedAt",
        "isPublished",
        "scheduledUpdateDate",
        "archived",
        "archivedAt",
        "id",
        # Access control, not content. Flipping these exposes a gated page.
        "publicAccessRulesEnabled",
        "publicAccessRules",
        "password",
    }
)

MAX_SEARCH_PAGES = 10  # cursor pages to walk when filtering by name


def _base_for(page_type: PageType) -> str:
    if page_type == "landing":
        return "/cms/v3/pages/landing-pages"
    if page_type == "site":
        return "/cms/v3/pages/site-pages"
    raise ValueError(f"page_type must be 'landing' or 'site', got {page_type!r}")


def sanitize_page_fields(
    fields: dict[str, Any], *, allow_raw_html: bool = False
) -> tuple[dict[str, Any], list[str]]:
    """Split a caller-supplied patch into (accepted, rejected-key-names)."""
    writable = ALLOWED_PAGE_FIELDS | (RAW_HTML_FIELDS if allow_raw_html else frozenset())
    accepted: dict[str, Any] = {}
    rejected: list[str] = []
    for key, value in fields.items():
        if key in FORBIDDEN_FIELDS or key not in writable:
            rejected.append(key)
        else:
            accepted[key] = value
    return accepted, sorted(rejected)


def list_pages(
    client: HubSpotClient,
    page_type: PageType,
    *,
    name_contains: str | None = None,
    state: str | None = None,
    language: str | None = None,
    updated_after: str | None = None,
    limit: int = 20,
    archived: bool = False,
) -> tuple[list[dict[str, Any]], bool]:
    """List pages. Returns (results, search_truncated).

    When name_contains is set the filter runs client-side, so we walk cursor
    pages until enough matches are found rather than filtering only the first
    page of results (which would report "not found" for anything further down).
    """
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

    if not name_contains:
        data = client.get(_base_for(page_type), params=params)
        return (data.get("results", []) if isinstance(data, dict) else []), False

    needle = name_contains.lower()
    matches: list[dict[str, Any]] = []
    after: str | None = None

    for _ in range(MAX_SEARCH_PAGES):
        page_params = dict(params)
        if after:
            page_params["after"] = after
        data = client.get(_base_for(page_type), params=page_params)
        if not isinstance(data, dict):
            break

        for row in data.get("results", []):
            if needle in (row.get("name") or "").lower():
                matches.append(row)
                if len(matches) >= wanted:
                    return matches, True

        after = (data.get("paging") or {}).get("next", {}).get("after")
        if not after:
            return matches, False

    return matches, True


def get_page(
    client: HubSpotClient,
    page_type: PageType,
    page_id: str,
    *,
    draft: bool = False,
) -> dict[str, Any]:
    suffix = "/draft" if draft else ""
    pid = path_segment(page_id, field="page_id")
    return client.get(f"{_base_for(page_type)}/{pid}{suffix}")


def create_page(
    client: HubSpotClient,
    page_type: PageType,
    payload: dict[str, Any],
) -> dict[str, Any]:
    body = {k: v for k, v in payload.items() if k not in FORBIDDEN_FIELDS}
    body["state"] = "DRAFT"
    return client.post(_base_for(page_type), json_body=body)


def update_page_draft(
    client: HubSpotClient,
    page_type: PageType,
    page_id: str,
    patch: dict[str, Any],
) -> dict[str, Any]:
    """PATCH the draft buffer. The live version is untouched."""
    safe = {k: v for k, v in patch.items() if k not in FORBIDDEN_FIELDS}
    pid = path_segment(page_id, field="page_id")
    return client.patch(f"{_base_for(page_type)}/{pid}/draft", json_body=safe)


def reset_draft(client: HubSpotClient, page_type: PageType, page_id: str) -> None:
    """Discard the draft buffer. Returns None — HubSpot answers 204."""
    client.post(f"{_base_for(page_type)}/{path_segment(page_id, field='page_id')}/draft/reset")


def clone_page(
    client: HubSpotClient,
    page_type: PageType,
    source_id: str,
    *,
    clone_name: str,
) -> dict[str, Any]:
    return client.post(
        f"{_base_for(page_type)}/clone",
        json_body={"id": path_segment(source_id, field="source_id"), "cloneName": clone_name},
    )


def create_language_variation(
    client: HubSpotClient,
    page_type: PageType,
    *,
    source_id: str,
    target_language: str,
) -> dict[str, Any]:
    """Create a language variant linked to the source's multi-language group.

    HubSpot's own docs are inconsistent about the path segment
    (create-language-variation vs create-language-variant), so try both.
    """
    body = {"id": path_segment(source_id, field="source_id"), "language": target_language}
    base = _base_for(page_type)
    try:
        return client.post(f"{base}/multi-language/create-language-variation", json_body=body)
    except HubSpotError as exc:
        if exc.status != 404:
            raise
        return client.post(f"{base}/multi-language/create-language-variant", json_body=body)
