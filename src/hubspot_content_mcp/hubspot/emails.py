"""Marketing emails.

Endpoints used:
  GET   /marketing/v3/emails
  GET   /marketing/v3/emails/{id}
  GET   /marketing/v3/emails/{id}/draft
  POST  /marketing/v3/emails
  PATCH /marketing/v3/emails/{id}/draft       ← draft buffer, never live
  POST  /marketing/v3/emails/clone

Drafts only. The publish and send endpoints are deliberately not wired up.
Note that /marketing/v3/emails has no `state` query filter — it exposes
`isPublished`, `archived` and `type` instead.
"""

from __future__ import annotations

from typing import Any

from .client import HubSpotClient, path_segment
from .pages import MAX_SEARCH_PAGES

ALLOWED_EMAIL_FIELDS = frozenset(
    {
        "name",
        "subject",
        "language",
        "content",
        "from",
        "to",
        "subscriptionDetails",
        "businessUnitId",
        "campaign",
        "activeDomain",
    }
)

FORBIDDEN_EMAIL_FIELDS = frozenset(
    {
        "id",
        "state",
        "isPublished",
        "publishDate",
        "publishedAt",
        "archived",
        "archivedAt",
        "isTransactional",
    }
)


def sanitize_email_fields(fields: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    accepted: dict[str, Any] = {}
    rejected: list[str] = []
    for key, value in fields.items():
        if key in FORBIDDEN_EMAIL_FIELDS or key not in ALLOWED_EMAIL_FIELDS:
            rejected.append(key)
        else:
            accepted[key] = value
    return accepted, sorted(rejected)


def list_emails(
    client: HubSpotClient,
    *,
    name_contains: str | None = None,
    is_published: bool | None = None,
    limit: int = 20,
    archived: bool = False,
) -> tuple[list[dict[str, Any]], bool]:
    """List marketing emails. Returns (results, search_truncated)."""
    wanted = max(1, min(limit, 100))
    params: dict[str, Any] = {"limit": 100 if name_contains else wanted, "archived": archived}
    if is_published is not None:
        params["isPublished"] = is_published

    if not name_contains:
        data = client.get("/marketing/v3/emails", params=params)
        return (data.get("results", []) if isinstance(data, dict) else []), False

    needle = name_contains.lower()
    matches: list[dict[str, Any]] = []
    after: str | None = None

    for _ in range(MAX_SEARCH_PAGES):
        page_params = dict(params)
        if after:
            page_params["after"] = after
        data = client.get("/marketing/v3/emails", params=page_params)
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


def get_email(client: HubSpotClient, email_id: str, *, draft: bool = False) -> dict[str, Any]:
    suffix = "/draft" if draft else ""
    eid = path_segment(email_id, field="email_id")
    return client.get(f"/marketing/v3/emails/{eid}{suffix}")


def create_email(client: HubSpotClient, payload: dict[str, Any]) -> dict[str, Any]:
    body = {k: v for k, v in payload.items() if k not in FORBIDDEN_EMAIL_FIELDS}
    body["state"] = "DRAFT"
    return client.post("/marketing/v3/emails", json_body=body)


def update_email_draft(
    client: HubSpotClient, email_id: str, patch: dict[str, Any]
) -> dict[str, Any]:
    """PATCH the draft buffer. The live email is untouched."""
    safe = {k: v for k, v in patch.items() if k not in FORBIDDEN_EMAIL_FIELDS}
    eid = path_segment(email_id, field="email_id")
    return client.patch(f"/marketing/v3/emails/{eid}/draft", json_body=safe)


def clone_email(client: HubSpotClient, source_id: str, *, clone_name: str) -> dict[str, Any]:
    return client.post(
        "/marketing/v3/emails/clone",
        json_body={"id": path_segment(source_id, field="source_id"), "cloneName": clone_name},
    )
