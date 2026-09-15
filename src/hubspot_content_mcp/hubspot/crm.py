"""CRM objects, properties, associations, lists, workflows and imports.

Only imported when ALLOW_CRM names a level. With the default configuration
this module is never loaded, its tools never registered, and the client
refuses every path in here before a request is built.

Two boundaries, not one
-----------------------
ALLOW_CRM is the convenient one: it narrows a single MCP client without
minting a new key, which matters when a portal shares one broad service key
across several automations.

The token scope is the real one. A key without `crm.objects.contacts.read`
cannot read a contact however this file is configured, because HubSpot
enforces that server-side. When HubSpot refuses on scope grounds the client
turns the 403 into a message naming the missing scope — see
`client.scope_error_message`.

Archiving, not erasing
----------------------
`archive_object` moves a record to the recycle bin, where HubSpot keeps it
for 90 days and a human can restore it. HubSpot also offers a GDPR endpoint
that erases a contact permanently and irreversibly. That one is deliberately
not wired up: it is a legal act with an audit trail attached, and an LLM tool
call is the wrong place for it. Do it in the HubSpot UI.
"""

from __future__ import annotations

from typing import Any

from .client import HubSpotClient, path_segment

# The four HubSpot ships with. Custom objects are addressed by their own
# name or type ID and pass through the same validation.
STANDARD_OBJECTS = ("contacts", "companies", "deals", "tickets")

# Sent when the caller names none. Keeping this short matters: every property
# returned is data that ends up in the model's context.
DEFAULT_PROPERTIES: dict[str, tuple[str, ...]] = {
    "contacts": ("firstname", "lastname", "email", "company", "lifecyclestage"),
    "companies": ("name", "domain", "industry", "country"),
    "deals": ("dealname", "dealstage", "amount", "closedate", "pipeline"),
    "tickets": ("subject", "hs_pipeline_stage", "hs_ticket_priority"),
}

MAX_LIMIT = 100


def _object_path(object_type: str) -> str:
    return f"/crm/v3/objects/{path_segment(object_type, field='object_type')}"


def _properties_for(object_type: str, properties: list[str] | None) -> list[str] | None:
    if properties:
        return [str(p) for p in properties]
    return list(DEFAULT_PROPERTIES.get(object_type.lower(), ())) or None


# --- reading ----------------------------------------------------------------


def search_objects(
    client: HubSpotClient,
    object_type: str,
    *,
    query: str | None = None,
    filter_groups: list[dict[str, Any]] | None = None,
    properties: list[str] | None = None,
    sorts: list[dict[str, str]] | None = None,
    limit: int = 20,
    after: str | None = None,
) -> dict[str, Any]:
    """POST /crm/v3/objects/{type}/search.

    `query` is HubSpot's free-text search. `filter_groups` is the structured
    form: a list of groups OR'd together, each group's filters AND'd.
    """
    body: dict[str, Any] = {"limit": min(max(int(limit), 1), MAX_LIMIT)}
    if query:
        body["query"] = query
    if filter_groups:
        body["filterGroups"] = filter_groups
    if sorts:
        body["sorts"] = sorts
    if after:
        body["after"] = after
    props = _properties_for(object_type, properties)
    if props:
        body["properties"] = props
    return client.post(f"{_object_path(object_type)}/search", json_body=body)


def get_object(
    client: HubSpotClient,
    object_type: str,
    object_id: str,
    *,
    properties: list[str] | None = None,
    associations: list[str] | None = None,
    id_property: str | None = None,
) -> dict[str, Any]:
    """GET one record. `id_property` looks it up by e.g. email instead of ID."""
    params: dict[str, Any] = {}
    props = _properties_for(object_type, properties)
    if props:
        params["properties"] = ",".join(props)
    if associations:
        params["associations"] = ",".join(associations)
    if id_property:
        params["idProperty"] = id_property
    oid = path_segment(object_id, field="object_id")
    return client.get(f"{_object_path(object_type)}/{oid}", params=params or None)


