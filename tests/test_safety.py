"""The guarantees that must never be allowed to go red.

Since 0.4.0 this server can publish and, when told to, reach the CRM. What
survives that is the shape of the promise rather than its contents: whatever
a configuration did not enable is *absent*, not present-and-refusing, and the
HTTP client will not carry a request to a surface the configuration left off.

The one people buy this for is the data boundary. With ALLOW_CRM unset, no
contact, company, deal or ticket is reachable — so no customer data can enter
the conversation, and none can reach whoever runs the model. Three tests
below pin that from three directions: the tool list, the HTTP client, and the
instructions the model is handed.
"""

from __future__ import annotations

import asyncio
import pathlib
import re

import httpx
import pytest
import respx

from hubspot_mcp.config import Settings
from hubspot_mcp.hubspot import blog as hub_blog
from hubspot_mcp.hubspot import emails as hub_emails
from hubspot_mcp.hubspot import pages as hub_pages
from hubspot_mcp.hubspot.client import HubSpotError
from hubspot_mcp.server import build_server

API = "https://api.hubapi.com"


# --- writes go to the draft buffer, never the live object -------------------


@respx.mock
def test_page_update_targets_draft_endpoint(client):
    route = respx.patch(f"{API}/cms/v3/pages/landing-pages/123/draft").mock(
        return_value=httpx.Response(200, json={"id": "123", "name": "x"})
    )

    hub_pages.update_page_draft(client, "landing", "123", {"name": "x"})

    assert route.called, "page update must PATCH {id}/draft, not the live object"


@respx.mock
def test_blog_update_targets_draft_endpoint(client):
    route = respx.patch(f"{API}/cms/v3/blogs/posts/55/draft").mock(
        return_value=httpx.Response(200, json={"id": "55"})
    )

    hub_blog.update_blog_post_draft(client, "55", {"name": "x"})

    assert route.called


@respx.mock
def test_email_update_targets_draft_endpoint(client):
    route = respx.patch(f"{API}/marketing/v3/emails/77/draft").mock(
        return_value=httpx.Response(200, json={"id": "77"})
    )

    hub_emails.update_email_draft(client, "77", {"name": "x"})

    assert route.called


# --- publication fields cannot slip through --------------------------------


@pytest.mark.parametrize(
    "field",
    [
        "state",
        "currentState",
        "publishDate",
        "publishImmediately",
        "publishedAt",
        "isPublished",
        "scheduledUpdateDate",
        "archived",
    ],
)
def test_page_sanitizer_rejects_publication_fields(field):
    safe, rejected = hub_pages.sanitize_page_fields({"name": "ok", field: True})
    assert field not in safe
    assert field in rejected
    assert safe == {"name": "ok"}


@pytest.mark.parametrize("field", ["isPublished", "publishDate", "state", "archived"])
def test_email_sanitizer_rejects_publication_fields(field):
    safe, rejected = hub_emails.sanitize_email_fields({"name": "ok", field: True})
    assert field not in safe
    assert field in rejected


@respx.mock
def test_publication_fields_stripped_even_if_they_reach_the_http_layer(client):
    """Defence in depth: the hubspot layer filters too, not just the tool layer."""
    captured: dict = {}

    def capture(request: httpx.Request) -> httpx.Response:
        import json

        captured.update(json.loads(request.content))
        return httpx.Response(200, json={"id": "1"})

    respx.patch(f"{API}/cms/v3/pages/landing-pages/1/draft").mock(side_effect=capture)

    hub_pages.update_page_draft(
        client, "landing", "1", {"name": "ok", "publishImmediately": True, "state": "PUBLISHED"}
    )

    assert "publishImmediately" not in captured
    assert "state" not in captured
    assert captured["name"] == "ok"


@respx.mock
def test_create_page_forces_draft_state(client):
    captured: dict = {}

    def capture(request: httpx.Request) -> httpx.Response:
        import json

        captured.update(json.loads(request.content))
        return httpx.Response(201, json={"id": "9"})

    respx.post(f"{API}/cms/v3/pages/landing-pages").mock(side_effect=capture)

    hub_pages.create_page(client, "landing", {"name": "n", "state": "PUBLISHED"})

    assert captured["state"] == "DRAFT", "create must always force DRAFT"


# --- no dangerous tools exist ----------------------------------------------

# With the default config (no ALLOW_PUBLISH) none of these may appear.
# Anything whose name suggests it touches a CRM record. A content-only
# install must register none of them.
CRM_TOOL_SUBSTRINGS = [
    "crm",
    "contact",
    "company",
    "deal",
    "ticket",
    "owner",
    "pipeline",
    "workflow",
    "association",
]


def _names(settings) -> set[str]:
    server = build_server(settings)
    try:
        return {t.name for t in asyncio.run(server.list_tools())}
    finally:
        server._hubspot_client.close()


# --- the data boundary ------------------------------------------------------


