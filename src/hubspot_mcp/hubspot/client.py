"""HubSpot API client.

A single httpx.Client wrapped with auth, retry, and structured logging.
Tools reach HubSpot through the per-endpoint helper modules, never directly.

Path safety
-----------
Every caller-supplied ID goes through `path_segment()` before it is
interpolated into a URL. This is not cosmetic: httpx resolves `..` segments
when merging a relative path onto `base_url`, so an unvalidated ID of
`../../../crm/v3/objects/contacts` turns a form lookup into a CRM read.
A second check in `_attempt` refuses any request whose resolved host or path
prefix falls outside this server's declared API surface.

Retry policy
------------
Idempotent verbs (GET, HEAD, PUT, DELETE) are retried on connection errors,
timeouts, and 5xx. Non-idempotent verbs (POST, PATCH) are retried only on
connection errors — a timed-out POST may well have been applied server-side,
and retrying it would create duplicate drafts.
"""

from __future__ import annotations

import json
import re
import time
from typing import Any
from urllib.parse import quote

import httpx
import structlog
from tenacity import (
    RetryCallState,
    Retrying,
    stop_after_attempt,
    wait_exponential,
)

from .. import __version__

log = structlog.get_logger("hubspot_mcp.hubspot.client")

IDEMPOTENT_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "PUT", "DELETE"})

# Which paths this client may touch, grouped by the surface that unlocks
# them. The client is constructed with the surfaces the configuration turned
# on; everything else is refused before the request leaves the process, so a
# future f-string bug cannot reopen the traversal hole.
#
# This is the second of two lines. The first is the token itself: a key
# without CRM scopes cannot read a contact no matter what this file says,
# and HubSpot enforces that, not us. The surfaces below matter when the key
# is broader than the job — a shared service key, typically.
PATH_SURFACES: dict[str, tuple[str, ...]] = {
    "content": (
        "/cms/v3/",
        "/marketing/v3/emails",
        "/marketing/v3/forms",
        "/content/api/v2/templates",
        "/content/api/v2/pages",
        "/content/api/v2/blog-posts",
    ),
    "campaigns": ("/marketing/v3/campaigns",),
    "crm": (
        "/crm/v3/",
        "/crm/v4/",
        "/crm-objects/v1/",
        "/automation/v4/",
        "/marketing/v3/lists",
        "/marketing/v3/marketing-events",
    ),
}

# The surfaces a client gets when nobody says otherwise. Content only: no
# contact, company, deal or ticket path is reachable from here.
DEFAULT_SURFACES: tuple[str, ...] = ("content", "campaigns")

# Personal data lives behind these surfaces. Used for the boundary report the
# server prints at startup, so "no customer data can reach the model" is a
# statement someone can check rather than take on trust.
PERSONAL_DATA_SURFACES = frozenset({"crm"})


def prefixes_for(surfaces: object) -> tuple[str, ...]:
    """Flatten a set of surface names into the path prefixes they allow."""
    names = sorted(set(surfaces))
    unknown = [n for n in names if n not in PATH_SURFACES]
    if unknown:
        raise ValueError(f"Unknown API surface(s): {unknown}. Known: {sorted(PATH_SURFACES)}")
    return tuple(prefix for name in names for prefix in PATH_SURFACES[name])


MAX_LOGGED_PAYLOAD = 2000

