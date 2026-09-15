"""HubSpot Content MCP — a local MCP server for HubSpot content operations.

Landing pages, site pages, blog posts, forms and marketing emails. Drafts by
default, publishing opt-in per area via ALLOW_PUBLISH, and no CRM surface at
all — no tool in this package calls a /crm/ endpoint.
"""

__version__ = "0.3.0"

__all__ = ["__version__"]
