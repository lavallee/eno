# eno

**Structural intelligence and gardening for your Obsidian vault.**

A markdown vault grows into a pile. Notes go orphaned, stubs never get
finished, pages drift into saying the same thing twice, and every "what does
my vault know about X?" costs a full-text grep plus a fat LLM read. eno indexes
the vault into a queryable surface, gardens it, and exposes it — to you on the
command line, to coding agents over MCP, and to sibling tools over a local HTTP
service.

The core is deliberately light: `pip install enowiki` gives you the whole
structural and gardening surface with **no LLM dependency** and no model
runtime to stand up. The optional `enowiki[llm]` extra adds local-first
distillation and semantic dedup.

> The PyPI package is **`enowiki`** (the bare `eno` was already taken). The
> command, the config vars, and the `import eno` module are all just `eno`.

```bash
pip install enowiki
export ENO_VAULT_DIR=~/vault      # or pass --vault to any command
eno index                         # build the index
eno hygiene                       # orphans, stubs, stale, broken links
eno search "mechanism design"     # paths + excerpts, not full notes
```

## Why eno

- **Token-efficient by construction.** Index queries return paths and small
  excerpts, not whole notes. LLM operations are two-phase: cheap planning over
  the index, then targeted reads. Nothing loads your whole vault into a prompt.
- **The vault is its own dashboard.** Gardening reports are written back into
  the vault as notes (under `9 Vault Health/`), so they're wikilinkable,
  graph-visible, and indexable by eno itself. No separate UI for things
  markdown already shows well.
- **Resurfacing over collecting.** eno surfaces the forgotten, suggests rather
  than enforces, and treats vault content as soft authority. Every structural
  change keeps a human in the loop — it never auto-merges or auto-deletes.
- **Local-first, no phone-home.** The core has no network dependency at all.
  The LLM extra routes through [somm](https://github.com/lavallee/somm), which
  is local-first (ollama) by default; vault prose never has to leave your
  machine.

## Four surfaces, one index

| Package | What it is | Install |
| --- | --- | --- |
| `enowiki` | The library + `eno` CLI: index, retrieve, garden, hygiene | `pip install enowiki` |
| `eno-mcp` | MCP stdio server exposing the read/write tools to coding agents | `pip install eno-mcp` |
| `eno-service` | FastAPI face on the read endpoints, for sibling tools | `pip install eno-service` |
| `eno-plugin` | Obsidian plugin talking to a running `eno-service` | see [`packages/eno-plugin`](packages/eno-plugin) |

## What it does

**Retrieve** — `search`, `note`, `neighbors`, `concepts`, `frontier`, `hot`.
Graph-aware, excerpt-first retrieval over frontmatter, wikilinks, tags, and
headings.

**Garden & check health** — `orphans`, `stubs`, `stale`, `broken-links`,
`drift`, `hygiene`, `health`. Drift is the interesting one: fuzzy-matched
wikilink targets that *almost* resolve (a real bug), as distinct from
deliberately-incipient links (groundwork, not a bug).

**For coding agents (MCP)** — a stdio server gives any MCP client (Claude Code,
Cursor, Windsurf, …) a structural view of the vault: the retrieval and health
tools above, plus `eno_create_note` / `eno_append_to_note` for writing back
with provenance. The intelligence here is the *calling* agent — no model setup
of eno's own required.

### With the LLM extra (`pip install enowiki[llm]`)

**`eno fold`** — distills a date range or a topic (by wikilink, folder, or tag)
into a structured, cited rollup note, with supersession metadata and
fold-of-folds level stacking. Extractive-only, with a count-check that flags
any numeric claim or citation date not present in the sources.

**`eno tiling`** — body-content semantic dedup: finds notes that say the same
thing in different words, in two confidence bands. A signal for human review,
never an auto-merge.

Both route through [somm](https://github.com/lavallee/somm), which owns
provider selection and is local-first by default. eno itself makes no
assumption about a model runtime — call these without the extra installed and
you get a clean `pip install enowiki[llm]` hint, not a crash.

## Configuration

eno needs to know where your vault is. In precedence order:

1. `--vault PATH` on any command
2. `$ENO_VAULT_DIR`

There is no default — a tool that operates on your notes should never guess
which directory that is. The index lives at `<vault>/.eno/` (override with
`$ENO_DIR`).

## Status

**v0.1.0 — first public release.** The structural core, MCP server, and HTTP
service are stable in day-to-day use over a ~1k-note vault. The Obsidian plugin
is functional but the least battle-tested surface. Semantic embeddings are
intentionally deferred to the `[llm]` extra rather than baked into the core.

Requires Python 3.12+.

## License

MIT — see [LICENSE](LICENSE).
