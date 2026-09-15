"""MCP tools for HubSpot forms.

The v3 Forms API has no DRAFT state — a form exists as soon as it is created.
What this server does not do is embed the form anywhere or submit to it, so a
newly created form is inert until you place it on a page yourself.
"""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from ..hubspot import forms as hub_forms
from ..models.common import form_summary, wrap_untrusted

# Simplified type name -> HubSpot v3 fieldType
FIELD_TYPE_MAP = {
    "single_line_text": "single_line_text",
    "multi_line_text": "multi_line_text",
    "email": "single_line_text",
    "phone": "phone",
    "number": "number",
    "dropdown": "dropdown",
    "radio": "radio",
    "checkbox": "multiple_checkboxes",
    "multiple_checkboxes": "multiple_checkboxes",
    "single_checkbox": "single_checkbox",
    "date": "datepicker",
    "datepicker": "datepicker",
    "file": "file",
}

# Field types that require an `options` list.
NEEDS_OPTIONS = {"dropdown", "radio", "multiple_checkboxes"}

DEFAULT_CONFIGURATION: dict[str, Any] = {
    "cloneable": True,
    "editable": True,
    "archivable": True,
    "recaptchaEnabled": False,
    "notifyContactOwner": False,
    "notifyRecipients": [],
    "createNewContactForNewEmail": False,
    "allowLinkToResetKnownValues": False,
    "lifecycleStages": [],
}

DEFAULT_DISPLAY_OPTIONS: dict[str, Any] = {
    "renderRawHtml": False,
    "cssClass": "",
    "theme": "default_style",
    "submitButtonText": "Submit",
    "style": {},
}


def _normalize_options(raw: Any, field_name: str) -> list[dict[str, Any]]:
    """Accept ['a','b'] or [{'value':'a','label':'A'}] and normalize."""
    if not isinstance(raw, list) or not raw:
        raise ValueError(f"Field {field_name!r} needs a non-empty 'options' list.")
    options: list[dict[str, Any]] = []
    for index, option in enumerate(raw):
        if isinstance(option, str):
            options.append({"label": option, "value": option, "displayOrder": index})
        elif isinstance(option, dict):
            value = option.get("value", option.get("label"))
            label = option.get("label", value)
            if value is None:
                raise ValueError(
                    f"Option #{index + 1} of field {field_name!r} needs a 'value' or 'label'."
                )
            options.append({"label": str(label), "value": str(value), "displayOrder": index})
        else:
            raise ValueError(
                f"Option #{index + 1} of field {field_name!r} must be a string or an object."
            )
    return options


def build_field_group(field: dict[str, Any], index: int) -> dict[str, Any]:
    """Turn a simplified field spec into a HubSpot v3 fieldGroup."""
    if not isinstance(field, dict):
        raise ValueError(f"Field #{index + 1} must be an object, got {type(field).__name__}.")

    name = field.get("name")
    if not name:
        raise ValueError(
            f"Field #{index + 1} is missing 'name' — the HubSpot contact property "
            f"internal name, e.g. 'firstname', 'email', 'company'. "
            f"Supplied keys: {sorted(field)}"
        )

    requested_type = str(field.get("type", "single_line_text"))
    field_type = FIELD_TYPE_MAP.get(requested_type)
    if field_type is None:
        raise ValueError(
            f"Field {name!r} has unknown type {requested_type!r}. "
            f"Valid types: {sorted(FIELD_TYPE_MAP)}"
        )

    entry: dict[str, Any] = {
        "objectTypeId": field.get("objectTypeId", "0-1"),  # 0-1 = contact
        "name": name,
        "label": field.get("label", name),
        "required": bool(field.get("required", False)),
        "hidden": bool(field.get("hidden", False)),
        "fieldType": field_type,
    }
    if field_type in NEEDS_OPTIONS:
        entry["options"] = _normalize_options(field.get("options"), name)
    if field.get("placeholder"):
        entry["placeholder"] = field["placeholder"]
    if field.get("description"):
        entry["description"] = field["description"]
    if "defaultValue" in field:
        entry["defaultValues"] = [field["defaultValue"]]

    return {"groupType": "default_group", "richTextType": "text", "fields": [entry]}


