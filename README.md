# HubSpot MCP Server

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![MCP](https://img.shields.io/badge/MCP-2025--06--18-orange.svg)](https://modelcontextprotocol.io/)
[![Tests](https://github.com/tillheidrich/hubspot-mcp-server/actions/workflows/ci.yml/badge.svg)](https://github.com/tillheidrich/hubspot-mcp-server/actions/workflows/ci.yml)

**If you want an AI assistant actually working inside HubSpot, this is the server to point it at.**

65 tools across landing pages, site pages, blog posts, forms, marketing emails, campaigns and the CRM. Create, edit, schedule, publish, take back down. Language variants for multilingual sites, the XLSX that HubSpot's social bulk upload expects, and campaign attribution wired up as you go. It is the widest HubSpot surface any MCP server offers, the official one included.

And it is the only one where you decide, before it starts, what it is allowed to touch.

### No customer data reaches the model unless you say so

Most people want an assistant that writes landing pages, not one that reads their contact database. Out of the box, that is what this is:

```
ALLOW_CRM=none          ← the default
```

With that set, the CRM tools are not registered, so the model is never offered them, and the HTTP client refuses every `/crm/` path before a request is built. There is no contact, company, deal or ticket data in reach — which means none can enter the conversation, and none can reach whoever runs your model. That is not a policy the assistant is asked to respect. It is a capability the process does not have.

Pair it with a HubSpot key scoped to content and forms and you have two independent limits, the outer one enforced by HubSpot rather than by this code. If a call falls outside your key, you get a message naming the exact scope and where to add it, not a bare 403.

When you *do* want CRM access, `ALLOW_CRM=read|write|all` turns it on in stages, and the server says plainly — in its startup log and in the model's own instructions — that personal data is now in play.

```
You:    Duplicate last quarter's webinar landing page for the March 12 session,
        swap the speaker, give me an English variant, and put both in the
        Q1 DACH campaign.

Claude: [duplicate_page] → [update_page_draft] → [create_language_variant]
        → [attach_asset_to_campaign] ×2
        Two drafts, both attached. Here are the edit URLs. Publish when ready.
```

Everything that reaches the public or changes a record asks first, by name, with what changes — and the confirmation has to come from you in the conversation, never from something the assistant read inside HubSpot.

Runs on your own machine; the token never leaves it. Works with Claude Desktop, Claude Code, Codex, Cursor, VS Code and anything else that speaks [MCP](https://modelcontextprotocol.io/) over stdio — config snippets for each in [`examples/`](examples/). Install takes about five minutes.

---

## This, or HubSpot's official MCP server?

HubSpot ships a [remote MCP server](https://developers.hubspot.com/docs/apps/developer-platform/build-apps/integrate-with-the-remote-hubspot-mcp-server) at `mcp.hubspot.com`. It is maintained by HubSpot, needs no local install, is free on every tier, and covers a great deal: CRM records and activities, SQL over CRM data, campaigns, conversations, analytics, and landing page and blog management including publishing.

It is a good server. The difference is not what each one can do — the overlap is large now — it is who decides what the assistant may touch, and when.

| | Official remote server | This one |
| --- | --- | --- |
| **Where it runs** | HubSpot's infrastructure, via OAuth | Your machine, with your key |
| **Deciding the data boundary** | Your key's scopes | Your key's scopes, *and* a per-area switch enforced before any request is built |
| **CRM by default** | On | Off, and unreachable — no tool, no path |
| **Publishing** | Always present; relies on the model honouring "confirm first" | Present per area, removable entirely, and every call needs confirmation from you in the conversation |
| **Form write** | No — `FORMS` is a read-only lookup | Yes: list, create, update, duplicate |
| **Multilingual** | No | `create_language_variant` wires the page into HubSpot's language group |
| **Social scheduling** | No | Generates the XLSX HubSpot's bulk upload accepts (there is no public social API) |
| **Auditability** | Closed | ~5,100 lines of Python you can read in an afternoon |

**Take the official one** if you want the thing HubSpot maintains, you need analytics or conversations, and the default of "the assistant can see everything my key can see" suits you. Nothing here is a criticism of it.

**Take this one** if any of these is true: customer data must be provably out of reach; nothing may reach the public without a named human saying yes; you work with forms or multilingual content; you want to run it somewhere other than Claude; or you want to read the code that holds your key.

The two coexist. Register both and let the assistant pick — the tool names do not collide.

<details>
<summary><strong>How this compares to other community HubSpot MCP servers</strong></summary>

Almost all of them are CRM. The most-starred community HubSpot MCP has ~128 stars and seven tools — contacts, companies, engagements — and no content tools. The next has ~35 stars and ~100 tools, also all CRM. Searching PyPI and npm returns the same picture: no description mentions landing pages, blog posts or marketing emails.

A handful of repos do touch CMS content, all at 0–1 stars. One ships `push_live`, `schedule` and `delete` ungated while binding to `0.0.0.0` with optional auth.

So the honest comparison is HubSpot's own server, not the community ones.

</details>

---

## Install

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/tillheidrich/hubspot-mcp-server.git
cd hubspot-mcp-server
uv sync

cp .env.example .env
$EDITOR .env          # paste your HubSpot token

uv run hubspot-mcp-server --test-connection
```

<details>
<summary><strong>Windows (PowerShell)</strong></summary>

```powershell
git clone https://github.com/tillheidrich/hubspot-mcp-server.git
cd hubspot-mcp-server
uv sync

copy .env.example .env
notepad .env

uv run hubspot-mcp-server --test-connection
```

If `uv` is missing: `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"`
</details>

### Get a HubSpot token

In HubSpot, go to **Settings → Integrations → Service keys** (or **Private apps** on older portals) and create one with these scopes:

- `content` — pages, blog posts, marketing emails
- `forms` and `external_integrations.forms.access` — forms
- `files` — referencing images already hosted in HubSpot
- `marketing.campaigns.read` — campaigns, plus `.write` to create and attach

Grant a `crm.*` scope only if you intend to set `ALLOW_CRM`. Leaving them off means a leaked token cannot touch customer data whatever this server is configured to do — the key is the limit HubSpot enforces, and it is the one that holds if everything else fails.

Then fill in `.env`:

```env
HUBSPOT_ACCESS_TOKEN=pat-...
HUBSPOT_PORTAL_ID=12345678
DEFAULT_TIMEZONE=Europe/Berlin
```

`--test-connection` should print a row per API area:

```
hubspot-mcp-server 0.5.0 — connection test
  API base:   https://api.hubapi.com
  Portal ID:  12345678

  [ OK ] Landing pages: 1 item(s) readable
  [ OK ] Site pages: 1 item(s) readable
  [ OK ] Blogs: 3 item(s) readable
  [ OK ] Forms: 1 item(s) readable
  [ OK ] Marketing emails: 1 item(s) readable
  ...
All required checks passed. Ready to register with an MCP client.
```

---

## Connect it to a client

### Claude Desktop

`~/Library/Application Support/Claude/claude_desktop_config.json` on macOS,
`%APPDATA%\Claude\claude_desktop_config.json` on Windows:

```json
{
  "mcpServers": {
    "hubspot-mcp-server": {
      "command": "uv",
      "args": [
        "--directory", "/absolute/path/to/hubspot-mcp-server",
        "run", "hubspot-mcp-server"
      ]
    }
  }
}
```

Quit Claude Desktop completely and reopen it. On Windows use forward slashes in the path, or escape the backslashes.

### Codex, Cursor, VS Code, Continue

Plain stdio MCP, protocol `2025-06-18`, negotiating down to `2025-03-26` and `2024-11-05` for older clients. Nothing in it is Claude-specific. Ready-made snippets:

| Client | File | Snippet |
| --- | --- | --- |
| Claude Desktop | `claude_desktop_config.json` | [examples/claude_desktop_config.json](examples/claude_desktop_config.json) |
| Codex CLI | `~/.codex/config.toml` | [examples/codex_config.toml](examples/codex_config.toml) |
| Cursor | `~/.cursor/mcp.json` | [examples/cursor_mcp.json](examples/cursor_mcp.json) |
| VS Code | `.vscode/mcp.json` | [examples/vscode_mcp.json](examples/vscode_mcp.json) |
| Continue | `~/.continue/config.yaml` | [examples/continue_config.yaml](examples/continue_config.yaml) |

Watch the key names: Claude Desktop and Cursor use `mcpServers`, VS Code uses `servers` and wants `"type": "stdio"`, Codex uses `mcp_servers` in TOML.

Claude Code takes it on the command line:

```bash
claude mcp add hubspot-mcp-server -- uv --directory /path/to/hubspot-mcp-server run hubspot-mcp-server
```

To poke at it by hand:

```bash
npx @modelcontextprotocol/inspector uv --directory . run hubspot-mcp-server
```

---

## Tools

45 tools in the default configuration, 65 with CRM fully enabled. Every content write goes to a draft; everything that leaves the draft, or touches a record, asks first.

| Configuration | Tools |
| --- | --- |
| `ALLOW_PUBLISH=none`, `ALLOW_CRM=none` | 36 — read, draft and plan; nothing can go live |
| **default** (`ALLOW_PUBLISH=all`, `ALLOW_CRM=none`) | **45** — the above plus publishing, scheduling and unpublishing |
| `ALLOW_CRM=read` | 54 — plus search and read across CRM records |
| `ALLOW_CRM=write` | 63 — plus create, update, associate, list membership |
| `ALLOW_CRM=all` | 65 — plus archiving records and switching workflows |

<details>
<summary><strong>Pages — 9 tools</strong></summary>

| Tool | What it does |
| --- | --- |
| `list_landing_pages` | Filter by name, state, language, update date. Name search follows the paging cursor, so a match on page 7 is still found. |
| `list_site_pages` | Same, for site pages. |
| `get_page` | One page. Module content is omitted unless you pass `include_content=True`, because `layoutSections` runs to hundreds of KB. |
| `create_landing_page_draft` | New landing page from a template. |
| `create_site_page_draft` | New site page from a template. |
| `update_page_draft` | `PATCH {id}/draft`. Publication fields are refused and reported back, never silently dropped. |
| `reset_draft` | Roll the draft back to the live version. Destructive; the description tells the model to confirm first. |
| `duplicate_page` | Clone and apply overrides in one call. The workhorse. |
| `create_language_variant` | EN ↔ DE and friends, wired into the multi-language group. |

</details>

<details>
<summary><strong>Blog — 6 tools</strong></summary>

| Tool | What it does |
| --- | --- |
| `list_blogs` | Blog instances in the portal. |
| `list_blog_posts` | Filter by blog, name, state, language. |
| `get_blog_post` | Post body omitted unless `include_content=True`. |
| `create_blog_post_draft` | New post as a draft. |
| `update_blog_post_draft` | `PATCH {id}/draft`. |
| `reset_blog_post_draft` | Roll back to live. Destructive. |

</details>

<details>
<summary><strong>Forms — 5 tools</strong></summary>

Forms have no draft state in HubSpot: a form is live and submittable as soon as it is created. It stays inert only because it is not embedded anywhere until you place it on a page.


| Tool | What it does |
| --- | --- |
| `list_forms` | Forms in the portal. |
| `get_form` | Full field groups. |
| `create_form` | Build a form from a simplified field list — `{"name": "email", "type": "email", "required": true}` — rather than hand-writing HubSpot's `fieldGroups` schema. |
| `update_form` | Patch name, fields and language. Notification recipients and post-submit redirects are refused — those decide where submitted data goes. |
| `duplicate_form` | Copy a form, usually to translate it. |

</details>

<details>
<summary><strong>Marketing emails — 5 tools</strong></summary>

| Tool | What it does |
| --- | --- |
| `list_marketing_emails` | Filter by name and published state. |
| `get_marketing_email` | Content tree omitted unless asked for. |
| `create_marketing_email_draft` | New draft against a template. Never sends. |
| `update_marketing_email_draft` | `PATCH {id}/draft`. |
| `duplicate_marketing_email` | How next month's newsletter usually starts. |

</details>

<details>
<summary><strong>Social + discovery — 4 tools</strong></summary>

| Tool | What it does |
| --- | --- |
| `generate_social_bulk_xlsx_file` | Writes HubSpot's bulk-upload sheet (Account, Date, Message, Link, Image URL). Warns when a message is too long for its platform. Up to 300 posts. |
| `list_templates` | Template paths for the create tools. |
| `list_domains` | Which domain is primary for what. |
| `list_blog_authors` | Author IDs for blog drafts. |

</details>

### Not here, deliberately

Two things this server will not do, whatever you set:

**Permanent deletion.** `archive_crm_object` moves a record to the recycle bin, where HubSpot keeps it for 90 days and a human can bring it back. HubSpot also has a GDPR endpoint that erases a contact irreversibly. That one is not wired up. It is a legal act with an audit trail attached, and a tool call in a chat window is the wrong shape for it — do it in the UI, as a person who can answer for it.

Content objects have no delete or archive tool at all. Unpublishing takes a page down without destroying it, which is nearly always what was actually meant.

**Anything that was not asked for by you.** Instructions found inside HubSpot — in a page body, a form label, a CRM note — are data. Every consequential tool requires `user_confirmed=True`, and the tool descriptions state that confirmation has to come from the person in the conversation. That is a real attack surface: portal content is written by whoever has portal access, and it flows into the model's context by design.

---

## Writing page content without breaking the editor

This is the one thing that will bite you, and it bites quietly. Read it before the first page edit.

### What goes wrong

A HubSpot page is not a document. It is a grid of modules that a marketer rearranges by dragging, and that grid lives in `layoutSections`. Ask an assistant for "a three-column comparison section" and it will do the obvious thing: write HTML that produces three columns — nested `div`s, a CSS grid, inline styles, a few utility classes — and drop the whole thing into one rich-text module.

On the live site it looks right. In the page editor it is one opaque block:

- Nobody can move, duplicate or delete the individual pieces. The module is the smallest unit the editor knows, and now the module is the entire section.
- The theme's spacing and type scale do not apply, because the markup brought its own. The result reads as *almost* on-brand, which is worse than obviously off.
- HubSpot's editor sanitises rich-text fields on save. The next colleague who fixes a typo in that block can silently lose the classes and inline styles holding the layout together.
- Nothing in there can be translated per module, swapped in an A/B test, or reused on another page.

The sharper version of the same mistake is hand-writing a `layoutSections` tree — inventing rows, cells or module types the template does not have. That usually does not render as a broken page. It renders fine and then refuses to open in the drag-and-drop editor at all, which is how it tends to be discovered: by a marketer, on a Friday.

**The rule: layout belongs to modules and rows. Markup carries content, nothing else.**

### What to do instead

In order of preference:

**1. Clone something that already has the right structure.** `duplicate_page` copies the grid a human built, and then the assistant only fills text into modules that already exist. This covers most recurring work — webinar pages, campaign variants, event landing pages — and it is the reason `duplicate_page` exists.

**2. Edit in place, and send the tree back whole.** Fetch with `include_content=True`, change values inside the structure you got back, and PATCH the entire `layoutSections`. HubSpot's API accepts nothing smaller, and a tree you assembled yourself will not survive the editor.

**3. Need a section that does not exist yet? Build the empty shell by hand, once.** Drop the modules into place in HubSpot, save it as a template or as a saved section, and from then on the assistant fills it. Ten minutes of clicking buys you a structure the assistant can safely reuse forever.

**4. Keep rich-text markup boring.** Headings, paragraphs, lists, links, bold and italic. That is the whole vocabulary. No `div`s, no grid, no `style=`, no class names.

### Prompts

Works — the structure already exists, the assistant only supplies content:

```
Duplicate the Q2 webinar landing page, set the date module to March 12,
replace the speaker bio text, and attach the DACH registration form.
```

Breaks the editor — the assistant has to invent structure to satisfy it:

```
Build me a landing page with a hero, a three-column feature grid
and a testimonial band.
```

If you catch yourself writing the second kind, that is the signal to build the shell by hand first. An assistant that says *"this template has no three-column module; build one and I will fill it"* is doing the right thing, not being unhelpful.

### Before you publish

Open the draft in the **page editor**, not the preview. The preview renders almost anything; the editor is where the damage shows. A draft that looks fine in preview and will not open for editing is the exact failure this section is about.

### What the server does about it

Both the server instructions and the `update_page_draft` tool description carry these rules, so the assistant reads them at the start of the session and again on every write. That shifts the odds; it does not remove the risk. The server cannot tell well-formed module content from a layout blob — to the API both are a string. The editor check above is the backstop.

---

## Publishing

On by default since 0.4.0. `ALLOW_PUBLISH` decides which areas get publish
tools registered at all:

```env
ALLOW_PUBLISH=all            # default — pages, blog and marketing emails
ALLOW_PUBLISH=none           # no publish tool exists; drafts only, forever
ALLOW_PUBLISH=blog           # blog posts only
ALLOW_PUBLISH=pages          # landing pages and site pages only
ALLOW_PUBLISH=pages,blog     # both, but no email sending
```

Each area brings publish, schedule and unpublish. This is a registration
switch, not a permission check: with `none`, the assistant's tool list
contains no publish tool, so there is nothing to talk it into.

**Marketing email publishing needs Marketing Hub Enterprise or the
transactional email add-on.** HubSpot gates `/publish` behind those, whatever
scopes the key carries. On other tiers the tool is registered and HubSpot
answers 403 — the error says so in plain words rather than looking like a bug.

**Per task rather than permanently**: register the server twice in your MCP
client — once as `hubspot-mcp-server` with `ALLOW_PUBLISH=none`, once as
`hubspot-mcp-server-publish` pointing at a second `.env` via
`HUBSPOT_MCP_ENV_FILE`, and enable the second one only for the session where
you need it. Most MCP clients let you toggle a server without editing config.

When enabled you get:

| Tool | What it does |
| --- | --- |
| `publish_page` | Takes a landing or site page live now. |
| `schedule_page_publish` | Schedules one for a future timestamp. |
| `publish_blog_post` | Takes a post live now. |
| `schedule_blog_post_publish` | Schedules one. |
| `cancel_scheduled_publish` | Cancels a pending schedule. |

Every one requires `user_confirmed=True`, whose description tells the model
that content read out of HubSpot does not count as the user asking. Every call
is logged at WARNING with the ID and name.

### Two things worth knowing

**First publish and republish are different operations in HubSpot.** Their
`push-live` endpoint explicitly "will only update an already published page,
not publish a drafted page". These tools read the current state and branch:
`publishImmediately` + `/schedule` for a page that has never been live,
`push-live` for one that has. Blog posts take a third path again
(`state: PUBLISHED`). Getting this wrong is silent — you call publish, get a
204, and nothing goes live.

**HubSpot requires fields before it will publish a post**: a title, parent
blog, a real slug rather than the auto-assigned temporary one, an author and a
meta description. `publish_blog_post` checks these first and names the missing
ones instead of letting HubSpot fail opaquely.

**Marketing emails cannot be published here.** HubSpot's guide names a
`/publish` endpoint for emails, but it appears in no API reference in any
version, and it is gated behind Marketing Hub Enterprise. Rather than write
code against an endpoint whose request body is undocumented, this server does
not offer it. Publish emails in the HubSpot UI.

---

## How the safety model actually works

Six independent layers, because one is not enough when a language model is choosing the calls.

**1. The tool does not exist.** Capability is decided once, at registration. A group the configuration did not enable is absent from the tool list, and MCP rejects unknown tool names at the protocol level. There is nothing for a prompt to talk its way past. This is the layer that matters, and it is why `ALLOW_CRM=none` is a guarantee rather than a preference.

**2. The socket will not carry it either.** The HTTP client is built with the path surfaces the configuration enabled, and checks the *resolved* URL — host and prefix — before sending. A bug in a helper module cannot reach an endpoint this install did not enable. That check is what closed the path-traversal hole in 0.3.0, where an ID of `../../../crm/v3/objects/contacts` turned a form lookup into a CRM dump.

**3. Your key is the outer limit.** Scopes are enforced by HubSpot, not by this code, so they hold even if both layers above fail. Scope the key to content and forms and the CRM is unreachable by construction. When HubSpot refuses on scope grounds, the error names the exact scope and where to add it instead of repeating HubSpot's own unhelpful sentence.

**4. Writes target the draft buffer.** Every content update goes to `PATCH {id}/draft`, never `PATCH {id}`. HubSpot's bare PATCH edits the *live* version of a published object, and getting that wrong silently overwrites production. Tests pin the URL for pages, posts and emails, and a CI gate greps for a bare patch in those three modules.

**5. Dangerous fields are filtered before the request leaves.** `update_*` takes a free-form dict, so an allow-list decides what survives. `state`, `publishDate`, `publishImmediately`, `archived` and friends are dropped in the HTTP layer regardless of caller. A form's notification recipients and post-submit redirect decide where submitted data goes — changing those is exfiltration, not editing, and they are refused. Rejected keys come back in `rejected_fields` rather than vanishing, so the assistant can tell you what did not apply.

**6. Consequences require a named yes.** Everything that reaches the public, changes a person's record, or cannot be undone from here takes `user_confirmed`, defaulting to false. A test walks every registered tool in the most permissive configuration and fails if one of them is missing the gate — so a tool added later cannot quietly skip it.

Plus the hygiene: the token is redacted from logs at any nesting depth and from tracebacks; HTTP-library loggers are pinned to WARNING so `LOG_LEVEL=DEBUG` cannot write an `Authorization` header to disk; `HUBSPOT_API_BASE` is host-allow-listed because the bearer token follows it; redirects are not followed; `.env` is not read from parent directories; spreadsheet cells are written as inert text so a `=cmd|...` payload cannot fire when the file is opened; raw `<head>` HTML is off unless you opt in.

```bash
uv run pytest tests/test_safety.py tests/test_security.py
```

The safety tests are behavioural, not grep-based. That distinction was learned the hard way: in an earlier version the greps stayed green while the traversal hole was wide open.

---

## Development

```bash
uv sync --extra dev
uv run pytest                    # 181 tests
uv run ruff check src tests
```

Adding a tool is two functions: an HTTP wrapper in `src/hubspot_mcp/hubspot/`, and an `@mcp.tool()` in the matching module under `tools/`. [CONTRIBUTING.md](CONTRIBUTING.md) has the full walkthrough and the rules a new tool has to follow.

```
src/hubspot_mcp/
├── server.py          FastMCP instance, tool registration
├── config.py          .env → frozen Settings
├── logging_setup.py   structlog, redaction, rotation
├── hubspot/           HTTP layer — knows nothing about MCP
├── tools/             MCP layer — one module per content area
├── models/            response shaping
└── social/            XLSX generator
```

The two-layer split is deliberate: `hubspot/` is reusable from a script or a CLI without dragging MCP along.

---

## Known limits

- **Rate limits are not tracked.** HubSpot allows 10 requests/second on standard portals. Nothing here throttles; you would see 429s in the log first.
- **This targets HubSpot's `/cms/v3/` path family.** HubSpot now also publishes a dated family (`/cms/pages/2026-09/...`) with the same payloads. v3 is still live and documented; if HubSpot retires it, the paths in `hubspot/` are the only thing that needs changing.
- **`list_templates` uses a legacy endpoint.** HubSpot never shipped a v3 template listing. `/content/api/v2/templates` works today and may not forever. Pass `template_path` manually if it fails.
- **No asset uploads.** You can reference images already in HubSpot by URL, but not upload new ones.
- **Module-level updates resend the whole `layoutSections`.** HubSpot's API takes nothing smaller.
- **The server cannot tell good markup from a layout blob.** To the API both are a string. See [Writing page content without breaking the editor](#writing-page-content-without-breaking-the-editor).
- **No social publishing.** HubSpot retired the public social API. The XLSX route is the supported alternative.

---

## Contributing

Issues and PRs welcome. Two rules that are not negotiable: no tool may publish, schedule, delete or archive anything, and no tool may touch CRM data. Everything else is open for discussion — see [CONTRIBUTING.md](CONTRIBUTING.md).

## License

MIT © Till Heidrich. See [LICENSE](LICENSE).

Not affiliated with or endorsed by HubSpot, Inc. HubSpot is a trademark of HubSpot, Inc.
