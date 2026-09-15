# Security Policy

## Reporting a vulnerability

Please do not open a public issue.

Use GitHub's [private vulnerability reporting](https://github.com/tillheidrich/hubspot-mcp/security/advisories/new)
on this repository. You should get a response within a few days.

This is a small side project maintained in spare time, so please do not expect
enterprise response times — but anything that could expose a token or let an
agent take content live will be treated as urgent.

## What counts as a vulnerability here

The security model of this server is narrow and specific, so these are the
things worth reporting:

**Critical — the core guarantees**

- Any path by which an install reaches a surface its configuration did not
  enable — a CRM path under `ALLOW_CRM=none`, a publish call under
  `ALLOW_PUBLISH=none`, or a tool registered that should not have been.
- Any path by which something consequential happens without `user_confirmed`,
  or with a confirmation the model inferred from content it read rather than
  from the user.
- Any path by which a content write reaches the live version of an object
  instead of the draft buffer.
- Any way the access token can end up in a log file, a tool response, an
  output file, or the MCP transport.
- Anything that permanently destroys data.

**High**

- Writing files outside the configured output directory.
- Prompt-injection routes: content fetched from HubSpot being interpreted as
  instructions in a way that causes an unintended write.
- Dependency vulnerabilities with a plausible exploit path here.

**Out of scope**

- Anything requiring an attacker who already has your `.env` file or shell
  access to your machine. At that point the token is gone regardless.
- HubSpot API behaviour itself — report that to HubSpot.
- Rate limiting. Known gap, documented in the README.

## Handling your token

The server reads `HUBSPOT_ACCESS_TOKEN` from `.env`, keeps it in memory, and
sends it only to `api.hubapi.com` as a bearer header. It is redacted from
structured logs, and the HTTP libraries are pinned to WARNING so that
`LOG_LEVEL=DEBUG` cannot write an `Authorization` header to disk.

What that does not protect against:

- `.env` is a plaintext file. Anything running as your user can read it.
- Least privilege matters, and the key is the boundary HubSpot enforces rather
  than this code. For the content side grant `content`, `forms`,
  `external_integrations.forms.access`, `files` and `marketing.campaigns.read`.
  Grant a `crm.*` scope only if you actually set `ALLOW_CRM` — without those
  scopes a leaked token stays useless against customer data, whatever this
  server is configured to do.
- Rotate the key every six months. HubSpot's rotation flow gives the old key a
  seven-day grace period, so you can swap `.env` without downtime.

**If you think a token leaked:** revoke it in HubSpot immediately
(Settings → Integrations → Service keys → Revoke), then issue a new one. Do
not wait for a reply here. If the key was ever committed to git, revoke it even
if you rewrote history — assume it was scraped.

## Supported versions

The latest release on `main`. This project does not backport fixes.
