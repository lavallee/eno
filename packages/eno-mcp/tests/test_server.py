"""Smoke test that build_server() wires every tool without import errors."""

from eno_mcp.server import build_server


def test_build_server_has_eno_name():
    server = build_server()
    assert server.name == "eno"


def test_build_server_registers_all_nine_tools():
    server = build_server()
    # FastMCP exposes registered tools via list_tools (async) or its internal
    # registry. We grab the internal names regardless of API shape.
    names = _registered_tool_names(server)
    expected = {
        "eno_search",
        "eno_note",
        "eno_neighbors",
        "eno_orphans",
        "eno_stubs",
        "eno_stale",
        "eno_broken_links",
        "eno_concepts",
        "eno_drift",
        "eno_hygiene",
        "eno_create_note",
        "eno_append_to_note",
        "eno_health",
    }
    assert expected.issubset(names), f"missing: {expected - names}"


def _registered_tool_names(server) -> set[str]:
    # Try several known FastMCP attrs across versions.
    for attr in ("_tool_manager", "tool_manager"):
        mgr = getattr(server, attr, None)
        if mgr is None:
            continue
        tools = getattr(mgr, "_tools", None) or getattr(mgr, "tools", None)
        if tools is None:
            continue
        if isinstance(tools, dict):
            return set(tools.keys())
        # list of Tool objects with .name
        return {getattr(t, "name", None) for t in tools if getattr(t, "name", None)}
    # Fallback: introspect the FastMCP-decorated attributes
    return set()
