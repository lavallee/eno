# eno-mcp

MCP stdio server exposing eno's read + write tools to coding agents and
autonomous agents (Claude Code, Cursor, anything that speaks MCP).

## Tools

Read:
- `eno_search` — find notes by title or tag
- `eno_note` — frontmatter + headings + ~400-char excerpt for one note
- `eno_neighbors` — backlinks + outbound for one note
- `eno_orphans` — notes with no inbound links (resurfacing)
- `eno_stubs` — short notes with no outbound links
- `eno_stale` — notes past a recency threshold
- `eno_broken_links` — raw broken wikilinks (use eno_concepts / eno_drift instead for classified output)
- `eno_concepts` — incipient wikilinks (groundwork for not-yet-written notes)
- `eno_drift` — drift candidates (almost-matches, real bugs)
- `eno_hygiene` — frontmatter contract violations
- `eno_health` — diagnostic

Write:
- `eno_create_note` — create a note; frontmatter auto-populated with `origin: llm` + `author: '[[X]]'`
- `eno_append_to_note` — append content, optionally under a specific heading

## Wiring it into an MCP agent

Many autonomous agents load MCP servers natively. Two pieces:

**1. Onboarding skill.** Drop the agent brief into a place the agent
loads from at startup (skill directory, system prompt path, etc.).

```sh
# Whichever of these matches your agent's setup:
cp packages/eno-mcp/skills/agent-onboarding.md \
   ~/.config/my-agent/skills/

# or, if you sync skills via the vault:
cp packages/eno-mcp/skills/agent-onboarding.md \
   /path/to/vault/.eno/skills/
```

The onboarding brief covers the postures (resurfacing > collecting,
incipient links are intentional, two-phase reads), the tool inventory,
and common patterns. Self-contained. Read it yourself before deploying
— it's the contract
the agent will operate under.

**2. MCP config.** Add eno-mcp to the agent's MCP config — typically
`~/.config/my-agent/mcp.json` or whatever your install expects.

```json
{
  "mcpServers": {
    "eno": {
      "command": "uv",
      "args": [
        "run",
        "--directory",
        "/path/to/eno",
        "eno-mcp"
      ],
      "env": {
        "ENO_VAULT_DIR": "/path/to/vault",
        "ENO_AGENT_NAME": "Weaver"
      }
    }
  }
}
```

Or, if you prefer the agent to talk to a long-running `eno-serve` daemon
on dash-main (so multiple agents share one index):

```json
{
  "mcpServers": {
    "eno": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/eno", "eno-mcp"],
      "env": {
        "ENO_SERVICE_URL": "http://dash-main:7891",
        "ENO_AGENT_NAME": "Weaver"
      }
    }
  }
}
```

`ENO_AGENT_NAME=Weaver` is what makes new notes get
`author: '[[Weaver]]'` automatically — the AGENTS.md convention that
keeps provenance legible without per-call ceremony.

## Wiring it into other agents

Claude Code (project-level): the repo's own `.mcp.json` already wires
this for sessions opened inside `/eno`. To get it in every Claude Code
session, copy that snippet into `~/.claude/.mcp.json`.

Other MCP-compatible agents (Cursor, openclaw, custom): same shape —
spawn `eno-mcp` over stdio with the env vars above.

## Backend choice

The server picks a backend at runtime:
- `$ENO_SERVICE_URL` set → ServiceBackend (HTTP to a running `eno-serve`)
- otherwise → LocalBackend (direct sqlite at `$ENO_VAULT_DIR/.eno/index.db`)

Single-host work: omit `ENO_SERVICE_URL`, set `ENO_VAULT_DIR`. Multi-host
fleet: run `eno-serve` on dash-main and point all workstation agents at
it via `ENO_SERVICE_URL`.

## Two postures encoded in the tool docstrings

Every tool's docstring is the description an agent sees. Two postures
are deliberately repeated across tools and worth keeping in mind when
extending:

1. **Resurfacing > collecting.** Orphans, stale notes, and concept
   candidates are framed as opportunities, not errors. Tools never tell
   the agent to "fix" or "clean up" these.
2. **Incipient links are intentional.** `eno_broken_links` returns raw
   data; `eno_concepts` separates intentional groundwork from drift.
   Agents must never describe concepts as broken-link bugs.

If you add a tool that touches link integrity or vault structure, match
this framing.
