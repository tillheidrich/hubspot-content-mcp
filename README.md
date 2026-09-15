# HubSpot Content MCP

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![MCP](https://img.shields.io/badge/MCP-2025--06--18-orange.svg)](https://modelcontextprotocol.io/)
[![Tests](https://github.com/tillheidrich/hubspot-content-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/tillheidrich/hubspot-content-mcp/actions/workflows/ci.yml)

**If you want Claude — or any AI assistant — actually working inside HubSpot, this is the server to point it at.**

29 tools covering landing pages, site pages, blog posts, forms and marketing emails, plus language variants for multilingual sites and the XLSX that HubSpot's social bulk upload expects. That is the widest content surface of any HubSpot MCP server, the official one included. It is also the only one that structurally cannot publish behind your back.

Cloning last quarter's webinar page for the new date, swapping the speaker, building the English variant, attaching the right form: the kind of job that quietly eats an afternoon. Your assistant could do it in one sentence. What stops most teams from handing it over is always the same worry — that something reaches the live site before a human looked at it, or that the model wanders off into the contact database.

This server settles both at the level of what exists, not what it promises. Publishing tools are not disabled here; they are never registered, so there is no call for a model to make. Nothing in the code path can reach `/crm/v3/*`, which means you can scope the token to content and forms and leave contacts and deals outside the blast radius altogether. What the assistant writes lands in HubSpot's draft buffer, where you read it and press publish yourself.

```
You:    Duplicate last quarter's webinar landing page for the March 12 session,
        swap the speaker, and give me an English variant.

Claude: [duplicate_page] → [update_page_draft] → [create_language_variant]
        Two drafts ready. Here are the edit URLs. You publish.
```

When you *do* want it to publish, you switch that on per area ([see below](#publishing)) — and only then do those tools appear at all.

About 3,500 lines of Python on your own machine, with a token that never leaves it. Works in Claude Desktop, Claude Code, Cursor and anything else that speaks [MCP](https://modelcontextprotocol.io/). Install takes about five minutes.

---

## Should you use this or HubSpot's official MCP server?

Be honest with yourself here, because for most people the answer is the official one.

HubSpot ships a [remote MCP server](https://developers.hubspot.com/docs/apps/developer-platform/build-apps/integrate-with-the-remote-hubspot-mcp-server) at `mcp.hubspot.com`. It is maintained by HubSpot, requires no local install, and has grown a lot: CRM records and activities, SQL queries over CRM data, campaigns, conversations, email analytics, content analytics, and full landing page and blog post management — **including publishing**.

**Use the official server if** you want CRM access, analytics, campaign management, site-navigation editing, or you simply want the thing HubSpot maintains. It is free on every tier, including free CRM.

**Use this one if** one of these is true:

| Need | Why this server |
| --- | --- |
| **Nothing may go live without a human** | The official server always carries `PUBLISH` and relies on the model honouring "confirm first" — a prompt-level guard. Here it is capability-level: publishing is off by default and the tools are not registered at all. When you do enable it, it is per-area, every call needs explicit confirmation, and each one is logged. |
| **The assistant must not reach the CRM** | No tool here calls `/crm/v3/*`. Your token can be scoped to content and forms only, so contacts and deals are outside the blast radius entirely. |
| **You work with forms** | The official server cannot write forms — `FORMS` there is a read-only lookup for embedding. This one lists, creates, updates and duplicates them. |
| **You run multilingual content** | `create_language_variant` wires a new page into HubSpot's multi-language group so the language switcher works. |
| **You schedule social posts in bulk** | HubSpot has no public social publishing API. This generates the XLSX that HubSpot's own bulk-upload accepts. |
| **You want to read the code** | About 3,500 lines of Python you can audit in an afternoon, running on your machine, with a token that never leaves it. No OAuth app, no remote service. |

The two can coexist. Register both and let the assistant pick; the tool names do not collide.

<details>
<summary><strong>How this compares to other community HubSpot MCP servers</strong></summary>

Almost all of them are CRM. The most-starred community HubSpot MCP has ~128 stars and seven tools — contacts, companies, engagements — and no content tools at all. The next has ~35 stars and ~100 tools, all CRM. Searching PyPI and npm for HubSpot MCP packages returns the same picture: no description mentions landing pages, blog posts or marketing emails.

A handful of repos do touch CMS content, all at 0–1 stars, and none combines drafts-only with form write and no CRM surface. One of them ships `push_live`, `schedule` and `delete` ungated and binds to `0.0.0.0` with optional auth.

So the real comparison is HubSpot's own server, not the community ones.

</details>

---

## Install

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/tillheidrich/hubspot-content-mcp.git
cd hubspot-content-mcp
uv sync

cp .env.example .env
$EDITOR .env          # paste your HubSpot token

uv run hubspot-content-mcp --test-connection
```

<details>
<summary><strong>Windows (PowerShell)</strong></summary>

```powershell
git clone https://github.com/tillheidrich/hubspot-content-mcp.git
cd hubspot-content-mcp
uv sync

copy .env.example .env
notepad .env

uv run hubspot-content-mcp --test-connection
```

If `uv` is missing: `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"`
</details>

### Get a HubSpot token

In HubSpot, go to **Settings → Integrations → Service keys** (or **Private apps** on older portals) and create one with these scopes:

- `content` — pages, blog posts, marketing emails
- `forms` and `external_integrations.forms.access` — forms
- `files` — referencing images already hosted in HubSpot

Do **not** grant any `crm.*` scope. Nothing here uses them, and leaving them off means a leaked token cannot touch customer data.

Then fill in `.env`:

```env
HUBSPOT_ACCESS_TOKEN=pat-...
HUBSPOT_PORTAL_ID=12345678
DEFAULT_TIMEZONE=Europe/Berlin
```

`--test-connection` should print a row per API area:

```
hubspot-content-mcp 0.2.0 — connection test
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
    "hubspot-content": {
      "command": "uv",
      "args": [
        "--directory", "/absolute/path/to/hubspot-content-mcp",
        "run", "hubspot-content-mcp"
      ]
    }
  }
}
```

Quit Claude Desktop completely and reopen it. On Windows use forward slashes in the path, or escape the backslashes.

### Anything else

The server speaks stdio, so it works with Claude Code, Cursor, Cline, Zed, ChatGPT Desktop and the [MCP Inspector](https://github.com/modelcontextprotocol/inspector) using the same command. To poke at it by hand:

```bash
npx @modelcontextprotocol/inspector uv --directory . run hubspot-content-mcp
```

---

## Tools

29 tools by default, 34 with publishing fully enabled. Everything that writes to a page, post or email writes to a draft.

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

`delete_page`, `archive_page`, `send_email`, and anything touching contacts, companies, deals, lists or conversations. Use the HubSpot UI or the official MCP server for those. Publishing exists but is opt-in — see [Publishing](#publishing).


---

## Publishing

Off by default. `ALLOW_PUBLISH` decides whether the publish tools are
registered at all:

```env
ALLOW_PUBLISH=none        # default — no publish tools exist
ALLOW_PUBLISH=blog        # blog posts only
ALLOW_PUBLISH=pages       # landing pages and site pages only
ALLOW_PUBLISH=pages,blog  # both
ALLOW_PUBLISH=all         # same as pages,blog
```

This is a registration switch, not a permission check. With `none`, the
assistant's tool list contains no publish tool, so there is nothing to talk it
into.

**Per task rather than permanently**: register the server twice in your MCP
client — once as `hubspot-content` with `ALLOW_PUBLISH=none`, once as
`hubspot-content-publish` pointing at a second `.env` via
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

Three independent layers, because one is not enough when an LLM is choosing the calls.

**1. The tool does not exist.** With the default config, no amount of prompting produces a publish, delete or CRM call, because MCP rejects unknown tool names at the protocol level. This is the layer that matters.

**2. Writes target the draft buffer.** Every update goes to `PATCH {id}/draft`, not `PATCH {id}`. This distinction is easy to get wrong — HubSpot's bare PATCH edits the *live* version of a published object — and getting it wrong silently overwrites production content. There are tests pinning the URL for pages, posts and emails.

**3. Dangerous fields are filtered before the request leaves.** `update_*` tools take a free-form dict, so an allow-list decides what survives. `state`, `publishDate`, `publishImmediately`, `isPublished`, `scheduledUpdateDate`, `archived` and friends are dropped in the HTTP layer regardless of caller, and creates hard-override `state="DRAFT"`. Rejected keys come back in `rejected_fields` rather than vanishing, so the model can tell the user what did not apply.

**4. IDs are validated before they reach a URL.** httpx resolves `..` when merging a path onto the base URL, so an unvalidated ID of `../../../crm/v3/objects/contacts` turns a form lookup into a CRM dump. Every ID is checked against `^[A-Za-z0-9_-]{1,64}$`, and the client independently refuses any request whose resolved host or path prefix falls outside its declared surface.

**5. Fields that route data are not writable.** A form's notification recipients and post-submit redirect decide where submitted data goes; changing them is exfiltration, not editing. Same for a page's password protection. Both are refused.

Plus the hygiene: the token is redacted from logs at any nesting depth and from tracebacks, HTTP-library loggers are pinned to WARNING so `LOG_LEVEL=DEBUG` cannot write an `Authorization` header to disk, `HUBSPOT_API_BASE` is allow-listed because the bearer token follows it, redirects are not followed, `.env` is not read from parent directories, spreadsheet cells are written as inert text so a `=cmd|...` payload cannot fire when you open the file, and raw `<head>` HTML is off unless you opt in.

Run `pytest tests/test_safety.py tests/test_security.py` to check all of it — 164 tests, and the security ones are behavioural rather than grep-based.

---

## Development

```bash
uv sync --extra dev
uv run pytest                    # 164 tests
uv run ruff check src tests
```

Adding a tool is two functions: an HTTP wrapper in `src/hubspot_content_mcp/hubspot/`, and an `@mcp.tool()` in the matching module under `tools/`. [CONTRIBUTING.md](CONTRIBUTING.md) has the full walkthrough and the rules a new tool has to follow.

```
src/hubspot_content_mcp/
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
- **No social publishing.** HubSpot retired the public social API. The XLSX route is the supported alternative.

---

## Contributing

Issues and PRs welcome. Two rules that are not negotiable: no tool may publish, schedule, delete or archive anything, and no tool may touch CRM data. Everything else is open for discussion — see [CONTRIBUTING.md](CONTRIBUTING.md).

## License

MIT © Till Heidrich. See [LICENSE](LICENSE).

Not affiliated with or endorsed by HubSpot, Inc. HubSpot is a trademark of HubSpot, Inc.
