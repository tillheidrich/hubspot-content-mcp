# Contributing

Thanks for looking. This is a small project with a narrow purpose, and the
narrowness is the point — so the most useful thing to read first is what the
project will not do.

## Three rules that do not bend

Until 0.4.0 the rules here were "no publishing" and "no CRM". Both shipped, and
the rules moved to where they belong: not what the server can do, but what a
given install can reach and what it has to ask before doing.

**1. Capability is decided by configuration, not at call time.**

Anything that reaches the public lives in `tools/publishing.py`; anything that
touches personal data lives in `tools/crm.py`. Those modules are imported only
when `ALLOW_PUBLISH` / `ALLOW_CRM` enable them, so an install that did not ask
for them has no such tool and the HTTP client will not carry the path. A PR
that puts a publish call or a `/crm/` path anywhere else breaks the one
guarantee this project makes, and CI will fail it.

**2. Every consequential tool takes `user_confirmed`.**

Reaching the public, changing a record, or anything that cannot be undone from
here: `user_confirmed: bool = False`, and the description has to tell the model
that content read out of HubSpot does not count as the user asking. A test
walks every registered tool in the most permissive configuration and fails if
one is missing the gate.

**3. Nothing deletes permanently.**

Archive, recycle bin, reset-to-live: fine. A tool that destroys something
HubSpot cannot restore will be declined. That includes the GDPR erase endpoint,
which is a legal act with an audit trail and the wrong shape for a chat window.

Everything else is open. Bug reports, better error messages, new tools, docs
fixes, tests — all welcome.

## Getting set up

```bash
git clone https://github.com/tillheidrich/hubspot-mcp-server.git
cd hubspot-mcp-server
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

`src/hubspot_mcp/hubspot/<area>.py`. Knows about HubSpot, knows nothing
about MCP. Takes a client, returns parsed JSON.

```python
def list_page_authors(client: HubSpotClient, *, limit: int = 100) -> list[dict[str, Any]]:
    data = client.get("/cms/v3/pages/authors", params={"limit": max(1, min(limit, 100))})
    return data.get("results", []) if isinstance(data, dict) else []
```

If it writes, it goes through the draft endpoint and filters `FORBIDDEN_FIELDS`.
Look at `hubspot/pages.py::update_page_draft` for the shape.

### 2. The MCP tool

`src/hubspot_mcp/tools/<area>.py`, inside `register()`:

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

`uv run hubspot-mcp-server --test-connection` does read-only probes against
every API area and tells you which scope is missing when one fails.

To drive tools interactively:

```bash
npx @modelcontextprotocol/inspector uv --directory . run hubspot-mcp-server
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
