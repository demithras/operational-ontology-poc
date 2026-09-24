"""Small shared helpers for tests/agent/ — a synchronous wrapper around
FastMCP's async `call_tool`/`list_tools` (this repo's established
sync-everywhere test style; see services/mcp/decision_client.py's own
docstring for the same rationale) plus WMS-ground-truth re-exports so every
scenario file asserts "zero forbidden external effects" the same way
Phase 5's own delegation/injection tests do — never against the decision
record's self-report.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError

from tests.integration.decision_helpers import inventory_unchanged, set_inventory_and_wait, sku_to_canonical

__all__ = ["call_tool", "list_tool_names", "inventory_unchanged", "set_inventory_and_wait", "sku_to_canonical", "ToolError"]


def call_tool(mcp: FastMCP, name: str, arguments: dict[str, Any]) -> dict | list:
    """Calls an MCP tool exactly the way a real client would (by name +
    JSON-shaped arguments — never a direct Python function reference, so
    this exercises the SAME dispatch/validation path a real agent/LLM
    client goes through) and returns the tool's structured result, parsed
    from its own JSON text content. Raises `ToolError` (unknown tool /
    tool-internal exception) exactly like a real MCP client would see."""

    async def _run():
        result = await mcp.call_tool(name, arguments)
        content = result[0] if isinstance(result, tuple) else result
        if isinstance(content, dict):
            return content
        text = content[0].text if content else "null"
        return json.loads(text)

    return asyncio.run(_run())


def list_tool_names(mcp: FastMCP) -> set[str]:
    async def _run():
        tools = await mcp.list_tools()
        return {t.name for t in tools}

    return asyncio.run(_run())
