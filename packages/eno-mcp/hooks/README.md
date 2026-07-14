# Hot-cache hooks

Optional Claude Code hook bundle for projects that want eno's
"what's hot" bundle injected at session start (and after compaction).

The pattern is borrowed from
[claude-obsidian](https://github.com/AgriciDaniel/claude-obsidian)'s
`wiki/hot.md` SessionStart trick — but in eno's version the hot bundle
is **derived live** from the index by `eno hot`, not written to a
file. So there's no cache file to keep current; every read is fresh.

## What gets injected

`eno hot` emits markdown with four sections:

1. **Frontier** — pages with high outward reach, low inbound, recently
   touched. Where you're currently pulling threads.
2. **Recent appends** — notes whose mtime is within 7 days, newest
   first.
3. **Top incipient concepts** — wikilinks the user has gestured at
   across multiple notes (durable themes, *not* broken links).
4. **Recent agent contributions** — notes the agent itself authored
   within 14 days, when `--agent NAME` is provided.

## Install (Claude Code)

1. Edit `hot-cache-hooks.json` and replace `/CHANGE_ME/path/to/eno`
   with the absolute path to this repo on your machine.
2. Merge the `hooks` key into `~/.claude/settings.json`. If you
   already have hooks in there, append these inside the existing
   `hooks` object (don't overwrite siblings).
3. Make sure the agent's MCP config exports both env vars
   (eno-mcp's README has the canonical example):
   - `ENO_VAULT_DIR=/path/to/vault`
   - `ENO_AGENT_NAME=Weaver` (or whatever the agent calls itself)

When the hook fires, it runs `eno hot --agent $ENO_AGENT_NAME`. The
guard `[ -n "${ENO_VAULT_DIR:-}" ] && ... || true` means the hook
is a no-op (exit 0) in non-eno sessions — safe to install globally.

## Non-Claude-Code agents

Some agents load MCP servers natively but don't honor Claude Code hooks.
For those, the equivalent is the **session-start protocol** documented
in `packages/eno-mcp/skills/agent-onboarding.md`: call `eno_hot`
yourself at the start of every session. The skill brief covers the
when, why, and what to do with the result.

## Why no Stop hook

The upstream `wiki/hot.md` pattern includes a Stop hook that prompts
the agent to overwrite `hot.md` with a session summary. Eno doesn't
need this:

- Durable session output flows through `eno_create_note` and
  `eno_append_to_note`, both of which stamp `author: '[[Agent]]'`
  in frontmatter. Provenance is automatic.
- The next session's `eno hot` re-derives `agent_recent` from those
  same notes, so the contribution trail is always live.

If you want a per-session log on top of that, add it as a separate
hook — but it's orthogonal to hot-cache.