# Which HubSpot scope a path family needs, used when HubSpot returns a 403
# without naming one. Not exhaustive — it only has to cover what this server
# calls.
_SCOPE_BY_PREFIX: tuple[tuple[str, str], ...] = (
    ("/cms/v3/blogs", "content"),
    ("/cms/v3/pages", "content"),
    ("/cms/v3/", "content"),
    ("/content/api/v2/", "content"),
    ("/marketing/v3/forms", "forms"),
    ("/marketing/v3/emails", "marketing-email"),
    ("/marketing/v3/campaigns", "marketing.campaigns.read (and .write to edit)"),
    ("/marketing/v3/lists", "crm.lists.read (and .write to edit)"),
    ("/marketing/v3/marketing-events", "marketing.events.read"),
    ("/crm/v3/objects/contacts", "crm.objects.contacts.read (and .write to edit)"),
    ("/crm/v3/objects/companies", "crm.objects.companies.read (and .write to edit)"),
    ("/crm/v3/objects/deals", "crm.objects.deals.read (and .write to edit)"),
    ("/crm/v3/objects/tickets", "tickets"),
    ("/crm/v3/properties", "crm.schemas.contacts.read, or the matching object's schema scope"),
    ("/crm/v3/owners", "crm.objects.owners.read"),
    ("/crm/v3/pipelines", "crm.pipelines.deals.read"),
    ("/crm/v4/objects", "the read scope of both objects being associated"),
    ("/crm/v4/associations", "the read scope of both objects being associated"),
    ("/automation/v4/", "automation"),
)


def _scope_for_path(path: str) -> str:
    for prefix, scope in _SCOPE_BY_PREFIX:
        if path.startswith(prefix):
            return scope
    return ""


def _required_scopes(payload: Any) -> list[str]:
    """Pull the scope names out of a HubSpot MISSING_SCOPES body.

    HubSpot has used several shapes for this over the years, so read all of
    them and deduplicate rather than betting on one.
    """
    found: list[str] = []
    if not isinstance(payload, dict):
        return found

    def collect(container: Any) -> None:
        if not isinstance(container, dict):
            return
        for key in ("requiredScopes", "requiredGranularScopes", "requiredAllScopes"):
            value = container.get(key)
            if isinstance(value, str):
                found.append(value)
            elif isinstance(value, list):
                found.extend(str(v) for v in value)

    collect(payload)
    collect(payload.get("context"))
    for error in payload.get("errors") or []:
        if isinstance(error, dict):
            collect(error)
            collect(error.get("context"))

    seen: set[str] = set()
    return [s for s in found if not (s in seen or seen.add(s))]


def scope_error_message(payload: Any, path: str) -> str:
    """Turn HubSpot's generic 403 into something the user can act on.

    HubSpot answers a key that is missing a scope with the same opaque
    sentence whatever you asked for. The useful part — which scope — is
    sometimes in the body and sometimes nowhere, so derive it from the path
    when it is absent.
    """
    if path.endswith(("/publish", "/unpublish")) and path.startswith("/marketing/v3/emails"):
        return (
            "HubSpot refused to publish this marketing email. The /publish and "
            "/unpublish endpoints need Marketing Hub Enterprise or the "
            "transactional email add-on — on any other tier they answer 403 no "
            "matter which scopes the key carries. This is a billing boundary, "
            "not a bug and not something the key can fix.\n\n"
            "The email itself is fine: open it in HubSpot and send it from "
            "there. Everything else in this server works on your tier."
        )

    scopes = _required_scopes(payload)
    if scopes:
        wanted = ", ".join(scopes)
        lead = f"Your HubSpot key is missing the scope(s): {wanted}."
    else:
        guess = _scope_for_path(path)
        lead = (
            f"HubSpot refused this call as out of scope for your key. "
            f"Based on the endpoint ({path}), the scope you need is likely: {guess}."
            if guess
            else f"HubSpot refused this call as out of scope for your key ({path})."
        )
    return (
        f"{lead}\n\n"
        "This is your key deciding what the assistant may touch, which is the "
        "boundary working as intended. To widen it: HubSpot → Settings → "
        "Integrations → Private Apps (or Service keys) → your app → Scopes → "
        "add the scope → save. A rotated or re-scoped key is a new token: paste "
        "it into your .env and restart the MCP client.\n\n"
        "If this scope covers personal data and you did not intend to give the "
        "assistant access to it, the right answer is to leave the key as it is "
        "and tell the user the request is out of scope."
    )


