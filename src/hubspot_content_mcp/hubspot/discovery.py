"""Discovery helpers: templates, domains, blog authors."""

from __future__ import annotations

from typing import Any

from .client import HubSpotClient, HubSpotError


def list_templates(
    client: HubSpotClient,
    *,
    category_id: int | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """List CMS templates via the legacy Design Manager API.

    HubSpot never shipped a v3 endpoint for template listing; templates live
    under /content/api/v2/templates. A token with the `content` scope can read
    it with the usual Bearer auth.
    """
    params: dict[str, Any] = {"limit": max(1, min(limit, 100))}
    if category_id is not None:
        params["category_id"] = category_id

    try:
        data = client.get("/content/api/v2/templates", params=params)
    except HubSpotError as exc:
        if exc.status in (401, 403, 404):
            raise HubSpotError(
                exc.status,
                "Template listing is unavailable on this portal. The legacy Design "
                "Manager API (/content/api/v2/templates) needs the `content` scope. "
                "If you already know the template path, pass it to the create tool "
                "directly — you can copy it from Design Manager in the HubSpot UI.",
                exc.payload,
            ) from None
        raise

    if isinstance(data, dict):
        return data.get("objects", data.get("results", []))
    return []


def list_domains(client: HubSpotClient, *, limit: int = 100) -> list[dict[str, Any]]:
    data = client.get("/cms/v3/domains", params={"limit": max(1, min(limit, 100))})
    return data.get("results", []) if isinstance(data, dict) else []


def list_authors(client: HubSpotClient, *, limit: int = 100) -> list[dict[str, Any]]:
    data = client.get("/cms/v3/blogs/authors", params={"limit": max(1, min(limit, 100))})
    return data.get("results", []) if isinstance(data, dict) else []
