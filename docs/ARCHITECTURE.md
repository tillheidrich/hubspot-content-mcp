# Architecture

For anyone reading the code, extending it, or deciding whether to trust it.

## Shape

```
MCP client (Claude Desktop, Cursor, ...)
   │  stdio, JSON-RPC 2.0
   ▼
__main__.py          argparse, Settings.load(), setup_logging(), server.run()
   ▼
server.py            FastMCP instance; calls register() on each tool module
   ▼
tools/*.py           MCP layer — user-facing arguments, validation,
                     response shaping, allow-list filtering
   ▼
hubspot/*.py         HTTP layer — endpoint paths, query params, draft routing
   ▼
hubspot/client.py    httpx + retry + structured logging + error translation
   ▼
api.hubapi.com
```

No database, no cache, no background work. Each tool call is one or a few HTTP
requests and then the process goes back to waiting on stdin.

## Why two layers

`hubspot/` knows about HubSpot and nothing about MCP. `tools/` knows about MCP
and delegates everything else. The split costs a little indirection and buys
three things:

- `hubspot/` is usable from a plain script or a CLI, with no MCP dependency.
- The safety filtering lives in `hubspot/`, so it holds no matter who calls.
- Tests can exercise HTTP behaviour without constructing a FastMCP server.

## Protocol