def list_objects(
    client: HubSpotClient,
    object_type: str,
    *,
    properties: list[str] | None = None,
    limit: int = 20,
    after: str | None = None,
) -> dict[str, Any]:
    params: dict[str, Any] = {"limit": min(max(int(limit), 1), MAX_LIMIT)}
    props = _properties_for(object_type, properties)
    if props:
        params["properties"] = ",".join(props)
    if after:
        params["after"] = after
    return client.get(_object_path(object_type), params=params)


def batch_read(
    client: HubSpotClient,
    object_type: str,
    ids: list[str],
    *,
    properties: list[str] | None = None,
    id_property: str | None = None,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "inputs": [{"id": path_segment(i, field="object_id")} for i in ids],
    }
    props = _properties_for(object_type, properties)
    if props:
        body["properties"] = props
    if id_property:
        body["idProperty"] = id_property
    return client.post(f"{_object_path(object_type)}/batch/read", json_body=body)


# --- writing ----------------------------------------------------------------


def create_object(
    client: HubSpotClient,
    object_type: str,
    properties: dict[str, Any],
    *,
    associations: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    body: dict[str, Any] = {"properties": properties}
    if associations:
        body["associations"] = associations
    return client.post(_object_path(object_type), json_body=body)


def update_object(
    client: HubSpotClient,
    object_type: str,
    object_id: str,
    properties: dict[str, Any],
    *,
    id_property: str | None = None,
) -> dict[str, Any]:
    oid = path_segment(object_id, field="object_id")
    params = {"idProperty": id_property} if id_property else None
    return client.patch(
        f"{_object_path(object_type)}/{oid}",
        params=params,
        json_body={"properties": properties},
    )


def batch_update(
    client: HubSpotClient,
    object_type: str,
    updates: list[dict[str, Any]],
) -> dict[str, Any]:
    """Each entry is {"id": ..., "properties": {...}}."""
    inputs = [
        {"id": path_segment(u["id"], field="object_id"), "properties": u.get("properties", {})}
        for u in updates
    ]
    return client.post(f"{_object_path(object_type)}/batch/update", json_body={"inputs": inputs})


def archive_object(client: HubSpotClient, object_type: str, object_id: str) -> None:
    """Move a record to the recycle bin. Recoverable in HubSpot for 90 days."""
    oid = path_segment(object_id, field="object_id")
    client.delete(f"{_object_path(object_type)}/{oid}")


# --- properties -------------------------------------------------------------


def list_properties(client: HubSpotClient, object_type: str) -> dict[str, Any]:
    return client.get(f"/crm/v3/properties/{path_segment(object_type, field='object_type')}")


def get_property(client: HubSpotClient, object_type: str, name: str) -> dict[str, Any]:
    ot = path_segment(object_type, field="object_type")
    return client.get(f"/crm/v3/properties/{ot}/{path_segment(name, field='property_name')}")


def create_property(
    client: HubSpotClient, object_type: str, definition: dict[str, Any]
) -> dict[str, Any]:
    ot = path_segment(object_type, field="object_type")
    return client.post(f"/crm/v3/properties/{ot}", json_body=definition)


# --- associations (v4) ------------------------------------------------------


def list_associations(
    client: HubSpotClient,
    from_type: str,
    from_id: str,
    to_type: str,
    *,
    limit: int = 100,
) -> dict[str, Any]:
    ft = path_segment(from_type, field="from_type")
    fid = path_segment(from_id, field="from_id")
    tt = path_segment(to_type, field="to_type")
    return client.get(
        f"/crm/v4/objects/{ft}/{fid}/associations/{tt}",
        params={"limit": min(max(int(limit), 1), 500)},
    )


def associate(
    client: HubSpotClient,
    from_type: str,
    from_id: str,
    to_type: str,
    to_id: str,
    *,
    association_types: list[dict[str, Any]] | None = None,
) -> Any:
    """Link two records. Without explicit types HubSpot picks the default label."""
    ft = path_segment(from_type, field="from_type")
    fid = path_segment(from_id, field="from_id")
    tt = path_segment(to_type, field="to_type")
    tid = path_segment(to_id, field="to_id")
    path = f"/crm/v4/objects/{ft}/{fid}/associations/{tt}/{tid}"
    if association_types is None:
        return client.put(f"{path}/default")
    return client.put(path, json_body=association_types)


def remove_association(
    client: HubSpotClient, from_type: str, from_id: str, to_type: str, to_id: str
) -> None:
    ft = path_segment(from_type, field="from_type")
    fid = path_segment(from_id, field="from_id")
    tt = path_segment(to_type, field="to_type")
    tid = path_segment(to_id, field="to_id")
    client.delete(f"/crm/v4/objects/{ft}/{fid}/associations/{tt}/{tid}")


# --- owners and pipelines ---------------------------------------------------


def list_owners(client: HubSpotClient, *, email: str | None = None) -> dict[str, Any]:
    params = {"email": email} if email else None
    return client.get("/crm/v3/owners", params=params)


def list_pipelines(client: HubSpotClient, object_type: str) -> dict[str, Any]:
    return client.get(f"/crm/v3/pipelines/{path_segment(object_type, field='object_type')}")


# --- lists ------------------------------------------------------------------


def search_lists(
    client: HubSpotClient, *, query: str | None = None, limit: int = 20
) -> dict[str, Any]:
    body: dict[str, Any] = {"count": min(max(int(limit), 1), MAX_LIMIT)}
    if query:
        body["query"] = query
    return client.post("/marketing/v3/lists/search", json_body=body)


def get_list(client: HubSpotClient, list_id: str) -> dict[str, Any]:
    return client.get(f"/marketing/v3/lists/{path_segment(list_id, field='list_id')}")


def create_list(
    client: HubSpotClient,
    name: str,
    object_type_id: str = "0-1",
    *,
    processing_type: str = "MANUAL",
) -> dict[str, Any]:
    return client.post(
        "/marketing/v3/lists",
        json_body={
            "name": name,
            "objectTypeId": object_type_id,
            "processingType": processing_type,
        },
    )


def add_to_list(client: HubSpotClient, list_id: str, record_ids: list[str]) -> Any:
    lid = path_segment(list_id, field="list_id")
    ids = [path_segment(r, field="record_id") for r in record_ids]
    return client.put(f"/marketing/v3/lists/{lid}/memberships/add", json_body=ids)


def remove_from_list(client: HubSpotClient, list_id: str, record_ids: list[str]) -> Any:
    lid = path_segment(list_id, field="list_id")
    ids = [path_segment(r, field="record_id") for r in record_ids]
    return client.put(f"/marketing/v3/lists/{lid}/memberships/remove", json_body=ids)


# --- workflows --------------------------------------------------------------


def list_workflows(client: HubSpotClient, *, limit: int = 50) -> dict[str, Any]:
    return client.get("/automation/v4/flows", params={"limit": min(max(int(limit), 1), 100)})


def get_workflow(client: HubSpotClient, flow_id: str) -> dict[str, Any]:
    return client.get(f"/automation/v4/flows/{path_segment(flow_id, field='flow_id')}")


def set_workflow_enabled(client: HubSpotClient, flow_id: str, enabled: bool) -> dict[str, Any]:
    """Turn a workflow on or off. Everything enrolled starts or stops moving."""
    fid = path_segment(flow_id, field="flow_id")
    return client.patch(f"/automation/v4/flows/{fid}", json_body={"isEnabled": bool(enabled)})


# --- imports ----------------------------------------------------------------


def list_imports(client: HubSpotClient, *, limit: int = 20) -> dict[str, Any]:
    return client.get("/crm/v3/imports", params={"limit": min(max(int(limit), 1), MAX_LIMIT)})


def get_import(client: HubSpotClient, import_id: str) -> dict[str, Any]:
    return client.get(f"/crm/v3/imports/{path_segment(import_id, field='import_id')}")
