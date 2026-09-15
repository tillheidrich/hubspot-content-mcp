"""MCP tools for marketing emails. Drafts only — nothing is ever sent."""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from ..hubspot import emails as hub_emails
from ..models.common import email_summary, wrap_untrusted


def register(mcp: FastMCP, context: dict[str, Any]) -> None:
    client = context["client"]
    portal = context["settings"].hubspot_portal_id

    @mcp.tool()
    def list_marketing_emails(
        name_contains: str | None = None,
        published_only: bool | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        """List marketing emails.

        Args:
          name_contains: case-insensitive substring of the email name.
          published_only: True lists published emails, False lists unpublished
            ones, omit for both. HubSpot's email API has no general state
            filter, only this flag.
          limit: maximum results, 1-100. Default 20.
        """
        rows, truncated = hub_emails.list_emails(
            client,
            name_contains=name_contains,
            is_published=published_only,
            limit=limit,
        )
        out: dict[str, Any] = {
            "results": [email_summary(e, portal_id=portal) for e in rows],
            "count": len(rows),
        }
        if truncated:
            out["note"] = "Search stopped early — there may be more matches."
        return out

    @mcp.tool()
    def get_marketing_email(
        email_id: str, include_content: bool = False, draft: bool = True
    ) -> dict[str, Any]:
        """Fetch one marketing email.

        Args:
          email_id: HubSpot email ID.
          include_content: set True to include the full content/widgets tree.
            That payload is large — only ask for it when editing content.
          draft: True (default) reads the draft version, False reads live.
        """
        raw = hub_emails.get_email(client, email_id, draft=draft)
        if include_content:
            return wrap_untrusted(raw, kind="marketing-email")
        summary = email_summary(raw, portal_id=portal)
        summary["template_path"] = (raw.get("content") or {}).get("templatePath")
        summary["version"] = "draft" if draft else "live"
        summary["note"] = "Call again with include_content=True to see the body."
        return summary

    @mcp.tool()
    def create_marketing_email_draft(
        name: str,
        subject: str,
        template_path: str,
        html_body: str | None = None,
        widgets: dict[str, Any] | None = None,
        from_name: str | None = None,
        reply_to: str | None = None,
        preview_text: str | None = None,
        language: str = "en",
        email_type: str = "BATCH_EMAIL",
        subscription_type_id: int | None = None,
        business_unit_id: str | None = None,
    ) -> dict[str, Any]:
        """Create a marketing email in DRAFT state. Nothing is scheduled or sent.

        Args:
          name: internal email name shown in the HubSpot listing.
          subject: subject line.
          template_path: path of the email template to render into, e.g.
            '@marketplace/theme/templates/email/base.html'. Required by HubSpot —
            widgets have nothing to render into without one.
          html_body: HTML for the template's main rich-text module. Convenience
            shortcut for widgets={"main_content": {"body": {"html": ...}}}.
          widgets: explicit widget tree when the template uses several modules.
            Keys are the module names defined in the template. Takes precedence
            over html_body for any overlapping key.
          from_name: sender display name. Portal default is used if omitted.
          reply_to: reply-to address.
          preview_text: preheader shown in the inbox next to the subject.
          language: ISO 639-1 code. Default 'en'.
          email_type: BATCH_EMAIL | AB_EMAIL | AUTOMATED_EMAIL. Default BATCH_EMAIL.
          subscription_type_id: HubSpot subscription type. Marketing emails cannot
            be sent without one, so set it if you know it.
          business_unit_id: only for portals using Business Units.
        """
        widget_tree: dict[str, Any] = {}
        if html_body:
            widget_tree["main_content"] = {"body": {"html": html_body}}
        if preview_text:
            widget_tree["preview_text"] = {"body": {"value": preview_text}}
        if widgets:
            widget_tree.update(widgets)

        if not widget_tree:
            raise ValueError("Provide html_body or widgets — otherwise the email has no content.")

        sender: dict[str, Any] = {}
        if from_name:
            sender["fromName"] = from_name
        if reply_to:
            sender["replyTo"] = reply_to

        payload: dict[str, Any] = {
            "name": name,
            "subject": subject,
            "type": email_type,
            "language": language,
            "content": {
                "templatePath": template_path,
                "widgets": widget_tree,
            },
        }
        if sender:
            payload["from"] = sender
        if subscription_type_id is not None:
            payload["subscriptionDetails"] = {"subscriptionId": subscription_type_id}
        if business_unit_id:
            payload["businessUnitId"] = business_unit_id

        created = hub_emails.create_email(client, payload)
        out = email_summary(created, portal_id=portal)
        if subscription_type_id is None:
            out["note"] = (
                "No subscription_type_id was set. HubSpot will not let this email "
                "be sent until a subscription type is chosen in the UI."
            )
        return out

    @mcp.tool()
    def update_marketing_email_draft(email_id: str, fields: dict[str, Any]) -> dict[str, Any]:
        """Patch a marketing email's DRAFT. The published version is never touched.

        Args:
          email_id: HubSpot email ID.
          fields: any of name, subject, language, content, from, to,
            subscriptionDetails, businessUnitId, campaign.

        Anything that would publish or send the email is refused and reported
        in `rejected_fields`.
        """
        safe, rejected = hub_emails.sanitize_email_fields(fields)
        if not safe:
            raise ValueError(
                f"No writable fields supplied. Rejected: {rejected or list(fields)}. "
                f"Allowed: {sorted(hub_emails.ALLOWED_EMAIL_FIELDS)}"
            )
        updated = hub_emails.update_email_draft(client, email_id, safe)
        out = email_summary(updated, portal_id=portal)
        out["updated_fields"] = sorted(safe)
        if rejected:
            out["rejected_fields"] = rejected
        return out

    @mcp.tool()
    def duplicate_marketing_email(source_id: str, new_name: str) -> dict[str, Any]:
        """Duplicate a marketing email — the usual way to start next month's newsletter.

        Args:
          source_id: ID of the email to copy.
          new_name: internal name for the copy.
        """
        cloned = hub_emails.clone_email(client, source_id, clone_name=new_name)
        if not isinstance(cloned, dict) or not cloned.get("id"):
            raise RuntimeError(
                f"HubSpot returned no email ID when cloning {source_id}. Response: {cloned!r}"
            )
        out = email_summary(cloned, portal_id=portal)
        out["source_id"] = source_id
        return out
