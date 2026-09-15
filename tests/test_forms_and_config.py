from __future__ import annotations

import pytest

from hubspot_mcp.config import Settings, build_edit_url
from hubspot_mcp.tools.forms import build_field_group

# --- form field groups match the v3 schema ---------------------------------


def test_field_group_has_the_required_group_keys():
    """A bare {"fields": [...]} is rejected by HubSpot."""
    group = build_field_group({"name": "firstname", "label": "First name"}, 0)

    assert group["groupType"] == "default_group"
    assert group["richTextType"] == "text"
    assert len(group["fields"]) == 1


def test_field_defaults_to_a_contact_property():
    group = build_field_group({"name": "email", "type": "email"}, 0)
    assert group["fields"][0]["objectTypeId"] == "0-1"


def test_missing_name_explains_what_is_expected():
    with pytest.raises(ValueError) as excinfo:
        build_field_group({"label": "First name"}, 2)
    message = str(excinfo.value)
    assert "Field #3" in message
    assert "firstname" in message


def test_unknown_field_type_lists_the_valid_ones():
    with pytest.raises(ValueError, match="single_line_text"):
        build_field_group({"name": "x", "type": "wysiwyg"}, 0)


def test_dropdown_without_options_is_rejected():
    with pytest.raises(ValueError, match="options"):
        build_field_group({"name": "salutation", "type": "dropdown"}, 0)


def test_plain_string_options_are_normalized():
    group = build_field_group(
        {"name": "salutation", "type": "dropdown", "options": ["Mr", "Ms"]}, 0
    )
    options = group["fields"][0]["options"]
    assert options[0] == {"label": "Mr", "value": "Mr", "displayOrder": 0}
    assert options[1]["displayOrder"] == 1


def test_object_options_keep_label_and_value():
    group = build_field_group(
        {"name": "size", "type": "radio", "options": [{"value": "s", "label": "Small"}]}, 0
    )
    assert group["fields"][0]["options"][0] == {
        "label": "Small",
        "value": "s",
        "displayOrder": 0,
    }


def test_required_and_hidden_are_booleans():
    group = build_field_group({"name": "x", "required": "yes", "hidden": 1}, 0)
    field = group["fields"][0]
    assert field["required"] is True
    assert field["hidden"] is True


# --- config path handling ---------------------------------------------------


def test_absolute_output_dir_is_honoured(tmp_path, monkeypatch):
    target = tmp_path / "somewhere" / "else"
    monkeypatch.setenv("HUBSPOT_ACCESS_TOKEN", "t")
    monkeypatch.setenv("OUTPUT_DIR", str(target))
    monkeypatch.setenv("LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.chdir(tmp_path)

    settings = Settings.load()

    assert settings.output_dir == target, "an absolute OUTPUT_DIR must not be rewritten"
    assert target.exists()


def test_relative_output_dir_resolves_against_cwd(tmp_path, monkeypatch):
    monkeypatch.setenv("HUBSPOT_ACCESS_TOKEN", "t")
    monkeypatch.setenv("OUTPUT_DIR", "./exports")
    monkeypatch.setenv("LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.chdir(tmp_path)

    settings = Settings.load()

    assert settings.output_dir == (tmp_path / "exports").resolve()


def test_missing_token_raises_an_actionable_error(tmp_path, monkeypatch):
    monkeypatch.delenv("HUBSPOT_ACCESS_TOKEN", raising=False)
    monkeypatch.chdir(tmp_path)

    with pytest.raises(RuntimeError, match=r"\.env\.example"):
        Settings.load(require_token=True)


def test_token_whitespace_is_stripped(tmp_path, monkeypatch):
    monkeypatch.setenv("HUBSPOT_ACCESS_TOKEN", "  pat-eu1-abc  ")
    monkeypatch.setenv("LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.setenv("OUTPUT_DIR", str(tmp_path / "out"))
    monkeypatch.chdir(tmp_path)

    assert Settings.load().hubspot_access_token == "pat-eu1-abc"


@pytest.mark.parametrize(
    "kind,expected",
    [
        ("landing-page", "content-editor"),
        ("site-page", "content-editor"),
        ("blog-post", "blog"),
        ("email", "email/edit"),
        ("form", "forms/edit"),
    ],
)
def test_edit_url_prefixes(kind, expected):
    url = build_edit_url(kind, "123", "999")
    assert url == f"https://app.hubspot.com/{expected}/999/123"


def test_edit_url_is_empty_without_a_portal_id():
    assert build_edit_url("landing-page", "123", "") == ""