# HubSpot IDs are numeric; form IDs are UUIDs. Nothing legitimate needs a
# slash, a dot, or a query string.
_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def path_segment(value: object, *, field: str = "id") -> str:
    """Validate a caller-supplied value before it becomes a URL path segment."""
    text = str(value).strip()
    if not _ID_RE.match(text):
        raise ValueError(
            f"Invalid {field} {value!r}. HubSpot IDs contain only letters, digits, "
            f"'-' and '_' — no slashes, no '..', no query string. "
            f"Pass the bare ID, e.g. '95350142174'."
        )
    return quote(text, safe="")


class HubSpotError(RuntimeError):
    """A HubSpot response we want surfaced to the calling model.

    Attributes:
      status: HTTP status code.
      message: human-readable summary pulled out of HubSpot's error body.
      payload: the raw parsed body, for debugging.
    """

    def __init__(self, status: int, message: str, payload: Any = None):
        super().__init__(f"HubSpot {status}: {message}")
        self.status = status
        self.message = message
        self.payload = payload


def _truncate(payload: Any) -> Any:
    if isinstance(payload, str) and len(payload) > MAX_LOGGED_PAYLOAD:
        return payload[:MAX_LOGGED_PAYLOAD] + f"… [{len(payload) - MAX_LOGGED_PAYLOAD} more chars]"
    return payload


def _safe_json(response: httpx.Response) -> Any:
    try:
        return response.json()
    except (json.JSONDecodeError, ValueError):
        return response.text


