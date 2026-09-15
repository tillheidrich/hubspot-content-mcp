"""Dependency guards.

0.3.0 shipped with `mcp[cli]>=1.2.0` and no upper bound. MCP SDK 2.x renamed
FastMCP to MCPServer, so a fresh `uv sync` resolved a version the code cannot
import — and the failure surfaced as a bare ModuleNotFoundError at startup,
inside an MCP client, where nobody sees stack traces.

These tests make the same mistake loud and immediate.
"""

from __future__ import annotations

import importlib.metadata as metadata

import pytest
from packaging.specifiers import SpecifierSet
from packaging.version import Version


def test_mcp_sdk_is_v1():
    """The code uses mcp.server.fastmcp, which does not exist in 2.x."""
    installed = Version(metadata.version("mcp"))
    assert installed in SpecifierSet(">=1.9.4,<2"), (
        f"mcp {installed} is installed, but this code targets the 1.x API "
        f"(mcp.server.fastmcp.FastMCP). 2.x renamed it to MCPServer. "
        f"Either pin mcp<2 or migrate the server module."
    )


def test_fastmcp_is_importable():
    """A direct check, so the error names the cause rather than the symptom."""
    try:
        from mcp.server.fastmcp import FastMCP  # noqa: F401
    except ModuleNotFoundError as exc:
        pytest.fail(
            f"Cannot import FastMCP: {exc}. This usually means MCP SDK 2.x was "
            f"resolved. Run `uv sync` after confirming pyproject pins mcp<2."
        )


def test_pyproject_pins_an_upper_bound_on_mcp():
    """An unbounded >= on a dependency with a major rewrite is how this broke."""
    import pathlib
    import re

    root = pathlib.Path(__file__).resolve().parents[1]
    text = (root / "pyproject.toml").read_text()
    match = re.search(r'"mcp\[cli\][^"]*"', text)
    assert match, "mcp dependency not found in pyproject.toml"
    assert "<2" in match.group(0), (
        f"mcp dependency {match.group(0)} has no upper bound. "
        f"2.x is API-incompatible with this code."
    )
