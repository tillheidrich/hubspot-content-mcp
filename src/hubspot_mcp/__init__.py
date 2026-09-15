"""HubSpot MCP Server — a local MCP server for the HubSpot API.

Landing pages, site pages, blog posts, forms, marketing emails, campaigns and
the CRM. What of that is reachable is decided by configuration before the
server starts: ALLOW_CRM gates the CRM surface and defaults to none, ALLOW_PUBLISH
gates publishing per area. Anything a configuration did not enable is absent
from the tool list, and the HTTP client refuses the path.
"""

__version__ = "0.5.0"

__all__ = ["__version__"]
