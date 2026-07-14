"""FastMCP server — wires tool functions onto the MCP protocol."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from eno_mcp.tools import (
    eno_append_to_note,
    eno_broken_links,
    eno_concepts,
    eno_create_note,
    eno_drift,
    eno_frontier,
    eno_health,
    eno_hot,
    eno_hygiene,
    eno_neighbors,
    eno_note,
    eno_orphans,
    eno_search,
    eno_stale,
    eno_stubs,
    eno_tiling,
)


def build_server() -> FastMCP:
    server = FastMCP("eno")
    server.tool()(eno_search)
    server.tool()(eno_note)
    server.tool()(eno_neighbors)
    server.tool()(eno_orphans)
    server.tool()(eno_stubs)
    server.tool()(eno_stale)
    server.tool()(eno_broken_links)
    server.tool()(eno_concepts)
    server.tool()(eno_drift)
    server.tool()(eno_frontier)
    server.tool()(eno_hot)
    server.tool()(eno_tiling)
    server.tool()(eno_hygiene)
    server.tool()(eno_create_note)
    server.tool()(eno_append_to_note)
    server.tool()(eno_health)
    return server
