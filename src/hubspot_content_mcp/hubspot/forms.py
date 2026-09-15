"""HubSpot Forms (Marketing Forms v3).

Endpoints used:
  GET   /marketing/v3/forms
  GET   /marketing/v3/forms/{id}
  POST  /marketing/v3/forms
  PATCH /marketing/v3/forms/{id}

Note that forms have no draft state — a form exists and is submittable as
soon as it is created. It is not embedded anywhere until someone places it
on a page, which is the only thing keeping a new form inert.

Submissions are never read or written here.
"""

from __future__ import annotations

from typing import Any

from .client import HubSpotClient, path_segment
from .pages import MAX_SEARCH_PAGES

CREATABLE_FORM_TYPE = "hubspot"

# Top-level keys a caller may write.
ALLOWED_FORM_FIELDS = frozenset({"name", "fieldGroups", "displayOptions", "legalConsentOptions"})

# Configuration sub-keys that route submitted data somewhere, or that mutate
# CRM records. A form is a data-collection endpoint, so repointing where its
# submissions go is an exfiltration primitive — never writable from a tool call.
FORBIDDEN_CONFIG_KEYS = frozenset(
    {
        "notifyRecipients",
        "notifyContactOwner",
        "postSubmitAction",
        "redirectUrl",
        "createNewContactForNewEmail",
        "lifecycleStages",
        "archivable",
        "recaptchaEnabled",
    }
)

# Configuration sub-keys that are safe to change from a tool call.
ALLOWED_CONFIG_KEYS = frozenset({"language", "cloneable", "editable"})


def sanitize_form_fields(fields: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Split a caller-supplied patch into (accepted, rejected-key-names)."""
    accepted: dict[str, Any] = {}
    rejected: list[str] = []

    for key, value in fields.items():
        if key == "configuration" and isinstance(value, dict):
            kept = {}
            for sub_key, sub_value in value.items():
                if sub_key in ALLOWED_CONFIG_KEYS:
                    kept[sub_key] = sub_value
                else:
                    rejected.append(f"configuration.{sub_key}")
            if kept:
                accepted["configuration"] = kept
        elif key in ALLOWED_FORM_FIELDS:
            accepted[key] = value
        else:
            rejected.append(key)

    return accepted, sorted(rejected)


def list_forms(
    client: HubSpotClient,
    *,
    name_contains: str | None = None,
    form_type: str | None = None,
    limit: int = 50,
    archived: bool = False,
) -> tuple[list[dict[str, Any]], bool]:
    """List forms. Returns (results, search_truncated)."""
    wanted = max(1, min(limit, 100))
    params: dict[str, Any] = {"limit": 100 if name_contains else wanted, "archived": archived}
    if form_type:
        params["formTypes"] = form_type

    if not name_contains:
        data = client.get("/marketing/v3/forms", params=params)
        return (data.get("results", []) if isinstance(data, dict) else []), False

    needle = name_contains.lower()
    matches: list[dict[str, Any]] = []
    after: str | None = None

    for _ in range(MAX_SEARCH_PAGES):
        page_params = dict(params)
        if after:
            page_params["after"] = after
        data = client.get("/marketing/v3/forms", params=page_params)
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


def get_form(client: HubSpotClient, form_id: str) -> dict[str, Any]:
    return client.get(f"/marketing/v3/forms/{path_segment(form_id, field='form_id')}")


def create_form(client: HubSpotClient, payload: dict[str, Any]) -> dict[str, Any]:
    return client.post("/marketing/v3/forms", json_body=payload)


def update_form(client: HubSpotClient, form_id: str, patch: dict[str, Any]) -> dict[str, Any]:
    safe, _rejected = sanitize_form_fields(patch)
    return client.patch(
        f"/marketing/v3/forms/{path_segment(form_id, field='form_id')}", json_body=safe
    )
