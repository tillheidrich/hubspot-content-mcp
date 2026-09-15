"""CLI entry point.

Default: run the MCP server over stdio, which is how an MCP client starts it.
--test-connection: check credentials and scopes, then exit.
"""

from __future__ import annotations

import argparse
import sys

from . import __version__
from .config import Settings
from .logging_setup import setup_logging


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="hubspot-mcp-server",
        description=(
            "Local MCP server for HubSpot. Content, publishing and campaigns by "
            "default; CRM only when ALLOW_CRM says so."
        ),
    )
    parser.add_argument(
        "--test-connection",
        action="store_true",
        help="Verify the HubSpot token and scopes, print a report, then exit.",
    )
    parser.add_argument(
        "--log-level",
        default=None,
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Override LOG_LEVEL from the environment.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"hubspot-mcp-server {__version__}",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    try:
        settings = Settings.load(require_token=True)
    except RuntimeError as exc:
        print(f"Configuration error:\n{exc}", file=sys.stderr)
        return 2

    log = setup_logging(settings.log_dir, level=args.log_level or settings.log_level)
    log.info(
        "startup",
        version=__version__,
        api_base=settings.hubspot_api_base,
        portal_id=settings.hubspot_portal_id or "(unset)",
        timezone=settings.default_timezone,
        output_dir=str(settings.output_dir),
    )

    if args.test_connection:
        return run_connection_test(settings)

    from .server import build_server

    server = build_server(settings)
    try:
        server.run()
    finally:
        client = getattr(server, "_hubspot_client", None)
        if client is not None:
            client.close()
    return 0


def run_connection_test(settings: Settings) -> int:
    """Read-only checks against every API area this configuration enables.

    Also prints the data boundary, because the claim worth checking is not
    "the token works" but "what can this thing reach". Read-only throughout:
    nothing here creates, changes or publishes anything.
    """
    from .hubspot import blog, campaigns, discovery, emails, forms, pages
    from .hubspot.client import DEFAULT_SURFACES, HubSpotClient, HubSpotError

    surfaces = list(DEFAULT_SURFACES) + (["crm"] if settings.crm_enabled else [])
    client = HubSpotClient(
        access_token=settings.hubspot_access_token,
        api_base=settings.hubspot_api_base,
        surfaces=surfaces,
    )

    checks: list[tuple[str, str, object]] = [
        ("Landing pages", "content", lambda: pages.list_pages(client, "landing", limit=1)[0]),
        ("Site pages", "content", lambda: pages.list_pages(client, "site", limit=1)[0]),
        ("Blogs", "content", lambda: blog.list_blogs(client, limit=5)),
        ("Blog posts", "content", lambda: blog.list_blog_posts(client, limit=1)[0]),
        ("Forms", "forms", lambda: forms.list_forms(client, limit=1)[0]),
        ("Marketing emails", "content", lambda: emails.list_emails(client, limit=1)[0]),
        ("Domains", "content", lambda: discovery.list_domains(client, limit=1)),
        (
            "Campaigns",
            "marketing.campaigns.read",
            lambda: campaigns.list_campaigns(client, limit=1),
        ),
        ("Templates (optional)", "content", lambda: discovery.list_templates(client, limit=1)),
    ]

    if settings.crm_enabled:
        from .hubspot import crm

        checks += [
            (
                "CRM contacts",
                "crm.objects.contacts.read",
                lambda: crm.list_objects(client, "contacts", limit=1),
            ),
            (
                "CRM companies",
                "crm.objects.companies.read",
                lambda: crm.list_objects(client, "companies", limit=1),
            ),
            (
                "CRM deals",
                "crm.objects.deals.read",
                lambda: crm.list_objects(client, "deals", limit=1),
            ),
            ("CRM owners (optional)", "crm.objects.owners.read", lambda: crm.list_owners(client)),
            (
                "Contact lists (optional)",
                "crm.lists.read",
                lambda: crm.search_lists(client, limit=1),
            ),
            ("Workflows (optional)", "automation", lambda: crm.list_workflows(client, limit=1)),
        ]

    out = sys.stderr
    print(f"hubspot-mcp-server {__version__} — connection test", file=out)
    print(f"  API base:   {settings.hubspot_api_base}", file=out)
    print(
        f"  Portal ID:  {settings.hubspot_portal_id or '(not set — edit URLs disabled)'}", file=out
    )
    print(f"  Output dir: {settings.output_dir}", file=out)
    print(f"  Log dir:    {settings.log_dir}", file=out)
    print("", file=out)

    print("  What this configuration can reach", file=out)
    print("  ---------------------------------", file=out)
    publish = ", ".join(sorted(settings.publish_scope)) or "nothing — drafts only"
    print(f"  Publishing:     {publish}", file=out)
    print(f"  CRM access:     {settings.crm_scope or 'off'}", file=out)
    if settings.crm_enabled:
        print(
            "  Personal data:  REACHABLE. Records the assistant reads are copied\n"
            "                  into the conversation and reach your model provider.",
            file=out,
        )
    else:
        print(
            "  Personal data:  out of reach. No CRM tool is registered and the\n"
            "                  HTTP client refuses every CRM path, so no customer\n"
            "                  data can enter a conversation.",
            file=out,
        )
    print("", file=out)
    print(
        "  Your key's scopes are the outer limit either way — they are enforced\n"
        "  by HubSpot, not by this server. The probes below show what they allow.",
        file=out,
    )
    print("", file=out)

    failures = 0
    for name, scope, probe in checks:
        optional = "(optional)" in name
        try:
            result = probe()  # type: ignore[operator]
            count = len(result) if isinstance(result, list) else 1
            print(f"  [ OK ] {name}: {count} item(s) readable", file=out)
        except HubSpotError as exc:
            marker = "WARN" if optional else "FAIL"
            if not optional:
                failures += 1
            hint = f" — needs the '{scope}' scope" if exc.status in (401, 403) else ""
            print(f"  [{marker}] {name}: HTTP {exc.status}{hint}", file=out)
            first_line = exc.message.strip().splitlines()[0] if exc.message else ""
            print(f"         {first_line}", file=out)
        except Exception as exc:  # noqa: BLE001
            if not optional:
                failures += 1
            print(f"  [FAIL] {name}: {exc.__class__.__name__}: {exc}", file=out)

    client.close()
    print("", file=out)

    if failures == 0:
        print("All required checks passed. Ready to register with an MCP client.", file=out)
        return 0

    print(
        f"{failures} check(s) failed. Each line above names the scope it wanted. "
        "Add it to the private app or service key in HubSpot, save, then paste the "
        "new token into .env — re-scoping issues a new one. Also check the token "
        "was copied without surrounding whitespace.",
        file=out,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
