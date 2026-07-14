"""End-to-end MCP smoke: drive eno-mcp over stdio against your vault via LocalBackend."""

import asyncio
import json
import os
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def main() -> int:
    vault = Path(
        os.environ.get(
            "ENO_VAULT_DIR",
            "/path/to/vault",
        )
    )
    eno_dir = os.environ.get("ENO_DIR", "/tmp/eno-smoke")

    print(f"vault:    {vault}")
    print(f"eno-dir:  {eno_dir}")

    if not (Path(eno_dir) / "index.db").exists():
        print(f"no index at {eno_dir}/index.db — run `eno index` first")
        return 1

    params = StdioServerParameters(
        command="uv",
        args=["run", "eno-mcp"],
        env={
            **os.environ,
            "ENO_VAULT_DIR": str(vault),
            "ENO_DIR": eno_dir,
        },
    )

    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            init = await session.initialize()
            print(f"\nserver:   {init.serverInfo.name} v{init.serverInfo.version}")

            tools = await session.list_tools()
            print(f"tools:    {[t.name for t in tools.tools]}")

            print("\n=== eno_health ===")
            res = await session.call_tool("eno_health", {})
            print(_unwrap(res))

            print("\n=== eno_orphans (min_words=5000, limit=3) ===")
            res = await session.call_tool(
                "eno_orphans", {"min_words": 5000, "limit": 3}
            )
            payload = _unwrap(res)
            print(f"count: {payload.get('count')}")
            for o in payload.get("orphans", []):
                print(f"  {o['path']}  ({o['word_count']} words)")

            print("\n=== eno_search 'widget' ===")
            res = await session.call_tool("eno_search", {"query": "widget"})
            payload = _unwrap(res)
            for h in payload.get("hits", []):
                print(f"  {h['path']}  [{h['title']}]")

            print("\n=== eno_note '2 Projects/Acme/Widget.md' ===")
            res = await session.call_tool(
                "eno_note", {"path": "2 Projects/Acme/Widget.md"}
            )
            payload = _unwrap(res)
            print(f"title:    {payload.get('title')}")
            print(f"words:    {payload.get('word_count')}")
            print(f"headings: {[h['text'] for h in payload.get('headings', [])]}")
            excerpt = payload.get("excerpt", "")
            if excerpt:
                print(f"excerpt:  {excerpt[:120]}…")

            print("\n=== eno_concepts (top 8) ===")
            res = await session.call_tool("eno_concepts", {"limit": 8})
            payload = _unwrap(res)
            print(f"total: {payload.get('count')}")
            for c in payload.get("concepts", []):
                print(f"  [[{c['target_text']}]] — {c['mention_count']} mentions")

            print("\n=== eno_drift (top 5) ===")
            res = await session.call_tool("eno_drift", {"limit": 5})
            payload = _unwrap(res)
            print(f"total: {payload.get('count')}")
            for d in payload.get("drift", []):
                print(
                    f"  [[{d['target_text']}]] → {d['suggested_path']}  "
                    f"({d['score']:.0%})"
                )

            print("\n=== eno_hygiene ===")
            res = await session.call_tool("eno_hygiene", {})
            payload = _unwrap(res)
            print(f"counts: {payload.get('counts')}")

    return 0


def _unwrap(result):
    """MCP tool calls return a CallToolResult; pull the JSON-serialized payload out."""
    if not result.content:
        return None
    for block in result.content:
        text = getattr(block, "text", None)
        if text:
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                return {"_raw": text}
    return None


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
