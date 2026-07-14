---
title: Agent onboarding for eno
type: skill
audience: any MCP agent
---

# Agent onboarding for eno

You are running with the **eno** MCP server attached. eno is the structural
intelligence layer for an Obsidian-style markdown vault: it indexes the vault
and exposes it as a queryable surface so you can ground your work in what's
already written instead of grepping and reading whole files. Read this once,
internalize the postures, and operate from them.

## Session start protocol

**First action of every session: call `eno_hot`.** Pass `agent_name` (or read
`$ENO_AGENT_NAME`). It returns four signals derived live from the index:

- `frontier` — pages reaching outward (high out-degree, low in-degree,
  recently touched). Active threads with momentum.
- `recent_appends` — notes touched in the last 7 days. Active surfaces,
  regardless of graph shape.
- `top_concepts` — durable themes gestured at via incipient wikilinks
  (**not** bugs — see posture 2).
- `agent_recent` — your own contributions in the last 14 days, so you
  remember what *you* built before the user has to remind you.

Internalize this as recent context. Don't announce it or dump it back at the
user. Just have it available.

**After context compaction**: call `eno_hot` again. Hook-injected context
doesn't survive compaction in most agent harnesses; only explicitly-loaded
skill files do. Re-derive on demand.

## Three postures (non-negotiable)

### 1. Ground in the vault before generating

The vault already holds research, notes, and frameworks. Your highest-leverage
move is finding material that already exists — not generating fresh content
from training-data priors. When the user asks about something, your first
action is `eno_search` or `eno_note`, not a blank page.

### 2. Incipient links are opportunities, not broken links

Authors deliberately write wikilinks like `[[Mechanism Design]]` *before*
creating the target note — it's how conceptual groundwork gets laid.
`eno_concepts` surfaces these. A high-mention-count concept with no note yet is
often a page waiting to be written. **Never** frame concept candidates as
"broken links to fix."

The actual link-bug class is `eno_drift` — wikilinks that *almost* match an
existing note (em-dash vs hyphen, casing, trailing punctuation) and silently
don't resolve. Those are real cleanup candidates, and those you can call bugs.

### 3. Two-phase reads, always

Tools return paths + small excerpts (~1KB) by default. To go deeper, call
`eno_note` on the specific path. Don't read whole files until you've scoped
which file actually matters. Frontmatter + headings + a 400-char excerpt
answers most questions without burning budget on full bodies.

## Tool inventory

**Read (cheap, no LLM behind them):**
- `eno_hot(agent_name?)` — session-start bundle. Call first.
- `eno_search(query, kind=title|tag)` — find by title substring or tag
- `eno_note(path)` — frontmatter + headings + ~400-char excerpt
- `eno_neighbors(path)` — backlinks + outbound; map the neighborhood
- `eno_frontier(folder?, halflife_days?)` — active outward-reaching pages
- `eno_orphans(folder?, min_words?)` — substantive notes nothing links to
- `eno_concepts()` — incipient wikilinks (groundwork, *not* bugs)
- `eno_drift()` — drift candidates (almost-matches; real bugs)
- `eno_stale(older_than_days?)` — notes past a recency threshold
- `eno_stubs()` — short notes with no outbound links
- `eno_hygiene()` — frontmatter contract violations
- `eno_health()` — diagnostic only

**Body-content analysis (requires the `eno[llm]` extra):**
- `eno_tiling(...)` — semantic dedup. Before writing on a topic, check
  whether similar material already exists across notes.

**Folds (synthesized rollups; `eno fold` is CLI-only, deliberate human ops):**
- Read committed folds via `eno_note("9 Vault Health/folds/<id>")` and find
  them with `eno_search("fold-", kind="title")`. Folds are dense summaries of a
  time range or topic — often the best starting point for a brief.

**Write (mutate the vault):**
- `eno_create_note(path, body, title?, overwrite?, author?)` — create a
  durable note. Refuses to overwrite by default.
- `eno_append_to_note(path, content, under_heading?)` — extend an existing
  note rather than creating a sibling duplicate.

## Common patterns

**"What's active right now?"** → `eno_hot`, then `eno_concepts`, then
`eno_note` on the candidates; surface the 2-3 most relevant with a one-line
why.

**"Write about X"** → `eno_search(X)` → `eno_note` + `eno_neighbors` to map
context → read a relevant fold if one exists → write, wikilinking to the source
material.

**"What substantial material is buried?"** → `eno_orphans(min_words=1000)` +
`eno_stale(older_than_days=90)` → `eno_note` each to check density.

**"Did I already cover this?"** → `eno_tiling` for near-duplicates +
`eno_search` by title before creating anything new.

## What NOT to do

- Don't generate from training-data priors when the vault has the material.
  Search first.
- Don't write into `.eno/`, `.git/`, `.obsidian/`, or `.trash/` (the safety
  net rejects these).
- Don't frame `eno_concepts` results as "broken links to fix" — they're
  candidates, not bugs.
- Don't overwrite notes silently — `eno_create_note` refuses by default; use
  `eno_append_to_note` to extend.
- Don't omit the `author` field on notes you create (it's auto-stamped from
  `$ENO_AGENT_NAME` — just don't override it away). This keeps machine-written
  pages distinguishable from the human's.
- Don't read full file bodies via filesystem tools when `eno_note` gives you a
  structured ~1KB summary.

## Self-check before any write

1. Did I search first? (`eno_search`, `eno_concepts`)
2. Is there a canonical note this belongs in? (extend, don't duplicate)
3. Does the path land in a sensible folder for its primary intent?
4. Are my wikilinks pointing at notes that exist (or incipient on purpose)?
5. Will `author` be set automatically? (yes, if `$ENO_AGENT_NAME` is set —
   check `eno_health`)

If any answer is uncertain, prefer surfacing to the user over writing.
