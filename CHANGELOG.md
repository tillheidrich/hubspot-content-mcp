# Changelog

All notable changes to this project are documented here.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
versioning follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.3.0] — 2026-09-14

### Security — found by a dedicated pre-release audit

- **Path traversal in every ID-interpolated URL (critical).** httpx resolves
  `..` when merging a relative path onto `base_url`, so an ID of
  `../../../crm/v3/objects/contacts` turned `get_form` into a CRM dump, and
  `update_form` — the one write helper whose path had no trailing suffix — into
  an arbitrary `PATCH`, including against live pages. Verified against httpx
  0.28.1 before and after. Every ID now goes through `path_segment()`, and the
  client independently refuses any request whose resolved host or path prefix
  is outside its declared surface.
- **Form updates used a deny-list.** `configuration.notifyRecipients` and
  `postSubmitAction` decide where a form's submissions are sent; both were
  writable. Replaced with an allow-list that refuses every data-routing key.
- **`HUBSPOT_API_BASE` was unvalidated and `.env` was read from parent
  directories.** Together: a `.env` in any ancestor of the working directory
  could redirect the bearer token to an arbitrary host. Host is now
  allow-listed, https is required, and only the current directory (or an
  explicit `HUBSPOT_MCP_ENV_FILE`) is read.
- **`headHtml` / `footerHtml` were freely writable** — a `<script>` there is
  persistent XSS on the published site, and easy to miss when reviewing a
  draft. Now behind `ALLOW_RAW_HTML`, off by default.
- **`publicAccessRulesEnabled` was writable**, so a password-gated page could
  be silently un-gated as if it were a content edit. Now forbidden.
- **XLSX cells were written as live formulas.** A `=cmd|'/c ...'!A1` message
  reached code execution when the user opened the generated file to review it.
  All text cells are now written inert.
- **Log redaction was single-level** and missed nested API error bodies, the
  event string, and tracebacks. Now recursive, regex-backed, and applied by the
  stdlib formatter too. `LOG_LEVEL=DEBUG` no longer raises HTTP-library loggers.
- Redirects are no longer followed (the bearer token is a client-level header).
- Symlinked output paths are refused; control characters and over-long cells no
  longer escape as raw openpyxl errors.
- 429 responses are now retried with `Retry-After` instead of surfacing
  immediately.

### Fixed — dependency

- **`mcp[cli]` had no upper bound.** MCP SDK 2.x renamed `FastMCP` to
  `MCPServer`, so a fresh `uv sync` resolved a version this code cannot
  import. The failure surfaced as a bare `ModuleNotFoundError` at startup —
  inside an MCP client, where nobody reads stack traces. Pinned to
  `>=1.9.4,<2`, `uv.lock` committed, and three tests added that check the
  installed version, import `FastMCP` directly, and assert that
  `pyproject.toml` carries an upper bound at all.

  Migrating to the 2.x API is deliberately deferred rather than done blind.

### Added

- **Guidance against breaking the drag-and-drop editor.** The most common way
  to damage a HubSpot page through an API is not a wrong endpoint — it is
  well-formed content in the wrong shape. An assistant asked for a
  three-column section writes layout HTML into a single rich-text module, or
  assembles a `layoutSections` tree by hand. Both render correctly on the live
  site; both leave a page a marketer can no longer edit, and the second one
  will not open in the editor at all.

  The rules now sit in the server instructions and in the `update_page_draft`
  description, so the assistant reads them when the session starts and again
  on every write. The README has a section on the failure mode, the four
  patterns that avoid it, and prompts that do and do not work. Two tests pin
  the wording in both places — verified to fail when either is removed.

  The server still cannot tell well-formed module content from a layout blob;
  to the API both are a string. Checking the draft in the page editor rather
  than the preview remains the backstop.

- **Opt-in publishing.** `ALLOW_PUBLISH=none|pages|blog|all`. When an area is
  not enabled its tools are never registered, so they are absent from the tool
  list rather than present-and-refusing. Every publish requires
  `user_confirmed=True` and is logged at WARNING.
- `publish_page`, `schedule_page_publish`, `publish_blog_post`,
  `schedule_blog_post_publish`, `cancel_scheduled_publish`.
- First-publish vs republish branching. HubSpot's `push-live` "will only update
  an already published page, not publish a drafted page", so a never-published
  page goes through `publishImmediately` + `/schedule`, and a blog post through
  `state: PUBLISHED`. Publishing a post also pre-checks HubSpot's required
  fields and names the missing ones.
- Raw HubSpot objects returned to the model are labelled as untrusted data and
  size-capped, so injected instructions in page names or form labels are
  marked as content rather than arriving as unmarked context.

