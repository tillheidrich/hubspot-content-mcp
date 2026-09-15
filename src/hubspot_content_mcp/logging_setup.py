"""Structlog configuration. Log output goes to a file, never to stdout.

stdout carries the MCP wire protocol, so a stray print() or log line there
corrupts the session. Only errors go to stderr, where the MCP client shows
them to the user.

Redaction runs at two levels, because a token can arrive by more than one
route: as a structured key (`token=...`), nested inside a logged HubSpot
error body, or embedded in an exception message that the stdlib formatter
appends as a traceback.
"""

from __future__ import annotations

import logging
import logging.handlers
import re
import sys
from pathlib import Path
from typing import Any

import structlog

REDACTED = "***redacted***"

# Keys whose values are blanked wherever they appear, at any nesting depth.
_SENSITIVE_KEYS = {
    "hubspot_access_token",
    "access_token",
    "authorization",
    "token",
    "api_key",
    "apikey",
    "secret",
    "password",
    "client_secret",
}

# HubSpot tokens and bearer headers, matched anywhere in a string. This is the
# backstop for values that are not under a sensitive key — exception text,
# nested API error bodies, tracebacks.
_TOKEN_RE = re.compile(
    r"(pat-[a-z0-9]+-[0-9a-fA-F-]{8,}|Bearer\s+[A-Za-z0-9._\-]+)",
    re.IGNORECASE,
)

_MAX_DEPTH = 6

# HTTP libraries log full request headers at DEBUG — including the bearer
# token. Pinned to WARNING so LOG_LEVEL=DEBUG stays safe to hand to a user.
_NOISY_LIBRARIES = ("httpx", "httpcore", "hpack", "h11", "urllib3", "asyncio", "anyio")


def scrub(value: Any, depth: int = 0) -> Any:
    """Recursively blank credential-looking keys and token-shaped strings."""
    if depth > _MAX_DEPTH:
        return value
    if isinstance(value, str):
        return _TOKEN_RE.sub(REDACTED, value)
    if isinstance(value, dict):
        return {
            key: (REDACTED if str(key).lower() in _SENSITIVE_KEYS else scrub(sub_value, depth + 1))
            for key, sub_value in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [scrub(item, depth + 1) for item in value]
    return value


def _redact(_logger, _method, event_dict):
    return scrub(event_dict)


class RedactingFormatter(logging.Formatter):
    """Catches tokens in anything the stdlib appends, tracebacks included."""

    def format(self, record: logging.LogRecord) -> str:
        return _TOKEN_RE.sub(REDACTED, super().format(record))


def setup_logging(log_dir: Path, level: str = "INFO") -> structlog.stdlib.BoundLogger:
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "server.log"

    file_handler = logging.handlers.TimedRotatingFileHandler(
        log_path, when="midnight", backupCount=30, encoding="utf-8"
    )
    file_handler.setFormatter(RedactingFormatter("%(message)s"))

    stderr_handler = logging.StreamHandler(sys.stderr)
    stderr_handler.setLevel(logging.ERROR)
    stderr_handler.setFormatter(RedactingFormatter("[hubspot-content-mcp] %(message)s"))

    root = logging.getLogger()
    for existing in list(root.handlers):
        root.removeHandler(existing)
    root.addHandler(file_handler)
    root.addHandler(stderr_handler)

    # DEBUG applies to our own loggers only. Third-party libraries stay at
    # INFO or above no matter what, so nothing can widen the blast radius by
    # logging a request header.
    requested = getattr(logging, level.upper(), logging.INFO)
    root.setLevel(max(requested, logging.INFO))
    logging.getLogger("hubspot_content_mcp").setLevel(requested)

    for name in _NOISY_LIBRARIES:
        logging.getLogger(name).setLevel(logging.WARNING)

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            _redact,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    return structlog.get_logger("hubspot_content_mcp")
