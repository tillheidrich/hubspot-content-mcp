"""Publishing is opt-in. These tests pin both halves of that.

When ALLOW_PUBLISH is unset the tools must be absent from the tool list —
not present-but-refusing. Absent is the guarantee the README sells.
"""

from __future__ import annotations

import asyncio

import httpx
import pytest
import respx

from hubspot_content_mcp.config import Settings
from hubspot_content_mcp.hubspot import publishing as hub_publishing
from hubspot_content_mcp.server import build_server

API = "https://api.hubapi.com"
LP = f"{API}/cms/v3/pages/landing-pages"

PUBLISH_TOOLS = {
    "publish_page",
    "schedule_page_publish",
    "publish_blog_post",
    "schedule_blog_post_publish",
    "cancel_scheduled_publish",
}


def _settings(tmp_path, monkeypatch, allow_publish: str | None) -> Settings:
    monkeypatch.setenv("HUBSPOT_ACCESS_TOKEN", "t")
    monkeypatch.setenv("HUBSPOT_PORTAL_ID", "1")
    monkeypatch.setenv("OUTPUT_DIR", str(tmp_path / "o"))
    monkeypatch.setenv("LOG_DIR", str(tmp_path / "l"))
    if allow_publish is None:
        monkeypatch.delenv("ALLOW_PUBLISH", raising=False)
    else:
        monkeypatch.setenv("ALLOW_PUBLISH", allow_publish)
    monkeypatch.chdir(tmp_path)
    return Settings.load()


def _tool_names(settings) -> set[str]:
    server = build_server(settings)
    try:
        return {t.name for t in asyncio.run(server.list_tools())}
    finally:
        server._hubspot_client.close()


# --- the default is no publishing at all ------------------------------------


def test_no_publish_tools_exist_by_default(tmp_path, monkeypatch):
    names = _tool_names(_settings(tmp_path, monkeypatch, None))
    assert not (names & PUBLISH_TOOLS), "publishing must be absent unless opted in"


@pytest.mark.parametrize("value", ["none", "off", "false", "0", ""])
def test_explicit_off_values_disable_publishing(tmp_path, monkeypatch, value):
    names = _tool_names(_settings(tmp_path, monkeypatch, value))
    assert not (names & PUBLISH_TOOLS)


def test_default_instructions_say_the_server_cannot_publish(tmp_path, monkeypatch):
    from hubspot_content_mcp.server import build_instructions

    text = build_instructions(_settings(tmp_path, monkeypatch, None))
    assert "cannot publish" in text.lower()


# --- opting in --------------------------------------------------------------


def test_all_enables_every_publish_tool(tmp_path, monkeypatch):
    names = _tool_names(_settings(tmp_path, monkeypatch, "all"))
    assert names >= PUBLISH_TOOLS


def test_scope_is_per_area(tmp_path, monkeypatch):
    names = _tool_names(_settings(tmp_path, monkeypatch, "blog"))
    assert "publish_blog_post" in names
    assert "publish_page" not in names, "enabling blog must not enable pages"


def test_unknown_area_is_rejected_with_a_helpful_message(tmp_path, monkeypatch):
    with pytest.raises(RuntimeError, match="unknown area"):
        _settings(tmp_path, monkeypatch, "pages,contacts")


def test_emails_are_not_publishable(tmp_path, monkeypatch):
    """HubSpot's email publish endpoint is undocumented — we do not guess it."""
    with pytest.raises(RuntimeError, match="Marketing emails cannot be published"):
        _settings(tmp_path, monkeypatch, "emails")


def test_enabled_instructions_name_the_areas(tmp_path, monkeypatch):
    from hubspot_content_mcp.server import build_instructions

    text = build_instructions(_settings(tmp_path, monkeypatch, "pages"))
    assert "ENABLED" in text
    assert "pages" in text


# --- confirmation gate -------------------------------------------------------


def test_publishing_without_confirmation_is_refused(tmp_path, monkeypatch):
    settings = _settings(tmp_path, monkeypatch, "all")
    server = build_server(settings)
    try:
        with pytest.raises(Exception) as excinfo:
            asyncio.run(
                server.call_tool("publish_page", {"page_id": "123", "page_type": "landing"})
            )
        assert "confirm" in str(excinfo.value).lower()
    finally:
        server._hubspot_client.close()


# --- first publish vs republish ---------------------------------------------


def test_is_live_recognises_published_and_scheduled_states():
    assert hub_publishing.is_live({"currentState": "PUBLISHED"})
    assert hub_publishing.is_live({"currentState": "PUBLISHED_OR_SCHEDULED"})
    assert hub_publishing.is_live({"state": "SCHEDULED_AB"})
    assert not hub_publishing.is_live({"currentState": "DRAFT"})
    assert not hub_publishing.is_live({})


@respx.mock
def test_republish_uses_push_live(client):
    route = respx.post(f"{LP}/123/draft/push-live").mock(return_value=httpx.Response(204))
    hub_publishing.push_page_live(client, "landing", "123")
    assert route.called


@respx.mock
def test_schedule_puts_the_id_in_the_body_not_the_path(client):
    captured: dict = {}

    def capture(request: httpx.Request) -> httpx.Response:
        import json

        captured.update(json.loads(request.content))
        return httpx.Response(204)

    respx.post(f"{LP}/schedule").mock(side_effect=capture)
    hub_publishing.schedule_page(client, "landing", "123", publish_at="2026-10-01T09:00:00Z")

    assert captured == {"id": "123", "publishDate": "2026-10-01T09:00:00Z"}


def test_post_publish_preconditions_are_reported_by_name():
    """HubSpot fails opaquely when a post is missing these; we say which."""
    missing = hub_publishing.missing_post_publish_fields({"name": "Title"})
    joined = " ".join(missing)
    assert "slug" in joined
    assert "author" in joined
    assert "meta description" in joined


def test_a_complete_post_has_no_missing_fields():
    assert (
        hub_publishing.missing_post_publish_fields(
            {
                "name": "Title",
                "contentGroupId": "1",
                "slug": "real-slug",
                "blogAuthorId": "2",
                "metaDescription": "desc",
                "useFeaturedImage": False,
            }
        )
        == []
    )


@respx.mock
def test_publish_ids_are_validated_like_every_other_id(client):
    respx.route().mock(side_effect=AssertionError("request must never be sent"))
    with pytest.raises(ValueError, match="Invalid"):
        hub_publishing.push_page_live(client, "landing", "../../../crm/v3/objects/contacts")


@respx.mock
def test_first_publish_uses_publish_immediately_then_schedule(client):
    """push-live refuses a never-published page, so first publish is two calls."""
    patched = respx.patch(f"{LP}/123").mock(return_value=httpx.Response(200, json={"id": "123"}))
    scheduled = respx.post(f"{LP}/schedule").mock(return_value=httpx.Response(204))

    hub_publishing.set_page_publish_immediately(client, "landing", "123")
    hub_publishing.schedule_page(client, "landing", "123", publish_at="2026-10-01T09:00:00Z")

    assert patched.called
    assert scheduled.called


def test_now_iso_is_a_valid_utc_timestamp():
    from datetime import datetime

    from hubspot_content_mcp.tools.publishing import _now_iso

    stamp = _now_iso()
    assert stamp.endswith("Z")
    datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ")
