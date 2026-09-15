from __future__ import annotations

import httpx
import pytest
import respx

from hubspot_content_mcp.hubspot.client import HubSpotClient, HubSpotError

API = "https://api.hubapi.com"


def test_missing_token_is_rejected_loudly():
    with pytest.raises(RuntimeError, match="HUBSPOT_ACCESS_TOKEN"):
        HubSpotClient(access_token="")


@respx.mock
def test_bearer_token_is_sent(client):
    captured: dict = {}

    def capture(request: httpx.Request) -> httpx.Response:
        captured["auth"] = request.headers.get("authorization")
        return httpx.Response(200, json={"results": []})

    respx.get(f"{API}/cms/v3/domains").mock(side_effect=capture)
    client.get("/cms/v3/domains")

    assert captured["auth"] == "Bearer test-token"


@respx.mock
def test_4xx_becomes_hubspot_error_with_message(client):
    respx.get(f"{API}/cms/v3/domains").mock(
        return_value=httpx.Response(403, json={"message": "Missing scope: content"})
    )

    with pytest.raises(HubSpotError) as excinfo:
        client.get("/cms/v3/domains")

    assert excinfo.value.status == 403
    assert "Missing scope" in excinfo.value.message


@respx.mock
def test_4xx_is_not_retried(client):
    route = respx.get(f"{API}/cms/v3/domains").mock(
        return_value=httpx.Response(404, json={"message": "nope"})
    )

    with pytest.raises(HubSpotError):
        client.get("/cms/v3/domains")

    assert route.call_count == 1, "client errors must not be retried"


@respx.mock
def test_5xx_is_retried_on_get_then_surfaces_as_hubspot_error(client):
    route = respx.get(f"{API}/cms/v3/domains").mock(
        return_value=httpx.Response(502, json={"message": "bad gateway"})
    )

    with pytest.raises(HubSpotError) as excinfo:
        client.get("/cms/v3/domains")

    assert route.call_count == 2, "GET 5xx should be retried up to max_attempts"
    assert excinfo.value.status == 502
    assert not isinstance(excinfo.value, httpx.HTTPStatusError)


@respx.mock
def test_5xx_recovers_when_the_retry_succeeds(client):
    route = respx.get(f"{API}/cms/v3/domains").mock(
        side_effect=[
            httpx.Response(503, json={"message": "later"}),
            httpx.Response(200, json={"results": [{"id": "1"}]}),
        ]
    )

    data = client.get("/cms/v3/domains")

    assert route.call_count == 2
    assert data["results"][0]["id"] == "1"


@respx.mock
def test_post_is_not_retried_on_timeout(client):
    """A timed-out POST may already have created something. Never replay it."""
    route = respx.post(f"{API}/cms/v3/pages/landing-pages").mock(
        side_effect=httpx.ReadTimeout("too slow")
    )

    with pytest.raises(HubSpotError):
        client.post("/cms/v3/pages/landing-pages", json_body={"name": "x"})

    assert route.call_count == 1, "POST must not be replayed after a timeout"


@respx.mock
def test_get_is_retried_on_timeout(client):
    route = respx.get(f"{API}/cms/v3/domains").mock(
        side_effect=[httpx.ReadTimeout("slow"), httpx.Response(200, json={"results": []})]
    )

    client.get("/cms/v3/domains")

    assert route.call_count == 2


@respx.mock
def test_204_returns_none(client):
    respx.post(f"{API}/cms/v3/pages/landing-pages/1/draft/reset").mock(
        return_value=httpx.Response(204)
    )

    assert client.post("/cms/v3/pages/landing-pages/1/draft/reset") is None


@respx.mock
def test_html_error_body_does_not_crash_the_summarizer(client):
    respx.get(f"{API}/cms/v3/domains").mock(
        return_value=httpx.Response(500, text="<html><body>Server Error</body></html>")
    )

    with pytest.raises(HubSpotError) as excinfo:
        client.get("/cms/v3/domains")

    assert excinfo.value.status == 500


def test_context_manager_closes_the_transport():
    with HubSpotClient(access_token="t") as c:
        assert not c._client.is_closed
    assert c._client.is_closed
