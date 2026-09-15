# Setup guide

The long version. If you are comfortable in a terminal, the README quickstart
is enough — this page is for the parts that trip people up.

Roughly 15 minutes, most of it in HubSpot's settings.

---

## 1. Install uv

`uv` is a Python package manager. It installs Python itself if you do not have
a suitable version, so this is the only prerequisite.

**macOS / Linux**

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Close the terminal and open a new one, then check:

```bash
uv --version
```

**Windows (PowerShell)**

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

Close PowerShell, reopen, then `uv --version`.

If script execution is blocked:

```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

---

## 2. Get the code

```bash
git clone https://github.com/tillheidrich/hubspot-content-mcp.git
cd hubspot-content-mcp
uv sync
```

`uv sync` creates a `.venv` inside the project and installs everything. Takes
a few seconds. You can delete `.venv` and re-run it any time.

Note the absolute path — you need it later:

```bash
pwd                 # macOS / Linux
(Get-Location).Path # Windows
```

---

## 3. Create a HubSpot token

HubSpot has reorganised this area more than once, so the naming depends on how
old your portal is. You are looking for **service keys** or, on older portals,
**private apps**.

**Settings (gear icon) → Integrations → Service keys**

or, equivalently, **Development → Keys → Service keys** in the main nav.

> **Not** "MCP Auth Apps". That is HubSpot's own OAuth flow for their remote
> MCP server at `mcp.hubspot.com` — a different thing entirely. If you are
> looking at a dialog asking for a redirect URL, you are in the wrong place.

Click **Create service key**, name it something like
`hubspot-content-mcp (laptop)`, and add these scopes:

| Scope | Needed for |
| --- | --- |
| `content` | Landing pages, site pages, blog posts, marketing emails |
| `forms` | Forms |
| `external_integrations.forms.access` | Forms via the v3 API |
| `files` | Referencing images already hosted in HubSpot |

Leave everything else off. In particular **do not add any `crm.*` scope** —
no tool in this server uses them, and omitting them means a leaked key cannot
reach customer data.

Click create. **The key is shown in full exactly once.** Copy it now; afterwards
it is masked.

### Portal ID

Also grab your portal ID (sometimes "hub ID"). Click your account name in the
top right, or look under **Settings → Account & Billing**. It is an 8–9 digit
number.

It is optional — without it the tools still work, they just cannot build
`app.hubspot.com` edit links, which is most of what makes the output useful.

---

## 4. Configure

```bash
cp .env.example .env    # Windows: copy .env.example .env
```

Open `.env` and fill in the two values:

```env
HUBSPOT_ACCESS_TOKEN=pat-xxx-...
HUBSPOT_PORTAL_ID=12345678
DEFAULT_TIMEZONE=Europe/Berlin
```

`.env` is gitignored. Keep the real token there and nowhere else — in
particular, do not edit `.env.example`, which is the committed template.

---

## 5. Test the connection

```bash
uv run hubspot-content-mcp --test-connection
```

```
hubspot-content-mcp 0.2.0 — connection test
  API base:   https://api.hubapi.com
  Portal ID:  12345678
  Output dir: /Users/you/hubspot-content-mcp/output
  Log dir:    /Users/you/hubspot-content-mcp/logs

  [ OK ] Landing pages: 1 item(s) readable
  [ OK ] Site pages: 1 item(s) readable
  [ OK ] Blogs: 3 item(s) readable
  [ OK ] Blog posts: 1 item(s) readable
  [ OK ] Forms: 1 item(s) readable
  [ OK ] Marketing emails: 1 item(s) readable
  [ OK ] Domains: 1 item(s) readable
  [ OK ] Templates (optional): 1 item(s) readable

All required checks passed. Ready to register with an MCP client.
```

Everything here is read-only; nothing is created.

**`[FAIL] ... HTTP 401`** — the token is wrong, or whitespace came along when
you copied it.

**`[FAIL] ... HTTP 403 — needs the 'forms' scope`** — add the scope in HubSpot
and save. No need to regenerate the key.

**`[WARN] Templates (optional)`** — fine. That endpoint is legacy and not
enabled on every portal. You can still pass `template_path` by hand; copy it
from Design Manager.

---

## 6. Register with your MCP client

### Claude Desktop

Config file location:

- **macOS** `~/Library/Application Support/Claude/claude_desktop_config.json`
- **Windows** `%APPDATA%\Claude\claude_desktop_config.json`

If the file does not exist yet, create it with exactly this, substituting your
path:

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

If it already exists, add the `"hubspot-content"` block inside the existing
`mcpServers` object, and mind the commas.

On Windows, JSON treats `\` as an escape character. Use forward slashes —
`C:/Users/you/hubspot-content-mcp` — or double the backslashes.

Now quit Claude Desktop **completely**: `Cmd+Q` on macOS, or right-click the
tray icon and Quit on Windows. Closing the window is not enough; the config is
only read at startup.

Reopen it, start a new chat, and look for the tools icon near the message box.
`hubspot-content` should be listed with 29 tools.

Try it:

> List my five most recently updated landing pages in HubSpot.

### Claude Code

```bash
claude mcp add hubspot-content -- uv --directory /absolute/path/to/hubspot-content-mcp run hubspot-content-mcp
```

### Cursor

`~/.cursor/mcp.json`, same JSON structure as Claude Desktop.

### MCP Inspector

For poking at tools directly without an assistant in the way:

```bash
npx @modelcontextprotocol/inspector uv --directory . run hubspot-content-mcp
```

---

## Troubleshooting

**The server does not appear in the client**

Validate the JSON first — a trailing comma is the usual culprit:

```bash
python -m json.tool < ~/Library/Application\ Support/Claude/claude_desktop_config.json
```

Then check the client's own MCP log:

- macOS `~/Library/Logs/Claude/mcp-server-hubspot-content.log`
- Windows `%APPDATA%\Claude\logs\mcp-server-hubspot-content.log`

**`command not found: uv` in that log**

Your MCP client does not inherit the PATH from your login shell. Give it the
full path instead:

```bash
which uv     # e.g. /Users/you/.local/bin/uv
```

```json
"command": "/Users/you/.local/bin/uv"
```

**A tool call fails**

`logs/server.log` has one JSON event per line, including the full HubSpot error
body:

```bash
tail -20 logs/server.log | jq .
```

To confirm whether the problem is yours or HubSpot's, call the endpoint
directly:

```bash
source .env
curl -s -H "Authorization: Bearer $HUBSPOT_ACCESS_TOKEN" \
  "https://api.hubapi.com/cms/v3/pages/landing-pages?limit=1" | jq .
```

**The assistant says it cannot publish**

Correct, and deliberate. Take the edit URL it gives you and publish in HubSpot.

---

## Updating

```bash
cd hubspot-content-mcp
git pull
uv sync
```

Restart your MCP client so it re-reads the tool list.

## Rotating the key

HubSpot suggests every six months. In HubSpot, open the service key and choose
**Rotate and expire later** — the old key keeps working for seven days, so you
can paste the new one into `.env`, restart the client, and confirm everything
still works before the old one dies.

## Uninstalling

Remove the `"hubspot-content"` block from your client config, restart it,
delete the directory, and revoke the service key in HubSpot.
