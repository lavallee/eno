# eno-mcp

MCP stdio server exposing [eno](https://github.com/lavallee/eno)'s read +
write tools to coding agents and autonomous agents (Claude Code, Cursor,
anything that speaks MCP). It gives an MCP client a structural view of an
Obsidian vault; the intelligence is the *calling* agent — no model setup of
eno's own required.

## Install

```bash
pip install eno-mcp
```

Requires Python 3.12+. Pulls in the `enowiki` core (which imports as `eno`).
The server exposes the tools over stdio; you wire it into your agent's MCP
config (below).

## Tools

Read:
- `eno_search` — find notes by title, body text, or tag; Flip results name their owning bundle
- `eno_note` — frontmatter + headings + ~400-char excerpt for one note
- `eno_neighbors` — backlinks + outbound for one note
- `eno_orphans` — notes with no inbound links (resurfacing)
- `eno_stubs` — short notes with no outbound links
- `eno_stale` — notes past a recency threshold
- `eno_frontier` — pages actively reaching outward (high out-degree, low in-degree, recent)
- `eno_hot` — session-start "what's hot" bundle (frontier + recent + concepts + your recent notes)
- `eno_broken_links` — raw broken wikilinks (use eno_concepts / eno_drift instead for classified output)
- `eno_concepts` — incipient wikilinks (groundwork for not-yet-written notes)
- `eno_drift` — drift candidates (almost-matches, real bugs)
- `eno_tiling` — body-content semantic dedup (needs the core's `enowiki[llm]` extra)
- `eno_hygiene` — frontmatter contract violations
- `eno_health` — diagnostic

Write:
- `eno_create_note` — create a note; frontmatter auto-populated with `origin: llm` + `author: '[[X]]'`
- `eno_append_to_note` — append content, optionally under a specific heading

## Wiring it into an MCP agent

Many autonomous agents load MCP servers natively. Two pieces:

**1. Agent instruction surface.** Evaluated Codex and Claude Code sessions should use the
minimal [`eno-vault` skill](https://github.com/lavallee/eno/tree/main/packages/eno-mcp/skills/eno-vault).
It keeps Eno's vault-grounding, concept-versus-drift, and canonical-write
boundaries without repeating the MCP tool schemas. Its Spindle manifest records
the exact harness, model, effort, role, build, and Eno tool envelope that have
been evaluated; an unknown tuple receives the invariant core without a tuned
claim.

```sh
# From a source checkout:
cp -R skills/eno-vault ~/.codex/skills/eno-vault

# Portable Claude project fallback (invariant core only):
cp -R skills/eno-vault /path/to/project/.claude/skills/eno-vault
```

The direct copies above load the portable invariant core. For evaluated runtime
routing, a session adapter should ask Spindle to realize this same package from
the actual requested and served model tuple, then project the immutable result
into the session-local skill root. The pinned Claude Sonnet 5 explorer profile
uses the core unchanged; the pinned Claude Opus 5 reviewer profile adds one
12-word instruction that keeps vault reads on Eno rather than filesystem tools.
The evaluated mixed-model Claude adapter keeps the parent realization in that
session-local skill root and supplies a differently modeled child's independent
realization through its custom-agent system prompt. A child-scoped MCP server
still requires `mcp__eno__*` in the session permission allowlist. Do not rewrite
a global installed skill when a session or subagent changes models.

The wheel also carries the skill under `eno_mcp/skills/eno-vault`. Locate an
installed copy with:

```sh
python -c 'from importlib.resources import files; print(files("eno_mcp").joinpath("skills", "eno-vault"))'
```

For unevaluated harnesses or integrations that need a self-contained tool inventory,
the longer portable brief remains at
[`skills/agent-onboarding.md`](https://github.com/lavallee/eno/blob/main/packages/eno-mcp/skills/agent-onboarding.md):

```sh
cp skills/agent-onboarding.md ~/.config/my-agent/skills/

# or, if you sync skills via the vault:
cp skills/agent-onboarding.md \
   /path/to/vault/.eno/skills/
```

The onboarding brief is cross-harness integration material, not the tuned
Codex/Claude runtime surface. Read whichever artifact you deploy—the selected
instructions are the contract the agent will operate under.

**2. MCP config.** Add eno-mcp to the agent's MCP config — typically
`~/.config/my-agent/mcp.json` or whatever your install expects. If you
installed with `pip install eno-mcp`, the command is simply `eno-mcp`
(with `"args": []`); the examples below use `uv run --directory` for
running against a source checkout.

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
on a shared host (so multiple agents share one index):

```json
{
  "mcpServers": {
    "eno": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/eno", "eno-mcp"],
      "env": {
        "ENO_SERVICE_URL": "http://your-host:7891",
        "ENO_AGENT_NAME": "Weaver"
      }
    }
  }
}
```

`ENO_AGENT_NAME=Weaver` is what makes new notes get
`author: '[[Weaver]]'` automatically — the AGENTS.md convention that
keeps provenance legible without per-call ceremony.

For one read surface across repo-local Flip notebooks, point
`ENO_VAULT_DIR` at their common projects root, point `ENO_DIR` at the seeded
estate index, and set `ENO_READ_ONLY=1`. `eno_health` then reports the indexed
notebook and shadow-copy counts. Search results carry `bundle_path`; use that
path to route an authorized write through the owning repo rather than through
the shared estate process.

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
fleet: run `eno-serve` on a shared host and point all workstation agents at
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

## License

MIT — see [LICENSE](https://github.com/lavallee/eno/blob/main/LICENSE).
