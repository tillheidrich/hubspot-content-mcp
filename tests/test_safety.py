"""The drafts-only guarantee is the whole point of this server.

These tests are the ones that must never be allowed to go red.
"""

from __future__ import annotations

import asyncio

import httpx
import pytest
import respx

from hubspot_content_mcp.hubspot import blog as hub_blog
from hubspot_content_mcp.hubspot import emails as hub_emails
from hubspot_content_mcp.hubspot import pages as hub_pages
from hubspot_content_mcp.server import build_server

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
FORBIDDEN_TOOL_SUBSTRINGS = [
    "publish",
    "delete",
    "archive",
    "schedule_post",
    "send",
    "contact",
    "company",
    "deal",
    "crm",
]


def test_no_publishing_or_crm_tools_are_registered(settings):
    server = build_server(settings)
    try:
        names = {t.name for t in asyncio.run(server.list_tools())}
    finally:
        server._hubspot_client.close()

    for name in names:
        for bad in FORBIDDEN_TOOL_SUBSTRINGS:
            assert bad not in name.lower(), f"tool {name!r} looks like a {bad} tool"


def test_expected_tool_surface(settings):
    server = build_server(settings)
    try:
        names = {t.name for t in asyncio.run(server.list_tools())}
    finally:
        server._hubspot_client.close()

    expected = {
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