def test_content_only_install_registers_no_crm_tools(settings):
    """First of three: nothing in the tool list can reach a person's record."""
    for name in _names(settings):
        for bad in CRM_TOOL_SUBSTRINGS:
            assert bad not in name.lower(), f"tool {name!r} looks like a {bad} tool"


def test_content_only_client_refuses_crm_paths(settings):
    """Second: even a bug in a helper module cannot get a request out.

    The tool list is what a model sees. This is what the socket allows, and
    it is checked on the resolved URL, after httpx has merged the path onto
    the base — which is where the traversal bug lived in 0.3.0.
    """
    server = build_server(settings)
    client = server._hubspot_client
    try:
        for path in (
            "/crm/v3/objects/contacts",
            "/crm/v3/objects/deals/1",
            "/crm/v4/objects/contacts/1/associations/companies",
            "/automation/v4/flows",
            "/marketing/v3/lists/search",
        ):
            with pytest.raises(HubSpotError) as excinfo:
                client._build_and_check("GET", path, None, None)
            assert "outside this server" in excinfo.value.message
    finally:
        client.close()


def test_content_only_instructions_state_the_boundary(settings):
    """Third: the model can tell the user why, instead of improvising."""
    from hubspot_mcp.server import build_instructions, data_boundary

    text = build_instructions(settings)
    assert "CRM access is OFF" in text
    assert "no customer data" in text.lower()

    boundary = data_boundary(settings)
    assert boundary["personal_data_reachable"] is False
    assert boundary["crm_access"] == "off"


def test_crm_tools_appear_only_when_allow_crm_is_set(settings, monkeypatch):
    monkeypatch.setenv("ALLOW_CRM", "read")
    enabled = _names(Settings.load())
    assert "search_crm_objects" in enabled
    assert "get_crm_object" in enabled

    monkeypatch.delenv("ALLOW_CRM")
    assert not (_names(Settings.load()) & {"search_crm_objects", "get_crm_object"})


def test_crm_read_level_cannot_write(settings, monkeypatch):
    monkeypatch.setenv("ALLOW_CRM", "read")
    names = _names(Settings.load())
    assert "search_crm_objects" in names
    for writer in ("create_crm_object", "update_crm_object", "archive_crm_object"):
        assert writer not in names


def test_crm_write_level_cannot_destroy(settings, monkeypatch):
    monkeypatch.setenv("ALLOW_CRM", "write")
    names = _names(Settings.load())
    assert "update_crm_object" in names
    for destructive in ("archive_crm_object", "set_workflow_enabled"):
        assert destructive not in names


def test_crm_client_surface_follows_the_setting(settings, monkeypatch):
    monkeypatch.setenv("ALLOW_CRM", "read")
    server = build_server(Settings.load())
    try:
        server._hubspot_client._build_and_check("GET", "/crm/v3/objects/contacts", None, None)
    finally:
        server._hubspot_client.close()


def test_expected_tool_surface(settings):
    """The full default surface. Fails on any tool added without a decision."""
    server = build_server(settings)
    try:
        names = {t.name for t in asyncio.run(server.list_tools())}
    finally:
        server._hubspot_client.close()

    expected = {
        "list_campaigns",
        "get_campaign",
        "create_campaign",
        "update_campaign",
        "list_campaign_assets",
        "attach_asset_to_campaign",
        "detach_asset_from_campaign",
        "publish_page",
        "schedule_page_publish",
        "unpublish_page",
        "publish_blog_post",
        "schedule_blog_post_publish",
        "unpublish_blog_post",
        "publish_marketing_email",
        "unpublish_marketing_email",
        "cancel_scheduled_publish",
        "list_landing_pages",
        "list_site_pages",
        "get_page",
        "create_landing_page_draft",
        "create_site_page_draft",
        "update_page_draft",
        "reset_draft",
        "duplicate_page",
        "create_language_variant",
        "list_blogs",
        "list_blog_posts",
        "get_blog_post",
        "create_blog_post_draft",
        "update_blog_post_draft",
        "reset_blog_post_draft",
        "list_forms",
        "get_form",
        "create_form",
        "update_form",
        "duplicate_form",
        "list_marketing_emails",
        "get_marketing_email",
        "create_marketing_email_draft",
        "update_marketing_email_draft",
        "duplicate_marketing_email",
        "generate_social_bulk_xlsx_file",
        "list_templates",
        "list_domains",
        "list_blog_authors",
    }
    assert names == expected


def test_every_tool_has_a_description(settings):
    server = build_server(settings)
    try:
        tools = asyncio.run(server.list_tools())
    finally:
        server._hubspot_client.close()

    for tool in tools:
        assert tool.description, f"{tool.name} has no description for the model to read"
        assert len(tool.description) > 40, f"{tool.name} description is too thin"


# --- page structure guidance reaches the model -------------------------------
#
# The layout rules only work if the assistant actually reads them. They live
# in two places for that reason, and both are easy to drop during a refactor
# without anything failing. These tests fail instead.


def _flat(text: str) -> str:
    """Collapse the line wrapping so a rule can be matched as one sentence."""
    return " ".join(text.split())


