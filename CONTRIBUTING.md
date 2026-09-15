# Contributing

Thanks for looking. This is a small project with a narrow purpose, and the
narrowness is the point — so the most useful thing to read first is what the
project will not do.

## Two rules that do not bend

**1. No tool may publish, schedule, push live, delete or archive anything.**

The whole value proposition is that an agent physically cannot take content
live. A PR that adds `publish_page`, `schedule_publish`, `delete_page` or any
variant will be declined, however well written. If you want that, HubSpot's
[official MCP server](https://developers.hubspot.com/docs/apps/developer-platform/build-apps/integrate-with-the-remote-hubspot-mcp-server)
does it properly and is maintained by HubSpot.

**2. No tool may touch CRM data.**

Nothing calls `/crm/v3/*`. Contacts, companies, deals, tickets, lists and
conversations are out of scope permanently. Users are told they can scope their
token to content only, and that promise has to stay true.

Everything else is open. Bug reports, better error messages, new content-side
tools, docs fixes, tests — all welcome.

## Getting set up

```bash
git clone https://github.com/tillheidrich/hubspot-content-mcp.git
cd hubspot-content-mcp
uv sync --extra dev

cp .env.example .env    # only needed for --test-connection against a real portal
uv run pytest
uv run ruff check src tests
```

The test suite mocks HubSpot with `respx`, so you do not need a portal or a
token to run it.

## Adding a tool

Two layers, always in this order.

### 1. The HTTP wrapper

`src/hubspot_content_mcp/hubspot/<area>.py`. Knows about HubSpot, knows nothing
about MCP. Takes a client, returns parsed JSON.

```python
def list_page_authors(client: HubSpotClient, *, limit: int = 100) -> list[dict[str, Any]]:
    data = client.get("/cms/v3/pages/authors", params={"limit": max(1, min(limit, 100))})
    return data.get("results", []) if isinstance(data, dict) else []
```

If it writes, it goes through the draft endpoint and filters `FORBIDDEN_FIELDS`.
Look at `hubspot/pages.py::update_page_draft` for the shape.

### 2. The MCP tool

`src/hubspot_content_mcp/tools/<area>.py`, inside `register()`:

```python
@mcp.tool()
def list_page_authors(limit: int = 50) -> list[dict[str, Any]]:
    """List authors assignable to landing and site pages.

    Args:
      limit: maximum results, 1-100. Default 50.
    """
    rows = hub_pages.list_page_authors(client, limit=limit)
    return [{"id": str(a.get("id", "")), "name": a.get("name")} for a in rows]
```

It has to be inside `register()` — the closure is how the tool gets the
configured client. A module-level decorator will not be registered.

### What a good tool looks like

**The docstring is the API.** The model sees it, not your code. Document every
argument with its value range (`state: ANY | DRAFT | PUBLISHED`) and a format
example (`ISO 8601, e.g. '2026-01-13T09:00:00'`). Vague docstrings produce
wrong calls, and the user blames the assistant.

**Return summaries, not raw payloads.** A landing page with `layoutSections` is
hundreds of kilobytes. Dumping it costs the user real context window. Use the
helpers in `models/common.py`, and put full content behind an explicit
`include_content=True`.

**Fail with instructions.** `raise ValueError("Field #3 is missing 'name' — the
HubSpot property internal name, e.g. 'firstname'")` lets a model fix itself.
`KeyError: 'name'` does not.

**Never return an error dict.** Raise. Returning `{"error": "..."}` reads as
success to the caller, and the model will happily tell the user the file was
written.

**Name it `verb_object_form`.** `create_landing_page_draft`, not
`new_landing_page`. Consistency helps the model pick correctly.

### Then

- Add tests. Safety-relevant behaviour goes in `tests/test_safety.py`.
- Update the tool table in `README.md`.
- Add a line to `CHANGELOG.md` under Unreleased.

## Testing against a real portal

`uv run hubspot-content-mcp --test-connection` does read-only probes against
every API area and tells you which scope is missing when one fails.

To drive tools interactively:

```bash
npx @modelcontextprotocol/inspector uv --directory . run hubspot-content-mcp
```

Use a sandbox portal for anything that writes. HubSpot offers free developer
test accounts.

## Reporting bugs

Include:

- what you asked the assistant to do
- which tool it called and with what arguments
- the relevant lines from `logs/server.log` (it is JSON, one event per line —
  the token is redacted, but skim it before pasting anyway)
- your Python version and MCP client

## Security

Do not open a public issue for a security problem. See [SECURITY.md](SECURITY.md).
