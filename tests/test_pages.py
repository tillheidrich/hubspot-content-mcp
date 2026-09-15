from __future__ import annotations

import httpx
import pytest
import respx

from hubspot_mcp.hubspot import blog as hub_blog
from hubspot_mcp.hubspot import pages as hub_pages
from hubspot_mcp.models.common import page_summary
from hubspot_mcp.tools.pages import validate_slug

API = "https://api.hubapi.com"
LP = f"{API}/cms/v3/pages/landing-pages"
POSTS = f"{API}/cms/v3/blogs/posts"


# --- state / language filters use the documented __in syntax ----------------


@respx.mock
def test_state_filter_uses_state_in(client):
    captured: dict = {}

    def capture(request: httpx.Request) -> httpx.Response:
        captured.update(dict(request.url.params))
        return httpx.Response(200, json={"results": []})

    respx.get(LP).mock(side_effect=capture)
    hub_pages.list_pages(client, "landing", state="DRAFT", language="de")

    assert "state__in" in captured, "a bare ?state= is ignored by HubSpot"
    assert "DRAFT" in captured["state__in"]
    assert captured["language__in"] == "de"


@respx.mock
def test_any_state_sends_no_state_filter(client):
    captured: dict = {}

    def capture(request: httpx.Request) -> httpx.Response:
        captured.update(dict(request.url.params))
        return httpx.Response(200, json={"results": []})

    respx.get(LP).mock(side_effect=capture)
    hub_pages.list_pages(client, "landing", state="ANY")

    assert "state__in" not in captured


def test_unknown_state_is_rejected_with_a_helpful_message(client):
    with pytest.raises(ValueError, match="ANY, DRAFT, PUBLISHED, SCHEDULED"):
        hub_pages.list_pages(client, "landing", state="LIVE")


def test_unknown_page_type_is_rejected(client):
    with pytest.raises(ValueError, match="landing.*site"):
        hub_pages.list_pages(client, "newsletter")  # type: ignore[arg-type]


# --- name search walks pages instead of filtering only the first -----------


@respx.mock
def test_name_search_follows_the_paging_cursor(client):
    respx.get(LP).mock(
        side_effect=[
            httpx.Response(
                200,
                json={
                    "results": [{"id": "1", "name": "Unrelated"}],
                    "paging": {"next": {"after": "CURSOR"}},
                },
            ),
            httpx.Response(200, json={"results": [{"id": "2", "name": "NIS2 Webcast"}]}),
        ]
    )

    rows, truncated = hub_pages.list_pages(client, "landing", name_contains="nis2")

    assert [r["id"] for r in rows] == ["2"], "match on page 2 must still be found"
    assert truncated is False


@respx.mock
def test_name_search_is_case_insensitive(client):
    respx.get(LP).mock(
        return_value=httpx.Response(200, json={"results": [{"id": "1", "name": "NIS2 Webcast"}]})
    )

    rows, _ = hub_pages.list_pages(client, "landing", name_contains="nis2 web")
    assert len(rows) == 1


@respx.mock
def test_name_search_stops_at_the_requested_limit(client):
    respx.get(LP).mock(
        return_value=httpx.Response(
            200,
            json={
                "results": [{"id": str(i), "name": f"Webcast {i}"} for i in range(10)],
                "paging": {"next": {"after": "MORE"}},
            },
        )
    )

    rows, truncated = hub_pages.list_pages(client, "landing", name_contains="webcast", limit=3)

    assert len(rows) == 3
    assert truncated is True


# --- clone + language variant ----------------------------------------------


@respx.mock
def test_clone_sends_id_and_clone_name(client):
    captured: dict = {}

    def capture(request: httpx.Request) -> httpx.Response:
        import json

        captured.update(json.loads(request.content))
        return httpx.Response(200, json={"id": "999"})

    respx.post(f"{LP}/clone").mock(side_effect=capture)
    hub_pages.clone_page(client, "landing", "123", clone_name="Copy")

    assert captured == {"id": "123", "cloneName": "Copy"}


@respx.mock
def test_language_variant_falls_back_to_the_other_spelling(client):
    """HubSpot's docs disagree with themselves about variation vs variant."""
    respx.post(f"{LP}/multi-language/create-language-variation").mock(
        return_value=httpx.Response(404, json={"message": "not found"})
    )
    fallback = respx.post(f"{LP}/multi-language/create-language-variant").mock(
        return_value=httpx.Response(200, json={"id": "42"})
    )

    result = hub_pages.create_language_variation(
        client, "landing", source_id="1", target_language="en"
    )

    assert fallback.called
    assert result["id"] == "42"


# --- summaries --------------------------------------------------------------


def test_page_summary_never_returns_false_for_url():
    """Regression: the old expression leaked a boolean into the url field."""
    summary = page_summary({"id": "1", "publicAccessRulesEnabled": False}, portal_id="99")
    assert summary["url"] is None


def test_page_summary_prefers_url_then_absolute_url():
    assert page_summary({"id": "1", "url": "https://a"})["url"] == "https://a"
    assert page_summary({"id": "1", "absoluteUrl": "https://b"})["url"] == "https://b"


def test_page_summary_builds_an_edit_url():
    summary = page_summary({"id": "555"}, kind="landing-page", portal_id="12345678")
    assert summary["edit_url"] == "https://app.hubspot.com/content-editor/12345678/555"


def test_page_summary_without_portal_id_has_no_edit_url():
    assert page_summary({"id": "555"}, portal_id="")["edit_url"] == ""


# --- slug validation --------------------------------------------------------


@pytest.mark.parametrize(
    "value,expected",
    [
        ("webcast-2026", "webcast-2026"),
        ("en/webcast-2026", "en/webcast-2026"),
        ("/leading-slash", "leading-slash"),
        ("  padded  ", "padded"),
    ],
)
def test_valid_slugs(value, expected):
    assert validate_slug(value) == expected


@pytest.mark.parametrize("value", ["has spaces", "Upper", "trailing-", "", "ümlaut", "a--b"])
def test_invalid_slugs_explain_themselves(value):
    with pytest.raises(ValueError, match="slug"):
        validate_slug(value)


# --- blog posts and pages do not share a state vocabulary -------------------


@respx.mock
def test_blog_state_filter_uses_the_post_vocabulary(client):
    """A published post carries a plain PUBLISHED.

    The page table maps PUBLISHED to PUBLISHED_OR_SCHEDULED, which matches no
    post at all, so the tool answered "no posts" for a blog full of them — a
    wrong answer wearing the clothes of a right one.
    """
    captured: dict = {}

    def capture(request: httpx.Request) -> httpx.Response:
        captured.update(dict(request.url.params))
        return httpx.Response(200, json={"results": []})

    respx.get(POSTS).mock(side_effect=capture)
    hub_blog.list_blog_posts(client, state="PUBLISHED")

    assert captured["state__in"] == "PUBLISHED"
    assert "PUBLISHED_OR_SCHEDULED" not in captured["state__in"]


@respx.mock
def test_page_state_filter_still_uses_the_page_vocabulary(client):
    captured: dict = {}

    def capture(request: httpx.Request) -> httpx.Response:
        captured.update(dict(request.url.params))
        return httpx.Response(200, json={"results": []})

    respx.get(LP).mock(side_effect=capture)
    hub_pages.list_pages(client, "landing", state="PUBLISHED")

    assert "PUBLISHED_OR_SCHEDULED" in captured["state__in"]