def test_server_instructions_carry_the_layout_rules(settings):
    text = _flat(build_server(settings).instructions)
    assert "Do not invent layout" in text
    assert "Never hand-write a layoutSections tree" in text
    assert "not just the preview" in text


def test_update_page_draft_description_carries_the_markup_rules(settings):
    server = build_server(settings)
    tools = {t.name: _flat(t.description or "") for t in asyncio.run(server.list_tools())}
    description = tools["update_page_draft"]
    assert "send the whole tree" in description
    assert "Layout belongs to modules and rows, not to markup" in description


# --- the confirmation gate, across every configuration ----------------------
#
# Individual tests check individual tools. This one checks the rule: anything
# that reaches the public, changes a person's record, or cannot be undone from
# here has to ask first. A tool added later without the gate fails here rather
# than in someone's portal.

CONSEQUENTIAL = (
    "publish",
    "unpublish",
    "schedule",
    "archive",
    "create_crm",
    "update_crm",
    "batch_update_crm",
    "associate_crm",
    "remove_crm_association",
    "add_records_to_list",
    "remove_records_from_list",
    "create_crm_list",
    "create_crm_property",
    "set_workflow_enabled",
)

# Reads and planning tools. Naming a campaign is not consequential, and
# cancelling a scheduled publish makes something *less* public, so neither
# needs a gate.
EXEMPT = {"cancel_scheduled_publish", "list_campaigns", "list_campaign_assets"}


def test_every_consequential_tool_requires_confirmation(settings, monkeypatch):
    monkeypatch.setenv("ALLOW_PUBLISH", "all")
    monkeypatch.setenv("ALLOW_CRM", "all")
    server = build_server(Settings.load())
    try:
        tools = asyncio.run(server.list_tools())
    finally:
        server._hubspot_client.close()

    missing = []
    for tool in tools:
        name = tool.name
        if name in EXEMPT or not any(name.startswith(p) or p in name for p in CONSEQUENTIAL):
            continue
        properties = (tool.inputSchema or {}).get("properties", {})
        if "user_confirmed" not in properties:
            missing.append(name)

    assert not missing, f"these change the world without asking first: {sorted(missing)}"


def test_confirmation_defaults_to_false(settings, monkeypatch):
    """A gate that defaults to True is not a gate."""
    monkeypatch.setenv("ALLOW_PUBLISH", "all")
    monkeypatch.setenv("ALLOW_CRM", "all")
    server = build_server(Settings.load())
    try:
        tools = asyncio.run(server.list_tools())
    finally:
        server._hubspot_client.close()

    for tool in tools:
        gate = (tool.inputSchema or {}).get("properties", {}).get("user_confirmed")
        if gate is not None:
            assert gate.get("default") is False, f"{tool.name} defaults to confirmed"


# --- the README's numbers have to be true -----------------------------------
#
# Counts in documentation rot silently: someone adds a tool, nobody edits the
# table, and the first thing a reader checks is now wrong. These assertions
# fail instead.


def _tool_count(monkeypatch, publish: str, crm: str) -> int:
    monkeypatch.setenv("ALLOW_PUBLISH", publish)
    monkeypatch.setenv("ALLOW_CRM", crm)
    return len(_names(Settings.load()))


def _documented_counts() -> dict[tuple[str, str], int]:
    """Read the tool-count table out of the README.

    Parsing the table rather than restating the numbers here is the point:
    a constant in this file would drift with the README instead of catching
    it. The row labels below are the configurations the table describes.
    """
    readme = (pathlib.Path(__file__).parent.parent / "README.md").read_text()
    rows = re.findall(r"^\|(.+?)\|(.+?)\|\s*$", readme, re.M)

    label_to_config = {
        "ALLOW_PUBLISH=none`, `ALLOW_CRM=none": ("none", "none"),
        "default": ("all", "none"),
        "ALLOW_CRM=read": ("all", "read"),
        "ALLOW_CRM=write": ("all", "write"),
        "ALLOW_CRM=all": ("all", "all"),
    }

    found: dict[tuple[str, str], int] = {}
    for label_cell, value_cell in rows:
        number = re.search(r"\d+", value_cell)
        if not number:
            continue
        for label, config in label_to_config.items():
            if label in label_cell and config not in found:
                found[config] = int(number.group())
    return found


def test_readme_tool_counts_match_reality(settings, monkeypatch):
    documented = _documented_counts()
    assert len(documented) == 5, (
        f"could not find all five rows of the tool-count table in README.md, "
        f"got {sorted(documented)}"
    )

    for (publish, crm), claimed in sorted(documented.items()):
        monkeypatch.setenv("ALLOW_PUBLISH", publish)
        monkeypatch.setenv("ALLOW_CRM", crm)
        actual = len(_names(Settings.load()))
        assert actual == claimed, (
            f"ALLOW_PUBLISH={publish}, ALLOW_CRM={crm}: README's table says "
            f"{claimed}, the server registers {actual}. Update README.md."
        )