def register(mcp: FastMCP, context: dict[str, Any]) -> None:
    client = context["client"]
    portal = context["settings"].hubspot_portal_id

    @mcp.tool()
    def list_forms(
        name_contains: str | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        """List forms in the portal.

        Args:
          name_contains: case-insensitive substring of the form name.
          limit: maximum results, 1-100. Default 50.
        """
        rows, truncated = hub_forms.list_forms(client, name_contains=name_contains, limit=limit)
        out: dict[str, Any] = {
            "results": [form_summary(f, portal_id=portal) for f in rows],
            "count": len(rows),
        }
        if truncated:
            out["note"] = "Search stopped early — there may be more matches."
        return out

    @mcp.tool()
    def get_form(form_id: str, include_fields: bool = False) -> dict[str, Any]:
        """Fetch one form.

        Args:
          form_id: HubSpot form ID (a UUID).
          include_fields: True (default) returns the full fieldGroups tree.
            Set False for just the summary.
        """
        raw = hub_forms.get_form(client, form_id)
        if include_fields:
            return wrap_untrusted(raw, kind="form")
        return form_summary(raw, portal_id=portal)

    @mcp.tool()
    def create_form(
        name: str,
        fields: list[dict[str, Any]],
        submit_button_text: str = "Submit",
        success_message: str = "Thanks — we'll be in touch.",
        language: str = "en",
    ) -> dict[str, Any]:
        """Create a HubSpot form.

        NOT a draft. HubSpot's v3 Forms API has no draft state, so this form is
        live and submittable the moment it is created. What keeps it inert is
        that it is not embedded anywhere — you place it on a page yourself once
        you have reviewed it. Say this to the user when you create one.

        Args:
          name: form name shown in the HubSpot listing.
          fields: list of simplified field specs, in display order. Each entry:
            {
              "name": "firstname",          # required: contact property internal name
              "label": "First name",
              "type": "single_line_text",   # see below
              "required": true,
              "hidden": false,
              "options": ["A", "B"],        # required for dropdown/radio/checkbox
              "placeholder": "...",
              "description": "..."
            }
            Types: single_line_text, multi_line_text, email, phone, number,
            dropdown, radio, checkbox, single_checkbox, date, file.
          submit_button_text: label on the submit button.
          success_message: message shown after a successful submission.
          language: ISO 639-1 code. Default 'en'.

        Note on consent: GDPR consent options are not set here, because they
        need a lawful basis and subscription type IDs that vary per portal.
        Configure consent in the HubSpot form editor after creation.
        """
        if not fields:
            raise ValueError("Provide at least one field.")

        field_groups = [build_field_group(f, i) for i, f in enumerate(fields)]

        payload: dict[str, Any] = {
            "name": name,
            "formType": hub_forms.CREATABLE_FORM_TYPE,
            "fieldGroups": field_groups,
            "configuration": {
                **DEFAULT_CONFIGURATION,
                "language": language,
                "postSubmitAction": {"type": "thank_you_message", "value": success_message},
            },
            "displayOptions": {
                **DEFAULT_DISPLAY_OPTIONS,
                "submitButtonText": submit_button_text,
            },
        }

        created = hub_forms.create_form(client, payload)
        out = form_summary(created, portal_id=portal)
        out["field_count"] = len(fields)
        out["note"] = (
            "Form created. Review it in the HubSpot form editor, set consent "
            "options if you need them, then embed it on a page."
        )
        return out

    @mcp.tool()
    def update_form(form_id: str, fields: dict[str, Any]) -> dict[str, Any]:
        """Patch a form.

        Args:
          form_id: HubSpot form ID.
          fields: any of name, fieldGroups, configuration, displayOptions,
            legalConsentOptions.

        To change the field set, call get_form first, modify the returned
        fieldGroups, and pass the whole tree back here.
        """
        if not fields:
            raise ValueError("Provide at least one field to update.")
        safe, rejected = hub_forms.sanitize_form_fields(fields)
        if not safe:
            raise ValueError(
                f"No writable fields supplied. Rejected: {rejected or list(fields)}. "
                f"Allowed: {sorted(hub_forms.ALLOWED_FORM_FIELDS)} plus "
                f"configuration.{{{', '.join(sorted(hub_forms.ALLOWED_CONFIG_KEYS))}}}."
            )
        updated = hub_forms.update_form(client, form_id, safe)
        out = form_summary(updated, portal_id=portal)
        out["updated_fields"] = sorted(safe)
        if rejected:
            out["rejected_fields"] = rejected
            out["note"] = (
                "These were not applied. Fields that decide where submitted data "
                "goes (notification recipients, redirect targets) cannot be set "
                "through this server — change them in the HubSpot form editor."
            )
        return out

    @mcp.tool()
    def duplicate_form(source_id: str, new_name: str) -> dict[str, Any]:
        """Duplicate a form — the usual way to make a second-language variant.

        Copies the field definitions and settings under a new name. Translate
        the labels afterwards with update_form_draft.

        Args:
          source_id: ID of the form to copy.
          new_name: name for the copy.
        """
        src = hub_forms.get_form(client, source_id)
        source_type = src.get("formType")
        if source_type and source_type != hub_forms.CREATABLE_FORM_TYPE:
            raise ValueError(
                f"Form {source_id} is of type {source_type!r}. Only "
                f"{hub_forms.CREATABLE_FORM_TYPE!r} forms can be created through the API — "
                f"duplicate this one in the HubSpot UI instead."
            )

        payload: dict[str, Any] = {
            "name": new_name,
            "formType": hub_forms.CREATABLE_FORM_TYPE,
            "fieldGroups": src.get("fieldGroups", []),
            "configuration": src.get("configuration", DEFAULT_CONFIGURATION),
            "displayOptions": src.get("displayOptions", DEFAULT_DISPLAY_OPTIONS),
        }
        if src.get("legalConsentOptions"):
            payload["legalConsentOptions"] = src["legalConsentOptions"]

        created = hub_forms.create_form(client, payload)
        out = form_summary(created, portal_id=portal)
        out["source_id"] = source_id
        return out