[Model Context Protocol](https://modelcontextprotocol.io/), spec `2025-06-18`,
over stdio. The client spawns this process and speaks JSON-RPC 2.0 on
stdin/stdout.

stdio rather than HTTP because it needs no port, no TLS, and no auth of its
own — the client already had to be on the machine to start the process. It
also means the server's lifetime is the client's lifetime; nothing is left
running.

`mcp[cli]`'s `FastMCP` handles the protocol. A tool is a decorated function:

```python
@mcp.tool()
def list_landing_pages(name_contains: str | None = None, limit: int = 20) -> dict:
    """List landing pages.

    Args:
      name_contains: case-insensitive substring of the page name.
      limit: maximum results, 1-100. Default 20.
    """
```

FastMCP derives the JSON schema from the type hints and uses the docstring as
the description the model reads. The docstring is the API contract — it is what
determines whether the model calls the tool correctly.

Tools are registered inside `register(mcp, context)` rather than at module
level, because they need the configured `HubSpotClient` as a closure variable
and configuration only exists at runtime.

## The safety model

Three layers, deliberately redundant, because the caller is a language model
that can be argued with.

**Layer 1 — absent tools.** There is no publish, schedule, delete or archive
tool, and nothing calls `/crm/v3/*`. MCP rejects unknown tool names at the
protocol level, so no prompt produces one. This is the layer that actually
matters; the rest is defence in depth.

**Layer 2 — draft routing.** Writes go to `PATCH {id}/draft`, never
`PATCH {id}`. HubSpot's bare PATCH edits the *live* version of a published
object — this was wrong in the first cut of the code and silently overwrote
published pages. `tests/test_safety.py` pins the URLs.

**Layer 3 — field filtering.** The `update_*` tools take a free-form dict, so
an allow-list decides what survives, and a `FORBIDDEN_FIELDS` set is applied
again down in `hubspot/`. Creates hard-override `state="DRAFT"` after merging
the caller's payload. Rejected keys are returned in `rejected_fields` so the
model can tell the user what did not apply rather than reporting false success.

CI greps the source for CRM and publish endpoints on every push, so a
regression fails the build rather than a review.

## Error handling

`HubSpotError` carries `status`, a `message` extracted from HubSpot's error
body, and the raw `payload`. Tools do not catch it — it propagates, and FastMCP
surfaces it to the model as a tool error, which is what lets the model retry
sensibly or explain the problem.

Input errors raise `ValueError` with a message written for a model to act on:

```
Invalid slug 'Webcast Q1'. Use lowercase letters, digits and hyphens,
with '/' only as a path separator — for example 'webcast-q1'.
```

Never return `{"error": ...}`. That reads as success and the model will report
the operation as done.

## Retries

Connection failures are always retried — the request never landed. Timeouts and
5xx are retried only for idempotent verbs, because a timed-out POST may well
have created something, and replaying it would produce a duplicate draft.

Implemented with an explicit `Retrying` object rather than the `@retry`
decorator, so the predicate can see the HTTP method.

## Configuration

`Settings` is a frozen dataclass built once at startup from `.env`. Missing
required values raise immediately with a message naming the file to fix.

Path resolution is more careful than it looks. `.env` is found with
`find_dotenv(usecwd=True)`, and its directory becomes the base for `output/`
and `logs/`. Without a `.env`, the base is `~/.hubspot-mcp-server/`. The
earlier version derived paths from `__file__`, which put `output/` inside
site-packages once the package was pip-installed.

Absolute `OUTPUT_DIR` and `LOG_DIR` values are honoured as given; relative ones
resolve against the working directory.

## Logging

structlog to a rotating file under `logs/`, JSON, one event per line. stdout is
off limits — it carries the MCP wire protocol. stderr gets errors only, which
is where MCP clients look when a server fails to start.

Two token protections: a redaction processor blanks any key that looks like a
credential, and `httpx`/`httpcore` loggers are pinned to WARNING so
`LOG_LEVEL=DEBUG` cannot write an `Authorization` header to disk.

Log structured (`log.info("startup", token=...)`), never interpolated
(`log.info(f"... {token}")`) — the redactor only sees keys.

## Response shaping

Raw HubSpot objects are enormous; a landing page with `layoutSections` is
routinely several hundred kilobytes. Returning that verbatim exhausts the
model's context in a couple of calls, so list tools return summaries from
`models/common.py`, and `get_*` tools omit body content unless
`include_content=True`.

## Pagination

`name_contains` cannot be done server-side for these endpoints, so it filters
client-side — which means filtering only the first page would make anything
further down invisible. The list helpers walk the cursor until they have enough
matches or hit `MAX_SEARCH_PAGES`, and set a `note` when the search was cut
short so the model does not claim "not found".

## Testing

`respx` intercepts httpx, so the whole suite runs without a token or a portal.

`tests/test_safety.py` is the file that matters: it asserts the tool surface
exactly, that no tool name contains publish/delete/archive/crm, that writes hit
draft endpoints, and that publication fields are stripped at the HTTP layer.
Everything else is a normal unit test.

## Deployment

There is none. It is a local process started by your MCP client, distributed by
`git clone`. No container, no service, no CI/CD to production.

A hosted multi-user version would need streamable HTTP transport, OAuth 2.1
with PKCE, and per-user token storage — a different project, not a flag on this
one. For that shape, HubSpot's own remote MCP server already exists.


---

## Where capability is decided

One place, once: `build_server()` in `server.py`. It reads `Settings`, decides
which tool modules to import and register, and constructs the HTTP client with
the matching path surfaces.

```
Settings.crm_scope  ──┬──> register tools/crm.py (or not)
                      └──> HubSpotClient(surfaces=[..., "crm"]) (or not)

Settings.publish_scope ──> register tools/publishing.py, per area
```

Two consequences worth stating, because they are the whole design:

**Absent, not refusing.** A tool group the configuration did not enable is
never registered, so it is not in the tool list the model receives, and MCP
rejects unknown tool names at the protocol level. There is no code path where
a model asks and something says no — there is nothing to ask.

**The socket agrees with the tool list.** `HubSpotClient` checks the resolved
URL's host and path prefix against the surfaces it was built with. A helper
module that somehow constructed a CRM path on a content-only install would be
refused by the client before the request left the process. The two layers are
independent on purpose: the first is about what a model can choose, the second
about what this process can send.

Neither replaces the token. Scopes are enforced by HubSpot, so they hold when
both layers above fail. `client.scope_error_message()` translates the 403 into
the specific scope and where to add it.

## Module map

```
tools/pages.py        landing pages and site pages
tools/blog.py         blog posts and authors
tools/forms.py        forms
tools/emails.py       marketing email drafts
tools/campaigns.py    campaigns and asset attachment
tools/social.py       social bulk-upload XLSX
tools/discovery.py    domains, templates, blogs
tools/publishing.py   publish, schedule, unpublish   — ALLOW_PUBLISH
tools/crm.py          records, properties, lists, …  — ALLOW_CRM
```

Each mirrors a `hubspot/` module of the same name that knows the endpoints and
nothing about MCP.
