"""`eno-mcp` — stdio MCP entrypoint.

No args. Backend choice via env: $ENO_SERVICE_URL → ServiceBackend (talks to
eno-serve); else $ENO_VAULT_DIR → LocalBackend (reads .eno/index.db directly).

Configure in `.mcp.json`:

    {"mcpServers": {"eno": {"command": "uv", "args": ["run", "eno-mcp"]}}}
"""

from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> int:
    from eno_mcp.server import build_server

    server = build_server()
    server.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
