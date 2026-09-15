"""Configuration: loads .env, exposes a frozen Settings object.

Two things here are security-relevant rather than merely tidy.

`.env` discovery does not walk up the directory tree. python-dotenv's
`find_dotenv(usecwd=True)` searches every ancestor of the working directory,
so running the server from inside an untrusted checkout would let that
checkout's `.env` supply a `HUBSPOT_API_BASE` — and the bearer token goes
wherever that points. We look only at the current directory, or at an
explicit path the operator names.

`HUBSPOT_API_BASE` is validated against an allow-list for the same reason.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import load_dotenv

APP_DIR_NAME = ".hubspot-content-mcp"

# The token is attached to every request as a bearer header, so the host it
# is sent to is a security decision, not a configuration convenience.
ALLOWED_API_HOSTS = frozenset({"api.hubapi.com", "api.hubapiqa.com", "localhost", "127.0.0.1"})

# Content areas that may be published. Publishing is ON by default; set
# ALLOW_PUBLISH=none for an install that can only ever produce drafts.
PUBLISHABLE_AREAS = frozenset({"pages", "blog", "emails"})

# CRM access levels, in increasing order. Each includes the ones before it.
#   read  — search and read objects, properties, owners, pipelines, lists
#   write — create, update, associate, add to lists, enrol in workflows
#   all   — archive and delete, batch imports, workflow state changes
CRM_LEVELS: tuple[str, ...] = ("read", "write", "all")

_EDIT_URL_PREFIX = {
    "landing-page": "content-editor",
    "site-page": "content-editor",
    "blog-post": "blog",
    "email": "email/edit",
    "form": "forms/edit",
    "campaign": "campaigns",
}

# CRM record deep links follow a different shape: /contacts/{portal}/record/{objectTypeId}/{id}
_CRM_OBJECT_TYPE_IDS = {
    "contacts": "0-1",
    "companies": "0-2",
    "deals": "0-3",
    "tickets": "0-5",
    "products": "0-7",
    "line_items": "0-8",
    "quotes": "0-14",
}

_TRUTHY = {"1", "true", "yes", "on"}


def _env(key: str, default: str | None = None, required: bool = False) -> str:
    value = os.environ.get(key, default)
    if required and not value:
        raise RuntimeError(
            f"Environment variable {key} is required but not set.\n"
            f"Copy .env.example to .env and fill in your HubSpot credentials, "
            f"or export {key} in your shell."
        )
    return value or ""


def _flag(key: str) -> bool:
    return _env(key, default="").strip().lower() in _TRUTHY


def _resolve_dir(raw: str, fallback: Path) -> Path:
    if not raw:
        return fallback
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = (Path.cwd() / path).resolve()
    return path


def _validate_api_base(raw: str) -> str:
    parts = urlsplit(raw)
    host = parts.hostname
    if not host:
        raise RuntimeError(f"HUBSPOT_API_BASE is not a valid URL: {raw!r}")
    if parts.scheme != "https" and host not in {"localhost", "127.0.0.1"}:
        raise RuntimeError(
            f"HUBSPOT_API_BASE must use https, got {raw!r}. Your access token is sent "
            f"as a bearer header on every request and would travel in cleartext."
        )
    if host not in ALLOWED_API_HOSTS:
        raise RuntimeError(
            f"HUBSPOT_API_BASE host {host!r} is not allowed. Expected one of "
            f"{sorted(ALLOWED_API_HOSTS)}. Pointing this elsewhere would send your "
            f"HubSpot token to that host."
        )
    return raw.rstrip("/")


def _parse_publish_scope(raw: str) -> frozenset[str]:
    """Parse ALLOW_PUBLISH into the set of publishable areas."""
    value = raw.strip().lower()
    if not value or value in {"none", "off", "false", "0"}:
        return frozenset()
    if value in {"all", "true", "1", "yes"}:
        return frozenset(PUBLISHABLE_AREAS)

    areas = {part.strip() for part in value.split(",") if part.strip()}
    unknown = areas - PUBLISHABLE_AREAS
    if unknown:
        raise RuntimeError(
            f"ALLOW_PUBLISH contains unknown area(s): {sorted(unknown)}. "
            f"Valid values: none, all, or a comma-separated subset of "
            f"{sorted(PUBLISHABLE_AREAS)}."
        )
    return frozenset(areas)


def _parse_crm_scope(raw: str) -> str:
    """Parse ALLOW_CRM into one of '', 'read', 'write', 'all'.

    Empty means the CRM module is never imported, its tools are never
    registered, and the client refuses CRM paths outright. That is the
    default: a content assistant has no business reading contact records
    unless someone decided it should.
    """
    value = raw.strip().lower()
    if not value or value in {"none", "off", "false", "0"}:
        return ""
    if value in {"true", "1", "yes", "on"}:
        return "all"
    if value not in CRM_LEVELS:
        raise RuntimeError(
            f"ALLOW_CRM={raw!r} is not a level I know. Use one of: none, "
            f"{', '.join(CRM_LEVELS)}. Each level includes the ones before it — "
            f"'write' can read, 'all' adds archiving, deletion and imports."
        )
    return value


def _find_dotenv() -> str:
    """Locate .env without walking up into directories we do not control."""
    explicit = os.environ.get("HUBSPOT_MCP_ENV_FILE", "").strip()
    if explicit:
        candidate = Path(explicit).expanduser()
        if not candidate.is_file():
            raise RuntimeError(f"HUBSPOT_MCP_ENV_FILE points at {candidate}, which does not exist.")
        return str(candidate)

    candidate = Path.cwd() / ".env"
    return str(candidate) if candidate.is_file() else ""


def build_edit_url(kind: str, content_id: str, portal_id: str) -> str:
    """HubSpot UI deep link for a piece of content. Empty string if unknown."""
    if not portal_id or not content_id:
        return ""
    prefix = _EDIT_URL_PREFIX.get(kind, "content-editor")
    return f"https://app.hubspot.com/{prefix}/{portal_id}/{content_id}"


def build_record_url(object_type: str, record_id: str, portal_id: str) -> str:
    """HubSpot UI deep link for a CRM record. Empty string if unknown."""
    if not portal_id or not record_id:
        return ""
    type_id = _CRM_OBJECT_TYPE_IDS.get(object_type.lower())
    if not type_id:
        return ""
    return f"https://app.hubspot.com/contacts/{portal_id}/record/{type_id}/{record_id}"


@dataclass(frozen=True)
class Settings:
    hubspot_access_token: str
    hubspot_portal_id: str
    hubspot_api_base: str
    default_timezone: str
    log_level: str
    output_dir: Path
    log_dir: Path
    base_dir: Path
    publish_scope: frozenset[str] = field(default_factory=frozenset)
    crm_scope: str = ""
    allow_raw_html: bool = False

    @property
    def publishing_enabled(self) -> bool:
        return bool(self.publish_scope)

    def may_publish(self, area: str) -> bool:
        return area in self.publish_scope

    @property
    def crm_enabled(self) -> bool:
        return bool(self.crm_scope)

    def crm_allows(self, level: str) -> bool:
        """True when the configured CRM scope reaches at least `level`."""
        if not self.crm_scope:
            return False
        return CRM_LEVELS.index(self.crm_scope) >= CRM_LEVELS.index(level)

    @classmethod
    def load(cls, *, require_token: bool = True) -> Settings:
        dotenv_path = _find_dotenv()
        if dotenv_path:
            load_dotenv(dotenv_path)
            base_dir = Path(dotenv_path).resolve().parent
        else:
            base_dir = Path.home() / APP_DIR_NAME

        token = _env("HUBSPOT_ACCESS_TOKEN", required=require_token).strip()
        portal = _env("HUBSPOT_PORTAL_ID", default="").strip()
        api_base = _validate_api_base(_env("HUBSPOT_API_BASE", default="https://api.hubapi.com"))
        timezone = _env("DEFAULT_TIMEZONE", default="UTC")
        log_level = _env("LOG_LEVEL", default="INFO").upper()
        publish_scope = _parse_publish_scope(_env("ALLOW_PUBLISH", default="all"))
        crm_scope = _parse_crm_scope(_env("ALLOW_CRM", default="none"))
        allow_raw_html = _flag("ALLOW_RAW_HTML")

        output_dir = _resolve_dir(_env("OUTPUT_DIR"), base_dir / "output")
        log_dir = _resolve_dir(_env("LOG_DIR"), base_dir / "logs")
        output_dir.mkdir(parents=True, exist_ok=True)
        log_dir.mkdir(parents=True, exist_ok=True)

        return cls(
            hubspot_access_token=token,
            hubspot_portal_id=portal,
            hubspot_api_base=api_base,
            default_timezone=timezone,
            log_level=log_level,
            output_dir=output_dir,
            log_dir=log_dir,
            base_dir=base_dir,
            publish_scope=publish_scope,
            crm_scope=crm_scope,
            allow_raw_html=allow_raw_html,
        )

    def edit_url(self, *, kind: str, content_id: str) -> str:
        return build_edit_url(kind, content_id, self.hubspot_portal_id)
