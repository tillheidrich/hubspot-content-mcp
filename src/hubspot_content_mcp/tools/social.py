"""MCP tool for generating a HubSpot social bulk-upload XLSX file."""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from ..social.xlsx_writer import SocialXLSXError, generate_social_bulk_xlsx


def register(mcp: FastMCP, context: dict[str, Any]) -> None:
    settings = context["settings"]

    @mcp.tool()
    def generate_social_bulk_xlsx_file(
        posts: list[dict[str, Any]],
        output_filename: str | None = None,
        timezone: str | None = None,
    ) -> dict[str, Any]:
        """Write a HubSpot-format Excel file for scheduling social posts in bulk.

        HubSpot has no public social publishing API, so this is the supported
        route: generate the file here, then upload it under
        Marketing → Social → 'Schedule in bulk'. HubSpot previews every post
        before anything goes out — this tool never publishes.

        Args:
          posts: list of post objects, at most 300. Each requires:
            - account: the account name exactly as configured in HubSpot,
              e.g. "Acme Inc - LinkedIn". A mismatch here is the most common
              reason HubSpot rejects the upload.
            - scheduled_at: ISO 8601 datetime, e.g. "2026-01-13T09:00:00".
            - message: the post text.
            Optional per post:
            - link_url: URL to attach.
            - image_url: image URL, already reachable on the public internet.
          output_filename: bare filename for the output. Defaults to
            social_schedule_<today>.xlsx. Any directory part is stripped.
          timezone: IANA timezone for interpreting and formatting the dates,
            e.g. 'Europe/Berlin'. Defaults to the server's DEFAULT_TIMEZONE.

        Returns the file path, post count, accounts, date range, and a
        `warnings` list when a message looks too long for its platform.
        """
        tz = timezone or settings.default_timezone
        try:
            return generate_social_bulk_xlsx(
                posts,
                output_dir=settings.output_dir,
                output_filename=output_filename,
                timezone=tz,
            )
        except SocialXLSXError as exc:
            # Raise so MCP marks the call as failed; returning an {"error": ...}
            # dict would look like success to the caller.
            raise ValueError(str(exc)) from None
