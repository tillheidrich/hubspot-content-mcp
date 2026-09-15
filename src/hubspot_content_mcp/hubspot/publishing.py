"""Publishing and scheduling. Only reachable when ALLOW_PUBLISH is set.

This module is imported and registered conditionally. With the default
configuration it is never loaded, so the publish tools do not appear in the
tool list at all and no amount of prompting can reach them.

First publish is not the same call as republish
-----------------------------------------------
HubSpot documents this explicitly and it is easy to get wrong:

  "This endpoint accepts no payload and will only update an already
   published page, not publish a drafted page."   — CMS Pages guide, on push-live

So:

  Pages, never published   → PATCH {publishImmediately: true}, then POST /schedule
  Pages, already published → POST {id}/draft/push-live
  Posts, never published   → PATCH {id} with state=PUBLISHED (+ required fields)
  Posts, already published → POST {id}/draft/push-live

Scheduling is the same `/schedule` endpoint for both, with the ID in the body
rather than the path.

Cancelling a schedule has no v3 endpoint at all — the only documented route is
the legacy v2 Content API's publish-action.
"""

from __future__ import annotations

from typing import Any, Literal

from .client import HubSpotClient, path_segment
from .pages import PageType, _base_for

# States HubSpot uses for content that is live or queued to go live.
LIVE_STATES = frozenset(
    {
        "PUBLISHED",
        "PUBLISHED_OR_SCHEDULED",
        "PUBLISHED_AB",
        "SCHEDULED",
        "SCHEDULED_AB",
    }
)

# Fields HubSpot requires on a blog post before it will accept state=PUBLISHED.
POST_PUBLISH_REQUIREMENTS = (
    ("name", "a title"),
    ("contentGroupId", "a parent blog (contentGroupId)"),
    ("slug", "a real slug, not the auto-assigned temporary one"),
    ("blogAuthorId", "an author (blogAuthorId)"),
    ("metaDescription", "a meta description"),
)


def is_live(obj: dict[str, Any]) -> bool:
    """True when the object has a published or scheduled version."""
    for key in ("currentState", "state"):
        value = obj.get(key)
        if isinstance(value, str) and value.upper() in LIVE_STATES:
            return True
    return bool(obj.get("publishDate")) and bool(obj.get("isPublished"))


def missing_post_publish_fields(post: dict[str, Any]) -> list[str]:
    """Which of HubSpot's publish preconditions this post does not meet."""
    missing = []
    for key, description in POST_PUBLISH_REQUIREMENTS:
        if not post.get(key):
            missing.append(description)
    if not post.get("featuredImage") and post.get("useFeaturedImage") is not False:
        missing.append("either a featuredImage, or useFeaturedImage set to false")
    return missing


# --- pages ------------------------------------------------------------------


def push_page_live(client: HubSpotClient, page_type: PageType, page_id: str) -> None:
    """Push draft changes onto an already-published page. 204, no body."""
    pid = path_segment(page_id, field="page_id")
    client.post(f"{_base_for(page_type)}/{pid}/draft/push-live")


def schedule_page(
    client: HubSpotClient,
    page_type: PageType,
    page_id: str,
    *,
    publish_at: str,
) -> None:
    """Schedule a page. The ID goes in the body, not the path. 204, no body."""
    client.post(
        f"{_base_for(page_type)}/schedule",
        json_body={
            "id": path_segment(page_id, field="page_id"),
            "publishDate": publish_at,
        },
    )


def set_page_publish_immediately(
    client: HubSpotClient, page_type: PageType, page_id: str
) -> dict[str, Any]:
    """Mark a page to go live as soon as /schedule is called.

    This is the only documented way to publish a page that has never been
    published — push-live refuses those.
    """
    pid = path_segment(page_id, field="page_id")
    return client.patch(f"{_base_for(page_type)}/{pid}", json_body={"publishImmediately": True})


# --- blog posts -------------------------------------------------------------


def push_post_live(client: HubSpotClient, post_id: str) -> None:
    """Push draft changes onto an already-published post. 204, no body."""
    pid = path_segment(post_id, field="post_id")
    client.post(f"/cms/v3/blogs/posts/{pid}/draft/push-live")


def publish_post_first_time(client: HubSpotClient, post_id: str) -> dict[str, Any]:
    """Publish a post that has never been live, via state=PUBLISHED."""
    pid = path_segment(post_id, field="post_id")
    return client.patch(f"/cms/v3/blogs/posts/{pid}", json_body={"state": "PUBLISHED"})


def schedule_post(client: HubSpotClient, post_id: str, *, publish_at: str) -> None:
    """Schedule a post. ID in the body. 204, no body."""
    client.post(
        "/cms/v3/blogs/posts/schedule",
        json_body={
            "id": path_segment(post_id, field="post_id"),
            "publishDate": publish_at,
        },
    )


# --- cancelling a schedule --------------------------------------------------

ContentKind = Literal["page", "post"]


def cancel_scheduled_publish(client: HubSpotClient, kind: ContentKind, content_id: str) -> None:
    """Cancel a pending scheduled publish.

    There is no v3 endpoint for this; the legacy v2 Content API is the only
    documented route. Whether it reliably cancels a schedule created through
    the v3 /schedule endpoint is not stated by HubSpot — verify the result in
    the UI.
    """
    cid = path_segment(content_id, field="content_id")
    segment = "pages" if kind == "page" else "blog-posts"
    client.post(
        f"/content/api/v2/{segment}/{cid}/publish-action",
        json_body={"action": "cancel-publish"},
    )