class HubSpotClient:
    def __init__(
        self,
        *,
        access_token: str,
        api_base: str = "https://api.hubapi.com",
        timeout: float = 30.0,
        max_attempts: int = 3,
        surfaces: object = DEFAULT_SURFACES,
    ) -> None:
        if not access_token:
            raise RuntimeError(
                "No HubSpot access token. Set HUBSPOT_ACCESS_TOKEN in your .env file."
            )
        self._max_attempts = max(1, max_attempts)
        self.surfaces: frozenset[str] = frozenset(surfaces)
        self._allowed_prefixes = prefixes_for(self.surfaces)
        self._api_host = httpx.URL(api_base).host
        self._client = httpx.Client(
            base_url=api_base,
            timeout=timeout,
            # The bearer token is a client-level header. Following a redirect
            # would carry it to whatever host the redirect names.
            follow_redirects=False,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
                "User-Agent": f"hubspot-mcp-server/{__version__}",
            },
        )

    # -- lifecycle ---------------------------------------------------------
    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> HubSpotClient:
        return self

    def __exit__(self, *_exc_info: object) -> None:
        self.close()

    # -- core --------------------------------------------------------------
    def request(
        self,
        method: str,
        path: str,
        *,
        params: dict | None = None,
        json_body: Any | None = None,
    ) -> Any:
        method = method.upper()
        idempotent = method in IDEMPOTENT_METHODS

        retryer = Retrying(
            reraise=True,
            stop=stop_after_attempt(self._max_attempts),
            wait=wait_exponential(multiplier=0.5, max=4),
            retry=lambda state: self._should_retry(state, idempotent=idempotent),
            before_sleep=self._honour_retry_after,
        )

        try:
            return retryer(self._attempt, method, path, params, json_body)
        except httpx.TimeoutException as exc:
            raise HubSpotError(
                408,
                f"HubSpot did not respond within the timeout ({exc.__class__.__name__}). "
                "Check https://status.hubspot.com and retry.",
            ) from exc
        except httpx.TransportError as exc:
            raise HubSpotError(
                503,
                f"Could not reach the HubSpot API ({exc.__class__.__name__}: {exc}).",
            ) from exc

    @staticmethod
    def _honour_retry_after(state: RetryCallState) -> None:
        """Sleep out a 429's Retry-After before tenacity's own backoff."""
        outcome = state.outcome
        if outcome is None or not outcome.failed:
            return
        exc = outcome.exception()
        retry_after = getattr(exc, "retry_after", None)
        if retry_after:
            time.sleep(min(float(retry_after), 30.0))

    @staticmethod
    def _should_retry(state: RetryCallState, *, idempotent: bool) -> bool:
        outcome = state.outcome
        if outcome is None or not outcome.failed:
            return False
        exc = outcome.exception()

        # Connection-level failures: the request never landed, safe to replay.
        if isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout)):
            return True

        # Rate limiting: always worth waiting out, the call had no effect.
        if isinstance(exc, _RetryableStatus) and exc.status == 429:
            return True

        # Timeouts and 5xx: only replay when the verb is idempotent.
        if isinstance(exc, httpx.TimeoutException):
            return idempotent
        if isinstance(exc, _RetryableStatus):
            return idempotent

        return False

    def _build_and_check(
        self,
        method: str,
        path: str,
        params: dict | None,
        json_body: Any | None,
    ) -> httpx.Request:
        request = self._client.build_request(method, path, params=params, json=json_body)
        url = request.url
        if url.host != self._api_host or not url.path.startswith(self._allowed_prefixes):
            raise HubSpotError(
                400,
                f"Refusing to call {url.host}{url.path} — that is outside this server's "
                f"API surface. Enabled surfaces: {sorted(self.surfaces)}. "
                f"Either an ID contained path characters, or this call needs a surface "
                f"that the configuration has not enabled (CRM paths need ALLOW_CRM).",
            )
        return request

    def _attempt(
        self,
        method: str,
        path: str,
        params: dict | None,
        json_body: Any | None,
    ) -> Any:
        request = self._build_and_check(method, path, params, json_body)

        with structlog.contextvars.bound_contextvars(method=method, path=request.url.path):
            resp = self._client.send(request)
            duration_ms = round(resp.elapsed.total_seconds() * 1000)

            if resp.status_code >= 400:
                payload = _safe_json(resp)
                log.warning(
                    "hubspot.error",
                    status=resp.status_code,
                    duration_ms=duration_ms,
                    response=_truncate(payload),
                )
                if resp.status_code == 403:
                    message = scope_error_message(payload, request.url.path)
                else:
                    message = self._summarize_error(payload, resp.status_code)
                if resp.status_code == 429 or 500 <= resp.status_code < 600:
                    # Raised so the retry predicate can see it; still a
                    # HubSpotError once attempts are exhausted.
                    err = _RetryableStatus(resp.status_code, message, payload)
                    err.retry_after = resp.headers.get("Retry-After")
                    raise err
                raise HubSpotError(resp.status_code, message, payload)

            log.info("hubspot.ok", status=resp.status_code, duration_ms=duration_ms)

            if resp.status_code == 204 or not resp.content:
                return None
            return _safe_json(resp)

    @staticmethod
    def _summarize_error(payload: Any, status: int) -> str:
        if isinstance(payload, dict):
            for key in ("message", "error", "errorType"):
                value = payload.get(key)
                if value:
                    return str(value)
            errors = payload.get("errors")
            if isinstance(errors, list) and errors:
                first = errors[0]
                if isinstance(first, dict) and first.get("message"):
                    return str(first["message"])
        if isinstance(payload, str) and payload.strip():
            return payload.strip()[:300]
        return f"HTTP {status}"

    # -- shortcuts ---------------------------------------------------------
    def get(self, path: str, **kwargs: Any) -> Any:
        return self.request("GET", path, **kwargs)

    def post(self, path: str, **kwargs: Any) -> Any:
        return self.request("POST", path, **kwargs)

    def patch(self, path: str, **kwargs: Any) -> Any:
        return self.request("PATCH", path, **kwargs)

    def put(self, path: str, **kwargs: Any) -> Any:
        return self.request("PUT", path, **kwargs)

    def delete(self, path: str, **kwargs: Any) -> Any:
        return self.request("DELETE", path, **kwargs)


class _RetryableStatus(HubSpotError):
    """Internal marker for 429/5xx so the retry predicate can spot them.

    Subclasses HubSpotError so that, once retries are exhausted and tenacity
    re-raises, callers still receive a well-formed HubSpotError.
    """

    retry_after: str | None = None