### Changed

- `create_form_draft` / `update_form_draft` renamed to `create_form` /
  `update_form`. HubSpot forms have no draft state — the old names claimed a
  guarantee the API does not provide.
- `get_form` no longer returns full field groups by default.
- CI safety gates are behavioural rather than grep-based. The old greps passed
  while the CRM path was being assembled at runtime from a tool argument.
- Marketing email publishing is explicitly unsupported and `ALLOW_PUBLISH=emails`
  is rejected with an explanation: HubSpot's email `/publish` endpoint is named
  in their guide but documented in no API reference, and is Enterprise-gated.


## [0.2.0] — 2026-09-14

First public release.

### Fixed — these are the reason 0.1.0 was never published

- **Writes went to the live object, not the draft.** `update_page_draft`,
  `update_blog_post_draft` and `update_marketing_email_draft` all issued
  `PATCH {id}` rather than `PATCH {id}/draft`. HubSpot's bare PATCH edits the
  live version of a published object, so the central promise of the server was
  false for every published page, post and email. All three now target the
  draft buffer, with tests pinning the URLs.
- **`state` and `language` filters did nothing.** HubSpot expects
  `propertyName__operator=value`; the code sent bare `state=` and `language=`,
  which the API ignores. Lists came back unfiltered while appearing filtered.
  Now uses `state__in` and `language__in`, and maps the friendly
  `DRAFT`/`PUBLISHED`/`SCHEDULED` values onto HubSpot's real state names.
- **Name search only looked at the first page of results.** `name_contains`
  filtered client-side after the server-side limit, so searching a large portal
  reported "not found" for anything past the first 20 rows. Now follows the
  paging cursor and flags truncation.
- **5xx responses were never retried** despite the retry decorator, because
  `httpx.HTTPStatusError` was not in the retry predicate. They also surfaced as
  raw httpx errors instead of `HubSpotError`. Retries now work, and are
  restricted to idempotent verbs so a timed-out POST cannot create duplicates.
- **`create_form_draft` could not have worked.** Field groups were missing the
  required `groupType` and `richTextType` keys, and `configuration` was missing
  fields HubSpot requires on create.
- **Marketing email payloads did not match the v3 schema.** `from`, preview
  text and template path were in the wrong place or absent, so `from_name`,
  `reply_to` and `preview_text` were silently discarded and the email had no
  template to render into.
- **`page_summary` could return `False` as a URL** — operator precedence made
  the expression resolve to the password-protection flag.
- **Data directories were resolved relative to the installed package**, so a
  `pip install`ed copy wrote `logs/` and `output/` into site-packages.
  `OUTPUT_DIR` also mangled absolute paths via `lstrip("./")`.
- **`LOG_LEVEL=DEBUG` wrote the bearer token to disk** via httpcore's request
  header logging. HTTP library loggers are now pinned to WARNING.
- **`output_filename` was joined unsanitised**, allowing writes outside the
  output directory.
- Date parsing errors in the XLSX generator escaped as raw pendulum
  tracebacks with no row number; the tool also returned `{"error": ...}` as a
  successful result, which reads as success to a model.
- The HubSpot client was never closed.

### Added

- `reset_blog_post_draft`, for parity with pages.
- `include_content` on `get_page`, `get_blog_post` and `get_marketing_email`.
  Body content is now omitted by default — these payloads run to hundreds of
  kilobytes and were filling the model's context.
- `draft` parameter on the same tools, to read the draft or the live version
  explicitly.
- Allow-list field filtering on all update tools, with rejected keys returned
  in `rejected_fields` instead of silently dropped.
- Slug validation with an error message that shows a correct example.
- Platform length warnings in the social XLSX generator.
- `subscription_type_id` and `template_path` on marketing email creation.
- Fallback between HubSpot's two documented spellings of the language-variant
  endpoint.
- 169 tests, including a safety suite that asserts no publish, delete, archive
  or CRM tool exists and that writes hit draft endpoints.
- CI on Python 3.11, 3.12 and 3.13.

### Changed

- Renamed from an internal name to `hubspot-content-mcp`; package is now
  `hubspot_content_mcp`, MCP server name `hubspot-content`.
- Defaults are English and UTC rather than German and Europe/Berlin.
- `list_*` tools return `{results, count, note?}` instead of a bare list, so
  truncated searches can say so.
- Connection test reports which scope a failure implies and treats the legacy
  template endpoint as optional.

[Unreleased]: https://github.com/tillheidrich/hubspot-content-mcp/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/tillheidrich/hubspot-content-mcp/releases/tag/v0.3.0
[0.2.0]: https://github.com/tillheidrich/hubspot-content-mcp/releases/tag/v0.2.0
