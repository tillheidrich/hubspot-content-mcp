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

log = structlog.get_logger("hubspot_content_mcp.hubspot.client")

IDEMPOTENT_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "PUT", "DELETE"})

# Every path this server is allowed to touch. Anything else is refused before
# the request leaves the process, so a future f-string bug cannot reopen the
# traversal hole.
ALLOWED_PATH_PREFIXES: tuple[str, ...] = (
    "/cms/v3/",
    "/marketing/v3/emails",
    "/marketing/v3/forms",
    "/content/api/v2/templates",
    "/content/api/v2/pages",
    "/content/api/v2/blog-posts",
)

MAX_LOGGED_PAYLOAD = 2000

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
    ) -> None:
        if not access_token:
            raise RuntimeError(
                "No HubSpot access token. Set HUBSPOT_ACCESS_TOKEN in your .env file."
            )
        self._max_attempts = max(1, max_attempts)
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
                "User-Agent": f"hubspot-content-mcp/{__version__}",
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
        if url.host != self._api_host or not url.path.startswith(ALLOWED_PATH_PREFIXES):
            raise HubSpotError(
                400,
                f"Refusing to call {url.host}{url.path} — that is outside this server's "
                f"API surface. This usually means an ID contained path characters.",
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
